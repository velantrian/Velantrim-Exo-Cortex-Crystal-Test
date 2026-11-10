"""Call Crystal's ordinary read path: query() → generate_answer → receipt.

This is laboratory instrumentation around existing functions, not a new
production API.
"""
from __future__ import annotations

from typing import Any

from core.pipeline import generate_answer, guardian
from core.provenance import build_receipt
from core.query_pipeline import query


# Static call chain of query() as of this Crystal-Test checkout (v6.1 / PR #14
# head plus the lab's applicability path). Keep in sync with core/query_pipeline.py.
QUERY_CALL_CHAIN = (
    "core.query_pipeline.query",
    "core.applicability.request_error",
    "core.query_pipeline._retrieve_read_only",
    "core.query_pipeline._resolve_retrieval_hits",
    "core.evidence.has_valid_evidence_for_grounding (VERIFIED filter)",
    "core.trace.build_trace",
    "core.pipeline.guardian",
    "core.pipeline.generate_answer",
    "core.canonical_view.project_canonical",
    "core.applicability.select (via generate_answer/select_applicability)",
    "core.generation.ExtractiveGenerator.generate (default)",
    "core.provenance.build_receipt (only when an extractive answer exists)",
)


def run_crystal_query_path(
    query_text: str,
    *,
    asked_object: str | None = None,
    as_of: str | None = None,
    temporal_scope: str | None = None,
) -> dict[str, Any]:
    result = query(
        query_text,
        asked_object=asked_object,
        as_of=as_of,
        temporal_scope=temporal_scope,
    )
    receipt = None
    receipt_error = None
    if result.get("answer") is not None:
        receipt = build_receipt(result)
    else:
        receipt_error = "build_receipt refuses a blocked result (no answer to attest to)"
    return {
        "entry": "core.query_pipeline.query",
        "functions": list(QUERY_CALL_CHAIN),
        "result": result,
        "receipt": receipt,
        "receipt_error": receipt_error,
        "certifies_model_text": False,
    }


__all__ = ["QUERY_CALL_CHAIN", "run_crystal_query_path", "generate_answer", "guardian"]
