"""Regression contract for issue #214 supply-chain verification hardening.

Crystal-Test deliberately excludes upstream GitHub Actions workflows
(see FORGE_LAB_PROVENANCE.md). This contract therefore:

- asserts the excluded workflow files remain absent;
- keeps Dependabot and security-tool pin checks that still apply locally;
- documents upstream action-SHA expectations without requiring ci.yml.
"""

from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = ROOT / "FORGE_LAB_PROVENANCE.md"
WORKFLOWS = (
    ROOT / ".github/workflows/ci.yml",
    ROOT / ".github/workflows/l3-benchmark-history.yml",
    ROOT / ".github/workflows/postgresql-integration.yml",
)
# Documented upstream expectations for the canonical Crystal repository.
# Crystal-Test does not enforce these against missing workflow files.
EXPECTED_ACTION_REFS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "gitleaks/gitleaks-action": "e0c47f4f8be36e29cdc102c57e68cb5cbf0e8d1e",
}
USE_RE = re.compile(r"^\s*-?\s*uses:\s*([^@\s]+)@([0-9a-f]{40})(?:\s+#\s+.+)?$")
UPSTREAM_SNAPSHOT = "692e05e319d1a789752fe797235798d4380e60d4"


def test_lab_excludes_upstream_workflows_by_design():
    for workflow in WORKFLOWS:
        assert not workflow.exists(), (
            f"Crystal-Test must not restore excluded upstream workflow: {workflow}"
        )


def test_forge_lab_provenance_pin_is_visible_and_explicit():
    text = PROVENANCE.read_text(encoding="utf-8")
    assert f"upstream_snapshot_commit: {UPSTREAM_SNAPSHOT}" in text
    assert "workflows_present: false" in text
    assert "authority: LAB_ONLY" in text
    for relative in (
        ".github/workflows/ci.yml",
        ".github/workflows/l3-benchmark-history.yml",
        ".github/workflows/postgresql-integration.yml",
    ):
        assert relative in text


def test_security_tool_pins_remain_exact_without_ci_yml():
    requirements = ROOT / ".github/requirements-security.txt"
    pins = {
        line.strip()
        for line in requirements.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert pins == {"bandit==1.9.4", "pip-audit==2.10.1"}
    assert not (ROOT / ".github/workflows/ci.yml").exists()


def test_upstream_action_pin_contract_is_documented_not_enforced_here():
    """Keep the reviewed upstream action map as documentation only.

    If a future lab intentionally restores a workflow file, that change must
    separately re-enable immutable-ref enforcement. Until then, absence is the
    contract.
    """
    assert set(EXPECTED_ACTION_REFS) == {
        "actions/checkout",
        "actions/setup-python",
        "actions/upload-artifact",
        "gitleaks/gitleaks-action",
    }
    assert all(re.fullmatch(r"[0-9a-f]{40}", ref) for ref in EXPECTED_ACTION_REFS.values())
    assert USE_RE.pattern
    for workflow in WORKFLOWS:
        assert not workflow.exists()
    provenance = PROVENANCE.read_text(encoding="utf-8")
    assert "documented expectations for the canonical repository" in provenance


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
