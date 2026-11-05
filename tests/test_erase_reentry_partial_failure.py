"""Fault injection for the experimental erase + Immune partial-failure boundary.

Offline-only: isolated_db fixture pins SQLite, mock L3 and no network.
"""

import pytest

from core import audit, immune, memory
from core import erasure
from core.l3_graph import get_l3_graph

FID = "ing:partial-erasure-fault"
CLAIM = "Synthetic fault injection marker P8V4 equals 271828."


def test_guard_survives_pre_l1_delete_failure_and_retry_recovers(monkeypatch):
    monkeypatch.setenv("VELANTRIM_DEMO_SEED", "0")
    monkeypatch.setenv("VELANTRIM_IMMUNE_BLOCK_SEVERITY", "0.5")
    memory.store_fact({
        "fact_id": FID, "claim": CLAIM, "source": "test://fault-injection",
        "confidence": 0.9, "epistemic_state": "Validated",
        "claim_type": "WORLD_FACT", "source_status": "EXTERNAL",
    })
    get_l3_graph().merge_fact(memory.get_fact(FID))
    original_delete = erasure.delete_fact_l1

    def fail_before_l1_delete(_fact_id):
        raise RuntimeError("synthetic pre-L1 deletion failure")

    monkeypatch.setattr(erasure, "delete_fact_l1", fail_before_l1_delete)
    with pytest.raises(RuntimeError, match="synthetic pre-L1"):
        erasure.erase_fact(
            FID, reason="curator_wrong_claim",
            actor="lab-operator", block_reentry=True,
        )

    # Failure must never be mistaken for a successful erasure receipt.
    assert memory.get_fact(FID) is not None
    assert get_l3_graph().get_fact(FID) is not None
    assert memory.get_tombstone(FID) is None
    guard = immune.match_threat(CLAIM)
    assert guard is not None
    assert guard["threat_type"] == "erasure_reentry"
    assert audit.verify_audit_log()["ok"]
    # Guard installation is audited; completed erase is not.
    from core import audit as audit_module
    with memory._db() as conn:
        events = [row[0] for row in conn.execute(
            "SELECT event_type FROM audit_log"
        ).fetchall()]
    assert "immune_threat_recorded" in events
    assert "erase" not in events

    # Explicit operator retry, not an automatic rollback of a shared guard.
    monkeypatch.setattr(erasure, "delete_fact_l1", original_delete)
    receipt = erasure.erase_fact(
        FID, reason="curator_wrong_claim",
        actor="lab-operator", block_reentry=True,
    )
    assert receipt["erased_now"] is True
    assert receipt["reentry_pattern_id"] == guard["pattern_id"]
    assert memory.get_fact(FID) is None
    assert get_l3_graph().get_fact(FID) is None
    assert memory.get_tombstone(FID) is not None
    assert immune.match_threat(CLAIM) is not None
    assert audit.verify_audit_log()["ok"]
