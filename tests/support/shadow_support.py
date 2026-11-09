"""Shadow lexical check: does an admitted ground support an answer.

Records a verdict for analysis. Never blocks and grants no new authority.
This is not Titan Issue #512 (manual claim-support reviews) and is not
wired into Crystal or Titan production paths.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from tests.support.crystal_titan_bridge import flatten_messages

_TOKEN = re.compile(r"\b\w+\b", re.UNICODE)
_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_IDENT = re.compile(r"\b[A-Z]{1,8}-[A-Z0-9]{2,}\b")


def _tokens(text: str) -> set[str]:
    return set(_TOKEN.findall((text or "").lower()))


def _in_prepared(fact: Mapping[str, Any], prepared: str) -> bool:
    claim = str(fact.get("claim") or "")
    fact_id = str(fact.get("fact_id") or "")
    return bool((claim and claim in prepared) or (fact_id and fact_id in prepared))


def evaluate_shadow_support(
    *,
    answer: str | None,
    prepared_messages: Sequence[Mapping[str, Any]] | None,
    admitted: Sequence[Mapping[str, Any]],
    excluded: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    text = answer or ""
    prepared = flatten_messages(prepared_messages)
    by_source: dict[str, list[str]] = {}
    for fact in admitted:
        label = str(fact.get("source") or "")
        if label:
            by_source.setdefault(label, []).append(str(fact.get("fact_id")))
    ambiguous_sources = {
        label: ids for label, ids in by_source.items() if len(ids) > 1
    }

    in_context = []
    missing_from_context = []
    for fact in admitted:
        item = {"fact_id": fact.get("fact_id"), "in_prepared_context": _in_prepared(fact, prepared)}
        (in_context if item["in_prepared_context"] else missing_from_context).append(item)

    cited_excluded = []
    for fact in excluded:
        claim = str(fact.get("claim") or "")
        fact_id = str(fact.get("fact_id") or "")
        if (claim and claim in text) or (fact_id and fact_id in text):
            cited_excluded.append(fact_id or claim)

    contradictions = []
    supports = []
    insufficient = []
    for fact in admitted:
        claim = str(fact.get("claim") or "")
        if not claim:
            insufficient.append(fact.get("fact_id"))
            continue
        claim_l = claim.lower()
        ans_l = text.lower()
        claim_not = " not " in f" {claim_l} " or "не " in claim_l
        ans_not = " not " in f" {ans_l} " or "не " in ans_l
        claim_nums = _NUMBER.findall(claim)
        ans_nums = _NUMBER.findall(text)
        claim_ids = _IDENT.findall(claim)
        ans_ids = _IDENT.findall(text)
        cond = "only if" in claim_l or "только если" in claim_l
        if claim_not != ans_not and (claim.replace(" NOT ", " ").lower() in ans_l.replace(" not ", " ") or ans_l):
            if ("not" in claim_l) ^ ("not" in ans_l):
                # Answer and ground disagree on negation of a shared stem.
                stem = claim_l.replace(" not ", " ")
                ans_stem = ans_l.replace(" not ", " ")
                if any(tok in ans_stem for tok in _tokens(stem) if len(tok) > 3):
                    contradictions.append({"fact_id": fact.get("fact_id"), "reason": "negation_mismatch"})
                    continue
        if claim_nums and ans_nums and set(claim_nums) != set(ans_nums):
            contradictions.append({"fact_id": fact.get("fact_id"), "reason": "number_mismatch"})
            continue
        if claim_ids and ans_ids and set(claim_ids) != set(ans_ids):
            contradictions.append({"fact_id": fact.get("fact_id"), "reason": "identifier_mismatch"})
            continue
        if cond and "only if" not in ans_l and "только если" not in ans_l and claim.split(" only if")[0].lower() in ans_l:
            contradictions.append({"fact_id": fact.get("fact_id"), "reason": "missing_condition"})
            continue
        if claim in text or claim_l in ans_l:
            supports.append(fact.get("fact_id"))
        else:
            overlap = _tokens(claim) & _tokens(text)
            if len(overlap) >= 3:
                supports.append(fact.get("fact_id"))
            else:
                insufficient.append(fact.get("fact_id"))

    source_ambiguity = []
    for label, ids in ambiguous_sources.items():
        if label and label in text:
            source_ambiguity.append({"source": label, "fact_ids": ids})

    if cited_excluded:
        verdict = "cites_excluded_record"
    elif source_ambiguity:
        verdict = "ambiguous_source_label"
    elif contradictions:
        verdict = "contradicts"
    elif supports:
        verdict = "supports"
    else:
        verdict = "insufficient"

    return {
        "authority": "shadow",
        "blocks": False,
        "check_available": True,
        "verdict": verdict,
        "citation_in_prepared_context": in_context,
        "missing_from_prepared_context": missing_from_context,
        "supports": supports,
        "contradicts": contradictions,
        "insufficient": insufficient,
        "cited_excluded": cited_excluded,
        "ambiguous_source_labels": {
            label: ids for label, ids in ambiguous_sources.items()
        },
        "source_ambiguity_in_answer": source_ambiguity,
        "limits": (
            "Lexical heuristics only. Not a model, not Crystal CanonicalView, "
            "and not Titan OutputFaithfulnessChecker. Never blocks."
        ),
    }
