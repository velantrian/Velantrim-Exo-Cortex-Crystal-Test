"""Evidence of three v2 defect classes found after eee4062.

Runs the FROZEN v2 snapshot ``tests/query_parse_v2.py`` (byte-identical to
``core/query_parse.py`` at eee4062, sha256 d2cab8d0…92d0) and asserts its
DEFECTIVE behaviour, so the evidence stays reproducible after the fix. These
document v2; they are not the specification (see test_query_parse_v3_props.py).
"""
from tests import query_parse_eval as ev
from tests import query_parse_v2 as v2

OBJ = ev.SETUP["known_objects"]
NOW, TZ = ev.NOW, ev.SETUP["timezone"]


def run(question, objects=OBJ):
    calls = []
    out = v2.ask(question, objects, None, now=NOW, timezone=TZ,
                 query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    return out["parse"], calls


def test_v2_defect_1_zone_case_changes_decision():
    parse, calls = run("Какой статус L был 8 ноября в 13:00 по Лондону?")
    assert parse["kind"] == "needs_clarification" and calls == []
    for q in ("Какой статус L был 8 ноября в 13:00 по лондону?", "По Лондону какой статус L был 8 ноября в 13:00?",
              "Какой статус L был 8 ноября в 13:00 ПО ЛОНДОНУ?"):
        parse, calls = run(q)
        # unknown zone silently ignored, default Berlin used, query ran
        assert parse["params"]["as_of"] == "2026-11-08T13:00:00+01:00" and len(calls) == 1


def test_v2_defect_2_clock_truncated_to_minutes():
    for q, wrong in (("Какой статус L был 8 ноября в 10:00:30?", "2026-11-08T10:00:00+01:00"),
                     ("Какой статус L был 8 ноября в 10:00:30 по Москве?", "2026-11-08T10:00:00+03:00"),
                     ("Статус L на 2026-11-08 10:00:30?", "2026-11-08T10:00:00+01:00"),
                     ("Какой статус L был 8 ноября в 10:00:61?", "2026-11-08T10:00:00+01:00"),
                     ("Какой статус L был 8 ноября в 10 часов 30 минут?", "2026-11-08T10:00:00+01:00"),
                     ("Какой статус L был 8 ноября в 10:30 вечера?", "2026-11-08T10:30:00+01:00"),
                     ("Какой статус L был 8 ноября в половине десятого?", "2026-11-08")):
        parse, calls = run(q)
        assert parse["params"]["as_of"] == wrong and len(calls) == 1, q


def test_v2_defect_3_object_choice_depends_on_catalogue_order():
    m, y = {"id": "M", "names": ["Мост"]}, {"id": "Y", "names": ["Моста"]}
    for q in ("Какой статус Моста сейчас?", "Какой статус Мостами сейчас?"):
        first, c1 = run(q, [m, y])
        second, c2 = run(q, [y, m])
        assert first["params"]["asked_object"] == "M" and second["params"]["asked_object"] == "Y"
        assert len(c1) == len(c2) == 1
    res = ev.permutation_check(v2, "counterexamples_v3")
    assert res["changed"] == ["K20", "K21"]
