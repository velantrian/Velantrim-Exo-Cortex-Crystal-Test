#!/usr/bin/env python3
"""Reproduce supersede() with different objects on a main Crystal checkout.

Observation script, not a pytest regression test. Read-only with respect
to that checkout: uses a temporary SQLite DB and prints one JSON object
to stdout. Set CRYSTAL_MAIN_ROOT to the Crystal tree (the directory that
contains core/reconcile.py).
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_EXPECTED_HEAD = "ba8e84a4f8f24bdb816ea8fb89485f1dedccd0a3"


def git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(root), text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable:{exc}"


def git_dirty_status(root: Path) -> list[str]:
    """Tracked changes and untracked files; do not skip untracked paths."""
    try:
        raw = subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=str(root),
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"unavailable:{exc}"]
    return [line for line in raw.splitlines() if line]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Observe supersede() across different objects on a Crystal checkout."
    )
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="Run even if HEAD or cleanliness does not match the expected reproduction.",
    )
    return parser.parse_args(argv)


def dump(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def checkout_identity(crystal: Path, expected_head: str) -> dict:
    head = git_head(crystal)
    dirty = git_dirty_status(crystal)
    head_ok = head == expected_head
    clean = dirty == []
    return {
        "expected_head": expected_head,
        "crystal_head": head,
        "head_matches_expected": head_ok,
        "checkout_clean": clean,
        "dirty_status": dirty,
        "matches_reproduction_checkout": head_ok and clean,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    diagnostic = args.diagnostic or (
        (os.environ.get("CRYSTAL_REPRO_DIAGNOSTIC") or "").strip() in
        ("1", "true", "yes", "on")
    )
    expected_head = (
        (os.environ.get("CRYSTAL_REPRO_EXPECTED_HEAD") or "").strip()
        or DEFAULT_EXPECTED_HEAD
    )
    raw = (os.environ.get("CRYSTAL_MAIN_ROOT") or "").strip()
    if not raw:
        dump({
            "error": "missing_crystal_main_root",
            "message": "CRYSTAL_MAIN_ROOT is required (path to a main Crystal checkout)",
            "mode": "error",
            "reproduction_of_expected_head": False,
        })
        return 2
    crystal = Path(raw).resolve()
    if not (crystal / "core" / "reconcile.py").is_file():
        dump({
            "error": "invalid_crystal_main_root",
            "message": f"CRYSTAL_MAIN_ROOT does not look like Crystal: {crystal}",
            "mode": "error",
            "reproduction_of_expected_head": False,
            "crystal_root": str(crystal),
        })
        return 2

    identity = checkout_identity(crystal, expected_head)
    if not identity["matches_reproduction_checkout"] and not diagnostic:
        dump({
            "error": "checkout_not_reproducible",
            "message": (
                "CRYSTAL_MAIN_ROOT is not a clean checkout of the expected "
                "commit. Re-run with --diagnostic or CRYSTAL_REPRO_DIAGNOSTIC=1 "
                "to observe this tree without claiming a reproduction."
            ),
            "mode": "error",
            "reproduction_of_expected_head": False,
            "crystal_root": str(crystal),
            **identity,
        })
        return 1

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
        "mode": "diagnostic" if diagnostic else "reproduction",
        "reproduction_of_expected_head": identity["matches_reproduction_checkout"],
        "crystal_root": str(crystal),
        "expected_head": identity["expected_head"],
        "crystal_head": identity["crystal_head"],
        "head_matches_expected": identity["head_matches_expected"],
        "checkout_clean": identity["checkout_clean"],
        "dirty_status": identity["dirty_status"],
        "expected_head_prefix": identity["expected_head"][:7],
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
