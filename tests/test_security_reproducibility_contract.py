"""Regression contract for issue #214 supply-chain verification hardening."""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = (ROOT / ".github/workflows/lab.yml",)
EXPECTED_ACTION_REFS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
}
USE_RE = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([0-9a-f]{40})(?:\s+#\s+.+)?$")


def test_all_committed_workflow_actions_are_immutable_reviewed_refs():
    seen: set[str] = set()
    for workflow in WORKFLOWS:
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line:
                continue
            match = USE_RE.match(line)
            assert match is not None, f"mutable or malformed action ref: {workflow}: {line}"
            action, ref = match.groups()
            assert action in EXPECTED_ACTION_REFS, f"unreviewed action: {action}"
            assert ref == EXPECTED_ACTION_REFS[action], f"unexpected ref for {action}: {ref}"
            seen.add(action)
    assert seen == set(EXPECTED_ACTION_REFS)


def test_lab_ci_runs_full_suite_and_coverage_gate():
    ci = (ROOT / ".github/workflows/lab.yml").read_text(encoding="utf-8")
    assert "python -m pip install -e '.[dev]'" in ci
    assert "python -m pytest tests/ --cov=. --cov-fail-under=100" in ci
    assert "permissions:\n  contents: read" in ci
    pins = {
        line.strip() for line in (ROOT / ".github/requirements-security.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert pins == {"bandit==1.9.4", "pip-audit==2.10.1"}
    # The laboratory intentionally omitted these upstream workflows at creation;
    # preserve that provenance instead of pretending they run here.
    assert not (ROOT / ".github/workflows/ci.yml").exists()
    assert "deliberately excluded" in (ROOT / "FORGE_LAB_PROVENANCE.md").read_text()


def test_dependabot_has_bounded_weekly_action_and_security_tool_update_paths():
    config = (ROOT / ".github/dependabot.yml").read_text(encoding="utf-8")
    assert 'package-ecosystem: "github-actions"' in config
    assert 'directory: "/"' in config
    assert 'package-ecosystem: "pip"' in config
    assert 'directory: "/.github"' in config
    assert config.count('interval: "weekly"') == 2


def test_fixture_data_manifest_is_bounded_and_non_certifying():
    path = ROOT / "docs/security/FIXTURE_DATA_MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["tracking_issue"] == 214
    assert manifest["review_status"] == "BOUNDED_REVIEW_COMPLETE"
    assert manifest["repository_wide_pii_clean_claim"] is False
    assert manifest["confirmed_secret_or_pii_incident"] is False
    assert manifest["history_rewrite_authorized"] is False

    classes = {item["classification"] for item in manifest["classifications"]}
    assert "GENERATED_SYNTHETIC_BENCHMARK_DATA" in classes
    assert "GENERATED_BENCHMARK_RESULT_DATA" in classes
    assert "ARCHIVED_DESIGN_MATERIAL" in classes

    reviewed_paths = {
        reviewed_path
        for item in manifest["classifications"]
        for reviewed_path in item["paths"]
    }
    required = {
        "eval/reader_rc8_retrieval_adversarial.jsonl",
        "eval/reader_retrieval_eval_v2_queries.jsonl",
        "eval/reader_retrieval_eval_v2_candidates.jsonl",
        "eval/reader_retrieval_eval_v2_qrels.jsonl",
        "docs/archive/Velantrim_V8_Crystal_Sprint1.jsonl",
        "docs/archive/Velantrim_V8_Crystal_Sprint1_toc.md",
    }
    assert required <= reviewed_paths
    for reviewed_path in reviewed_paths:
        assert (ROOT / reviewed_path).is_file(), reviewed_path
