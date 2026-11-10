"""Pins the independent-check run of the frozen v4 parser (nothing is fixed here)."""
import hashlib

from tests import query_parse_independent_v4 as ind
from tests.query_parse_independent_v4_review import DISAGREEMENTS


def test_files_unchanged_and_parser_frozen():
    data, sha = ind.load()
    assert sha == "4bd2d804b726eaac97120daa175eddd2a42dc67afcb91d3411f858298b0f4cb6"
    assert hashlib.sha256(ind.FILE.read_bytes()).hexdigest() == sha and len(data["items"]) == 30


def test_scores_and_disagreements_pinned():
    rows, counts = ind.main([])
    assert counts == {"correct_parse": 12, "confident_misparse": 3, "correct_clarification": 11,
                      "unnecessary_clarification": 0, "correct_unsupported": 2, "wrong_unsupported": 1,
                      "clarification_instead_of_unsupported": 1}
    assert {r["id"] for r in rows if not r["category"].startswith("correct")} == set(DISAGREEMENTS)
    assert all(r["ask_not_called_on_non_parsed"] for r in rows)
    assert all(r["query_calls"] == (r["parser"]["kind"] == "parsed") for r in rows)
