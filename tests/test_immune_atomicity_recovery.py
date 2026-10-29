"""Crash and checkpoint failure probes for the Draft immune/audit transaction.

Synthetic SQLite data only. No model, network, or production store is accessed.
"""

import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from core import audit, immune, memory


_PATTERN = "synthetic aborted marker"

# os._exit bypasses Python finally/context-manager cleanup. It is a process
# termination probe, not a power-loss/disk-durability certification.
_CHILD = """
import os
import sys
from core import audit, immune

original = audit.append_event

def exit_at_boundary(*args, **kwargs):
    if sys.argv[1] == 'before_audit':
        os._exit(71)
    original(*args, **kwargs)
    # Audit event and chain checkpoint were written, but the immune caller
    # has not exited memory._db(), so it has not committed the transaction.
    os._exit(72)

audit.append_event = exit_at_boundary
if sys.argv[2] == 'record':
    immune.record_threat('synthetic aborted marker', actor='test-curator')
else:
    immune.forget_threat(sys.argv[3], actor='test-curator')
raise AssertionError('child did not hit crash injection')
"""


def _reopened_snapshot():
    """Read all three tables through a newly opened, then closed, connection."""
    queries = (
        "SELECT pattern_id, pattern, threat_type, severity, recorded_at, "
        "actor, hits, last_hit_at FROM immune_memory ORDER BY pattern_id",
        "SELECT seq, ts, event, fact_id, detail, prev_hash, entry_hash, "
        "signature FROM audit_log ORDER BY seq",
        "SELECT seq, head_hash FROM chain_checkpoints "
        "WHERE chain_name = 'audit' AND scope_id = ''",
    )
    with closing(sqlite3.connect(memory.SQLITE_PATH)) as conn:
        snapshot = tuple(tuple(conn.execute(q).fetchall()) for q in queries)
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    return snapshot


def _seed(operation):
    if operation == "record":
        # Force the existing-head UPDATE path, not just initial checkpoint INSERT.
        audit.append_event("synthetic_baseline", None, {"actor": "test"})
        return ""
    return immune.record_threat(_PATTERN, actor="test-curator")["pattern_id"]


def _retry_successfully(operation, pattern_id, event_count):
    if operation == "record":
        recorded = immune.record_threat(_PATTERN, actor="test-curator")
        assert immune.match_threat(_PATTERN)["pattern_id"] == recorded["pattern_id"]
    else:
        assert immune.forget_threat(pattern_id, actor="test-curator") is True
        assert immune.match_threat(_PATTERN) is None

    assert len(audit.audit_log()) == event_count + 1
    assert audit.verify_audit_log()["ok"] is True
    checkpoint = _reopened_snapshot()[2]
    assert checkpoint and checkpoint[0][0] == event_count + 1


@pytest.mark.parametrize("operation", ["record", "forget"])
@pytest.mark.parametrize(
    "stage, expected_exit",
    [("before_audit", 71), ("after_checkpoint", 72)],
)
def test_abrupt_process_exit_rolls_back_then_retry_survives_reopen(
    operation, stage, expected_exit
):
    pattern_id = _seed(operation)
    before = _reopened_snapshot()

    env = os.environ.copy()
    env["VELANTRIM_DB"] = str(memory.SQLITE_PATH)
    child = subprocess.run(
        [sys.executable, "-c", _CHILD, stage, operation, pattern_id],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert child.returncode == expected_exit, child.stderr
    assert _reopened_snapshot() == before
    assert audit.verify_audit_log()["ok"] is True
    _retry_successfully(operation, pattern_id, len(before[1]))


@pytest.mark.parametrize("operation", ["record", "forget"])
def test_checkpoint_write_failure_rolls_back_guard_and_audit(operation):
    pattern_id = _seed(operation)
    before = _reopened_snapshot()

    # A real SQLite write rejection occurs after audit_log INSERT but before
    # the checkpoint UPDATE can finish. The trigger exists only in the test DB.
    with closing(sqlite3.connect(memory.SQLITE_PATH)) as conn:
        conn.execute(
            "CREATE TRIGGER fail_audit_checkpoint "
            "BEFORE UPDATE ON chain_checkpoints "
            "WHEN NEW.chain_name = 'audit' AND NEW.scope_id = '' "
            "BEGIN SELECT RAISE(ABORT, 'synthetic checkpoint failure'); END"
        )
        conn.commit()
    try:
        with pytest.raises(sqlite3.IntegrityError, match="synthetic checkpoint failure"):
            if operation == "record":
                immune.record_threat(_PATTERN, actor="test-curator")
            else:
                immune.forget_threat(pattern_id, actor="test-curator")
        assert _reopened_snapshot() == before
        assert audit.verify_audit_log()["ok"] is True
    finally:
        with closing(sqlite3.connect(memory.SQLITE_PATH)) as conn:
            conn.execute("DROP TRIGGER IF EXISTS fail_audit_checkpoint")
            conn.commit()

    _retry_successfully(operation, pattern_id, len(before[1]))
