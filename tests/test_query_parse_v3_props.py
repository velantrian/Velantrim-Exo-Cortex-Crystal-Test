"""v3 general properties (stdlib only: itertools, str case methods).

1. The case of a zone/place name never changes the decision.
2. The clock is parsed whole: seconds kept exactly, other precision -> clarification.
3. Object choice does not depend on catalogue order or alias order; ranking is
   longest span > exact name > match via inflection; a tie -> clarification.
For every clarification the memory query must not run (spy ``query_fn``).
Isolated synthetic data; no model calls. v2 behaviour is evidenced separately
in tests/test_query_parse_v2_defects.py.
"""
import itertools
from copy import deepcopy
from datetime import datetime

import pytest

from core.query_parse import ask, parse_question
from tests import query_parse_eval as ev

OBJ = ev.SETUP["known_objects"]
NOW, TZ = ev.NOW, ev.SETUP["timezone"]


def gated(question, objects=OBJ, context=None, tz=TZ):
    calls = []
    out = ask(question, objects, context, now=NOW, timezone=tz,
              query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    p = out["parse"]
    if p["kind"] == "parsed":
        assert calls == [p["params"]] and out["query_called"] is True
    else:
        assert calls == [] and out["query_called"] is False and out["answer"] is None
    return p


def decision(p):
    return p["kind"], tuple(sorted((p.get("params") or {}).items())), tuple(sorted(p.get("candidates", [])))


# ── 1. zone-name case ──────────────────────────────────────────────────────

CASE_FNS = (str, str.lower, str.upper, str.title, str.swapcase, str.capitalize)
ZONES = {  # phrase -> expected as_of for «8 ноября в 13:00 <phrase>», or None = clarification
    "по Лондону": None, "по Парижу": None, "по Токио": None, "по местному времени": None,
    "по киевскому времени": None, "по Гринвичу": None, "GMT": None, "GMT+3": None, "МСК+1": None,
    "в часовом поясе Самары": None, "по времени Самары": None,
    "по московскому времени": "2026-11-08T13:00:00+03:00", "по Москве": "2026-11-08T13:00:00+03:00",
    "МСК": "2026-11-08T13:00:00+03:00", "MSK": "2026-11-08T13:00:00+03:00",
    "по Берлину": "2026-11-08T13:00:00+01:00", "по берлинскому времени": "2026-11-08T13:00:00+01:00",
    "UTC": "2026-11-08T13:00:00+00:00", "по UTC": "2026-11-08T13:00:00+00:00",
}


@pytest.mark.parametrize("phrase", list(ZONES))
def test_zone_case_never_changes_decision(phrase):
    expected = ZONES[phrase]
    seen = set()
    for fn in CASE_FNS:
        z = fn(phrase)
        for q in ("Какой статус L был 8 ноября в 13:00 %s?" % z, "%s, какой статус L был 8 ноября в 13:00?" % z):
            p = gated(q)
            seen.add(decision(p))
            if expected is None:
                assert p["kind"] == "needs_clarification", (q, p)
            else:
                assert p["kind"] == "parsed" and p["params"]["as_of"] == expected, (q, p)
    assert len(seen) == 1


def test_lowercase_unknown_place_is_not_silently_replaced_by_default_zone():
    for q in ("Какой статус L был 8 ноября в 13:00 по лондону?", "По Лондону какой статус L был 8 ноября в 13:00?",
              "ПО ЛОНДОНУ КАКОЙ СТАТУС L БЫЛ 8 НОЯБРЯ В 13:00?"):
        assert gated(q)["kind"] == "needs_clarification"


@pytest.mark.parametrize("q,as_of", [
    ("Что с L сегодня в 07:00 по статусу?", "2026-11-09T07:00:00+01:00"),  # v6 C1: «сегодня» needs a clock
    ("Какой статус L по состоянию на 8 ноября 13:00?", "2026-11-08T13:00:00+01:00"),
    ("Какой статус L по данным на 8 ноября 13:00?", "2026-11-08T13:00:00+01:00"),
    ("Что по Мосту сейчас со статусом?", "2026-11-09T07:58:00+01:00"),
    ("Что по L2 сейчас со статусом?", "2026-11-09T07:58:00+01:00"),
])
def test_non_place_words_after_po_do_not_clarify(q, as_of):
    for fn in (str, str.lower, str.upper):
        p = gated(fn(q))
        assert p["kind"] == "parsed" and p["params"]["as_of"] == as_of


# ── 2. the clock is parsed whole ──────────────────────────────────────────

@pytest.mark.parametrize("h,m,s", list(itertools.product((0, 9, 10, 23), (0, 1, 59), (0, 1, 30, 59))))
def test_seconds_are_kept_exactly(h, m, s):
    clock = "%02d:%02d:%02d" % (h, m, s)
    for template, off in (("Какой статус L был 8 ноября в %s?", "+01:00"),
                          ("Какой статус L был 8 ноября в %s по Москве?", "+03:00"),
                          ("Статус L на 2026-11-08 %s?", "+01:00")):
        p = gated(template % clock)
        assert p["params"]["as_of"] == "2026-11-08T%s%s" % (clock, off)
        assert datetime.fromisoformat(p["params"]["as_of"]).second == s


@pytest.mark.parametrize("form", ["10:00:30.5", "10:00:30,25", "10:00:60", "10:60", "24:00:00", "10.00", "10.30",
                                  "10 часов 30 минут", "10 минут одиннадцатого", "половине десятого",
                                  "четверть одиннадцатого", "полдень", "полночь", "15:00 утра", "11 дня"])
def test_other_precision_or_forms_clarify_and_do_not_query(form):
    p = gated("Какой статус L был 8 ноября в %s?" % form)
    assert p["kind"] == "needs_clarification", p


def test_iso_t_form_clarifies():
    for q in ("Статус L на 2026-11-08T10:00:30?", "Статус L на 2026-11-08T10:00:30+03:00?", "Статус L на 2026-11-08T10:00Z?"):
        assert gated(q)["kind"] == "needs_clarification"


@pytest.mark.parametrize("form,as_of", [
    ("10:30 вечера", "2026-11-08T22:30:00+01:00"), ("22:30 вечера", "2026-11-08T22:30:00+01:00"),
    ("10:30:15 утра", "2026-11-08T10:30:15+01:00"), ("10 часов вечера", "2026-11-08T22:00:00+01:00"),
    ("10 утра", "2026-11-08T10:00:00+01:00"), ("3 дня", "2026-11-08T15:00:00+01:00"),
    ("10 вечера", "2026-11-08T22:00:00+01:00"), ("12 ночи", "2026-11-08T00:00:00+01:00"),
    ("2 ночи", "2026-11-08T02:00:00+01:00"), ("10 ночи", "2026-11-08T22:00:00+01:00"),
])
def test_day_part_after_clock_is_applied_not_dropped(form, as_of):
    assert gated("Какой статус L был 8 ноября в %s?" % form)["params"]["as_of"] == as_of


def test_no_clock_digits_lost_on_any_fixture():
    """For every parsed fixture/counterexample with an explicit HH:MM[:SS], the local
    as_of shows exactly those digits (day-part words aside)."""
    import re
    checked = 0
    for split in ev.V3_SPLITS:
        data = ev.load_split(split)
        objects = ev.split_objects(data)
        for it in data["items"]:
            tz = it["timezone"] if "timezone" in it else TZ
            ctx = ev.build_context(ev.parser_current, it, objects, tz)
            p = parse_question(it["question"], objects, ctx, now=NOW, timezone=tz)
            m = re.search(r"(?<![\d:.])(\d{1,2}):(\d{2})(?::(\d{2}))?(?![\d:.,])", it["question"])
            if p["kind"] != "parsed" or not m or re.search(r"утра|дня|вечера|ночи", it["question"]):
                continue
            local = datetime.fromisoformat(p["params"]["as_of"])
            assert (local.hour, local.minute, local.second) == (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
            checked += 1
    assert checked >= 10


# ── 3. catalogue order ────────────────────────────────────────────────────

M = {"id": "M", "names": ["M", "Мост"]}
Y = {"id": "Y", "names": ["Y", "Моста"]}
B = {"id": "B", "names": ["B", "Главный мост"]}
S = {"id": "S", "names": ["S", "Главстрой мост"]}
P1 = {"id": "P1", "names": ["P1", "Пульсар"]}
P2 = {"id": "P2", "names": ["P2", "Пульсар"]}
L = {"id": "L", "names": ["L", "Л"]}


def all_orders(catalogue):
    for objs in ev.catalogue_variants(catalogue, full=True):
        yield objs


@pytest.mark.parametrize("q,catalogue,kind,obj_or_cands", [
    # v4 (user rule change 2026-11-09): direct «Моста» (Y) and inflected «Мост»+а (M) -> ask.
    # v3 expected ("parsed", "Y") here; that expectation is kept against the frozen v3 snapshot
    # in tests/test_query_parse_v3_gold_change.py.
    ("Какой статус Моста сейчас?", [M, Y, L], "needs_clarification", ["M", "Y"]),
    ("Какой статус Мост сейчас?", [M, Y, L], "parsed", "M"),
    ("Какой статус Мостами сейчас?", [M, Y, L], "needs_clarification", ["M", "Y"]),  # inflection tie
    ("Какой статус Пульсаром сейчас?", [P1, P2, L], "needs_clarification", ["P1", "P2"]),  # same alias
    ("Какой статус Пульсар сейчас?", [P1, P2, L], "needs_clarification", ["P1", "P2"]),
    ("Какой статус Главного моста сейчас?", [M, Y, B, L], "parsed", "B"),  # longest span
    ("Какой статус Главнейшего моста сейчас?", [M, B, S, L], "needs_clarification", ["B", "M", "S"]),  # near-miss union
    ("Какой статус Главнейшего моста сейчас?", [M, B, L], "needs_clarification", ["B", "M"]),
])
def test_object_choice_invariant_under_every_catalogue_and_alias_order(q, catalogue, kind, obj_or_cands):
    seen = set()
    for objs in all_orders(catalogue):
        before = deepcopy(objs)
        p = gated(q, objs)
        assert objs == before  # parser does not touch its inputs
        seen.add(decision(p))
        assert p["kind"] == kind
        if kind == "parsed":
            assert p["params"]["asked_object"] == obj_or_cands
        else:
            assert p["candidates"] == obj_or_cands
    assert len(seen) == 1


def test_match_type_is_reported():
    p = gated("Какой статус Моста сейчас?", [Y, L])
    assert "точное совпадение" in p["explanation"]["asked_object"]
    p = gated("Какой статус Мостом сейчас?", [M, Y])
    assert p["params"]["asked_object"] == "M" and "через склонение" in p["explanation"]["asked_object"]
    p = gated("Какой статус Моста сейчас?", [M, Y])  # v4: both kept, match types named
    assert p["kind"] == "needs_clarification" and "M (через склонение «мост»)" in p["question"]
    assert "Y (точное название «моста»)" in p["question"]


def test_context_follow_up_invariant_under_catalogue_order():
    from core.query_parse import context_turn
    for objs in all_orders([M, Y, L]):
        ctx = []
        for q in ("Какой статус L сейчас?", "Что менялось у Моста за неделю?"):
            ctx.append(context_turn(q, parse_question(q, objs, ctx, now=NOW, timezone=TZ)))
        p = gated("А его статус?", objs, ctx)
        # v4: «Моста» mentions both M and Y (v3: only Y)
        assert p["kind"] == "needs_clarification" and p["candidates"] == ["L", "M", "Y"]


@pytest.mark.parametrize("split", ev.V3_SPLITS)
def test_permutation_invariance_on_all_fixture_sets(split):
    res = ev.permutation_check(ev.parser_current, split, full=True)
    assert res["changed"] == [] and res["variants"] > 0
