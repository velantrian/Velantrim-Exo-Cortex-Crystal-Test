#!/usr/bin/env python3
"""Reproduce supersede() with different objects on a main Crystal checkout.

Read-only with respect to that checkout: uses a temporary SQLite DB and
prints one JSON object to stdout. Set CRYSTAL_MAIN_ROOT to the Crystal
tree (the directory that contains core/reconcile.py). This file is not a
pytest test (name does not match test_*.py).
"""
from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(root), text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable:{exc}"


def main() -> int:
    raw = (os.environ.get("CRYSTAL_MAIN_ROOT") or "").strip()
    if not raw:
        print(
            "CRYSTAL_MAIN_ROOT is required (path to a main Crystal checkout)",
            file=sys.stderr,
        )
        return 2
    crystal = Path(raw).resolve()
    if not (crystal / "core" / "reconcile.py").is_file():
        print(
            f"CRYSTAL_MAIN_ROOT does not look like Crystal: {crystal}",
            file=sys.stderr,
        )
        return 2

    work = Path(tempfile.mkdtemp(prefix="crystal-supersede-repro-"))
    os.environ["VELANTRIM_L3_BACKEND"] = "mock"
    os.environ["VELANTRIM_EMBEDDER"] = "hashing"
    os.environ["VELANTRIM_GENERATOR"] = "extractive"
    os.environ["VELANTRIM_QUEUE_BACKEND"] = "sqlite"
    os.environ["VELANTRIM_DEMO_SEED"] = "0"
    os.environ["VELANTRIM_STORAGE_PROFILE_PATH"] = str(work / "storage-profile.json")
    sys.path.insert(0, str(crystal))

    from core import embedding, generation, l3_graph, memory, queue
    from core.memory import get_fact, store_fact, transition_esm
    from core.reconcile import REL_SUPERSEDED_BY, supersede

    memory.SQLITE_PATH = str(work / "test.db")
    memory._L0.clear()
    l3_graph.reset_l3_graph()
    embedding.reset_embedder()
    generation.reset_generator()
    if hasattr(queue, "reset_outbox_queue"):
        queue.reset_outbox_queue()

    lines, start = inspect.getsourcelines(supersede)
    object_mentions = [
        line.rstrip()
        for line in lines
        if any(
            token in line
            for token in (
                "primary_object",
                "asked_object",
                "object",
                "valid_from",
                "valid_until",
                "period",
                "same object",
            )
        )
    ]

    old_in = {
        "fact_id": "obj-m",
        "claim": "M is open SUPERSEDE-M-MARKER",
        "source": "s",
        "confidence": 0.9,
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
        "truth_status": "VERIFIED",
        "restricted": False,
        "primary_object": "M",
        "object": "M",
        "observed_at": "2026-11-09T12:00:00+01:00",
        "metadata": {"primary_object": "M", "note": "old-about-M"},
    }
    new_in = {
        "fact_id": "obj-l",
        "claim": "L is closed SUPERSEDE-L-MARKER",
        "source": "s",
        "confidence": 0.9,
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
        "truth_status": "VERIFIED",
        "restricted": False,
        "primary_object": "L",
        "object": "L",
        "observed_at": "2026-11-09T12:00:00+01:00",
        "metadata": {"primary_object": "L", "note": "new-about-L"},
    }

    store_fact(old_in)
    transition_esm("obj-m", "Validated")
    stored_old_before = get_fact("obj-m")
    stored_new_before = get_fact("obj-l")

    error = None
    new_id = None
    try:
        new_id = supersede("obj-m", new_in)
    except Exception as exc:  # noqa: BLE001 — record the exact failure
        error = f"{type(exc).__name__}: {exc}"

    stored_old_after = get_fact("obj-m")
    stored_new_after = get_fact("obj-l")

    neighbors = []
    if stored_old_after is not None:
        neighbors = [
            n.get("fact_id")
            for n in l3_graph.get_l3_graph().neighbors(
                "obj-m", rel_type=REL_SUPERSEDED_BY
            )
        ]

    cols = []
    if Path(memory.SQLITE_PATH).exists():
        with sqlite3.connect(memory.SQLITE_PATH) as conn:
            cols = [row[1] for row in conn.execute("PRAGMA table_info(facts)")]

    def keys(row):
        return sorted(row.keys()) if isinstance(row, dict) else None

    report = {
        "crystal_root": str(crystal),
        "crystal_head": git_head(crystal),
        "expected_head_prefix": "ba8e84a",
        "temp_db": memory.SQLITE_PATH,
        "functions": {
            "supersede": {
                "qualname": f"{supersede.__module__}.{supersede.__name__}",
                "start_line": start,
                "end_line": start + len(lines) - 1,
                "file": str(crystal / "core" / "reconcile.py"),
            },
            "store_fact": {
                "qualname": f"{store_fact.__module__}.{store_fact.__name__}",
                "start_line": inspect.getsourcelines(store_fact)[1],
                "file": str(crystal / "core" / "memory.py"),
            },
            "get_fact": {
                "qualname": f"{get_fact.__module__}.{get_fact.__name__}",
                "start_line": inspect.getsourcelines(get_fact)[1],
                "file": str(crystal / "core" / "memory.py"),
            },
            "transition_esm": {
                "qualname": f"{transition_esm.__module__}.{transition_esm.__name__}",
                "start_line": inspect.getsourcelines(transition_esm)[1],
                "file": str(crystal / "core" / "memory.py"),
            },
        },
        "supersede_source_mentions_object_or_period": object_mentions,
        "supersede_checks_object_match": any(
            "primary_object" in line or "asked_object" in line
            for line in object_mentions
        ),
        "allowed_scenario_checks_in_supersede": [
            "store_fact(new) with epistemic_state=Observed",
            "if enforce_gate=True: core.pipeline.guardian then core.pipeline.truth_gate",
            "transition_esm(new_id, Validated)",
            "if old is Validated: transition_esm(old, Contradicted) then Deprecated",
            "l3_graph.add_edge(old_id, SUPERSEDED_BY, new_id)",
        ],
        "facts_table_columns": cols,
        "store_fact_record_fields_hardcoded": [
            "fact_id", "claim", "source", "confidence", "epistemic_state",
            "claim_type", "source_status", "significance", "created_at",
            "updated_at", "metadata",
        ],
        "input_old_object_fields": {
            "primary_object": old_in["primary_object"],
            "object": old_in["object"],
        },
        "input_new_object_fields": {
            "primary_object": new_in["primary_object"],
            "object": new_in["object"],
        },
        "stored_old_before_keys": keys(stored_old_before),
        "stored_old_before_top_level_primary_object": (
            stored_old_before.get("primary_object") if stored_old_before else None
        ),
        "stored_old_before_top_level_object": (
            stored_old_before.get("object") if stored_old_before else None
        ),
        "stored_old_before_metadata": (
            stored_old_before.get("metadata") if stored_old_before else None
        ),
        "stored_old_before_esm": (
            stored_old_before.get("epistemic_state") if stored_old_before else None
        ),
        "stored_new_before": stored_new_before,
        "supersede_error": error,
        "supersede_returned": new_id,
        "stored_old_after_esm": (
            stored_old_after.get("epistemic_state") if stored_old_after else None
        ),
        "stored_new_after_esm": (
            stored_new_after.get("epistemic_state") if stored_new_after else None
        ),
        "stored_old_after_top_level_primary_object": (
            stored_old_after.get("primary_object") if stored_old_after else None
        ),
        "stored_new_after_top_level_primary_object": (
            stored_new_after.get("primary_object") if stored_new_after else None
        ),
        "stored_old_after_metadata": (
            stored_old_after.get("metadata") if stored_old_after else None
        ),
        "stored_new_after_metadata": (
            stored_new_after.get("metadata") if stored_new_after else None
        ),
        "superseded_by_neighbors": neighbors,
        "deprecated_m_record": (
            stored_old_after.get("epistemic_state") == "Deprecated"
            if stored_old_after else False
        ),
        "note": (
            "store_fact does not persist top-level primary_object/object as "
            "columns; extra keys survive only if copied into metadata."
        ),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
