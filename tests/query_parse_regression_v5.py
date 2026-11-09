"""v5: the 30 questions of independent_v4.json are a REGRESSION set now (opened
after the v4 run; not independent any more). Scored with the original gold
(independent_v4.json) and with gold v2 (independent_v4_gold_v2.json, R1-R6
decision of 2026-11-09), for the frozen v4 parser and the current parser.
``python -m tests.query_parse_regression_v5 [--write] [--full-permutations]``.
"""
import json
import sys
from datetime import datetime

import core.query_parse as parser_v5
from tests import query_parse_eval as ev
from tests import query_parse_independent_v4 as ind
from tests import query_parse_v4 as parser_v4

GOLDS = (("original", "independent_v4.json"), ("gold_v2", "independent_v4_gold_v2.json"))
PARSERS = (("v4", parser_v4), ("v5", parser_v5))
OUT = ev.OUT / "regression_independent_v5.json"


def load(name):
    return json.loads((ev.FIX / name).read_text(encoding="utf-8"))


def score(data, parser):
    objects = [{"id": o["id"], "names": list(o["aliases"])} for o in data["catalogue"]]
    now, tz = datetime.fromisoformat(data["now"]), data["default_tz"]
    rows = [ind.run_item(it, objects, now, tz, parser) for it in data["items"]]
    counts = dict.fromkeys(ev.CATEGORIES, 0)
    for r in rows:
        counts[r["category"]] += 1
    return rows, counts


def permutations(data, parser, full):
    objects = [{"id": o["id"], "names": list(o["aliases"])} for o in data["catalogue"]]
    now, tz = datetime.fromisoformat(data["now"]), data["default_tz"]
    changed, variants = [], 0
    for it in data["items"]:
        seen = set()
        for objs in ev.catalogue_variants(objects, full=full):
            ctx = []
            for q in it["turns"][:-1]:
                ctx.append(parser.context_turn(q, parser.parse_question(q, objs, ctx, now=now, timezone=tz)))
            seen.add(ev.decision(parser.parse_question(it["turns"][-1], objs, ctx, now=now, timezone=tz)))
            variants += 1
        if len(seen) > 1:
            changed.append(it["id"])
    return {"orders": ("every permutation of the 8-object catalogue" if full else "all rotations")
                      + " x names as given/reversed", "variants": variants, "changed": changed}


def evaluate():
    out = {}
    for gname, fname in GOLDS:
        data = load(fname)
        for pname, parser in PARSERS:
            rows, counts = score(data, parser)
            out[(gname, pname)] = (rows, counts)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    res = evaluate()
    for (g, p), (rows, counts) in res.items():
        print(g, p, list(counts.values()), [r["id"] for r in rows if not r["category"].startswith("correct")])
        assert all(r["ask_not_called_on_non_parsed"] for r in rows)
    if "--write" in argv:
        v2 = load("independent_v4_gold_v2.json")
        payload = {
            "_note": "REGRESSION set, not independent: the 30 questions of independent_v4.json were opened after the v4 "
                     "run. Scored with the original gold and with gold v2 (rules R1-R6, user/Astra decision "
                     "2026-11-09; per-item old/new gold and reason in the gold file).",
            "questions_sha256": "4bd2d804b726eaac97120daa175eddd2a42dc67afcb91d3411f858298b0f4cb6",
            "gold_changes": v2["gold_changes"], "harness_mapping": ind.HARNESS_MAPPING,
            "harness_issues": ind.HARNESS_ISSUES, "answers_differ_from_manual": "n/a (H1: the set has no facts)",
            "scores": [{"gold": g, "parser": p, "n": len(rows), "counts": counts,
                        "not_correct": [{"id": r["id"], "category": r["category"], "contract_gap": r["contract_gap"]}
                                        for r in rows if not r["category"].startswith("correct")],
                        "no_query_on_clarification_or_unsupported": all(r["ask_not_called_on_non_parsed"] for r in rows)}
                       for (g, p), (rows, counts) in res.items()],
            "permutation_invariance_v5": permutations(v2, parser_v5, "--full-permutations" in argv),
            "rows_v5_gold_v2": res[("gold_v2", "v5")][0],
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return res


if __name__ == "__main__":
    main()
