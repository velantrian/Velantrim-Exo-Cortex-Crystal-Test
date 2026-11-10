"""Evidence for the 2026-11-09 rule change (user), on the FROZEN v3 snapshot.

``tests/query_parse_v3.py`` is byte-identical to ``core/query_parse.py`` at a6d11f3
(sha256 bd5e8f7a…2897). Under the old gold (counterexamples_v3.json) v3 had no
confident misparse; under gold v2 (counterexamples_v3_gold_v2.json) its
«exact beats inflection» choice for K20 is a confident misparse. These tests
document v3 against both gold versions; they are not the v4 specification.
"""
import json

from tests import query_parse_eval as ev
from tests import query_parse_v3 as v3

NOW, TZ = ev.NOW, ev.SETUP["timezone"]


def test_gold_v2_changes_only_k20_and_explains_it():
    old = ev.load_split("counterexamples_v3")
    new = ev.load_split("counterexamples_v3_gold_v2")
    assert [i["question"] for i in old["items"]] == [i["question"] for i in new["items"]]
    changed = [n["id"] for o, n in zip(old["items"], new["items"]) if o["gold"] != n["gold"]]
    assert changed == ["K20"]
    ch = new["gold_changes"]
    assert [c["id"] for c in ch] == ["K20"]
    assert ch[0]["old_gold"]["asked_object"] == "Y" and ch[0]["new_gold"] == {"kind": "needs_clarification"}
    assert "2026-11-09" in ch[0]["reason"] and "NOT a consequence of any parser result" in ch[0]["reason"]


def test_v3_scored_against_old_and_new_gold():
    assert ev.evaluate("counterexamples_v3", v3)["counts"]["confident_misparse"] == 0
    r = ev.evaluate("counterexamples_v3_gold_v2", v3)
    assert r["counts"]["confident_misparse"] == 1
    assert [x["id"] for x in r["rows"] if x["category"] == "confident_misparse"] == ["K20"]


def test_v3_picks_exact_alias_and_runs_query():
    objs = ev.split_objects(ev.load_split("counterexamples_v3"))
    calls = []
    out = v3.ask("Какой статус Моста сейчас?", objs, None, now=NOW, timezone=TZ,
                 query_fn=lambda q, **kw: calls.append(kw) or {"answer": "x"})
    assert out["parse"]["params"]["asked_object"] == "Y" and len(calls) == 1
