"""core.query_parse: rule-based question -> explicit #503 filter parameters.

Isolated synthetic data only; no model calls; explicit clock and timezone.
"""
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest

from core import provenance
from core.applicability import declarations, request_error
from core.query_parse import MAX_CONTEXT_TURNS, ask, context_turn, parse_question
from tests import query_parse_eval as ev
from tests.test_applicability_live_path import admit, dumps, reopen
from tests.test_applicability_live_path import durable as durable  # fixture registration

OBJ = ev.SETUP["known_objects"]
NOW = ev.NOW
TZ = ev.SETUP["timezone"]
NOW_S = "2026-11-09T07:58:00+01:00"


def p(question, context=None, *, now=NOW, tz=TZ, objects=OBJ):
    return parse_question(question, objects, context, now=now, timezone=tz)


def _never(*_a, **_k):
    raise AssertionError("status query must not run for a non-parsed result")


# ── the four scope examples + сейчас/сегодня/за вчера ─────────────────────

def test_scope_example_current():
    r = p("Какой статус L сейчас?")
    assert r["kind"] == "parsed"
    assert r["params"] == {"asked_object": "L", "as_of": NOW_S, "temporal_scope": "current"}
    assert "«L»" in r["explanation"]["asked_object"] and NOW_S in r["explanation"]["as_of"]


def test_scope_example_negation_and_in_utterance_pronoun():
    r = p("Не L2, а L — какой у него статус сейчас?")
    assert r["params"]["asked_object"] == "L"
    assert "исключено по отрицанию: L2" in r["explanation"]["asked_object"]
    assert "местоимение" in r["explanation"]["asked_object"]


def test_scope_example_past_moment_uses_explicit_year_and_zone():
    r = p("Какой статус L был 8 ноября в 10:00?")
    assert r["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    assert "2026" in r["explanation"]["as_of"] and "Europe/Berlin" in r["explanation"]["as_of"]
    clar = p("Какой статус L был 8 ноября в 10:00?", tz=None)
    assert clar["kind"] == "needs_clarification" and "часовом поясе" in clar["question"]
    assert p("Какой статус L был 8 ноября в 10:00?", now=None)["kind"] == "unsupported"


def test_scope_example_follow_up_needs_unambiguous_context():
    ctx = [context_turn("Какой статус L2 сейчас?", p("Какой статус L2 сейчас?"))]
    r = p("А его статус?", ctx)
    assert r["params"]["asked_object"] == "L2" and r["params"]["as_of"] == NOW_S
    assert "из контекста" in r["explanation"]["asked_object"]
    assert "заново привязано" in r["explanation"]["as_of"]
    assert p("А его статус?")["kind"] == "needs_clarification"
    amb = [context_turn("Какой статус Пульсара сейчас?", p("Какой статус Пульсара сейчас?"))]
    r = p("А его статус?", amb)
    assert r["kind"] == "needs_clarification" and r["candidates"] == ["P1", "P2"]


def test_follow_up_time_inherits_absolute_and_date_and_reanchors_now():
    later = NOW + timedelta(hours=2)
    ctx = [context_turn("q", p("Какой статус L был 8 ноября в 10:00?"))]
    assert p("А его статус?", ctx)["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    ctx_date = [context_turn("q", p("Какой статус L был 8 ноября?"))]
    assert p("А его статус?", ctx_date)["params"]["as_of"] == "2026-11-08"
    ctx_now = [context_turn("q", p("Какой статус L сейчас?"))]
    assert p("А его статус?", ctx_now, now=later)["params"]["as_of"] == later.astimezone(
        ev_tz()).isoformat()
    assert p("А его статус?", ctx_now, now=None)["kind"] == "unsupported"
    assert p("А сейчас?", ctx)["params"]["as_of"] == NOW_S
    assert p("А 8 ноября в 10:00?", ctx_now)["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    # Prior turn without a time reference: no silent inheritance.
    assert p("А его статус?", [{"question": "x", "kind": "parsed", "asked_object": "L"}])["kind"] == "needs_clarification"
    # Follow-up naming its own object inherits the previous time.
    assert p("А L?", ctx_now)["params"] == {"asked_object": "L", "as_of": NOW_S, "temporal_scope": "current"}


def ev_tz():
    from zoneinfo import ZoneInfo
    return ZoneInfo(TZ)


def test_context_is_bounded_and_structured():
    old = {"question": "Какой статус M сейчас?", "kind": "parsed", "asked_object": "M", "time_ref": "now", "as_of": NOW_S}
    filler = {"question": "Что менялось?", "kind": "unsupported"}
    assert p("А его статус?", [old] + [filler] * (MAX_CONTEXT_TURNS - 1))["params"]["asked_object"] == "M"
    r = p("А его статус?", [old] + [filler] * MAX_CONTEXT_TURNS + ["not a dict"])
    assert r["kind"] == "needs_clarification"
    assert context_turn("q", {"kind": "unsupported", "limitation": "x"}) == {"question": "q", "kind": "unsupported"}


def test_now_today_and_yesterday_are_not_interchangeable():
    now = p("Какой статус L сейчас?")["params"]["as_of"]
    today = p("Какой статус L сегодня?")["params"]["as_of"]
    assert now == NOW_S and today == "2026-11-09" and now != today
    assert p("Какой статус L за вчера?")["kind"] == "unsupported"
    assert p("Какой статус L вчера?")["params"]["as_of"] == "2026-11-08"
    assert p("Какой статус L был вчера в 10:00?")["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    # «сегодня» uses the explicit zone's calendar day, not the now offset.
    late_utc = datetime(2026, 11, 8, 23, 30, tzinfo=dt_timezone.utc)
    assert p("Какой статус L сегодня?", now=late_utc)["params"]["as_of"] == "2026-11-09"
    assert p("Какой статус L сегодня?", tz="UTC", now=late_utc)["params"]["as_of"] == "2026-11-08"


@pytest.mark.parametrize("q", ["Что менялось у L за неделю?", "Сравни статус L и L2",
                               "Какой статус L был с 1 по 5 ноября?", "Какой статус L между 1 и 5 ноября?",
                               "Когда L стал готов?", "Какой статус L будет завтра?",
                               "Покажи историю статусов L", "Как изменился статус L?"])
def test_periods_changes_and_comparisons_are_unsupported_not_point_queries(q):
    assert p(q)["kind"] == "unsupported"
    assert ask(q, OBJ, now=NOW, timezone=TZ, query_fn=_never)["query_called"] is False


@pytest.mark.parametrize("q,cands", [
    ("Какой статус L и L2 сейчас?", ["L", "L2"]),
    ("Какой статус Z сейчас?", ["L", "L2", "M", "P1", "P2"]),
    ("Какой статус L и Z сейчас?", ["L", "Z"]),
    ("Какой статус Пульсара сейчас?", ["P1", "P2"]),
    ("Какой статус сейчас?", ["L", "L2", "M", "P1", "P2"]),
    ("Какой статус не L?", ["L", "L2", "M", "P1", "P2"]),
])
def test_multiple_unknown_colliding_or_missing_object_asks_and_names_candidates(q, cands):
    r = p(q)
    assert r["kind"] == "needs_clarification" and r["candidates"] == cands


def test_multiword_alias_and_inflection():
    objs = OBJ + [{"id": "B", "names": ["Главный мост", "!!!"]}, {"id": "", "names": ["x"]}, {"names": ["y"]}]
    # v1 (d550f3f) returned M here — a confident misparse. That assertion is kept
    # verbatim, run against the frozen v1 snapshot, in
    # tests/test_query_parse_v1_defects.py::test_v1_defect_2_compound_name_replaced_by_short_alias.
    # v2: multi-word aliases are inflected word by word.
    assert p("Какой статус Главного моста сейчас?", objects=objs)["params"]["asked_object"] == "B"
    assert p("Какой статус у Главный мост сейчас?", objects=objs)["params"]["asked_object"] == "B"
    assert p("Какое состояние Моста сейчас?")["params"]["asked_object"] == "M"


@pytest.mark.parametrize("q,kind,needle", [
    ("", "needs_clarification", "пустой"),
    ("Расскажи про L сейчас", "unsupported", "статусе"),
    ("Какой статус L?", "needs_clarification", "сейчас или"),
    ("Статус L сейчас или 8 ноября в 10:00?", "needs_clarification", "сейчас или"),
    ("Какой статус L в 10:00?", "needs_clarification", "Какого дня"),
    ("Какой статус L утром?", "needs_clarification", "часть суток"),
    ("Какой статус L вчера утром?", "needs_clarification", "часть суток"),
    ("Какой статус L был 31 ноября в 10:00?", "needs_clarification", "некорректная дата"),
    ("Какой статус L на 2026-13-01?", "needs_clarification", "некорректная дата"),
    ("Какой статус L был 8 ноября в 25:00?", "needs_clarification", "не является временем"),
    ("Какой статус L был 8 ноября в 25 часов?", "needs_clarification", "не является временем"),
    ("Какой статус L был 20 декабря?", "needs_clarification", "Какой год"),
    ("Какой статус L был 20 декабря в 10:00?", "needs_clarification", "Какой год"),
    ("Какой статус L был 8 ноября 2027?", "unsupported", "будущем"),
    ("Какой статус L был 8 ноября 2027 в 10:00?", "unsupported", "будущем"),
    ("Какой статус L был 25 октября в 02:30?", "needs_clarification", "неоднозначно"),
])
def test_explicit_failure_modes(q, kind, needle):
    r = p(q)
    assert r["kind"] == kind
    assert needle in " ".join(str(r.get(k, "")) for k in ("question", "limitation", "reason"))


@pytest.mark.parametrize("q,as_of", [
    ("Какой статус L был 08.11.2026 в 10:00?", "2026-11-08T10:00:00+01:00"),
    ("Какой статус L был 8 ноября в 10 часов?", "2026-11-08T10:00:00+01:00"),
    ("Какой статус L был 8 ноября в 3 дня?", "2026-11-08T15:00:00+01:00"),
    ("Какой статус L был 8 ноября в 12 ночи?", "2026-11-08T00:00:00+01:00"),
    ("Статус M на 2026-11-08 10:00?", "2026-11-08T10:00:00+01:00"),
    ("Какой статус L был 8 ноября 2026 года?", "2026-11-08"),
])
def test_supported_date_and_clock_forms(q, as_of):
    assert p(q)["params"]["as_of"] == as_of


@pytest.mark.parametrize("kwargs,needle", [
    ({"now": datetime(2026, 11, 9, 7, 58)}, "часовым поясом"),
    ({"now": "2026-11-09"}, "часовым поясом"),
    ({"tz": "Mars/Phobos"}, "не распознан"),
    ({"tz": 5}, "не распознан"),
])
def test_clock_and_zone_must_be_explicit_and_valid(kwargs, needle):
    r = p("Какой статус L сейчас?", **kwargs)
    assert r["kind"] == "unsupported" and needle in r["limitation"]


def test_now_without_clock_and_dates_without_clock_are_unsupported_not_guessed():
    assert p("Какой статус L сейчас?", now=None)["kind"] == "unsupported"
    assert p("Какой статус L сегодня?", now=None)["kind"] == "unsupported"
    assert p("Какой статус L был 2026-11-08 10:00?", now=None)["kind"] == "unsupported"
    assert p("Какой статус L был 8 ноября 2026?", now=None)["kind"] == "unsupported"
    # No zone: "сейчас" is still the explicit instant; a tzinfo object is accepted.
    assert p("Какой статус L сейчас?", tz=None)["params"]["as_of"] == NOW_S
    assert p("Какой статус L сейчас?", tz=dt_timezone.utc)["params"]["as_of"] == "2026-11-09T06:58:00+00:00"


# ── hard rule: only parsed reaches the filter, always with all filters on ──

@pytest.mark.parametrize("split", ["dev", "heldout", "probes", "counterexamples_v2"])
def test_non_parsed_never_queries_and_parsed_always_carries_full_filter(split):
    data = ev.load_split(split)
    objects = ev.split_objects(data)
    for it in data["items"]:
        tz = it["timezone"] if "timezone" in it else TZ
        calls = []
        ctx = ev.build_context(ev.parser_current, it, objects, tz)
        out = ask(it["question"], objects, ctx, now=NOW, timezone=tz,
                  query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
        if out["parse"]["kind"] == "parsed":
            assert calls == [out["parse"]["params"]]
            kw = calls[0]
            assert kw["asked_object"] and kw["temporal_scope"] == "current"
            assert request_error(**kw) is None
        else:
            assert calls == [] and out["query_called"] is False and out["answer"] is None


# ── question/evidence boundary ─────────────────────────────────────────────

def test_parser_never_annotates_evidence_l_question_does_not_admit_l2_document():
    facts = ev.facts()
    snapshot = deepcopy(facts)
    seen = []

    def fn(q, **kw):
        out = ev.generate_answer({"facts": facts, "query": q, "total": len(facts), **kw}, trace=[])
        seen.append(out)
        return out

    out = ask("Не L2, а L — какой у него статус сейчас?", OBJ, now=NOW, timezone=TZ, query_fn=fn)
    assert facts == snapshot  # facts carry exactly their persisted declarations
    assert [f["fact_id"] for f in out["result"]["facts"]] == ["L-ready"]
    assert "L2-off" not in [f["fact_id"] for f in out["result"]["facts"]]
    only_l2 = [f for f in ev.facts() if f["fact_id"] == "L2-off"]
    r = ev.generate_answer({"facts": only_l2, "query": "q", "total": 1, **p("Какой статус L сейчас?")["params"]}, trace=[])
    assert r["answer"] is None and r["applicability"]["context_relations"][0]["status_transferred"] is False


def _admit_setup():
    for f in ev.SETUP["facts"]:
        admit(f["fact_id"], f["claim"], f["applicability"])
    reopen()


def test_live_store_parsed_question_memory_unchanged_and_receipts(durable):
    from core import memory
    from core.query_pipeline import query
    _admit_setup()
    stored_before = {f["fact_id"]: declarations(memory.get_fact(f["fact_id"])) for f in ev.SETUP["facts"]}
    before = dumps(durable)
    cur = ask("Какой статус L сейчас?", OBJ, now=NOW, timezone=TZ, query_fn=query)
    assert cur["answer"] == "L: статус — готов"
    assert [f["fact_id"] for f in cur["result"]["facts"]] == ["L-ready"]
    receipt = provenance.build_receipt(cur["result"])
    assert receipt["answer"] == "L: статус — готов"
    assert [c["fact_id"] for c in receipt["citations"]] == ["L-ready"]
    assert "в разработке" not in receipt["answer"]
    assert [h["fact_id"] for h in cur["result"]["applicability"]["historical_facts"]] == ["L-dev"]
    past = ask("Какой статус L был 8 ноября в 10:00?", OBJ, now=NOW, timezone=TZ, query_fn=query)
    assert past["answer"] == "L: статус — на ремонте"
    day = ask("Какой статус L был 8 ноября?", OBJ, now=NOW, timezone=TZ, query_fn=query)
    assert day["answer"] is None
    with pytest.raises(ValueError):
        provenance.build_receipt(day["result"])
    clar = ask("А его статус?", OBJ, now=NOW, timezone=TZ, query_fn=_never)
    assert clar["query_called"] is False
    reopen()
    assert dumps(durable) == before
    assert {f["fact_id"]: declarations(memory.get_fact(f["fact_id"])) for f in ev.SETUP["facts"]} == stored_before
    assert all(memory.get_fact(f["fact_id"])["epistemic_state"] for f in ev.SETUP["facts"])


# ── evaluation numbers are pinned so drift is visible ──────────────────────

def test_eval_counts_are_reproducible():
    res = {r["split"]: r for r in ev.main([])}
    assert res["dev"]["counts"]["correct_parse"] == 14 and res["dev"]["counts"]["confident_misparse"] == 0
    assert res["heldout"]["n"] == 24
    assert res["heldout"]["counts"] == {
        "correct_parse": 15, "confident_misparse": 0, "correct_clarification": 5,
        "unnecessary_clarification": 1, "correct_unsupported": 3, "wrong_unsupported": 0,
        "clarification_instead_of_unsupported": 0}
    # v2: P01 (zone in text) and P09 (UTC) are now correct parses.
    assert res["probes"]["counts"] == {
        "correct_parse": 3, "confident_misparse": 0, "correct_clarification": 4,
        "unnecessary_clarification": 2, "correct_unsupported": 0, "wrong_unsupported": 1,
        "clarification_instead_of_unsupported": 0}
    assert res["counterexamples_v2"]["n"] == 20
    assert res["counterexamples_v2"]["counts"] == {
        "correct_parse": 8, "confident_misparse": 0, "correct_clarification": 12,
        "unnecessary_clarification": 0, "correct_unsupported": 0, "wrong_unsupported": 0,
        "clarification_instead_of_unsupported": 0}
    assert res["counterexamples_v3"]["n"] == 23
    assert res["counterexamples_v3"]["counts"] == {
        "correct_parse": 11, "confident_misparse": 0, "correct_clarification": 12,
        "unnecessary_clarification": 0, "correct_unsupported": 0, "wrong_unsupported": 0,
        "clarification_instead_of_unsupported": 0}
    assert ev.evaluate("counterexamples_v3", ev.parser_v2_frozen)["counts"]["confident_misparse"] == 12
    v1 = {r["split"]: r for r in ev.main(["--version", "v1"])}
    assert set(v1) == {"dev", "heldout", "probes"} and v1["probes"]["counts"]["confident_misparse"] == 1
    assert ev.evaluate("counterexamples_v2", ev.parser_v1)["counts"]["confident_misparse"] == 14
    assert ev.classify({"kind": "unsupported"}, {"kind": "needs_clarification"}) == "clarification_instead_of_unsupported"
    assert ev.classify({"kind": "needs_clarification"}, {"kind": "unsupported"}) == "wrong_unsupported"
    rows, md = ev.demo(list(res.values()))
    assert "Question → parsed parameters → admitted grounds" in md and len(rows) == len(ev.DEMO_IDS)
