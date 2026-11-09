"""Evidence of the v1 confident misparses reported in review of PR #14 (d550f3f).

These tests run the FROZEN v1 snapshot ``tests/query_parse_v1.py`` (byte-identical
to ``core/query_parse.py`` at d550f3f, sha256 2182d38a…e6e3) and assert its
DEFECTIVE behaviour, so the original evidence stays reproducible after the fix.
They document v1; they are not the specification. The fixed behaviour is pinned
in ``tests/test_query_parse_v2_fixes.py`` against ``core.query_parse``.
"""
from tests import query_parse_eval as ev
from tests import query_parse_v1 as v1

OBJ = ev.SETUP["known_objects"]
OBJ_B = OBJ + [{"id": "B", "names": ["B", "Главный мост"]}]
NOW, TZ = ev.NOW, ev.SETUP["timezone"]


def run(question, context=None, objects=OBJ):
    calls = []
    out = v1.ask(question, objects, context, now=NOW, timezone=TZ,
                 query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    return out["parse"], calls


def test_v1_defect_1_zone_named_in_question_is_ignored():
    parse, calls = run("Какой статус L был 8 ноября в 10:00 по московскому времени?")
    assert parse["params"]["as_of"] == "2026-11-08T10:00:00+01:00"  # Berlin, not +03:00
    assert len(calls) == 1
    parse, calls = run("Какой статус L был 8 ноября в 13:00 по московскому времени?")
    assert parse["params"]["as_of"] == "2026-11-08T13:00:00+01:00" and len(calls) == 1
    # UTC is taken for an unknown object
    parse, calls = run("Какой статус L был 8 ноября в 11:30 UTC?")
    assert parse["kind"] == "needs_clarification" and "UTC" in parse["candidates"] and calls == []


def test_v1_defect_2_compound_name_replaced_by_short_alias():
    # Original unit-test assertion from d550f3f, kept verbatim as evidence.
    objs = OBJ + [{"id": "B", "names": ["Главный мост", "!!!"]}, {"id": "", "names": ["x"]}, {"names": ["y"]}]
    assert v1.parse_question("Какой статус Главного моста сейчас?", objs, now=NOW, timezone=TZ)["params"]["asked_object"] == "M"
    parse, calls = run("Какой статус Главного моста сейчас?", objects=OBJ_B)
    assert parse["params"]["asked_object"] == "M" and len(calls) == 1


def test_v1_defect_3_first_time_alternative_wins():
    parse, calls = run("Какой статус L был 8 ноября в 10:00 или в 12:00?")
    assert parse["params"]["as_of"] == "2026-11-08T10:00:00+01:00" and len(calls) == 1
    parse, calls = run("Какой статус L был 7 или 8 ноября?")
    assert parse["kind"] == "parsed" and len(calls) == 1


def test_v1_defect_4_unsupported_turn_loses_l2_and_pronoun_returns_to_l():
    ctx = []
    for q in ("Какой статус L сейчас?", "Был ли L2 готов вчера в 10:00?"):
        ctx.append(v1.context_turn(q, v1.parse_question(q, OBJ, ctx, now=NOW, timezone=TZ)))
    assert [t["kind"] for t in ctx] == ["parsed", "unsupported"]
    assert ctx[1] == {"question": "Был ли L2 готов вчера в 10:00?", "kind": "unsupported"}  # L2 lost
    parse, calls = run("А его статус?", ctx)
    assert parse["params"]["asked_object"] == "L" and len(calls) == 1
