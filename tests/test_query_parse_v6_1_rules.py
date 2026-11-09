"""v6.1 (user decision 2026-11-09): a later turn with an unresolved time or an
unfinished clarification, or an intermediate unsupported question with another
time, blocks inheriting the time of an older parsed turn. Inheriting an exact
moment from unambiguous context stays. Every blocked case is checked with a spy:
the memory query (ask -> query_fn) is not called. Isolated setup data only."""
import pytest

import core.query_parse as qp
from core.query_parse import context_turn
from tests import query_parse_eval as ev
from tests import query_parse_regression_v6_1 as reg
from tests import query_parse_v6 as v6

OBJ, NOW, TZ = ev.SETUP["known_objects"], ev.NOW, ev.SETUP["timezone"]
NOW_S, T10 = "2026-11-09T07:58:00+01:00", "2026-11-08T10:00:00+01:00"
Q_NOW, Q_10 = "Какой статус L сейчас?", "Какой статус L был 8 ноября в 10:00?"


def gated(question, context=None, parser=qp):
    calls = []
    out = parser.ask(question, OBJ, context, now=NOW, timezone=TZ,
                     query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    p = out["parse"]
    if p["kind"] == "parsed":
        assert calls == [p["params"]] and out["query_called"] is True
    else:
        assert calls == [] and out["query_called"] is False and out["answer"] is None
    return p, calls


def ctx_of(*qs, parser=qp):
    ctx = []
    for q in qs:
        ctx.append(parser.context_turn(q, parser.parse_question(q, OBJ, ctx, now=NOW, timezone=TZ)))
    return ctx


BLOCKED = [
    (Q_NOW, "А L вчера?"), (Q_NOW, "Какой статус L вчера?"),
    (Q_NOW, "Какой статус L будет 12 ноября в 10:00?"), (Q_NOW, "Какой статус L был весь день вчера?"),
    (Q_NOW, "Что менялось у L за неделю?"), (Q_NOW, "Какой статус L был в десять утра 8 ноября?"),
    (Q_NOW, "Какой статус L был 8 ноября в 13:00 по Лондону?"), (Q_NOW, "Какой статус L был 8 ноября в 10:00 или в 12:00?"),
    (Q_NOW, "Какой статус L?"), (Q_10, "Какой статус L сегодня?"), (Q_10, "Расскажи про L сейчас"),
]


@pytest.mark.parametrize("seq", BLOCKED)
def test_later_unresolved_or_other_time_blocks_inheritance(seq):
    ctx = ctx_of(*seq)
    p, calls = gated("А его статус?", ctx)
    assert p["kind"] == "needs_clarification" and calls == []
    assert p["question"].startswith("На какой момент нужен статус L") and "не наследуется" in p["reason"]
    # the clarification stays open: asking again does not fall back to the old moment
    ctx.append(context_turn("А его статус?", p))
    p2, calls2 = gated("А его статус?", ctx)
    assert p2["kind"] == "needs_clarification" and calls2 == []
    # v6 (frozen) silently went back to the old moment
    old, old_calls = gated("А его статус?", ctx_of(*seq, parser=v6), parser=v6)
    assert old["kind"] == "parsed" and old_calls == [old["params"]]


def test_new_explicit_time_and_answering_the_clarification():
    ctx = ctx_of(Q_NOW, "А L вчера?")
    for q in ("А его статус вчера в 10:00?", "А вчера в 10:00?"):
        p, calls = gated(q, ctx)
        assert p["params"] == {"asked_object": "L", "as_of": T10, "temporal_scope": "current"} and len(calls) == 1
    p, _ = gated("А его статус?", ctx_of(Q_NOW, "А L вчера?", "А его статус вчера в 10:00?"))
    assert p["params"]["as_of"] == T10
    p, _ = gated("А на 8 ноября в 10:00?", ctx_of(Q_NOW, "А L вчера?", "А его статус?"))
    assert p["params"]["as_of"] == T10


def test_positive_controls_inherit():
    assert gated("А его статус?", ctx_of(Q_10))[0]["params"] == {"asked_object": "L", "as_of": T10, "temporal_scope": "current"}
    assert gated("А L2?", ctx_of(Q_10))[0]["params"] == {"asked_object": "L2", "as_of": T10, "temporal_scope": "current"}
    assert gated("А его?", ctx_of(Q_NOW))[0]["params"]["as_of"] == NOW_S


@pytest.mark.parametrize("seq,as_of", [((Q_10, "Что менялось у L?"), T10), ((Q_NOW, "У L статус лучше?"), NOW_S),
                                       ((Q_NOW, "Расскажи про L сейчас"), NOW_S)])
def test_intermediate_turn_without_time_or_with_same_time_does_not_block(seq, as_of):
    ctx = ctx_of(*seq)
    assert ctx[-1]["kind"] == "unsupported"
    assert gated("А его статус?", ctx)[0]["params"]["as_of"] == as_of


def test_named_object_follow_up_unchanged():
    p, calls = gated("А L2?", ctx_of(Q_NOW, "А L вчера?"))
    assert p["kind"] == "needs_clarification" and calls == []


def test_time_state_is_structured_and_bounded():
    assert ctx_of(Q_NOW, "А L вчера?")[-1]["time_state"] == "unresolved"
    assert ctx_of(Q_10, "Расскажи про L сейчас")[-1]["time_state"] == {"time_ref": "now", "as_of": NOW_S}
    assert "time_state" not in ctx_of(Q_10, "Что менялось у L?")[-1]
    assert "time_state" not in ctx_of(Q_10)[-1]  # parsed turns keep time_ref/as_of
    # absolute vs absolute: the same instant in another offset does not block, another instant does
    base = {"question": "q", "kind": "parsed", "asked_object": "L", "time_ref": "absolute", "as_of": T10}
    mid = {"question": "m", "kind": "unsupported", "time_state": {"time_ref": "absolute", "as_of": "2026-11-08T09:00:00+00:00"}}
    assert gated("А его статус?", [base, mid])[0]["params"]["as_of"] == T10
    mid["time_state"]["as_of"] = "2026-11-08T12:00:00+01:00"
    assert gated("А его статус?", [base, mid])[0]["kind"] == "needs_clarification"
    mid["time_state"]["as_of"] = "garbage"
    assert gated("А его статус?", [base, mid])[0]["kind"] == "needs_clarification"
    # a blocking turn outside the bounded window is not seen
    far = [base, {"question": "m", "kind": "unsupported", "time_state": "unresolved"}, dict(base), dict(base), dict(base)]
    assert gated("А его статус?", far)[0]["params"]["as_of"] == T10


def test_zone_follow_up_after_moment_is_an_open_time_clarification():
    ctx = ctx_of(Q_10, "А по Москве?")
    assert ctx[-1]["time_state"] == "unresolved"
    assert gated("А его статус?", ctx)[0]["kind"] == "needs_clarification"


def test_eval_pins_v6_1():
    res = {r["split"]: r for r in ev.main([])}  # the harness default is v6_1 now
    pins = {"dev_gold_v3": [12, 0, 9, 0, 7, 0, 0], "heldout_gold_v2": [14, 0, 6, 1, 3, 0, 0],
            "probes": [3, 0, 4, 2, 0, 1, 0], "counterexamples_v2": [8, 0, 12, 0, 0, 0, 0],
            "counterexamples_v3_gold_v2": [10, 0, 13, 0, 0, 0, 0], "counterexamples_v4": [14, 0, 8, 0, 0, 0, 0],
            "counterexamples_v5_gold_v2": [6, 0, 14, 0, 16, 0, 0], "counterexamples_v6": [7, 0, 9, 0, 6, 0, 0],
            "counterexamples_v6_1": [9, 0, 12, 0, 0, 0, 0]}
    assert {k: list(v["counts"].values()) for k, v in res.items()} == pins
    assert list(ev.evaluate("counterexamples_v6_1", ev.PARSERS["v6"])["counts"].values()) == [9, 11, 1, 0, 0, 0, 0]
    r = reg.main([])
    assert list(r[("gold_v3", "v6_1")][1].values()) == [11, 0, 15, 0, 4, 0, 0]
    assert reg.permutations(reg.load("independent_v4_gold_v3.json"), qp, False)["changed"] == []


def test_v6_1_permutation_invariance():
    assert ev.permutation_check(ev.parser_current, "counterexamples_v6_1", full=True)["changed"] == []
