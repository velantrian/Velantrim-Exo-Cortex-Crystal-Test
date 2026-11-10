"""v6.1: the regression set (the 30 questions of independent_v4.json; not
independent) scored with the latest gold (gold v3, independent_v4_gold_v3.json;
no gold changed in v6.1) for the frozen v6 parser and the current parser.
``python -m tests.query_parse_regression_v6_1 [--write] [--full-permutations]``.
"""
import json
import sys

from core import query_parse as parser_v6_1  # current (v6.1)
from tests import query_parse_eval as ev
from tests import query_parse_independent_v4 as ind
from tests.query_parse_regression_v6 import load, permutations, score
from tests import query_parse_v6 as parser_v6  # frozen v6 (= tag query-parse-v6-frozen)

GOLDS = (("gold_v3", "independent_v4_gold_v3.json"),)
PARSERS = (("v6", parser_v6), ("v6_1", parser_v6_1))
OUT = ev.OUT / "regression_independent_v6_1.json"


def evaluate():
    out = {}
    for gname, fname in GOLDS:
        data = load(fname)
        for pname, parser in PARSERS:
            out[(gname, pname)] = score(data, parser)
    return out


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    res = evaluate()
    for (g, p), (rows, counts) in res.items():
        print(g, p, list(counts.values()), [r["id"] for r in rows if not r["category"].startswith("correct")])
        assert all(r["ask_not_called_on_non_parsed"] for r in rows)
    if "--write" in argv:
        data = load("independent_v4_gold_v3.json")
        v6_rows, v61_rows = res[("gold_v3", "v6")][0], res[("gold_v3", "v6_1")][0]
        payload = {
            "_note": "REGRESSION set, not independent (opened after the v4 run). Latest gold = gold v3 (final contract "
                     "C1-C6, user decision 2026-11-09); v6.1 changed no gold. Frozen v6 vs current v6.1.",
            "questions_sha256": "4bd2d804b726eaac97120daa175eddd2a42dc67afcb91d3411f858298b0f4cb6",
            "harness_mapping": ind.HARNESS_MAPPING, "harness_issues": ind.HARNESS_ISSUES,
            "scores": [{"gold": g, "parser": p, "n": len(rows), "counts": counts,
                        "not_correct": [{"id": r["id"], "category": r["category"], "contract_gap": r["contract_gap"]}
                                        for r in rows if not r["category"].startswith("correct")],
                        "no_query_on_clarification_or_unsupported": all(r["ask_not_called_on_non_parsed"] for r in rows)}
                       for (g, p), (rows, counts) in res.items()],
            "changed_v6_to_v6_1": [b["id"] for a, b in zip(v6_rows, v61_rows) if a != b],
            "permutation_invariance_v6_1": permutations(data, parser_v6_1, "--full-permutations" in argv),
            "rows_v6_1_gold_v3": v61_rows,
        }
        OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return res


if __name__ == "__main__":
    main()
