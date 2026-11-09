"""Minimal Crystal-Test → Titan context bridge (lab harness, no real model).

Crystal parses the question and selects admissible grounds. Titan then
receives exactly those grounds as memory records. Titan's own retrieval is
replaced in the spy process; auto-save is disabled. The spy captures the
exact messages Titan prepared for the provider.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from core.applicability import declarations, select
from core.generation import ExtractiveGenerator
from core.provenance import build_receipt, claim_digest, verify_receipt
from core.query_parse import parse_question

DEFAULT_TITAN_ROOT = Path(os.environ.get("TITAN_SANDBOX_ROOT", "/workspace/titan-sandbox"))
SPY_SCRIPT = Path(__file__).with_name("titan_chat_spy.py")
INVOKE_TITAN = Callable[[str, list[dict[str, Any]]], Mapping[str, Any]]
EXCLUSION_MARKERS = ("FOREIGN-OBJECT-MARKER", "STALE-GROUND-MARKER")


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def provenance_of(fact: Mapping[str, Any]) -> str:
    meta = fact.get("metadata") if isinstance(fact.get("metadata"), dict) else {}
    raw = meta.get("provenance")
    if raw:
        return _as_text(raw)
    return _as_text(fact.get("source"))


def ground_to_titan_record(fact: Mapping[str, Any]) -> dict[str, Any]:
    """Map a Crystal ground onto a Titan memory record.

    Titan's ``_memory_record_line`` emits only ``source``, ``confidence`` and
    ``claim``. Object, time and provenance are therefore serialized into
    ``source`` so they appear in the final messages without changing Titan.
    The original claim text is kept as ``claim``.
    """
    decls = declarations(fact)
    obj = decls.get("primary_object") or decls.get("object") or ""
    observed = decls.get("observed_at") or decls.get("date") or ""
    fact_id = str(fact.get("fact_id") or fact.get("id") or "")
    source = fact.get("source") or ""
    prov = provenance_of(fact)
    encoded_source = (
        f"source={source}; object={obj}; observed_at={observed}; "
        f"valid_from={decls.get('valid_from') or ''}; "
        f"valid_until={decls.get('valid_until') or ''}; "
        f"provenance={prov}; fact_id={fact_id}"
    )
    return {
        "fact_id": fact_id,
        "claim": fact.get("claim") or fact.get("text") or "",
        "source": encoded_source,
        "confidence": float(fact.get("confidence") or 1.0),
    }


def parse_and_select(
    question: str,
    candidate_facts: Sequence[Mapping[str, Any]],
    known_objects: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    timezone: Any,
) -> dict[str, Any]:
    parsed = parse_question(question, known_objects, now=now, timezone=timezone)
    if parsed.get("kind") != "parsed":
        return {
            "kind": parsed.get("kind"),
            "parsed": parsed,
            "params": None,
            "kept": [],
            "excluded": [],
            "selection": None,
        }
    params = parsed.get("params") or {}
    kept, info = select(
        list(candidate_facts),
        asked_object=params.get("asked_object"),
        as_of=params.get("as_of"),
        temporal_scope=params.get("temporal_scope"),
    )
    return {
        "kind": "parsed",
        "parsed": parsed,
        "params": params,
        "kept": kept,
        "excluded": list(info.get("exclusions") or []),
        "selection": info,
    }


def build_selection_receipt(
    question: str,
    params: Mapping[str, Any] | None,
    kept: Sequence[Mapping[str, Any]],
    selection: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Wrap Crystal's real selection artifacts; do not invent a new receipt schema.

    Sealed structure, when an extractive Crystal answer exists, is
    ``provenance.build_receipt`` (version, created_at, query, answer,
    citations with fact_id/claim_sha256/source/epistemic_state/truth_status,
    digest). That receipt attests Crystal's extractive concatenation of
    admitted claims — not a Titan-generated reply.

    Object, as_of and exclusions come from ``parse_question`` params and
    ``applicability.select`` (the ``applicability`` packet).
    """
    params = dict(params or {})
    info = dict(selection or {
        "exclusions": [],
        "historical_facts": [],
        "context_relations": [],
        "request_error": None,
    })
    admitted = [
        {
            "fact_id": fact.get("fact_id"),
            "claim": fact.get("claim"),
            "claim_sha256": claim_digest(fact.get("claim", "")),
        }
        for fact in kept
    ]
    provenance_receipt = None
    if kept:
        extractive = ExtractiveGenerator().generate(question, list(kept))
        provenance_receipt = build_receipt({
            "query": question,
            "answer": extractive,
            "facts": list(kept),
        })
    return {
        "certifies_response": False,
        "does_not_certify": ["titan_generated_answer"],
        "certifies": {
            "admitted_fact_ids": [row["fact_id"] for row in admitted],
            "claim_sha256": [row["claim_sha256"] for row in admitted],
            "admitted_claims": [row["claim"] for row in admitted],
            "asked_object": params.get("asked_object"),
            "as_of": params.get("as_of"),
            "temporal_scope": params.get("temporal_scope"),
            "exclusions": list(info.get("exclusions") or []),
        },
        "asked_object": params.get("asked_object"),
        "as_of": params.get("as_of"),
        "temporal_scope": params.get("temporal_scope"),
        "applicability": info,
        "admitted": admitted,
        "provenance_receipt": provenance_receipt,
    }


def receipt_digest_valid(receipt: Mapping[str, Any] | None) -> bool | None:
    sealed = (receipt or {}).get("provenance_receipt")
    if not sealed:
        return None
    return bool(verify_receipt(sealed).get("digest_valid"))


def check_answer_excludes_rejected_grounds(
    reply: str | None,
    excluded: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Bridge-side check: the final answer must not mention excluded grounds."""
    text = reply or ""
    hits: list[str] = []
    for marker in EXCLUSION_MARKERS:
        if marker in text:
            hits.append(marker)
    for fact in excluded:
        claim = str(fact.get("claim") or "")
        if claim and claim in text:
            hits.append(claim)
    unique = list(dict.fromkeys(hits))
    return {
        "side": "bridge",
        "passed": not unique,
        "hits": unique,
    }


def default_titan_invoker(
    titan_root: Path | None = None,
    canned_answer: str | None = None,
) -> INVOKE_TITAN:
    root = Path(titan_root or DEFAULT_TITAN_ROOT)

    def _invoke(message: str, records: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "message": message,
            "facts": records,
            "titan_root": str(root),
        }
        if canned_answer is not None:
            payload["canned_answer"] = canned_answer
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [sys.executable, str(SPY_SCRIPT)],
            input=json.dumps(payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            env=env,
            timeout=90,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "titan_chat_spy failed "
                f"(code={proc.returncode}): {proc.stderr[-4000:]}"
            )
        return json.loads(proc.stdout)

    return _invoke


def run_bridge(
    question: str,
    candidate_facts: Sequence[Mapping[str, Any]],
    known_objects: Sequence[Mapping[str, Any]],
    *,
    now: datetime,
    timezone: Any,
    invoke_titan: INVOKE_TITAN | None = None,
    titan_root: Path | None = None,
    canned_answer: str | None = None,
) -> dict[str, Any]:
    prep = parse_and_select(
        question, candidate_facts, known_objects, now=now, timezone=timezone
    )
    if prep["kind"] != "parsed":
        return {
            "kind": prep["kind"],
            "parsed": prep["parsed"],
            "clarification": prep["parsed"] if prep["kind"] == "needs_clarification" else None,
            "params": None,
            "kept": [],
            "excluded": [],
            "receipt": None,
            "titan_records": [],
            "titan_invoked": False,
            "provider_calls": 0,
            "final_messages": None,
            "context_report": None,
            "titan": None,
            "reply": None,
            "bridge_answer_check": None,
        }
    receipt = build_selection_receipt(
        question, prep["params"], prep["kept"], prep["selection"]
    )
    records = [ground_to_titan_record(fact) for fact in prep["kept"]]
    caller = (
        invoke_titan
        if invoke_titan is not None
        else default_titan_invoker(titan_root, canned_answer=canned_answer)
    )
    titan = caller(question, records)
    reply = titan.get("reply")
    return {
        "kind": "answer_request",
        "parsed": prep["parsed"],
        "clarification": None,
        "params": prep["params"],
        "kept": prep["kept"],
        "excluded": prep["excluded"],
        "receipt": receipt,
        "titan_records": records,
        "titan_invoked": True,
        "provider_calls": int(titan.get("provider_calls") or 0),
        "final_messages": titan.get("messages"),
        "context_report": titan.get("context_report"),
        "titan": titan,
        "reply": reply,
        "bridge_answer_check": check_answer_excludes_rejected_grounds(
            reply, prep["excluded"]
        ),
    }


def flatten_messages(messages: Sequence[Mapping[str, Any]] | None) -> str:
    if not messages:
        return ""
    return "\n".join(str(m.get("content") or "") for m in messages)
