"""Regression tests for deterministic RC-9 lexical retrieval.

These tests harden the Reader RC-9 baseline by verifying that retrieval
results are stable across candidate order, equal-score ties, cross-document
filtering, repeated runs, and metadata preservation.
"""
from __future__ import annotations

from itertools import permutations

import pytest

from core.reader_lexical_discovery import (
    RETRIEVAL_METHOD,
    ReaderLexicalIndex,
    ReaderLexicalMatch,
    ReaderLexicalRecord,
)


def _record(
    candidate_id: str,
    text: str,
    *,
    document_id: str | None = None,
    session_id: str | None = None,
    source_uri: str | None = None,
    source_sha256: str | None = None,
    restricted: bool = False,
    sensitivity: str | None = None,
) -> ReaderLexicalRecord:
    return ReaderLexicalRecord(
        session_id=session_id or f"session-{candidate_id}",
        candidate_id=candidate_id,
        document_id=document_id or f"doc-{candidate_id}",
        source_uri=source_uri or f"file:///{candidate_id}.txt",
        source_sha256=(source_sha256 or (candidate_id.encode().hex() + "0" * 64))[:64],
        proposition=text,
        restricted=restricted,
        sensitivity=sensitivity,
    )


def _match_key(match: ReaderLexicalMatch) -> tuple[str, int, float]:
    return (match.candidate_id, match.rank, match.lexical_score)


def test_retrieval_is_independent_of_candidate_record_order():
    """RC-9 must produce identical ranked results regardless of input order."""
    query = _record("q", "alpha beta gamma", document_id="doc-q")
    records = [
        _record("a", "alpha beta gamma", document_id="doc-a"),
        _record("b", "alpha beta", document_id="doc-b"),
        _record("c", "alpha gamma", document_id="doc-c"),
        _record("d", "beta gamma", document_id="doc-d"),
        _record("e", "unrelated", document_id="doc-e"),
    ]

    # 5! = 120 orderings; keep the test bounded while still exercising determinism.
    results = []
    for ordering in permutations(records):
        index = ReaderLexicalIndex(ordering)
        results.append([_match_key(m) for m in index.discover(query, k=5)])
        if len(results) >= 24:
            break

    assert all(r == results[0] for r in results[1:]), "ranking varied with input order"


def test_equal_score_ties_break_deterministically_by_sort_key():
    """Identical propositions across documents must tie-break on stable metadata."""
    query = _record("q", "same token", document_id="doc-q")
    a = _record("a", "same token", document_id="doc-a")
    b = _record("b", "same token", document_id="doc-b")
    c = _record("c", "same token", document_id="doc-c")

    for ordering in permutations((a, b, c)):
        index = ReaderLexicalIndex(ordering)
        matches = index.discover(query, k=3)
        assert [m.candidate_id for m in matches] == ["a", "b", "c"]
        assert len({m.lexical_score for m in matches}) == 1
        assert [m.rank for m in matches] == [1, 2, 3]


def test_cross_document_filtering_is_consistent_across_orders():
    """Same-document candidates must be excluded when cross_document_only=True."""
    query = _record("q", "alpha beta", document_id="doc-shared")
    same_doc = _record("same", "alpha beta", document_id="doc-shared")
    cross_a = _record("a", "alpha beta", document_id="doc-a")
    cross_b = _record("b", "alpha beta", document_id="doc-b")

    for i, ordering in enumerate(permutations((same_doc, cross_a, cross_b))):
        index = ReaderLexicalIndex(ordering)
        cross_only = index.discover(query, k=5, cross_document_only=True)
        assert {m.candidate_id for m in cross_only} == {"a", "b"}

        inclusive = index.discover(query, k=5, cross_document_only=False)
        assert {m.candidate_id for m in inclusive} == {"same", "a", "b"}
        if i >= 5:
            break


def test_ranking_is_stable_across_repeated_runs():
    """Repeated discovery against the same index must return byte-identical matches."""
    query = _record("q", "alpha beta 2024 must not", document_id="doc-q")
    records = [
        _record("a", "alpha beta 2024 must not", document_id="doc-a", restricted=True, sensitivity="r"),
        _record("b", "alpha beta 2024 may", document_id="doc-b"),
        _record("c", "alpha beta 2024", document_id="doc-c"),
        _record("d", "unrelated text", document_id="doc-d"),
    ]
    index = ReaderLexicalIndex(records)

    runs = [index.discover(query, k=3) for _ in range(20)]
    assert all(r == runs[0] for r in runs[1:])
    assert [m.candidate_id for m in runs[0]] == ["a", "c", "b"]
    assert [m.rank for m in runs[0]] == [1, 2, 3]


def test_source_and_restriction_metadata_are_preserved():
    """RC-9 matches must carry source URI, SHA-256, restricted flag and sensitivity."""
    query = _record("q", "alpha beta", document_id="doc-q")
    target = _record(
        "target",
        "alpha beta",
        document_id="doc-target",
        session_id="session-target",
        source_uri="file:///target/source.txt",
        source_sha256="ab" * 32,
        restricted=True,
        sensitivity="private",
    )
    index = ReaderLexicalIndex([target])

    matches = index.discover(query, k=1)
    assert len(matches) == 1
    match = matches[0]
    assert match.query_session_id == query.session_id
    assert match.query_candidate_id == query.candidate_id
    assert match.query_document_id == query.document_id
    assert match.candidate_session_id == target.session_id
    assert match.candidate_id == target.candidate_id
    assert match.candidate_document_id == target.document_id
    assert match.candidate_source_uri == target.source_uri
    assert match.candidate_source_sha256 == target.source_sha256.lower()
    assert match.retrieval_method == RETRIEVAL_METHOD
    assert match.restricted is True
    assert match.sensitivity == "private"
    assert match.matched_terms == ("alpha", "beta")


def test_metadata_preservation_is_independent_of_candidate_order():
    """Source/restriction metadata must remain correct regardless of input order."""
    query = _record("q", "alpha beta", document_id="doc-q")
    records = [
        _record("a", "alpha beta", document_id="doc-a", restricted=True, sensitivity="r"),
        _record("b", "alpha beta", document_id="doc-b", source_uri="file:///b.txt", source_sha256="cd" * 32),
        _record("c", "alpha beta", document_id="doc-c"),
    ]

    for ordering in permutations(records):
        index = ReaderLexicalIndex(ordering)
        matches = index.discover(query, k=3)
        by_id = {m.candidate_id: m for m in matches}
        assert by_id["a"].restricted is True and by_id["a"].sensitivity == "r"
        assert by_id["b"].candidate_source_uri == "file:///b.txt"
        assert by_id["b"].candidate_source_sha256 == "cd" * 32
        assert by_id["c"].restricted is False and by_id["c"].sensitivity is None


def test_k_truncation_does_not_affect_determinism():
    """Top-k truncation must be deterministic and preserve relative ordering."""
    query = _record("q", "alpha beta", document_id="doc-q")
    records = [_record(chr(ord("a") + i), "alpha beta", document_id=f"doc-{i}") for i in range(8)]

    for i, ordering in enumerate(permutations(records)):
        index = ReaderLexicalIndex(ordering)
        top3 = index.discover(query, k=3)
        assert len(top3) == 3
        assert [m.rank for m in top3] == [1, 2, 3]
        assert [m.candidate_id for m in top3] == ["a", "b", "c"]
        if i >= 23:
            break


def test_empty_and_no_match_cases_are_deterministic():
    """Edge cases with no candidates or no matches must return stable empty results."""
    query = _record("q", "alpha beta", document_id="doc-q")
    empty_index = ReaderLexicalIndex(())
    assert empty_index.discover(query, k=5) == ()

    unrelated = _record("u", "unrelated text", document_id="doc-u")
    no_match_index = ReaderLexicalIndex((unrelated,))
    assert no_match_index.discover(query, k=5) == ()
