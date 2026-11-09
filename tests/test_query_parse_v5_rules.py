"""v5 rules R1–R6 (user/Astra decision 2026-11-09). For every rule: parse
parameters, and a spy proving the memory query is NOT called on
clarification/unsupported. Isolated setup data only (L: «на ремонте» until
2026-11-08T11:59:59+01:00, «готов» from 12:00)."""
from datetime import datetime, timezone as dt_tz

import pytest

from core.query_parse import ask, context_turn, parse_question
from tests import query_parse_eval as ev
from tests import query_parse_regression_v5 as reg
from tests import query_parse_v4 as v4

OBJ, NOW, TZ = ev.SETUP["known_objects"], ev.NOW, ev.SETUP["timezone"]


def gated(question, context=None, now=NOW, tz=TZ, objects=OBJ, parser=None):
    calls = []
    fn = (parser or __import__("core.query_parse", fromlist=["ask"])).ask
    out = fn(question, objects, context, now=now, timezone=tz,
             query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    p = out["parse"]
    if p["kind"] == "parsed":
        assert calls == [p["params"]] and out["query_called"] is True
        assert "_future" not in p
    else:
        assert calls == [] and out["query_called"] is False and out["answer"] is None
        assert "_future" not in p
    return p


def ctx_of(*qs, now=NOW):
    ctx = []
    for q in qs:
        ctx.append(context_turn(q, parse_question(q, OBJ, ctx, now=now, timezone=TZ)))
    return ctx


# ── R1: time not parsed -> no query ─────────────────────────────────────────
@pytest.mark.parametrize("q,left", [
    ("Какой статус L был в десять утра 8 ноября?", "в десять утра"),
    ("Какой статус L был 8 ноября в десять?", "в десять"),
    ("Какой статус L был 8 ноября в 10?", "в 10"),
    ("Какой статус L был 8 ноября в час дня?", "час дня"),
    ("Какой статус L был 8 ноября в 9:00 вечером?", "вечером"),
    ("Какой статус L был 8 ноября в шесть вечера?", "в шесть вечера"),
    ("Какой статус L в десять?", "в десять"),
    ("Какой статус L был вчера в двенадцать часов?", "в двенадцать часов"),
])
def test_r1_unparsed_time_blocks_query(q, left):
    p = gated(q)
    assert p["kind"] == "needs_clarification" and "«%s»" % left in p["question"]
    assert "нельзя отбросить" in p["reason"]


def test_r1_v4_dropped_the_time_and_ran_a_query():
    assert gated("Какой статус L был в десять утра 8 ноября?", parser=v4)["params"]["as_of"] == "2026-11-08"
    assert gated("Какой статус L был 8 ноября в 9:00 вечером?", parser=v4)["params"]["as_of"] == "2026-11-08T09:00:00+01:00"


@pytest.mark.parametrize("q,as_of", [
    ("Какой статус L был 8 ноября в 9 вечера?", "2026-11-08T21:00:00+01:00"),
    ("Каким был статус L 8 ноября в 10 утра?", "2026-11-08T10:00:00+01:00"),
    ("Какой статус L был 8 ноября в 10 часов?", "2026-11-08T10:00:00+01:00"),
    ("Какой статус L был 8 ноября в 10:30 вечера?", "2026-11-08T22:30:00+01:00"),
])
def test_r1_supported_clock_forms_unchanged(q, as_of):
    assert gated(q)["params"] == {"asked_object": "L", "as_of": as_of, "temporal_scope": "current"}


def test_r1_bare_day_part_keeps_v1_message():
    assert "часть суток" in gated("Какой статус L вчера утром?")["reason"]


# ── R2: «сегодня в HH:MM» ───────────────────────────────────────────────────
def test_r2_today_with_clock_is_a_moment_in_the_explicit_zone():
    assert gated("Какой статус L сегодня в 07:00?")["params"]["as_of"] == "2026-11-09T07:00:00+01:00"
    assert gated("Какой статус L сегодня в 06:00 по UTC?")["params"]["as_of"] == "2026-11-09T06:00:00+00:00"
    later = datetime(2026, 11, 9, 9, 0, tzinfo=dt_tz.utc)  # 10:00 Berlin
    assert gated("Какой статус у L сегодня в 08:00?", now=later)["params"]["as_of"] == "2026-11-09T08:00:00+01:00"
    p = gated("Какой статус L сегодня в 07:00?", tz=None)
    assert p["kind"] == "needs_clarification" and "часовой пояс" in p["reason"]


# ── R3: explicit date without time ──────────────────────────────────────────
@pytest.mark.parametrize("q", ["Какой статус L был 7 ноября?", "Статус L на 2026-11-07?", "Статус L на 07.11?",
                               "Какой статус L был 8 ноября 2026 года?", "Какой статус L был весь день 7 ноября?"])
def test_r3_date_without_time_asks_for_the_time(q):
    p = gated(q)
    assert p["kind"] == "needs_clarification" and p["question"].startswith("На какое время")
    assert gated("А 7 ноября?", ctx_of("Какой статус L сейчас?"))["kind"] == "needs_clarification"


def test_r3_r4_today_and_yesterday_alone_keep_documented_whole_day():
    assert gated("Какой статус L сегодня?")["params"]["as_of"] == "2026-11-09"
    assert gated("Какой статус L был вчера?")["params"]["as_of"] == "2026-11-08"
    assert gated("Какой статус L весь день сегодня?")["params"]["as_of"] == "2026-11-09"
    assert gated("Какой статус L был весь день 7 ноября?", parser=v4)["params"]["as_of"] == "2026-11-07"  # v4: implicit


# ── R5: future moment -> unsupported, decided by the resolved time ──────────
@pytest.mark.parametrize("q,ctx", [
    ("Какой статус L 12 ноября в 10:00?", None), ("Какой статус L был 12 ноября?", None),
    ("Какой статус L будет 12 ноября в 10:00?", None), ("Какой статус L будет?", None),
    ("Статус L на 2027-01-05 10:00?", None), ("Какой статус L сегодня в 08:00?", None),
    ("Какой статус Пульсара 12 ноября в 10:00?", None), ("Какой статус Z будет?", None),
    ("А 12 ноября в 10:00?", ("Какой статус L сейчас?",)), ("А что будет?", ("Какой статус L сейчас?",)),
    ("Какой статус L был 12 ноября в 10:00 по Москве?", None),
])
def test_r5_future_is_unsupported(q, ctx):
    p = gated(q, ctx_of(*ctx) if ctx else None)
    assert p["kind"] == "unsupported" and "будущ" in p["limitation"]


def test_r5_future_word_with_past_or_current_time_clarifies():
    for q in ("Какой статус L будет 8 ноября в 10:00?", "Какой статус L будет сейчас?", "Какой статус L будет сегодня?"):
        p = gated(q)
        assert p["kind"] == "needs_clarification" and "противоречат" in p["reason"], q
    assert gated("Какой статус L будет 8 ноября?")["question"].startswith("На какое время")  # R3 first
    assert gated("Какой статус L будет 8 ноября в 10:00?", parser=v4)["kind"] == "unsupported"  # v4: by the word


def test_r5_past_moment_still_parsed_and_year_not_asked():
    assert gated("Какой статус L был 8 ноября в 10:00?")["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    assert gated("Какой статус L 12 ноября в 10:00?", parser=v4)["question"].startswith("Какой год")  # v4


def test_r5_inside_confirmed_choice_and_collision():
    obj = ev.split_objects(ev.load_split("counterexamples_v4"))
    p = gated("Какой статус Моста 12 ноября в 10:00?", objects=obj)
    assert p["kind"] == "unsupported"


# ── R6: comparisons ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("q", ["У L статус сейчас лучше, чем у L2?", "Статус L хуже, чем у L2?",
                               "Отличается ли статус L от L2 сейчас?", "Есть ли разница в статусе L и L2 сейчас?",
                               "У L и L2 одинаковый статус сейчас?", "Какой статус L сейчас по сравнению с L2?",
                               "Статус L сейчас лучше?"])
def test_r6_comparison_is_unsupported(q):
    p = gated(q)
    assert p["kind"] == "unsupported" and "сравнение" in p["limitation"]
    assert gated("У L статус сейчас лучше, чем у L2?", parser=v4)["kind"] == "needs_clarification"  # v4


# ── morning / evening: losing the time changes the answer ───────────────────
def test_morning_evening_example():
    me = ev.morning_evening()
    manual = {m["as_of"][11:16]: m["answer"] for m in me["manual"]}
    assert manual == {"09:00": "L: статус — на ремонте", "10:00": "L: статус — на ремонте",
                      "18:00": "L: статус — готов", "21:00": "L: статус — готов"}
    items = {i["id"]: i for i in me["items"]}
    assert items["V01"]["v4"]["query_called"] and items["V01"]["v4"]["answer"] is None  # whole day: no answer
    assert items["V05"]["v4"]["answer"] == "L: статус — на ремонте"  # 09:00, «вечером» dropped
    assert all(not i["v5"]["query_called"] and i["v5"]["kind"] == "needs_clarification" for i in me["items"])
    assert "Morning vs evening" in ev.morning_evening_md(me)


# ── regression set (former independent set) and invariance ──────────────────
def test_regression_set_scores():
    res = reg.evaluate()
    assert res[("gold_v2", "v5")][1] == {"correct_parse": 13, "confident_misparse": 0, "correct_clarification": 13,
                                         "unnecessary_clarification": 0, "correct_unsupported": 4,
                                         "wrong_unsupported": 0, "clarification_instead_of_unsupported": 0}
    assert [r["id"] for r in res[("original", "v5")][0] if not r["category"].startswith("correct")] == ["I15", "I19"]
    assert all(r["ask_not_called_on_non_parsed"] for rows, _ in res.values() for r in rows)
    assert reg.permutations(reg.load("independent_v4_gold_v2.json"), reg.parser_v5, False)["changed"] == []


@pytest.mark.parametrize("split", ["dev_gold_v2", "counterexamples_v5"])
def test_v5_sets_permutation_invariant(split):
    assert ev.permutation_check(ev.parser_current, split, full=True)["changed"] == []
