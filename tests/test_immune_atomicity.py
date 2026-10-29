"""Immune mutation and its audit event must commit or roll back together."""

import pytest

from core import audit, immune, memory


def fail_audit(*args, **kwargs):
    raise RuntimeError("synthetic audit append failure")


def test_failed_record_audit_leaves_no_blocking_pattern(monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(audit, "append_event", fail_audit)
        with pytest.raises(RuntimeError, match="synthetic audit"):
            immune.record_threat("synthetic denied marker", actor="test-curator")
    assert immune.list_threats() == []
    assert audit.audit_log() == []
    assert immune.match_threat("synthetic denied marker") is None

    # Positive control: successful recording really blocks matching content.
    recorded = immune.record_threat("synthetic denied marker", actor="test-curator")
    assert immune.match_threat("synthetic denied marker")["pattern_id"] == recorded["pattern_id"]
    assert immune.match_threat("independent allowed neighbor") is None
    assert audit.verify_audit_log()["ok"]


def test_failure_after_journal_insert_rolls_back_pattern_event_and_checkpoint(monkeypatch):
    append = audit.append_event

    def append_then_fail(*args, **kwargs):
        append(*args, **kwargs)
        raise RuntimeError("synthetic failure after audit insert")

    with monkeypatch.context() as patch:
        patch.setattr(audit, "append_event", append_then_fail)
        with pytest.raises(RuntimeError, match="after audit insert"):
            immune.record_threat("synthetic denied marker", actor="test-curator")
    assert immune.list_threats() == []
    assert audit.audit_log() == []
    assert audit.verify_audit_log()["ok"]


def test_caller_connection_requires_transaction_and_remains_uncommitted():
    with audit._AUDIT_LOCK:
        with memory._db() as conn:
            with pytest.raises(ValueError, match="active caller transaction"):
                audit.append_event("synthetic", None, connection=conn)
            memory.begin_immediate(conn)
            audit.append_event("synthetic", None, {"actor": "test"}, connection=conn)
            assert conn.in_transaction
            conn.rollback()
    assert audit.audit_log() == []
    assert audit.verify_audit_log()["ok"]


def test_failed_forget_audit_keeps_existing_block(monkeypatch):
    recorded = immune.record_threat("synthetic denied marker", actor="test-curator")
    before = audit.audit_log()
    with monkeypatch.context() as patch:
        patch.setattr(audit, "append_event", fail_audit)
        with pytest.raises(RuntimeError, match="synthetic audit"):
            immune.forget_threat(recorded["pattern_id"], actor="test-curator")
    assert immune.match_threat("synthetic denied marker") is not None
    assert audit.audit_log() == before
    assert audit.verify_audit_log()["ok"]

    assert immune.forget_threat(recorded["pattern_id"], actor="test-curator")
    assert immune.match_threat("synthetic denied marker") is None
    assert audit.verify_audit_log()["ok"]
