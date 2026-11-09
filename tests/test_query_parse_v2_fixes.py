"""v2 fixes for the four confident misparses found in review of PR #14 (d550f3f).

For each case both the parse parameters AND whether the filter/query ran are
checked (spy ``query_fn``). With ambiguity the query must not run. The
defective v1 behaviour is kept as evidence in tests/test_query_parse_v1_defects.py.
Isolated synthetic data; no model calls.
"""
import pytest

from core.query_parse import ask, context_turn, parse_question
from tests import query_parse_eval as ev
from tests import query_parse_v1 as v1
from tests.test_applicability_live_path import admit, dumps, reopen
from tests.test_applicability_live_path import durable as durable  # fixture registration

OBJ = ev.SETUP["known_objects"]
OBJ_B = OBJ + [{"id": "B", "names": ["B", "Главный мост"]}]
NOW, TZ = ev.NOW, ev.SETUP["timezone"]
CE = ev.load_split("counterexamples_v2")


def spy_ask(question, context=None, objects=OBJ, tz=TZ, module=None):
    calls = []
    fn = (module.ask if module else ask)
    out = fn(question, objects, context, now=NOW, timezone=tz,
             query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    return out, calls


def assert_not_run(question, context=None, objects=OBJ, tz=TZ):
    out, calls = spy_ask(question, context, objects, tz)
    assert out["parse"]["kind"] == "needs_clarification", out["parse"]
    assert calls == [] and out["query_called"] is False and out["answer"] is None
    return out["parse"]


def assert_run(question, expected, context=None, objects=OBJ, tz=TZ):
    out, calls = spy_ask(question, context, objects, tz)
    assert out["parse"]["kind"] == "parsed", out["parse"]
    assert out["parse"]["params"] == {**expected, "temporal_scope": "current"}
    assert calls == [out["parse"]["params"]] and out["query_called"] is True
    return out["parse"]


# ── 1. time zone named in the question ─────────────────────────────────────

@pytest.mark.parametrize("q,as_of,zone", [
    ("Какой статус L был 8 ноября в 10:00 по московскому времени?", "2026-11-08T10:00:00+03:00", "Europe/Moscow"),
    ("Какой статус L был 8 ноября в 13:00 по Москве?", "2026-11-08T13:00:00+03:00", "Europe/Moscow"),
    ("Какой статус L был 8 ноября в 13:00 МСК?", "2026-11-08T13:00:00+03:00", "Europe/Moscow"),
    ("Какой статус L был 8 ноября в 13:00 по Берлину?", "2026-11-08T13:00:00+01:00", "Europe/Berlin"),
    ("Какой статус L был 8 ноября в 13:00 по берлинскому времени?", "2026-11-08T13:00:00+01:00", "Europe/Berlin"),
    ("Какой статус L был 8 ноября в 11:30 UTC?", "2026-11-08T11:30:00+00:00", "UTC"),
    ("Какой статус L был 8 ноября в 11:30 по UTC?", "2026-11-08T11:30:00+00:00", "UTC"),
])
def test_closed_list_zone_in_text_is_used(q, as_of, zone):
    r = assert_run(q, {"asked_object": "L", "as_of": as_of})
    assert zone in r["explanation"]["as_of"]
    assert "часовой пояс назван в вопросе" in r["explanation"]["as_of"]


def test_zone_in_text_used_even_without_default_zone_and_for_today_and_now():
    assert_run("Какой статус L был 8 ноября в 13:00 по Москве?", {"asked_object": "L", "as_of": "2026-11-08T13:00:00+03:00"},
               tz=None)
    assert_run("Какой статус L сейчас по московскому времени?", {"asked_object": "L", "as_of": "2026-11-09T09:58:00+03:00"})
    # «сегодня» is the calendar day in the NAMED zone: 23:30 UTC on 8 Nov is already 9 Nov in Moscow.
    from datetime import datetime, timezone as dt_tz
    late = datetime(2026, 11, 8, 23, 30, tzinfo=dt_tz.utc)
    r = parse_question("Какой статус L сегодня по UTC?", OBJ, now=late, timezone="Europe/Moscow")
    assert r["params"]["as_of"] == "2026-11-08"
    r = parse_question("Какой статус L сегодня по Москве?", OBJ, now=late, timezone="UTC")
    assert r["params"]["as_of"] == "2026-11-09"


@pytest.mark.parametrize("q", [
    "Какой статус L был 8 ноября в 13:00 по местному времени?",
    "Какой статус L был 8 ноября в 13:00 по киевскому времени?",
    "Какой статус L был 8 ноября в 13:00 GMT+3?",
    "Какой статус L был 8 ноября в 13:00 GMT?",
    "Какой статус L был 8 ноября в 13:00 по Лондону?",
    "Какой статус L был 8 ноября в 13:00 по Гринвичу?",
    "Какой статус L был 8 ноября в 13:00 МСК+1?",
    "Какой статус L был 8 ноября в 13:00+03:00?",
    "Какой статус L был 8 ноября в 13:00 в часовом поясе Самары?",
    "Какой статус L был 8 ноября в 13:00 по времени Самары?",
    "Какой статус L был 8 ноября в 13:00 по Москве или по Берлину?",
])
def test_unparsed_or_conflicting_zone_in_text_clarifies_and_does_not_query(q):
    r = assert_not_run(q)
    assert "часов" in r["question"] or "пояс" in r["reason"]


def test_utc_is_a_zone_not_an_object_and_city_word_may_still_be_an_object_alias():
    r = assert_run("Какой статус L был 8 ноября в 11:30 UTC?", {"asked_object": "L", "as_of": "2026-11-08T11:30:00+00:00"})
    assert "UTC" not in r["explanation"]["asked_object"]
    # «по Мосту» is an inflected object alias, not a city zone
    assert_run("Что по Мосту сейчас со статусом?", {"asked_object": "M", "as_of": "2026-11-09T07:58:00+01:00"})


def test_zone_named_in_follow_up_without_moment_does_not_reinterpret_old_moment_silently():
    ctx = [context_turn("q", parse_question("Какой статус L был 8 ноября в 10:00?", OBJ, now=NOW, timezone=TZ))]
    assert_not_run("А по московскому времени?", ctx)
    ctx_now = [context_turn("q", parse_question("Какой статус L сейчас?", OBJ, now=NOW, timezone=TZ))]
    assert_run("А по московскому времени?", {"asked_object": "L", "as_of": "2026-11-09T09:58:00+03:00"}, ctx_now)


def test_moscow_vs_berlin_give_different_grounds_v1_hid_it():
    """13:00 MSK = 11:00 CET -> L-repair; 13:00 CET -> L-ready. P01 (10:00) matched only by coincidence."""
    run = ev.make_filter()
    msk = ask("Какой статус L был 8 ноября в 13:00 по московскому времени?", OBJ, now=NOW, timezone=TZ, query_fn=run)
    ber = ask("Какой статус L был 8 ноября в 13:00 по Берлину?", OBJ, now=NOW, timezone=TZ, query_fn=run)
    assert [f["fact_id"] for f in msk["result"]["facts"]] == ["L-repair"] and msk["answer"] == "L: статус — на ремонте"
    assert [f["fact_id"] for f in ber["result"]["facts"]] == ["L-ready"] and ber["answer"] == "L: статус — готов"
    # v1 used Berlin for the Moscow question -> the Berlin answer (wrong grounds)
    old = v1.ask("Какой статус L был 8 ноября в 13:00 по московскому времени?", OBJ, now=NOW, timezone=TZ, query_fn=run)
    assert old["answer"] == "L: статус — готов"
    # P01 at 10:00: both readings fall in L-repair, so the v1 bug was invisible in the answer
    p01_v1 = v1.ask("Какой статус L был 8 ноября в 10:00 по московскому времени?", OBJ, now=NOW, timezone=TZ, query_fn=run)
    p01_v2 = ask("Какой статус L был 8 ноября в 10:00 по московскому времени?", OBJ, now=NOW, timezone=TZ, query_fn=run)
    assert p01_v1["answer"] == p01_v2["answer"] == "L: статус — на ремонте"
    assert p01_v1["parse"]["params"]["as_of"] != p01_v2["parse"]["params"]["as_of"]


def test_moscow_vs_berlin_on_live_store_memory_unchanged(durable):
    from core.query_pipeline import query
    for f in ev.SETUP["facts"]:
        admit(f["fact_id"], f["claim"], f["applicability"])
    reopen()
    before = dumps(durable)
    msk = ask("Какой статус L был 8 ноября в 13:00 по московскому времени?", OBJ, now=NOW, timezone=TZ, query_fn=query)
    ber = ask("Какой статус L был 8 ноября в 13:00 по Берлину?", OBJ, now=NOW, timezone=TZ, query_fn=query)
    assert msk["answer"] == "L: статус — на ремонте" and ber["answer"] == "L: статус — готов"
    assert ask("Какой статус L был 8 ноября в 13:00 по киевскому времени?", OBJ, now=NOW, timezone=TZ,
               query_fn=query)["query_called"] is False
    reopen()
    assert dumps(durable) == before


# ── 2. compound names are not replaced by a shorter alias ─────────────────

@pytest.mark.parametrize("q", ["Какой статус Главного моста сейчас?", "Какое сейчас состояние у Главного моста?",
                               "Какой статус у Главный мост сейчас?", "Что с Главным мостом сейчас по статусу?"])
def test_compound_name_resolves_to_compound_object(q):
    r = assert_run(q, {"asked_object": "B", "as_of": "2026-11-09T07:58:00+01:00"}, objects=OBJ_B)
    assert "→ объект B" in r["explanation"]["asked_object"]


def test_short_alias_alone_still_resolves_and_near_miss_clarifies():
    assert_run("Какой статус Моста сейчас?", {"asked_object": "M", "as_of": "2026-11-09T07:58:00+01:00"}, objects=OBJ_B)
    assert_run("Моста статус сейчас какой?", {"asked_object": "M", "as_of": "2026-11-09T07:58:00+01:00"}, objects=OBJ_B)
    r = assert_not_run("Какой статус Главнейшего моста сейчас?", objects=OBJ_B)
    assert r["candidates"] == ["B", "M"]
    # near-miss check also applies on the right-hand side of the short alias
    objs = OBJ + [{"id": "MS", "names": ["Мост северный"]}]
    assert assert_not_run("Какой статус Моста северного-нового сейчас?", objects=objs)["candidates"] == ["M", "MS"]
    assert_run("Какой статус Моста северного сейчас?", {"asked_object": "MS", "as_of": "2026-11-09T07:58:00+01:00"}, objects=objs)


@pytest.mark.parametrize("alias,form", [("Главная станция", "Главной станции"), ("Главная станция", "Главную станцию"),
                                        ("Новый мост", "Нового моста"), ("Старая сеть", "Старой сети")])
def test_multiword_inflection_word_by_word(alias, form):
    objs = [{"id": "X", "names": [alias]}]
    assert parse_question("Какой статус %s сейчас?" % form, objs, now=NOW, timezone=TZ)["params"]["asked_object"] == "X"


def test_unhandled_inflection_fails_closed_not_to_another_object():
    # Fleeting vowel («узел» -> «узла») is not handled by the light rules: the
    # alias is not found, so the parser asks instead of guessing.
    objs = [{"id": "X", "names": ["Новый узел"]}]
    r = parse_question("Какой статус Нового узла сейчас?", objs, now=NOW, timezone=TZ)
    assert r["kind"] == "needs_clarification" and r["candidates"] == ["X"]


def test_compound_fixed_v1_evidence_kept():
    v1_parse = v1.parse_question("Какой статус Главного моста сейчас?", OBJ_B, now=NOW, timezone=TZ)
    assert v1_parse["params"]["asked_object"] == "M"  # original defect, reproducible
    assert parse_question("Какой статус Главного моста сейчас?", OBJ_B, now=NOW, timezone=TZ)["params"]["asked_object"] == "B"


# ── 3. time alternatives / several time expressions ───────────────────────

@pytest.mark.parametrize("q", [
    "Какой статус L был 8 ноября в 10:00 или в 12:00?",
    "Какой статус L был 7 или 8 ноября?",
    "Какой статус L был 8 ноября в 10 или 11 часов?",
    "Статус L 8 и 9 ноября?",
    "Какой статус L был 8 ноября в 10:00 и 9 ноября в 10:00?",
    "Какой статус L был вчера или 7 ноября в 10:00?",
    "Какой статус L был вчера или сегодня?",
    "Какой статус L был 08.11 или 07.11 в 10:00?",
    "Какой статус L был 8 ноября в 10:00, а не в 12:00?",
])
def test_time_alternatives_clarify_and_do_not_query(q):
    r = assert_not_run(q)
    assert "несколько моментов" in r["question"]


def test_single_moment_forms_still_parse():
    assert_run("Какой статус L был 8 ноября в 10:00?", {"asked_object": "L", "as_of": "2026-11-08T10:00:00+01:00"})
    assert_run("Какой статус L был 08.11.2026 в 10:00?", {"asked_object": "L", "as_of": "2026-11-08T10:00:00+01:00"})
    assert_run("Статус M на 2026-11-08 10:00?", {"asked_object": "M", "as_of": "2026-11-08T10:00:00+01:00"})


# ── 4. a non-parsed turn must not silently restore the old object ─────────

def _ctx(*questions, objects=OBJ):
    ctx = []
    for q in questions:
        ctx.append(context_turn(q, parse_question(q, objects, ctx, now=NOW, timezone=TZ)))
    return ctx


def test_reviewer_sequence_unsupported_l2_then_pronoun_clarifies():
    ctx = _ctx("Какой статус L сейчас?", "Был ли L2 готов вчера в 10:00?")
    assert ctx[0]["asked_object"] == "L"
    assert ctx[1]["kind"] == "unsupported" and ctx[1]["mentioned_objects"] == ["L2"]
    r = assert_not_run("А его статус?", ctx)
    assert r["candidates"] == ["L", "L2"] and "смена объекта" in r["reason"]


@pytest.mark.parametrize("second", ["Что менялось у L2 за неделю?", "Какой статус L2 был вчера утром?",
                                    "Какой статус L2 был 8 ноября в 10:00 или в 12:00?",
                                    "Какой статус L2 был 8 ноября в 13:00 по киевскому времени?"])
def test_any_non_parsed_turn_mentioning_another_object_blocks_old_object(second):
    ctx = _ctx("Какой статус L сейчас?", second)
    assert "L2" in ctx[1]["mentioned_objects"]
    assert assert_not_run("А его статус?", ctx)["candidates"] == ["L", "L2"]


def test_non_parsed_turn_mentioning_only_the_same_object_keeps_it():
    ctx = _ctx("Какой статус L сейчас?", "Расскажи про L сейчас")
    r = assert_run("А его статус?", {"asked_object": "L", "as_of": "2026-11-09T07:58:00+01:00"}, ctx)
    assert "промежуточные реплики упоминали только этот объект" in r["explanation"]["asked_object"]


def test_mentions_without_prior_parsed_object_and_with_prior_ambiguity():
    ctx = _ctx("Что менялось у L2 за неделю?")
    assert assert_not_run("А его статус?", ctx)["candidates"] == ["L2"]
    ctx = _ctx("Какой статус Пульсара сейчас?", "Что менялось у L2 за неделю?")
    assert assert_not_run("А его статус?", ctx)["candidates"] == ["L2", "P1", "P2"]
    # negated mention is not a possible switch
    ctx = _ctx("Какой статус L сейчас?", "Не L2, а L — что менялось за неделю?")
    assert ctx[1]["mentioned_objects"] == ["L"]
    assert_run("А его статус?", {"asked_object": "L", "as_of": "2026-11-09T07:58:00+01:00"}, ctx)
    # explicit object in the follow-up is still honoured
    ctx = _ctx("Какой статус L сейчас?", "Был ли L2 готов вчера в 10:00?")
    assert_run("А какой статус L2 сейчас?", {"asked_object": "L2", "as_of": "2026-11-09T07:58:00+01:00"}, ctx)


def test_mention_outside_bounded_window_is_forgotten_with_the_turn():
    ctx = _ctx("Какой статус L сейчас?", "Был ли L2 готов вчера в 10:00?")
    filler = {"question": "x", "kind": "parsed", "asked_object": "L", "time_ref": "now", "as_of": "2026-11-09T07:58:00+01:00"}
    assert_run("А его статус?", {"asked_object": "L", "as_of": "2026-11-09T07:58:00+01:00"}, ctx + [filler])
    garbage = [{"question": "x", "kind": "unsupported", "mentioned_objects": [5, None]}]
    assert_run("А его статус?", {"asked_object": "L", "as_of": "2026-11-09T07:58:00+01:00"}, ctx[:1] + garbage)


# ── whole v2 counterexample set: gate holds, v1 vs v2 ─────────────────────

@pytest.mark.parametrize("it", CE["items"], ids=[i["id"] for i in CE["items"]])
def test_counterexample_gold_v2(it):
    objects = ev.split_objects(CE)
    ctx = ev.build_context(ev.parser_v2, it, objects, TZ)
    out, calls = spy_ask(it["question"], ctx, objects)
    gold = it["gold"]
    assert out["parse"]["kind"] == gold["kind"]
    if gold["kind"] == "parsed":
        assert out["parse"]["params"]["asked_object"] == gold["asked_object"]
        assert ev._same_instant(out["parse"]["params"]["as_of"], gold["as_of"])
        assert len(calls) == 1
    else:
        assert calls == []
