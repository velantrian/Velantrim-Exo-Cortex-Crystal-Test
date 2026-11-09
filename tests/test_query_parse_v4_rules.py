"""v4 rules (user rule change 2026-11-09): direct-vs-inflection collision asks,
explicit identifiers select, a confirmed choice may be used in bounded context.

Every clarification is checked with a spy: the memory query does not run.
Catalogue-order invariance is re-checked for the new cases. Isolated data.
"""
from copy import deepcopy
from datetime import datetime, timezone as dt_tz

import pytest

from core.query_parse import ask, context_turn, parse_question
from tests import query_parse_eval as ev

NOW, TZ = ev.NOW, ev.SETUP["timezone"]
OBJ = ev.split_objects(ev.load_split("counterexamples_v4"))  # setup + Y «Моста»
NOW_S = "2026-11-09T07:58:00+01:00"


def gated(question, context=None, objects=OBJ, now=NOW, tz=TZ):
    calls = []
    out = ask(question, objects, context, now=now, timezone=tz,
              query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    p = out["parse"]
    if p["kind"] == "parsed":
        assert calls == [p["params"]] and out["query_called"] is True
    else:
        assert calls == [] and out["query_called"] is False and out["answer"] is None
    return p


def ctx_of(*questions, objects=OBJ, now=NOW, tz=TZ):
    ctx = []
    for q in questions:
        ctx.append(context_turn(q, parse_question(q, objects, ctx, now=now, timezone=tz)))
    return ctx


def test_direct_and_inflected_match_both_kept_and_asked():
    p = gated("Какой статус Моста сейчас?")
    assert p["kind"] == "needs_clarification" and p["candidates"] == ["M", "Y"]
    assert p["pending_time"] == {"time_ref": "now", "as_of": NOW_S, "tz": None}
    assert gated("Какой статус Мост сейчас?")["params"]["asked_object"] == "M"


@pytest.mark.parametrize("q,obj", [("Какой статус объекта M сейчас?", "M"), ("Какой статус объекта Y сейчас?", "Y"),
                                   ("Какой статус Моста (объект M) сейчас?", "M"), ("Какой статус Моста, объекта Y, сейчас?", "Y"),
                                   ("Какой статус Моста (M) сейчас?", "M"), ("Какой статус объекту Y сейчас?", "Y"),
                                   ("Какой статус Пульсара (объект P2) сейчас?", "P2")])
def test_explicit_identifier_selects(q, obj):
    p = gated(q)
    assert p["params"]["asked_object"] == obj and "явный идентификатор" in p["explanation"]["asked_object"]


@pytest.mark.parametrize("q,cands", [
    ("Какой статус Моста (объект L) сейчас?", ["L", "M", "Y"]),
    ("Какой статус Моста и объекта Y сейчас?", ["M", "Y"]),
    ("Какой статус объекта M или объекта Y сейчас?", ["M", "Y"]),
    ("Какой статус объекта M (объект Y) сейчас?", ["M", "Y"]),
    ("Какой статус объекта M и Z сейчас?", ["M", "Z"]),
])
def test_explicit_identifier_conflicts_clarify(q, cands):
    p = gated(q)
    assert p["kind"] == "needs_clarification" and p["candidates"] == cands


def test_lowercase_id_after_object_word_is_not_an_explicit_identifier():
    # ids are case-sensitive in #503; «объекта m» is a name match (alias M), not the id written exactly
    p = gated("Какой статус объекта m сейчас?")
    assert p["params"]["asked_object"] == "M" and "явный идентификатор" not in p["explanation"]["asked_object"]


def test_confirmed_choice_answers_clarified_question_and_is_kept_in_context():
    ctx = ctx_of("Какой статус Моста сейчас?")
    assert ctx[0]["pending_time"]["time_ref"] == "now"
    later = datetime(2026, 11, 9, 9, 0, tzinfo=dt_tz.utc)
    p = gated("M", ctx, now=later)
    assert p["params"] == {"asked_object": "M", "as_of": "2026-11-09T10:00:00+01:00", "temporal_scope": "current"}
    assert p["confirmed_object"] == "M" and "подтверждённый выбор" in p["explanation"]["asked_object"]
    ctx = ctx + [context_turn("M", p)]
    assert ctx[-1]["confirmed_object"] == "M"
    assert gated("А его статус сейчас?", ctx)["params"]["asked_object"] == "M"
    assert gated("Какой статус Моста сейчас?", ctx)["params"]["asked_object"] == "M"
    assert "подтверждён пользователем" in gated("Какой статус Моста сейчас?", ctx)["explanation"]["asked_object"]
    assert gated("объект M", ctx_of("Какой статус Моста сейчас?"))["params"]["asked_object"] == "M"
    assert gated("Да, Y", ctx_of("Какой статус Моста сейчас?"))["params"]["asked_object"] == "Y"


def test_confirmed_choice_with_named_zone_and_absolute_time():
    ctx = ctx_of("Какой статус Моста сейчас по московскому времени?")
    assert ctx[0]["pending_time"]["tz"] == "Europe/Moscow"
    assert gated("M", ctx)["params"]["as_of"] == "2026-11-09T09:58:00+03:00"
    ctx = ctx_of("Какой статус Мостами был 8 ноября в 10:00?")
    assert gated("Y", ctx)["params"]["as_of"] == "2026-11-08T10:00:00+01:00"
    ctx = ctx_of("Какой статус Моста сегодня?")  # v6 C1: no usable moment -> the choice asks for the time
    p = gated("Y", ctx)
    assert p["kind"] == "needs_clarification" and p["confirmed_object"] == "Y"


def test_confirmed_choice_without_time_asks_time_but_keeps_choice():
    ctx = ctx_of("Какой статус Моста?")
    assert "pending_time" not in ctx[0]
    p = gated("M", ctx)
    assert p["kind"] == "needs_clarification" and p["confirmed_object"] == "M"
    ctx.append(context_turn("M", p))
    assert ctx[-1]["confirmed_object"] == "M"
    assert gated("А сейчас?", ctx)["params"] == {"asked_object": "M", "as_of": NOW_S, "temporal_scope": "current"}
    assert gated("А его статус?", ctx)["kind"] == "needs_clarification"  # object known, time still not
    assert gated("Какой статус Моста сейчас?", ctx)["params"]["asked_object"] == "M"


def test_confirmed_choice_without_now_is_unsupported():
    ctx = ctx_of("Какой статус Моста сейчас?")
    assert gated("M", ctx, now=None)["kind"] == "unsupported"


@pytest.mark.parametrize("answer,cands", [("L", ["M", "Y"]), ("Мостами", ["M", "Y"]), ("объект Z", None)])
def test_answers_that_do_not_pick_exactly_one_offered_object(answer, cands):
    p = gated(answer, ctx_of("Какой статус Моста сейчас?"))
    assert p["kind"] in ("needs_clarification", "unsupported")
    if cands is not None:
        assert p["candidates"] == cands


def test_conflicting_context_prefers_clarification():
    base = ["Какой статус Моста сейчас?", "M"]
    for later in ("Что менялось у Y за неделю?", "Какой статус Y сейчас?", "Какой статус объекта Y сейчас?"):
        ctx = ctx_of(*base, later)
        p = gated("Какой статус Моста сейчас?", ctx)
        assert p["kind"] == "needs_clarification" and p["candidates"] == ["M", "Y"], later
        assert "противоречив" in p["reason"]
    # unrelated later turn does not conflict
    ctx = ctx_of(*base, "Какой статус L сейчас?")
    assert gated("Какой статус Моста сейчас?", ctx)["params"]["asked_object"] == "M"
    # out of the bounded window -> ask again
    ctx = ctx_of(*base, "Какой статус L сейчас?", "Какой статус L2 сейчас?", "Какой статус P1 сейчас?")
    assert gated("Какой статус Моста сейчас?", ctx)["kind"] == "needs_clarification"
    # a confirmation for another collision does not resolve this one
    ctx = ctx_of("Какой статус Пульсара сейчас?", "P1")
    assert gated("Какой статус Моста сейчас?", ctx)["candidates"] == ["M", "Y"]


def test_bare_object_without_preceding_clarification_keeps_v3_behaviour():
    assert gated("M")["kind"] == "unsupported"
    assert gated("M", ctx_of("Какой статус L сейчас?"))["kind"] == "unsupported"  # not a clarification answer
    assert gated("M", ctx_of("Что менялось у L за неделю?"))["kind"] == "unsupported"


@pytest.mark.parametrize("split", ["counterexamples_v3_gold_v2", "counterexamples_v4"])
def test_new_sets_permutation_invariant(split):
    res = ev.permutation_check(ev.parser_current, split, full=True)
    assert res["changed"] == []


def test_inputs_and_context_not_mutated():
    objs = deepcopy(OBJ)
    ctx = ctx_of("Какой статус Моста сейчас?", "M")
    snap = deepcopy(ctx)
    gated("Какой статус Моста сейчас?", ctx, objects=objs)
    assert objs == OBJ and ctx == snap
