"""v6 final contract C1–C6 (user decision 2026-11-09) and re-check of all earlier
guarantees on the current parser. Every non-parsed result is checked with a spy:
the memory query is not called. Isolated setup data only."""
import json
from datetime import datetime, timezone as dt_tz

import pytest

import core.query_parse as qp
from core.query_parse import context_turn, parse_question
from tests import query_parse_eval as ev
from tests import query_parse_regression_v6 as reg
from tests import query_parse_v5 as v5

OBJ, NOW, TZ = ev.SETUP["known_objects"], ev.NOW, ev.SETUP["timezone"]
OBJ_Y = ev.split_objects(ev.load_split("counterexamples_v4"))
NOW_S = "2026-11-09T07:58:00+01:00"


def gated(question, context=None, now=NOW, tz=TZ, objects=OBJ, parser=qp):
    calls = []
    out = parser.ask(question, objects, context, now=now, timezone=tz,
                     query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    p = out["parse"]
    if p["kind"] == "parsed":
        assert calls == [p["params"]] and out["query_called"] is True
        assert parser is not qp or "T" in p["params"]["as_of"], "v6: no date-only as_of may reach ask()"
    else:
        assert calls == [] and out["query_called"] is False and out["answer"] is None
    return p


def ctx_of(*qs, objects=OBJ):
    ctx = []
    for q in qs:
        ctx.append(context_turn(q, parse_question(q, objects, ctx, now=NOW, timezone=TZ)))
    return ctx


# ── C1 / C6: no time or a day without a time -> ask ────────────────────────
@pytest.mark.parametrize("q", ["Какой статус L сегодня?", "Какой статус L был вчера?", "Какой статус L был 7 ноября?",
                               "Статус L на 2026-11-07?", "Что с L сегодня по статусу?", "Какой статус L?",
                               "Какой статус L сегодня по Москве?"])
def test_c1_c6_day_without_time_or_no_time_asks(q):
    p = gated(q)
    assert p["kind"] == "needs_clarification"
    assert p["question"].startswith(("На какое время", "На какой момент"))


def test_c1_v5_gave_whole_day():
    assert gated("Какой статус L сегодня?", parser=v5)["params"]["as_of"] == "2026-11-09"
    assert gated("Какой статус L был вчера?", parser=v5)["params"]["as_of"] == "2026-11-08"


# ── C2: day with a clock = a moment in the established zone ────────────────
@pytest.mark.parametrize("q,tz,as_of", [
    ("Какой статус L сегодня в 07:00?", TZ, "2026-11-09T07:00:00+01:00"),
    ("Какой статус L вчера в 10:00?", TZ, "2026-11-08T10:00:00+01:00"),
    ("Какой статус L был 8 ноября в 10:00?", TZ, "2026-11-08T10:00:00+01:00"),
    ("Какой статус L был 8 ноября в 10:00 по Москве?", TZ, "2026-11-08T10:00:00+03:00"),
    ("Какой статус L был 8 ноября в 10:00 ПО МОСКВЕ?", None, "2026-11-08T10:00:00+03:00"),
    ("Какой статус L был 8 ноября в 10:00 utc?", TZ, "2026-11-08T10:00:00+00:00"),
    ("Какой статус L был 8 ноября в 10:00:30?", TZ, "2026-11-08T10:00:30+01:00"),
])
def test_c2_day_with_clock_is_a_moment(q, tz, as_of):
    assert gated(q, tz=tz)["params"] == {"asked_object": "L", "as_of": as_of, "temporal_scope": "current"}


@pytest.mark.parametrize("q,tz", [("Какой статус L был 8 ноября в 10:00?", None),
                                  ("Какой статус L был 8 ноября в 10:00 по Лондону?", TZ),
                                  ("Какой статус L сегодня в 07:00 по киевскому времени?", TZ)])
def test_c2_unknown_zone_asks(q, tz):
    assert gated(q, tz=tz)["kind"] == "needs_clarification"


# ── C3: explicit whole day -> unsupported ───────────────────────────────────
@pytest.mark.parametrize("q", ["Какой статус L был весь день 7 ноября?", "Какой статус L весь день сегодня?",
                               "Какой статус L был за весь день вчера?", "Какой статус L был в течение дня 8 ноября?",
                               "Какой статус был у L в течение вчерашнего дня?", "КАКОЙ СТАТУС L ВЕСЬ ДЕНЬ СЕГОДНЯ?"])
def test_c3_whole_day_unsupported(q):
    p = gated(q)
    assert p["kind"] == "unsupported" and "за весь день" in p["limitation"]


# ── C4 / C5 ─────────────────────────────────────────────────────────────────
def test_c4_future_unsupported_and_c5_future_word_with_past_moment_asks():
    for q in ("Какой статус L 12 ноября в 10:00?", "Какой статус L был 12 ноября?", "Какой статус L будет?",
              "Какой статус L сегодня в 08:00?", "Какой статус Пульсара будет 12 ноября в 10:00?"):
        assert gated(q)["kind"] == "unsupported", q
    for q in ("Какой статус L будет 8 ноября в 10:00?", "Какой статус L будет вчера в 10:00?"):
        p = gated(q)
        assert p["kind"] == "needs_clarification" and "противоречат" in p["reason"], q
    assert gated("Какой статус L будет сегодня?")["question"].startswith("На какое время")


# ── context: only a moment is inherited (documented v1 rule) ────────────────
def test_context_inherits_only_moments():
    assert gated("А его статус?", ctx_of("Какой статус L был 8 ноября в 10:00?"))["params"]["as_of"] == \
        "2026-11-08T10:00:00+01:00"
    later = datetime(2026, 11, 9, 9, 0, tzinfo=dt_tz.utc)
    assert gated("А его статус?", ctx_of("Какой статус L сейчас?"), now=later)["params"]["as_of"] == \
        "2026-11-09T10:00:00+01:00"
    assert gated("А его статус?", ctx_of("Какой статус L сегодня?"))["kind"] == "needs_clarification"
    assert gated("А сегодня?", ctx_of("Какой статус L сейчас?"))["kind"] == "needs_clarification"
    assert gated("А вчера в 10:00?", ctx_of("Какой статус L сейчас?"))["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    stale_date = [{"question": "x", "kind": "parsed", "asked_object": "L", "time_ref": "date", "as_of": "2026-11-08"}]
    assert gated("А его статус?", stale_date)["kind"] == "needs_clarification"
    assert gated("А по Москве?", [{"question": "x", "kind": "parsed", "asked_object": "L", "time_ref": "absolute",
                                    "as_of": "2026-11-08T10:00:00+01:00"}])["kind"] == "needs_clarification"
    # confirmed choice: a moment is reused, a day without time is not
    assert gated("P1", ctx_of("Какой статус Пульсара вчера в 10:00?"))["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    p = gated("P1", ctx_of("Какой статус Пульсара сегодня?"))
    assert p["kind"] == "needs_clarification" and p["confirmed_object"] == "P1"
    stale_pend = [{"question": "x", "kind": "needs_clarification", "candidates": ["P1", "P2"],
                   "pending_time": {"time_ref": "date", "as_of": "2026-11-09", "tz": None}}]
    assert gated("P1", stale_pend)["kind"] == "needs_clarification"


# ── earlier guarantees, re-checked on v6 ────────────────────────────────────
def test_prior_guarantees_still_hold():
    # zones: closed list, case-insensitive; unknown -> ask
    for q in ("Какой статус L был 8 ноября в 13:00 по лондону?", "ПО ЛОНДОНУ какой статус L был 8 ноября в 13:00?"):
        assert gated(q)["kind"] == "needs_clarification"
    # seconds kept, fractional -> ask; alternatives -> ask
    assert gated("Какой статус L был 8 ноября в 10:00:30.5?")["kind"] == "needs_clarification"
    for q in ("Какой статус L был 8 ноября в 10:00 или в 12:00?", "Какой статус L был 7 или 8 ноября?"):
        assert gated(q)["kind"] == "needs_clarification"
    # compound names, near miss
    obj_b = ev.split_objects(ev.load_split("counterexamples_v2"))
    assert gated("Какой статус Главного моста сейчас?", objects=obj_b)["params"]["asked_object"] == "B"
    assert gated("Какой статус Главнейшего моста сейчас?", objects=obj_b)["kind"] == "needs_clarification"
    # collision -> ask with match types; explicit id; confirmed choice; conflict
    p = gated("Какой статус Моста сейчас?", objects=OBJ_Y)
    assert p["candidates"] == ["M", "Y"]
    assert gated("Какой статус объекта Y сейчас?", objects=OBJ_Y)["params"]["asked_object"] == "Y"
    ctx = ctx_of("Какой статус Моста сейчас?", "M", objects=OBJ_Y)
    assert gated("Какой статус Моста сейчас?", ctx, objects=OBJ_Y)["params"]["asked_object"] == "M"
    ctx = ctx_of("Какой статус Моста сейчас?", "M", "Что менялось у Y за неделю?", objects=OBJ_Y)
    assert gated("Какой статус Моста сейчас?", ctx, objects=OBJ_Y)["kind"] == "needs_clarification"
    # object switch after an unsupported turn
    ctx = ctx_of("Какой статус L сейчас?", "Что менялось у L2 за неделю?")
    assert gated("А его статус?", ctx)["candidates"] == ["L", "L2"]
    # R1 / R6 from v5
    assert gated("Какой статус L был в десять утра 8 ноября?")["kind"] == "needs_clarification"
    assert gated("У L статус сейчас лучше, чем у L2?")["kind"] == "unsupported"
    assert gated("Какой статус L сейчас?")["params"]["as_of"] == NOW_S


def test_morning_evening_on_v6():
    run = ev.run_filter
    for q, at, answer in (("Какой статус L был 8 ноября в 09:00?", "2026-11-08T09:00:00+01:00", "L: статус — на ремонте"),
                          ("Какой статус L был 8 ноября в 18:00?", "2026-11-08T18:00:00+01:00", "L: статус — готов"),
                          ("Какой статус L вчера в 21:00?", "2026-11-08T21:00:00+01:00", "L: статус — готов")):
        out = qp.ask(q, OBJ, None, now=NOW, timezone=TZ, query_fn=run)
        assert out["parse"]["params"]["as_of"] == at and out["answer"] == answer
    for q in ("Какой статус L был в десять утра 8 ноября?", "Какой статус L был 8 ноября в 9:00 вечером?",
              "Какой статус L был 8 ноября в шесть вечера?", "Какой статус L был вчера?", "Какой статус L был весь день вчера?"):
        assert gated(q)["kind"] in ("needs_clarification", "unsupported")


def _all_fixture_turns():
    for name in sorted(p.stem for p in ev.FIX.glob("*.json") if p.stem not in ("setup",) and not p.stem.startswith("independent")):
        data = ev.load_split(name)
        objects = ev.split_objects(data)
        for it in data["items"]:
            yield objects, it.get("timezone", TZ) if "timezone" in it else TZ, it.get("context_questions", []), it["question"], it.get("context")
    for name in ("independent_v4.json",):
        d = json.loads((ev.FIX / name).read_text(encoding="utf-8"))
        objects = [{"id": o["id"], "names": o["aliases"]} for o in d["catalogue"]]
        for it in d["items"]:
            yield objects, d["default_tz"], it["turns"][:-1], it["turns"][-1], None


def test_no_date_only_parsed_anywhere():
    n = 0
    for objects, tz, cq, q, explicit in _all_fixture_turns():
        ctx = list(explicit) if explicit else []
        for t in cq + [q]:
            calls = []
            out = qp.ask(t, objects, ctx, now=NOW, timezone=tz, query_fn=lambda _q, **kw: calls.append(kw) or {})
            p = out["parse"]
            if p["kind"] == "parsed":
                assert "T" in p["params"]["as_of"] and calls == [p["params"]], (t, p)
            else:
                assert calls == []
            ctx.append(context_turn(t, p))
            n += 1
    assert n > 200


def test_eval_pins_v6():
    res = {r["split"]: r for r in ev.main([])}
    pins = {"dev_gold_v3": [12, 0, 9, 0, 7, 0, 0], "heldout_gold_v2": [14, 0, 6, 1, 3, 0, 0],
            "probes": [3, 0, 4, 2, 0, 1, 0], "counterexamples_v2": [8, 0, 12, 0, 0, 0, 0],
            "counterexamples_v3_gold_v2": [10, 0, 13, 0, 0, 0, 0], "counterexamples_v4": [14, 0, 8, 0, 0, 0, 0],
            "counterexamples_v5_gold_v2": [6, 0, 14, 0, 16, 0, 0], "counterexamples_v6": [7, 0, 9, 0, 6, 0, 0]}
    assert {k: list(v["counts"].values()) for k, v in res.items()} == pins
    r = reg.evaluate()
    assert list(r[("gold_v3", "v6")][1].values()) == [11, 0, 15, 0, 4, 0, 0]
    assert all(x["ask_not_called_on_non_parsed"] for rows, _ in r.values() for x in rows)
    assert reg.permutations(reg.load("independent_v4_gold_v3.json"), reg.parser_v6, False)["changed"] == []


@pytest.mark.parametrize("split", ev.V6_SPLITS)
def test_v6_permutation_invariance(split):
    assert ev.permutation_check(ev.parser_current, split, full=True)["changed"] == []
