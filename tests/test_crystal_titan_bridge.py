"""Crystal-Test → Titan bridge: selected grounds survive into Titan messages.

No real model is called. Titan is exercised in-process via a subprocess spy
with a fake HTTP provider (same pattern as Titan
``tests/test_llm_context_no_silent_truncation.py``).
"""
from __future__ import annotations

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from core.provenance import claim_digest, verify_receipt
from tests.support.crystal_titan_bridge import (
    flatten_messages,
    provenance_of,
    receipt_digest_valid,
    run_bridge,
)

TZ = "Europe/Berlin"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=ZoneInfo(TZ))
KNOWN = (
    {"id": "M", "names": ["M"]},
    {"id": "L", "names": ["L"]},
)
QUESTION_M_NOW = "Какой статус у M сейчас?"
QUESTION_AMBIGUOUS = "Какой статус?"

MATCHING = {
    "fact_id": "g-m-current",
    "claim": "M is operational MATCHING-GROUND-TEXT",
    "source": "operator-log:m-current",
    "confidence": 1.0,
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-CURRENT"}},
}
FOREIGN = {
    "fact_id": "g-l-foreign",
    "claim": "L is offline FOREIGN-OBJECT-MARKER",
    "source": "operator-log:l-foreign",
    "confidence": 1.0,
    "primary_object": "L",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-L-FOREIGN"}},
}
STALE = {
    "fact_id": "g-m-stale",
    "claim": "M was in maintenance STALE-GROUND-MARKER",
    "source": "operator-log:m-stale",
    "confidence": 1.0,
    "primary_object": "M",
    "observed_at": "2026-10-01T10:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-STALE"}},
}

CLEAN_ANSWER = "M is operational MATCHING-GROUND-TEXT as of the current check."
DIRTY_FOREIGN_ANSWER = "Also, L is offline FOREIGN-OBJECT-MARKER."
DIRTY_STALE_ANSWER = "Note that M was in maintenance STALE-GROUND-MARKER."
MIXED_CORPUS = [MATCHING, FOREIGN, STALE]


def _run(question, facts, spy=None, canned_answer=None):
    return run_bridge(
        question,
        facts,
        KNOWN,
        now=NOW,
        timezone=TZ,
        invoke_titan=spy,
        canned_answer=canned_answer,
    )


def test_matching_ground_is_present_in_final_messages():
    result = _run(QUESTION_M_NOW, [MATCHING])
    assert result["kind"] == "answer_request"
    assert result["titan_invoked"] is True
    assert result["provider_calls"] == 1
    assert [f["fact_id"] for f in result["kept"]] == ["g-m-current"]
    assert result["excluded"] == []
    blob = flatten_messages(result["final_messages"])
    assert MATCHING["claim"] in blob
    assert "object=M" in blob
    assert MATCHING["observed_at"] in blob
    assert MATCHING["source"] in blob
    assert "PROV-M-CURRENT" in blob
    assert provenance_of(MATCHING) in blob
    user_msg = result["final_messages"][-1]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == QUESTION_M_NOW
    report = result["context_report"]
    assert report["memory_records_sent"] == 1
    assert report["memory_records_total"] == 1
    assert report["memory_records_omitted"] == []
    assert "sent_facts" not in report
    assert "sent_fact_positions" not in report
    assert result["titan"]["titan_commit"].startswith("6b45854")
    assert result["titan"]["memory_auto_status"] == "off"
    assert result["titan"]["memory_saved"] == []


def test_foreign_or_stale_ground_is_absent_from_final_messages():
    result = _run(QUESTION_M_NOW, [FOREIGN, STALE])
    assert result["kind"] == "answer_request"
    assert result["titan_invoked"] is True
    assert result["provider_calls"] == 1
    assert result["kept"] == []
    excluded_ids = {item["fact_id"] for item in result["excluded"]}
    assert excluded_ids == {"g-l-foreign", "g-m-stale"}
    blob = flatten_messages(result["final_messages"])
    assert "FOREIGN-OBJECT-MARKER" not in blob
    assert "STALE-GROUND-MARKER" not in blob
    assert FOREIGN["claim"] not in blob
    assert STALE["claim"] not in blob
    assert "PROV-L-FOREIGN" not in blob
    assert "PROV-M-STALE" not in blob
    assert "g-l-foreign" not in blob
    assert "g-m-stale" not in blob
    report = result["context_report"]
    assert report["memory_records_sent"] == 0
    assert report["memory_records_total"] == 0
    user_msg = result["final_messages"][-1]
    assert user_msg["content"] == QUESTION_M_NOW


def test_ambiguous_question_clarifies_without_provider_call():
    calls = []

    def spy(message, records):
        calls.append((message, records))
        raise AssertionError("Titan must not be invoked for a clarification")

    result = _run(QUESTION_AMBIGUOUS, [MATCHING, FOREIGN, STALE], spy=spy)
    assert result["kind"] == "needs_clarification"
    assert result["titan_invoked"] is False
    assert result["provider_calls"] == 0
    assert result["final_messages"] is None
    assert result["receipt"] is None
    assert calls == []
    clarification = result["clarification"]
    assert clarification["kind"] == "needs_clarification"
    assert clarification["reason"] == "объект не назван"
    assert "M" in clarification["question"]


def test_receipt_is_preserved_end_to_end():
    result = _run(QUESTION_M_NOW, MIXED_CORPUS)
    receipt = result["receipt"]
    assert receipt is not None
    assert receipt["asked_object"] == "M"
    assert receipt["as_of"] == "2026-11-09T12:00:00+01:00"
    assert receipt["temporal_scope"] == "current"
    assert receipt["certifies"]["admitted_fact_ids"] == ["g-m-current"]
    assert receipt["certifies"]["claim_sha256"] == [claim_digest(MATCHING["claim"])]
    assert receipt["certifies"]["admitted_claims"] == [MATCHING["claim"]]
    excluded_ids = {item["fact_id"] for item in receipt["certifies"]["exclusions"]}
    assert excluded_ids == {"g-l-foreign", "g-m-stale"}
    assert receipt["applicability"]["exclusions"] == result["excluded"]
    sealed = receipt["provenance_receipt"]
    assert sealed["query"] == QUESTION_M_NOW
    assert sealed["answer"] == MATCHING["claim"]
    assert [c["fact_id"] for c in sealed["citations"]] == ["g-m-current"]
    assert sealed["citations"][0]["claim_sha256"] == claim_digest(MATCHING["claim"])
    assert sealed["digest"]
    assert receipt_digest_valid(receipt) is True


def test_receipt_scope_matches_grounds_sent_in_messages():
    result = _run(QUESTION_M_NOW, MIXED_CORPUS)
    blob = flatten_messages(result["final_messages"])
    receipt = result["receipt"]
    admitted = receipt["certifies"]["admitted_fact_ids"]
    assert admitted == ["g-m-current"]
    assert MATCHING["claim"] in blob
    assert "g-m-current" in blob
    assert FOREIGN["claim"] not in blob
    assert STALE["claim"] not in blob
    for item in receipt["certifies"]["exclusions"]:
        assert item["fact_id"] not in blob


def test_receipt_does_not_certify_titan_response():
    result = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=CLEAN_ANSWER)
    receipt = result["receipt"]
    assert receipt["certifies_response"] is False
    assert "titan_generated_answer" in receipt["does_not_certify"]
    assert result["reply"] == CLEAN_ANSWER
    assert receipt["provenance_receipt"]["answer"] == MATCHING["claim"]
    assert receipt["provenance_receipt"]["answer"] != result["reply"]


def test_receipt_digest_rejects_a_different_selection():
    result = _run(QUESTION_M_NOW, MIXED_CORPUS)
    sealed = copy.deepcopy(result["receipt"]["provenance_receipt"])
    assert verify_receipt(sealed)["digest_valid"] is True
    sealed["citations"] = list(sealed["citations"]) + [{
        "fact_id": FOREIGN["fact_id"],
        "claim_sha256": claim_digest(FOREIGN["claim"]),
        "source": FOREIGN["source"],
        "epistemic_state": "Observed",
        "truth_status": "UNVERIFIED",
    }]
    report = verify_receipt(sealed)
    assert report["digest_valid"] is False


def _checks(result):
    return result["titan"]["titan_response_checks"]


def test_canned_clean_answer_runs_standalone_titan_checks():
    result = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=CLEAN_ANSWER)
    assert result["reply"] == CLEAN_ANSWER
    assert result["bridge_answer_check"]["passed"] is True
    checks = _checks(result)
    assert checks["wired_on_chat_llm_reply"]["response_guardian"] is False
    assert checks["wired_on_chat_llm_reply"]["output_faithfulness"] is False
    assert checks["wired_on_chat_llm_reply"]["response_audit"] is False
    assert checks["feature_flags"]["enable_response_guardian"] is False
    assert checks["feature_flags"]["enable_output_faithfulness"] is False
    assert checks["gated_as_configured"]["response_guardian"]["decision"] == "approve"
    assert checks["gated_as_configured"]["response_guardian"]["reason"] == (
        "response_guardian disabled"
    )
    assert checks["gated_as_configured"]["output_faithfulness"] is None
    standalone_g = checks["standalone_enabled"]["response_guardian"]
    assert standalone_g["decision"] == "approve"
    faith = checks["standalone_enabled"]["output_faithfulness"]
    assert faith["unsupported"] == []
    assert faith["score"] >= 0.5


def test_response_guardian_currently_does_not_flag_dirty_foreign_answer():
    """FINDING: ResponseGuardian does not inspect answer text for excluded grounds."""
    result = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=DIRTY_FOREIGN_ANSWER)
    checks = _checks(result)
    assert result["reply"] == DIRTY_FOREIGN_ANSWER
    assert checks["gated_as_configured"]["response_guardian"]["decision"] == "approve"
    assert checks["flagged"]["gated_response_guardian"] is False
    assert checks["flagged"]["standalone_response_guardian"] is False
    assert checks["standalone_enabled"]["response_guardian"]["decision"] == "approve"


def test_response_guardian_currently_does_not_flag_dirty_stale_answer():
    """FINDING: ResponseGuardian does not inspect answer text for excluded grounds."""
    result = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=DIRTY_STALE_ANSWER)
    checks = _checks(result)
    assert result["reply"] == DIRTY_STALE_ANSWER
    assert checks["flagged"]["gated_response_guardian"] is False
    assert checks["flagged"]["standalone_response_guardian"] is False
    assert checks["standalone_enabled"]["response_guardian"]["decision"] == "approve"


def test_output_faithfulness_standalone_marks_dirty_answers_unsupported():
    foreign = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=DIRTY_FOREIGN_ANSWER)
    stale = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=DIRTY_STALE_ANSWER)
    foreign_faith = _checks(foreign)["standalone_enabled"]["output_faithfulness"]
    stale_faith = _checks(stale)["standalone_enabled"]["output_faithfulness"]
    assert foreign_faith["unsupported"]
    assert stale_faith["unsupported"]
    assert _checks(foreign)["flagged"]["standalone_output_faithfulness"] is True
    assert _checks(stale)["flagged"]["standalone_output_faithfulness"] is True
    # The gated wrapper used by pipeline.run is off by default, so /chat
    # configuration does not surface this score.
    assert _checks(foreign)["gated_as_configured"]["output_faithfulness"] is None
    assert _checks(foreign)["flagged"]["gated_output_faithfulness"] is None


def test_chat_path_currently_does_not_flag_dirty_answers_via_gated_checks():
    """FINDING: /chat does not run gated checkers on the LLM reply."""
    result = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=DIRTY_FOREIGN_ANSWER)
    checks = _checks(result)
    assert checks["wired_on_chat_llm_reply"]["response_guardian"] is False
    assert checks["wired_on_chat_llm_reply"]["output_faithfulness"] is False
    assert checks["wired_on_chat_llm_reply"]["response_audit"] is False
    assert result["reply"] == DIRTY_FOREIGN_ANSWER


def test_bridge_side_flags_excluded_markers_in_answer():
    foreign = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=DIRTY_FOREIGN_ANSWER)
    stale = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=DIRTY_STALE_ANSWER)
    clean = _run(QUESTION_M_NOW, MIXED_CORPUS, canned_answer=CLEAN_ANSWER)
    assert foreign["bridge_answer_check"]["side"] == "bridge"
    assert foreign["bridge_answer_check"]["passed"] is False
    assert "FOREIGN-OBJECT-MARKER" in foreign["bridge_answer_check"]["hits"]
    assert stale["bridge_answer_check"]["passed"] is False
    assert "STALE-GROUND-MARKER" in stale["bridge_answer_check"]["hits"]
    assert clean["bridge_answer_check"]["passed"] is True
    assert clean["bridge_answer_check"]["hits"] == []
