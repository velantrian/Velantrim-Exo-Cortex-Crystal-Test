"""Checkout guards for the supersede observation script.

Uses temporary git repositories only. Does not import or require a main
Crystal checkout: refuse-paths must exit before run_observation().
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent / "repro" / "repro_supersede_different_objects.py"
)
PINNED = "ba8e84a4f8f24bdb816ea8fb89485f1dedccd0a3"


def load_repro():
    spec = importlib.util.spec_from_file_location(
        "repro_supersede_different_objects", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(repo: Path, *args: str) -> str:
    env = os.environ.copy()
    env.setdefault("GIT_AUTHOR_NAME", "repro-test")
    env.setdefault("GIT_AUTHOR_EMAIL", "repro-test@example.invalid")
    env.setdefault("GIT_COMMITTER_NAME", "repro-test")
    env.setdefault("GIT_COMMITTER_EMAIL", "repro-test@example.invalid")
    return subprocess.check_output(
        ["git", *args], cwd=str(repo), text=True, env=env
    ).strip()


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "tree"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.name", "repro-test")
    git(repo, "config", "user.email", "repro-test@example.invalid")
    (repo / "README").write_text("observation fixture\n", encoding="utf-8")
    git(repo, "add", "README")
    git(repo, "commit", "-m", "init")
    return repo


def invoke(mod, monkeypatch, repo: Path | None, argv=None, env=None):
    if repo is None:
        monkeypatch.delenv("CRYSTAL_MAIN_ROOT", raising=False)
    else:
        monkeypatch.setenv("CRYSTAL_MAIN_ROOT", str(repo))
    monkeypatch.delenv("CRYSTAL_REPRO_EXPECTED_HEAD", raising=False)
    monkeypatch.delenv("CRYSTAL_REPRO_DIAGNOSTIC", raising=False)
    for key, value in (env or {}).items():
        if value is None:
            monkeypatch.delenv(key, raising=False)
        else:
            monkeypatch.setenv(key, value)
    called = []

    def _blocked(*_a, **_k):
        called.append(True)
        raise AssertionError("run_observation must not be called")

    monkeypatch.setattr(mod, "run_observation", _blocked)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    rc = mod.main(list(argv or []))
    payload = json.loads(buf.getvalue())
    return rc, payload, called


def test_normal_mode_refuses_head_mismatch(tmp_path, monkeypatch):
    mod = load_repro()
    repo = make_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    assert head != PINNED
    rc, payload, called = invoke(mod, monkeypatch, repo)
    assert rc == 1
    assert called == []
    assert payload["error"] == "checkout_not_reproducible"
    assert payload["mode"] == "error"
    assert payload["reproduction_of_expected_head"] is False
    assert payload["expected_head"] == PINNED
    assert payload["crystal_head"] == head
    assert payload["head_matches_expected"] is False
    assert payload["checkout_clean"] is True
    assert "supersede_returned" not in payload


def test_normal_mode_refuses_dirty_checkout(tmp_path, monkeypatch):
    mod = load_repro()
    repo = make_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    monkeypatch.setattr(mod, "DEFAULT_EXPECTED_HEAD", head)
    (repo / "stain.txt").write_text("untracked\n", encoding="utf-8")
    rc, payload, called = invoke(mod, monkeypatch, repo)
    assert rc == 1
    assert called == []
    assert payload["error"] == "checkout_not_reproducible"
    assert payload["mode"] == "error"
    assert payload["reproduction_of_expected_head"] is False
    assert payload["expected_head"] == head
    assert payload["crystal_head"] == head
    assert payload["head_matches_expected"] is True
    assert payload["checkout_clean"] is False
    assert payload["dirty_status"]
    assert "supersede_returned" not in payload


def test_override_in_normal_mode_does_not_make_other_commit_a_reproduction(
    tmp_path, monkeypatch
):
    mod = load_repro()
    repo = make_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    rc, payload, called = invoke(
        mod, monkeypatch, repo, env={"CRYSTAL_REPRO_EXPECTED_HEAD": head}
    )
    assert rc == 1
    assert called == []
    assert payload["error"] == "expected_head_override_not_allowed"
    assert payload["mode"] == "error"
    assert payload["reproduction_of_expected_head"] is False
    assert payload["expected_head"] == PINNED
    assert payload["requested_override"] == head
    assert payload["expected_head"] != head
    assert "supersede_returned" not in payload


def test_override_is_honored_in_diagnostic_mode(tmp_path, monkeypatch):
    mod = load_repro()
    repo = make_repo(tmp_path)
    head = git(repo, "rev-parse", "HEAD")
    code, payload, proceed = mod.preflight(
        repo, diagnostic=True, override=head
    )
    assert code == 0
    assert proceed is True
    assert payload["expected_head"] == head
    assert payload["crystal_head"] == head
    assert payload["head_matches_expected"] is True
    assert payload["checkout_clean"] is True
    assert payload["matches_reproduction_checkout"] is True

    rc, result, called = invoke(
        mod,
        monkeypatch,
        repo,
        argv=["--diagnostic"],
        env={"CRYSTAL_REPRO_EXPECTED_HEAD": head},
    )
    assert rc == 2
    assert called == []
    assert result["error"] == "invalid_crystal_main_root"
    assert result["expected_head"] == head
    assert result["head_matches_expected"] is True
    assert result["reproduction_of_expected_head"] is False
