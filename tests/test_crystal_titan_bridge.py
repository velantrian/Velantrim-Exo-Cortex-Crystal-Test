"""Crystal-Test → Titan bridge: selected grounds survive into Titan messages.

No real model is called. Titan is exercised in-process via a subprocess spy
with a fake HTTP provider (same pattern as Titan
``tests/test_llm_context_no_silent_truncation.py``).
"""
from __future__ import annotations

import copy
from datetime import datetime
from zoneinfo import ZoneInfo

from core.applicability import select
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

def _canon(fact, **extra):
    """A fact that passes CanonicalView.STRICT (same fields generate_answer uses)."""
    row = {
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
        "truth_status": "VERIFIED",
        "epistemic_state": "Validated",
        "restricted": False,
        "confidence": 1.0,
    }
    row.update(fact)
    row.update(extra)
    return row


MATCHING = _canon({
    "fact_id": "g-m-current",
    "claim": "M is operational MATCHING-GROUND-TEXT",
    "source": "operator-log:m-current",
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-CURRENT"}},
})
FOREIGN = _canon({
    "fact_id": "g-l-foreign",
    "claim": "L is offline FOREIGN-OBJECT-MARKER",
    "source": "operator-log:l-foreign",
    "primary_object": "L",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-L-FOREIGN"}},
})
STALE = _canon({
    "fact_id": "g-m-stale",
    "claim": "M was in maintenance STALE-GROUND-MARKER",
    "source": "operator-log:m-stale",
    "primary_object": "M",
    "observed_at": "2026-10-01T10:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-STALE"}},
})
# After reconcile.supersede the old fact is Deprecated. CanonicalView drops it;
# applicability.select does not read SUPERSEDED_BY edges.
OLD_OPEN = _canon({
    "fact_id": "g-m-open-old",
    "claim": "M is open SUPERSEDED-OPEN-MARKER",
    "source": "operator-log:m-open-old",
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-OPEN-OLD"}},
}, epistemic_state="Deprecated")
NEW_CLOSED = _canon({
    "fact_id": "g-m-closed-new",
    "claim": "M is closed CORRECTION-CLOSED-MARKER",
    "source": "operator-log:m-closed-new",
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-CLOSED-NEW"}},
})
NEGATED = _canon({
    "fact_id": "g-m-not-operational",
    "claim": "M is NOT operational NEGATION-NOT-MARKER",
    "source": "operator-log:m-not",
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-NOT"}},
})
CONDITIONAL = _canon({
    "fact_id": "g-m-if-power",
    "claim": "M is operational only if power is restored CONDITION-IF-MARKER",
    "source": "operator-log:m-if-power",
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "valid_from": "2026-11-01T00:00:00+01:00",
    "valid_until": "2026-11-30T23:59:59+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-IF-POWER"}},
})
ORDER_A = _canon({
    "fact_id": "g-m-order-a",
    "claim": "M north door is locked ORDER-A-MARKER",
    "source": "operator-log:m-order-a",
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
})
ORDER_B = _canon({
    "fact_id": "g-m-order-b",
    "claim": "M south door is locked ORDER-B-MARKER",
    "source": "operator-log:m-order-b",
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
})
DIRTY_SUPERSEDED_ANSWER = "Still reporting that M is open SUPERSEDED-OPEN-MARKER."

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
    assert result["handoff"]["provider_called"] is True
    assert result["handoff"]["prepared_messages"] == result["final_messages"]
    assert result["handoff"]["provider_received"] == result["final_messages"]
    assert result["handoff"]["prepared_matches_provider_received"] is True
    assert result["titan"]["capture_points"]["prepared"] != result["titan"]["capture_points"]["received"]
    assert result["titan"]["prepared_messages"] == result["titan"]["provider_received_messages"]
    assert result["handoff"]["provider_response"] == result["reply"]
    assert result["handoff"]["admitted_records_passed_to_titan"][0]["fact_id"] == "g-m-current"


def test_foreign_or_stale_ground_is_absent_from_final_messages():
    result = _run(QUESTION_M_NOW, [FOREIGN, STALE])
    assert result["kind"] == "no_matching_information"
    assert result["titan_invoked"] is False
    assert result["provider_calls"] == 0
    assert result["kept"] == []
    assert result["final_messages"] is None
    assert result["handoff"]["provider_called"] is False
    assert result["handoff"]["prepared_messages"] is None
    assert result["handoff"]["provider_received"] is None
    assert result["handoff"]["prepared_matches_provider_received"] is None
    assert result["handoff"]["provider_response"] is None
    assert "Подходящих сведений нет" in result["reply"]
    excluded_ids = {item["fact_id"] for item in result["excluded"]}
    assert excluded_ids == {"g-l-foreign", "g-m-stale"}


def test_ambiguous_question_clarifies_without_provider_call():
    calls = []

    def spy(message, records):
        calls.append((message, records))
        raise AssertionError("Titan must not be invoked for a clarification")

    result = _run(QUESTION_AMBIGUOUS, [MATCHING, FOREIGN, STALE], spy=spy)
    assert result["kind"] == "needs_clarification"
    assert result["kind"] != "no_matching_information"
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


def test_applicability_select_currently_keeps_deprecated_fact_that_covers_as_of():
    """FINDING: select() ignores ESM and SUPERSEDED_BY; both covering facts stay."""
    kept, info = select(
        [OLD_OPEN, NEW_CLOSED],
        asked_object="M",
        as_of="2026-11-09T12:00:00+01:00",
        temporal_scope="current",
    )
    assert [f["fact_id"] for f in kept] == ["g-m-open-old", "g-m-closed-new"]
    assert info["exclusions"] == []


def test_correction_only_the_validated_successor_reaches_titan():
    result = _run(QUESTION_M_NOW, [OLD_OPEN, NEW_CLOSED])
    blob = flatten_messages(result["final_messages"])
    assert [f["fact_id"] for f in result["kept"]] == ["g-m-closed-new"]
    assert NEW_CLOSED["claim"] in blob
    assert "CORRECTION-CLOSED-MARKER" in blob
    assert "M is closed CORRECTION-CLOSED-MARKER" in blob
    assert "SUPERSEDED-OPEN-MARKER" not in blob
    assert "M is open SUPERSEDED-OPEN-MARKER" not in blob
    assert "g-m-open-old" not in blob
    dropped = {f["fact_id"] for f in result["canonical_view_excluded"]}
    assert dropped == {"g-m-open-old"}
    # Crystal does not attach a 'superseded' reason in select(); the old
    # record is dropped by CanonicalView because epistemic_state is Deprecated.
    assert result["excluded"] == []
    receipt = result["receipt"]
    assert receipt["certifies"]["admitted_fact_ids"] == ["g-m-closed-new"]
    assert receipt["canonical_view_excluded_fact_ids"] == ["g-m-open-old"]
    assert receipt["provenance_receipt"]["answer"] == NEW_CLOSED["claim"]
    assert [c["fact_id"] for c in receipt["provenance_receipt"]["citations"]] == [
        "g-m-closed-new"
    ]
    assert receipt_digest_valid(receipt) is True


def test_negation_reaches_titan_with_not_intact():
    result = _run(QUESTION_M_NOW, [NEGATED])
    blob = flatten_messages(result["final_messages"])
    assert "M is NOT operational NEGATION-NOT-MARKER" in blob
    assert " NOT " in blob
    assert NEGATED["claim"] in blob
    assert result["receipt"]["certifies"]["admitted_claims"] == [NEGATED["claim"]]


def test_condition_text_and_validity_window_reach_titan_intact():
    result = _run(QUESTION_M_NOW, [CONDITIONAL])
    blob = flatten_messages(result["final_messages"])
    assert "M is operational only if power is restored CONDITION-IF-MARKER" in blob
    assert "only if power is restored" in blob
    assert "valid_from=2026-11-01T00:00:00+01:00" in blob
    assert "valid_until=2026-11-30T23:59:59+01:00" in blob
    assert result["receipt"]["certifies"]["admitted_fact_ids"] == ["g-m-if-power"]


def test_order_invariance_sent_set_is_stable():
    forward = _run(QUESTION_M_NOW, [OLD_OPEN, NEW_CLOSED, ORDER_A, ORDER_B])
    backward = _run(QUESTION_M_NOW, [ORDER_B, ORDER_A, NEW_CLOSED, OLD_OPEN])
    sent_fwd = {f["fact_id"] for f in forward["kept"]}
    sent_bwd = {f["fact_id"] for f in backward["kept"]}
    assert sent_fwd == sent_bwd == {"g-m-closed-new", "g-m-order-a", "g-m-order-b"}
    assert set(forward["receipt"]["certifies"]["admitted_fact_ids"]) == sent_fwd
    assert set(backward["receipt"]["certifies"]["admitted_fact_ids"]) == sent_bwd
    blob_fwd = flatten_messages(forward["final_messages"])
    blob_bwd = flatten_messages(backward["final_messages"])
    assert "CORRECTION-CLOSED-MARKER" in blob_fwd and "CORRECTION-CLOSED-MARKER" in blob_bwd
    assert "SUPERSEDED-OPEN-MARKER" not in blob_fwd
    assert "SUPERSEDED-OPEN-MARKER" not in blob_bwd
    assert forward["selection_fingerprint"]["sha256"] == backward["selection_fingerprint"]["sha256"]


def test_receipt_digest_currently_depends_on_created_at():
    """FINDING: build_receipt seals created_at, so two identical runs differ."""
    first = _run(QUESTION_M_NOW, [NEW_CLOSED])
    second = _run(QUESTION_M_NOW, [NEW_CLOSED])
    a = first["receipt"]["provenance_receipt"]
    b = second["receipt"]["provenance_receipt"]
    assert a["query"] == b["query"]
    assert a["answer"] == b["answer"]
    assert a["citations"] == b["citations"]
    if a["created_at"] != b["created_at"]:
        assert a["digest"] != b["digest"]


def test_receipt_digest_currently_depends_on_admitted_order():
    """FINDING: extractive answer and citations follow input order of kept facts."""
    forward = _run(QUESTION_M_NOW, [ORDER_A, ORDER_B])
    backward = _run(QUESTION_M_NOW, [ORDER_B, ORDER_A])
    assert forward["receipt"]["certifies"]["admitted_fact_ids"] == [
        "g-m-order-a", "g-m-order-b"
    ]
    assert backward["receipt"]["certifies"]["admitted_fact_ids"] == [
        "g-m-order-b", "g-m-order-a"
    ]
    assert forward["receipt"]["provenance_receipt"]["answer"] == (
        "M north door is locked ORDER-A-MARKER | M south door is locked ORDER-B-MARKER"
    )
    assert backward["receipt"]["provenance_receipt"]["answer"] == (
        "M south door is locked ORDER-B-MARKER | M north door is locked ORDER-A-MARKER"
    )


def test_bridge_side_flags_dirty_answer_repeating_superseded_status():
    result = _run(
        QUESTION_M_NOW, [OLD_OPEN, NEW_CLOSED],
        canned_answer=DIRTY_SUPERSEDED_ANSWER,
    )
    assert result["reply"] == DIRTY_SUPERSEDED_ANSWER
    assert result["bridge_answer_check"]["passed"] is False
    assert any("SUPERSEDED-OPEN-MARKER" in hit for hit in result["bridge_answer_check"]["hits"])
    checks = result["titan"]["titan_response_checks"]
    faith = checks["standalone_enabled"]["output_faithfulness"]
    # Record Titan's current score; do not treat it as a contract to fix.
    assert "unsupported" in faith
    assert "score" in faith


def test_confidence_zero_is_preserved_and_not_coerced_to_one():
    fact = dict(MATCHING)
    fact["confidence"] = 0.0
    result = _run(QUESTION_M_NOW, [fact])
    record = result["titan_records"][0]
    assert record["confidence"] == 0.0
    assert record["confidence_present"] is True
    assert record["confidence_repr"] == "0"
    blob = flatten_messages(result["final_messages"])
    assert "confidence=0" in blob
    assert "1.00" not in blob.split("MATCHING-GROUND-TEXT")[0] or "confidence=1" not in blob


def test_missing_confidence_is_represented_separately_from_zero():
    from tests.support.crystal_titan_bridge import encode_confidence, ground_to_titan_record
    fact = dict(MATCHING)
    fact.pop("confidence", None)
    encoded = encode_confidence(fact)
    assert encoded == {"present": False, "value": None, "repr": "missing"}
    record = ground_to_titan_record(fact)
    assert "confidence" not in record
    assert record["confidence_present"] is False
    assert record["confidence_repr"] == "missing"
    assert record["confidence_missing"] is True
    assert "confidence=missing" in record["source"]
    zero = encode_confidence({**MATCHING, "confidence": 0.0})
    assert zero == {"present": True, "value": 0.0, "repr": "0"}
    # FINDING: CanonicalView.STRICT treats missing confidence as invalid
    # and drops the fact before conversion, so run_bridge never ships it.
    result = _run(QUESTION_M_NOW, [fact])
    assert result["kind"] == "no_matching_information"
    assert result["titan_records"] == []
    assert "g-m-current" in {f["fact_id"] for f in result["canonical_view_excluded"]}


def test_non_status_question_is_not_rewritten_as_no_matching_information():
    result = _run("Почему небо голубое?", [MATCHING, FOREIGN])
    assert result["kind"] != "no_matching_information"
    assert result["kind"] in {"unsupported", "needs_clarification"}
    assert result["titan_invoked"] is False


def test_status_question_with_grounds_still_invokes_titan():
    result = _run(QUESTION_M_NOW, [MATCHING])
    assert result["kind"] == "answer_request"
    assert result["titan_invoked"] is True
    assert result["provider_calls"] == 1
    assert result["handoff"]["provider_called"] is True


def test_prepared_and_received_are_captured_at_distinct_points():
    """Independent hooks: Titan send-boundary vs fake-provider POST body."""
    result = _run(QUESTION_M_NOW, [MATCHING], canned_answer=CLEAN_ANSWER)
    handoff = result["handoff"]
    assert handoff["prepared_matches_provider_received"] is True
    assert result["titan"]["capture_points"] == {
        "prepared": "core.llm_stream._deepseek_request_body body['messages']",
        "received": "FakeAsyncClient.post(json) body['messages']",
    }
    assert MATCHING["claim"] in flatten_messages(handoff["prepared_messages"])
    assert MATCHING["claim"] in flatten_messages(handoff["provider_received"])


def test_missing_confidence_in_actual_titan_prompt_renders_zero():
    """FINDING: Titan formats a missing confidence key as conf=0.00.

    The lab bridge does not invent a number. CanonicalView.STRICT drops a
    fact with missing confidence before run_bridge, so this invokes Titan
    directly with the converted record.
    """
    from tests.support.crystal_titan_bridge import (
        default_titan_invoker,
        ground_to_titan_record,
    )

    fact = dict(MATCHING)
    fact.pop("confidence", None)
    record = ground_to_titan_record(fact)
    assert "confidence" not in record
    assert record["confidence_repr"] == "missing"
    assert "confidence=missing" in record["source"]
    titan = default_titan_invoker()(QUESTION_M_NOW, [record])
    blob = flatten_messages(titan["prepared_messages"])
    received = flatten_messages(titan["provider_received_messages"])
    assert "conf=0.00" in blob
    assert "conf=0.00" in received
    assert "confidence=missing" in blob
    assert titan["prepared_matches_provider_received"] is True


def test_selection_fingerprint_is_not_proof_of_identical_context():
    shared = {
        "fact_id": "g-m-current",
        "claim": "M is operational MATCHING-GROUND-TEXT",
        "primary_object": "M",
    }
    a = _canon({
        **shared,
        "source": "src-a",
        "observed_at": "2026-11-09T12:00:00+01:00",
        "valid_from": "2026-11-01T00:00:00+01:00",
        "valid_until": "2026-11-10T00:00:00+01:00",
        "metadata": {"provenance": {"origin": "a", "record": "PROV-A"}},
    })
    b = _canon({
        **shared,
        "source": "src-b",
        "observed_at": "2026-11-09T11:00:00+01:00",
        "valid_from": "2026-11-08T00:00:00+01:00",
        "valid_until": "2026-11-30T00:00:00+01:00",
        "metadata": {"provenance": {"origin": "b", "record": "PROV-B"}},
    })
    ra = _run(QUESTION_M_NOW, [a])
    rb = _run(QUESTION_M_NOW, [b])
    assert ra["selection_fingerprint"]["sha256"] == rb["selection_fingerprint"]["sha256"]
    assert ra["selection_fingerprint"]["proves_identical_context"] is False
    blob_a = flatten_messages(ra["final_messages"])
    blob_b = flatten_messages(rb["final_messages"])
    assert "src-a" in blob_a and "src-b" in blob_b
    assert "PROV-A" in blob_a and "PROV-B" in blob_b
    assert "valid_from=2026-11-01T00:00:00+01:00" in blob_a
    assert "valid_from=2026-11-08T00:00:00+01:00" in blob_b
