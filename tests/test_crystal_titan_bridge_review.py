"""Follow-up lab cases: normal Crystal path, SUPERSEDED_BY, shadow support.

Does not rewrite historical results. Isolated fixtures only.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from core.applicability import select
from core.memory import get_fact, store_fact, transition_esm
from core.provenance import RECEIPT_VERSION, verify_receipt
from core.reconcile import REL_SUPERSEDED_BY, supersede
from core.l3_graph import get_l3_graph
from tests.support.crystal_normal_path import QUERY_CALL_CHAIN, run_crystal_query_path
from tests.support.crystal_titan_bridge import flatten_messages, run_bridge
from tests.support.shadow_support import evaluate_shadow_support
from tests.test_applicability_live_path import admit, dumps, reopen
from tests.test_applicability_live_path import durable as durable  # fixture
from tests.test_crystal_titan_bridge import (
    CONDITIONAL,
    DIRTY_FOREIGN_ANSWER,
    FOREIGN,
    MATCHING,
    NEGATED,
    NEW_CLOSED,
    OLD_OPEN,
    QUESTION_M_NOW,
    STALE,
    TZ,
    NOW,
    KNOWN,
    _canon,
    _run,
)


QUESTION_M_PAST = "Какой статус был у M 1 октября 2026 в 10:00?"


def test_receipt_sealed_fields_include_time_and_are_event_specific():
    result = _run(QUESTION_M_NOW, [MATCHING])
    sealed = result["receipt"]["provenance_receipt"]
    assert sealed["version"] == RECEIPT_VERSION
    for key in ("version", "created_at", "query", "answer", "citations", "digest"):
        assert key in sealed
    report = verify_receipt(sealed)
    assert report["digest_valid"] is True
    assert result["receipt"]["certifies_response"] is False
    assert "titan_generated_answer" in result["receipt"]["does_not_certify"]
    # The sealed answer is Crystal's extractive concatenation, not Titan's reply.
    assert sealed["answer"] != result["reply"] or sealed["answer"] == MATCHING["claim"]
    assert MATCHING["claim"] in sealed["answer"]
    fingerprint = result["selection_fingerprint"]
    assert fingerprint["separate_from_receipt"] is True
    assert fingerprint["version"] == "lab-selection-fp-v1"
    assert fingerprint["sha256"] != sealed["digest"]


def test_selection_fingerprint_stable_across_order_and_distinct_from_receipt():
    a = _run(QUESTION_M_NOW, [MATCHING, NEW_CLOSED])
    b = _run(QUESTION_M_NOW, [NEW_CLOSED, MATCHING])
    assert a["selection_fingerprint"]["sha256"] == b["selection_fingerprint"]["sha256"]
    assert a["receipt"]["provenance_receipt"]["answer"] != b["receipt"]["provenance_receipt"]["answer"]


def test_case_a_old_record_already_out_of_current_state():
    result = _run(QUESTION_M_NOW, [OLD_OPEN, NEW_CLOSED])
    kept = {f["fact_id"] for f in result["kept"]}
    dropped = {f["fact_id"] for f in result["canonical_view_excluded"]}
    assert kept == {"g-m-closed-new"}
    assert "g-m-open-old" in dropped
    blob = flatten_messages(result["final_messages"])
    assert "CORRECTION-CLOSED-MARKER" in blob
    assert "SUPERSEDED-OPEN-MARKER" not in blob
    # FINDING: drop happens because CanonicalView filters Deprecated ESM,
    # not because select() reads a SUPERSEDED_BY edge.
    assert not any(item.get("fact_id") == "g-m-open-old" for item in result["excluded"])


def test_case_b_unresolved_contradiction_admits_both():
    open_now = _canon({
        "fact_id": "g-m-open-live",
        "claim": "M is open CONTRADICTION-OPEN-MARKER",
        "source": "operator-log:m-open-live",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    result = _run(QUESTION_M_NOW, [open_now, NEW_CLOSED])
    kept = {f["fact_id"] for f in result["kept"]}
    assert kept == {"g-m-open-live", "g-m-closed-new"}
    blob = flatten_messages(result["final_messages"])
    assert "CONTRADICTION-OPEN-MARKER" in blob
    assert "CORRECTION-CLOSED-MARKER" in blob


def test_case_c_proposed_supersession_link_has_no_admission_effect():
    proposed = _canon({
        "fact_id": "g-m-open-proposed",
        "claim": "M is open PROPOSED-OPEN-MARKER",
        "source": "operator-log:m-open-proposed",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
        "metadata": {
            "proposed_superseded_by": "g-m-closed-new",
            "provenance": {"origin": "fixture", "record": "PROV-M-OPEN-PROPOSED"},
        },
    })
    result = _run(QUESTION_M_NOW, [proposed, NEW_CLOSED])
    kept = {f["fact_id"] for f in result["kept"]}
    assert kept == {"g-m-open-proposed", "g-m-closed-new"}


def test_case_c_accepted_supersede_write_and_memory_before_after():
    before_old = {
        "fact_id": "sup-old",
        "claim": "M is open WRITE-OLD-MARKER",
        "source": "s",
        "confidence": 0.9,
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
        "truth_status": "VERIFIED",
        "restricted": False,
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    }
    store_fact(before_old)
    transition_esm("sup-old", "Validated")
    memory_before = {
        "sup-old": get_fact("sup-old")["epistemic_state"],
        "sup-new": get_fact("sup-new"),
    }
    new_id = supersede("sup-old", {
        "fact_id": "sup-new",
        "claim": "M is closed WRITE-NEW-MARKER",
        "source": "s",
        "confidence": 0.9,
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    assert new_id == "sup-new"
    memory_after = {
        "sup-old": get_fact("sup-old")["epistemic_state"],
        "sup-new": get_fact("sup-new")["epistemic_state"],
    }
    assert memory_before == {"sup-old": "Validated", "sup-new": None}
    assert memory_after == {"sup-old": "Deprecated", "sup-new": "Validated"}
    neighbors = get_l3_graph().neighbors("sup-old", rel_type=REL_SUPERSEDED_BY)
    assert "sup-new" in {n["fact_id"] for n in neighbors}
    old_as_input = _canon(dict(before_old), epistemic_state=memory_after["sup-old"])
    new_as_input = _canon({
        "fact_id": "sup-new",
        "claim": "M is closed WRITE-NEW-MARKER",
        "source": "s",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    }, epistemic_state=memory_after["sup-new"])
    result = _run(QUESTION_M_NOW, [old_as_input, new_as_input])
    assert {f["fact_id"] for f in result["kept"]} == {"sup-new"}
    assert "sup-old" in {f["fact_id"] for f in result["canonical_view_excluded"]}


def test_case_d_current_vs_past_as_of():
    past_cover = _canon({
        "fact_id": "g-m-past-cover",
        "claim": "M was in maintenance PAST-COVER-MARKER",
        "source": "operator-log:m-past-cover",
        "primary_object": "M",
        "observed_at": "2026-10-01T10:00:00+02:00",
    })
    current = _run(QUESTION_M_NOW, [past_cover, MATCHING])
    assert {f["fact_id"] for f in current["kept"]} == {"g-m-current"}
    assert any(item.get("fact_id") == "g-m-past-cover" for item in current["excluded"])
    past = _run(QUESTION_M_PAST, [past_cover, MATCHING])
    assert past["kind"] == "answer_request"
    assert {f["fact_id"] for f in past["kept"]} == {"g-m-past-cover"}
    blob = flatten_messages(past["final_messages"])
    assert "PAST-COVER-MARKER" in blob
    assert "MATCHING-GROUND-TEXT" not in blob
    assert past["parsed"]["params"]["as_of"] != current["parsed"]["params"]["as_of"]


def test_case_e_foreign_object_correction_does_not_drop_m():
    foreign_correction = _canon({
        "fact_id": "g-l-closed-new",
        "claim": "L is closed FOREIGN-CORRECTION-MARKER",
        "source": "operator-log:l-closed",
        "primary_object": "L",
        "observed_at": "2026-11-09T12:00:00+01:00",
        "metadata": {"supersedes": "g-m-open-proposed"},
    })
    m_open = _canon({
        "fact_id": "g-m-open-untouched",
        "claim": "M is open UNTOUCHED-OPEN-MARKER",
        "source": "operator-log:m-open-untouched",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    result = _run(QUESTION_M_NOW, [m_open, foreign_correction])
    assert {f["fact_id"] for f in result["kept"]} == {"g-m-open-untouched"}
    assert any(item.get("fact_id") == "g-l-closed-new" for item in result["excluded"])
    blob = flatten_messages(result["final_messages"])
    assert "UNTOUCHED-OPEN-MARKER" in blob
    assert "FOREIGN-CORRECTION-MARKER" not in blob


def test_supersede_does_not_check_object_match():
    """FINDING: reconcile.supersede does not require the new fact to share an object."""
    store_fact({
        "fact_id": "obj-m",
        "claim": "M is open",
        "source": "s",
        "confidence": 0.9,
        "primary_object": "M",
    })
    transition_esm("obj-m", "Validated")
    supersede("obj-m", {
        "fact_id": "obj-l",
        "claim": "L is closed OTHER-OBJECT-SUPERSEDE",
        "source": "s",
        "confidence": 0.9,
        "primary_object": "L",
    })
    assert get_fact("obj-m")["epistemic_state"] == "Deprecated"
    assert get_fact("obj-l")["epistemic_state"] == "Validated"


def test_shadow_support_counterexamples():
    result = _run(
        QUESTION_M_NOW, [NEGATED],
        canned_answer="M is operational and running.",
    )
    shadow = result["shadow_support"]
    assert shadow["blocks"] is False
    assert shadow["authority"] == "shadow"
    assert shadow["verdict"] == "contradicts"
    assert any(item["reason"] == "negation_mismatch" for item in shadow["contradicts"])

    numbers = _canon({
        "fact_id": "g-m-num",
        "claim": "M reports 41 units NUMBER-41-MARKER",
        "source": "operator-log:m-num",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    result = _run(QUESTION_M_NOW, [numbers], canned_answer="M reports 42 units.")
    assert any(item["reason"] == "number_mismatch" for item in result["shadow_support"]["contradicts"])

    ident = _canon({
        "fact_id": "g-m-id",
        "claim": "ticket AB-XYZQ is open IDENT-MARKER",
        "source": "operator-log:m-id",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    result = _run(QUESTION_M_NOW, [ident], canned_answer="ticket AB-WXYZ is open.")
    assert any(item["reason"] == "identifier_mismatch" for item in result["shadow_support"]["contradicts"])

    result = _run(
        QUESTION_M_NOW, [CONDITIONAL],
        canned_answer="M is operational CONDITION-IF-MARKER",
    )
    assert any(item["reason"] == "missing_condition" for item in result["shadow_support"]["contradicts"])

    result = _run(
        QUESTION_M_NOW, [MATCHING, FOREIGN],
        canned_answer=DIRTY_FOREIGN_ANSWER,
    )
    assert result["shadow_support"]["verdict"] == "cites_excluded_record"
    assert "g-l-foreign" in result["shadow_support"]["cited_excluded"]
    assert result["bridge_answer_check"]["passed"] is False


def test_duplicate_source_labels_are_explicitly_ambiguous():
    a = _canon({
        "fact_id": "g-m-dup-a",
        "claim": "M is 10 units DUP-A-MARKER",
        "source": "shared-log",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    b = _canon({
        "fact_id": "g-m-dup-b",
        "claim": "M is 20 units DUP-B-MARKER",
        "source": "shared-log",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    result = _run(QUESTION_M_NOW, [a, b], canned_answer="According to shared-log, M is 10 units.")
    shadow = result["shadow_support"]
    assert shadow["verdict"] == "ambiguous_source_label"
    assert shadow["ambiguous_source_labels"]["shared-log"] == ["g-m-dup-a", "g-m-dup-b"]
    blob = flatten_messages(result["final_messages"])
    # Titan prints each record as its own line; the harness unique-encodes
    # source with fact_id, so Titan itself does not collapse the pair.
    assert "DUP-A-MARKER" in blob and "DUP-B-MARKER" in blob
    assert "fact_id=g-m-dup-a" in blob and "fact_id=g-m-dup-b" in blob


def test_output_faithfulness_standalone_on_dirty_and_clean_answers():
    dirty = _run(QUESTION_M_NOW, [MATCHING], canned_answer=DIRTY_FOREIGN_ANSWER)
    faith = dirty["titan"]["titan_response_checks"]
    assert faith["wired_on_chat_llm_reply"]["output_faithfulness"] is False
    assert faith["feature_flags"]["enable_output_faithfulness"] is False
    assert faith["gated_as_configured"]["output_faithfulness"] is None
    standalone = faith["standalone_enabled"]["output_faithfulness"]
    assert standalone["unsupported"]
    clean = _run(QUESTION_M_NOW, [MATCHING], canned_answer=MATCHING["claim"])
    clean_faith = clean["titan"]["titan_response_checks"]["standalone_enabled"]["output_faithfulness"]
    assert clean_faith["unsupported"] == []
    assert clean_faith["score"] == 1.0


def test_normal_crystal_query_path_matching_and_foreign(durable):
    admit("live-m", "M is operational MATCHING-LIVE-TEXT", {
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    admit("live-l", "L is offline FOREIGN-LIVE-TEXT", {
        "primary_object": "L",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    reopen()
    before = dumps(durable)
    matching = run_crystal_query_path(
        "M is operational MATCHING-LIVE-TEXT",
        asked_object="M",
        as_of="2026-11-09T12:00:00+01:00",
        temporal_scope="current",
    )
    assert matching["entry"] == "core.query_pipeline.query"
    assert matching["functions"] == list(QUERY_CALL_CHAIN)
    assert matching["certifies_model_text"] is False
    assert matching["result"]["answer"] == "M is operational MATCHING-LIVE-TEXT"
    assert [f["fact_id"] for f in matching["result"]["facts"]] == ["live-m"]
    assert matching["receipt"] is not None
    assert matching["receipt"]["answer"] == matching["result"]["answer"]
    report = verify_receipt(matching["receipt"])
    assert report["digest_valid"] is True
    assert dumps(durable) == before


def test_normal_crystal_query_path_foreign_object_has_no_answer(durable):
    admit("live-l-only", "L is offline FOREIGN-LIVE-ONLY", {
        "primary_object": "L",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    reopen()
    before = dumps(durable)
    foreign_only = run_crystal_query_path(
        "L is offline FOREIGN-LIVE-ONLY",
        asked_object="M",
        as_of="2026-11-09T12:00:00+01:00",
        temporal_scope="current",
    )
    assert foreign_only["entry"] == "core.query_pipeline.query"
    assert "core.pipeline.generate_answer" in foreign_only["functions"]
    assert foreign_only["result"]["answer"] is None
    assert foreign_only["result"]["facts"] == []
    assert foreign_only["receipt"] is None
    assert foreign_only["receipt_error"]
    assert dumps(durable) == before


QUESTION_M_NOV9_PAST = "Какой статус был у M 9 ноября 2026 в 12:00?"


def test_past_as_of_against_deprecated_same_moment_correction():
    """Deprecated same-moment record: models a correction, not a closed interval.

    OLD_OPEN and NEW_CLOSED share observed_at=2026-11-09T12:00:00+01:00.
    That is the 'correction of an error' shape: two claims about the same
    moment. Crystal's supersede() does not distinguish this from 'end of a
    previously true fact'; both become Validated → Contradicted → Deprecated.
    Historical-read rules are unchanged here: CanonicalView.STRICT still
    drops Deprecated regardless of as_of, so a past question about that
    same timestamp does not recover the old record.
    """
    result = _run(QUESTION_M_NOV9_PAST, [OLD_OPEN])
    assert result["parsed"]["kind"] == "parsed"
    assert "2026-11-09" in (result["params"] or {}).get("as_of", "")
    assert result["kind"] == "no_matching_information"
    assert result["titan_invoked"] is False
    assert "g-m-open-old" in {f["fact_id"] for f in result["canonical_view_excluded"]}
    kept_by_select, _ = select(
        [OLD_OPEN],
        asked_object="M",
        as_of=result["params"]["as_of"],
        temporal_scope=result["params"].get("temporal_scope"),
    )
    assert [f["fact_id"] for f in kept_by_select] == ["g-m-open-old"]


def test_past_as_of_against_deprecated_earlier_observation():
    """Deprecated earlier observation: 'end of a previously true fact' shape.

    Crystal still does not keep the old record for historical as_of: STRICT
    projection removes Deprecated before select() runs. select() alone would
    admit the covering past record.
    """
    deprecated_past = _canon({
        "fact_id": "g-m-past-deprecated",
        "claim": "M was in maintenance PAST-DEPRECATED-MARKER",
        "source": "operator-log:m-past-deprecated",
        "primary_object": "M",
        "observed_at": "2026-10-01T10:00:00+02:00",
    }, epistemic_state="Deprecated")
    result = _run(QUESTION_M_PAST, [deprecated_past])
    assert result["parsed"]["kind"] == "parsed"
    assert "2026-10-01" in (result["params"] or {}).get("as_of", "")
    assert result["kind"] == "no_matching_information"
    assert result["titan_invoked"] is False
    assert "g-m-past-deprecated" in {
        f["fact_id"] for f in result["canonical_view_excluded"]
    }
    kept_by_select, _ = select(
        [deprecated_past],
        asked_object="M",
        as_of=result["params"]["as_of"],
        temporal_scope=result["params"].get("temporal_scope"),
    )
    assert [f["fact_id"] for f in kept_by_select] == ["g-m-past-deprecated"]


def test_shadow_does_not_support_answer_from_unsent_admitted_record():
    sent = _canon({
        "fact_id": "g-m-sent-only",
        "claim": "M north hall remains quiet this evening",
        "source": "operator-log:m-sent-only",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    unsent = _canon({
        "fact_id": "g-m-unsent-only",
        "claim": "M south hall has spare capacity available",
        "source": "operator-log:m-unsent-only",
        "primary_object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
    })
    prepared = [{"role": "system", "content": sent["claim"]}]
    shadow = evaluate_shadow_support(
        answer=unsent["claim"],
        prepared_messages=prepared,
        admitted=[sent, unsent],
        excluded=[],
    )
    assert shadow["verdict"] == "not_in_context"
    assert shadow["verdict"] != "supports"
    assert shadow["supports"] == []
    assert "g-m-unsent-only" in shadow["matched_outside_prepared_context"]
    assert any(
        item["fact_id"] == "g-m-unsent-only"
        for item in shadow["missing_from_prepared_context"]
    )
