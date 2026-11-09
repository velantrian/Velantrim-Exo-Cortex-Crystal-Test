"""Run the FROZEN v4 parser on the independent set (tests/fixtures/query_parse/independent_v4.json).

The questions and gold are used unchanged. This module only maps the set's
format into the harness (see HARNESS_MAPPING); it changes no parsing rule.
Disagreements are classified by hand in DISAGREEMENTS (from the run output) and
are NOT fixed.  ``python -m tests.query_parse_independent_v4 [--write]``.
"""
import hashlib
import json
import sys
from datetime import datetime

from tests import query_parse_v4 as parser  # frozen v4 (byte-identical to tag query-parse-v4-frozen)
from tests import query_parse_eval as ev

FILE = ev.FIX / "independent_v4.json"
SHA_FILE = ev.FIX / "independent_v4.json.sha256"
OUT = ev.OUT / "independent_v4_results.json"
FROZEN_SHA = "81e1f6632163ddd1d88d365b2d8a7f2121197ac00885c9452c865a93a9ac9d26"

HARNESS_MAPPING = {
    "catalogue": "{id, aliases} -> known_objects {id, names: aliases} (order as given)",
    "now / default_tz": "file 'now' and 'default_tz' are passed as now= and timezone=",
    "turns": "all turns but the last are run through the same frozen parser and stored with context_turn "
             "(structured context); the last turn is the scored question. context_assumptions are not injected; "
             "the actual context kinds are recorded per item",
    "gold": "gold_outcome -> kind; gold_parameters.object_id -> asked_object; as_of compared as an instant, "
            "gold 'date' compared to a date-only as_of; temporal_scope must be 'current'",
    "query_fn": "a spy that records calls and returns a stub; the set supplies no facts, so the "
                "'answers differ from manual' column is not applicable (harness issue H1)",
}
HARNESS_ISSUES = [
    {"id": "H1", "issue": "the independent set has no facts, so admitted grounds and the 'answers differ from "
                          "manual' column cannot be computed; reported as n/a, not as 0"},
]


def load():
    raw = FILE.read_bytes()
    expected = SHA_FILE.read_text(encoding="utf-8").split()[0]
    assert hashlib.sha256(raw).hexdigest() == expected, "independent_v4.json sha256 mismatch"
    assert hashlib.sha256((ev.ROOT / "tests" / "query_parse_v4.py").read_bytes()).hexdigest() == FROZEN_SHA, \
        "tests/query_parse_v4.py is not the frozen v4 file"
    return json.loads(raw.decode("utf-8")), expected


def gold_of(it):
    g = {"kind": it["gold_outcome"]}
    if g["kind"] == "parsed":
        gp = it["gold_parameters"]
        assert gp["temporal_scope"] == "current"
        g |= {"asked_object": gp["object_id"], "as_of": gp["as_of"] if "as_of" in gp else gp["date"]}
    return g


def run_item(it, objects, now, tz):
    ctx = []
    for q in it["turns"][:-1]:
        ctx.append(parser.context_turn(q, parser.parse_question(q, objects, ctx, now=now, timezone=tz)))
    calls = []
    out = parser.ask(it["turns"][-1], objects, ctx, now=now, timezone=tz,
                     query_fn=lambda q, **kw: calls.append(kw) or {"answer": None})
    p = out["parse"]
    gold = gold_of(it)
    return {
        "id": it["id"], "turns": it["turns"], "contract_gap": it["contract_gap"],
        "context_assumptions": it["context_assumptions"],
        "actual_context": [{"question": c["question"], "kind": c["kind"],
                            **{k: c[k] for k in ("asked_object", "candidates", "confirmed_object") if k in c}}
                           for c in ctx],
        "gold": gold, "category": ev.classify(gold, p),
        "parser": {"kind": p["kind"], "params": p.get("params"), "clarification": p.get("question"),
                   "reason": p.get("reason"), "candidates": p.get("candidates"), "limitation": p.get("limitation"),
                   "explanation": p.get("explanation")},
        "query_calls": len(calls),
        "ask_not_called_on_non_parsed": p["kind"] == "parsed" or (calls == [] and out["query_called"] is False),
    }


def rotation_invariance(data, objects, now, tz):
    changed, variants = [], 0
    for it in data["items"]:
        seen = set()
        for objs in ev.catalogue_variants(objects, full=False):
            ctx = []
            for q in it["turns"][:-1]:
                ctx.append(parser.context_turn(q, parser.parse_question(q, objs, ctx, now=now, timezone=tz)))
            seen.add(ev.decision(parser.parse_question(it["turns"][-1], objs, ctx, now=now, timezone=tz)))
            variants += 1
        if len(seen) > 1:
            changed.append(it["id"])
    return {"orders": "all rotations x names as given/reversed (not all 8! permutations)",
            "variants": variants, "changed": changed}


def evaluate():
    data, sha = load()
    objects = [{"id": o["id"], "names": list(o["aliases"])} for o in data["catalogue"]]
    now, tz = datetime.fromisoformat(data["now"]), data["default_tz"]
    rows = [run_item(it, objects, now, tz) for it in data["items"]]
    counts = dict.fromkeys(ev.CATEGORIES, 0)
    for r in rows:
        counts[r["category"]] += 1
    return data, sha, objects, now, tz, rows, counts


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    data, sha, objects, now, tz, rows, counts = evaluate()
    print(len(rows), json.dumps(counts))
    for r in rows:
        if not r["category"].startswith("correct"):
            print(r["id"], r["category"], "gap" if r["contract_gap"] else "", r["turns"][-1], "|",
                  r["parser"]["params"] or r["parser"]["clarification"] or r["parser"]["limitation"],
                  "| ctx:", [c["kind"] for c in r["actual_context"]])
    assert all(r["ask_not_called_on_non_parsed"] for r in rows)
    if "--write" in argv:
        from tests.query_parse_independent_v4_review import DISAGREEMENTS
        bad = {r["id"] for r in rows if not r["category"].startswith("correct")}
        assert bad == set(DISAGREEMENTS), (bad, set(DISAGREEMENTS))
        payload = {
            "parser": "core/query_parse.py (frozen v4, tag query-parse-v4-frozen)", "parser_sha256": FROZEN_SHA,
            "questions_file": "tests/fixtures/query_parse/independent_v4.json", "questions_sha256": sha,
            "author_note": data["author_note"], "now": data["now"], "timezone": tz,
            "harness_mapping": HARNESS_MAPPING, "harness_issues": HARNESS_ISSUES,
            "n": len(rows), "counts": counts,
            "answers_differ_from_manual": "n/a (H1)",
            "clarifications_and_unsupported_with_no_query_call": all(r["ask_not_called_on_non_parsed"] for r in rows),
            "rotation_invariance": rotation_invariance(data, objects, now, tz),
            "disagreements": [dict(id=i, **v) for i, v in DISAGREEMENTS.items() if not v["contract_gap"]],
            "contract_gap_disagreements": [dict(id=i, **v) for i, v in DISAGREEMENTS.items() if v["contract_gap"]],
            "contract_gap_items_all": [r["id"] for r in rows if r["contract_gap"]],
            "rows": rows,
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return rows, counts


if __name__ == "__main__":
    main()
