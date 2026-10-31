"""Opt-in erasure + Immune reentry guard (Crystal-Test LAB)."""

import pytest

from core import audit, immune, memory
from core.erasure import erase_fact
from core.ingest import ingest
from core.l3_graph import get_l3_graph

CLAIM = "The synthetic erased marker E4R7 has value 141421."
PEER = "The independent kept marker K9M3 has value 173205."
FID = "ing:erase-reentry-target"
PEER_ID = "ing:erase-reentry-peer"


def _seed(monkeypatch):
    monkeypatch.setenv("VELANTRIM_DEMO_SEED", "0")
    monkeypatch.setenv("VELANTRIM_IMMUNE_BLOCK_SEVERITY", "0.5")
    memory.store_fact({
        "fact_id": FID,
        "claim": CLAIM,
        "source": "test://erase-reentry",
        "confidence": 0.9,
        "epistemic_state": "Validated",
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
    })
    get_l3_graph().merge_fact(memory.get_fact(FID))
    memory.store_fact({
        "fact_id": PEER_ID,
        "claim": PEER,
        "source": "test://peer",
        "confidence": 0.9,
        "epistemic_state": "Validated",
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
    })
    get_l3_graph().merge_fact(memory.get_fact(PEER_ID))


def test_default_erase_allows_same_wording_to_return(monkeypatch):
    """Documents the Atlas gap: erasure tombstone is not an ingest tombstone."""
    _seed(monkeypatch)
    receipt = erase_fact(FID, reason="wrong_claim", actor="lab-operator")
    assert receipt["erased_now"] is True
    assert "reentry_pattern_id" not in receipt
    assert immune.match_threat(CLAIM) is None

    again = ingest(
        CLAIM,
        fact_id="ing:returned-after-erase",
        source="test://replay",
        claim_type="WORLD_FACT",
        source_status="EXTERNAL",
        confidence=0.9,
    )
    assert again["accepted"] is True
    assert memory.get_fact(PEER_ID) is not None


def test_block_reentry_erase_blocks_screened_reingest(monkeypatch):
    _seed(monkeypatch)
    receipt = erase_fact(
        FID,
        reason="curator_wrong_claim",
        actor="lab-operator",
        block_reentry=True,
    )
    assert receipt["erased_now"] is True
    assert receipt["reentry_pattern_id"]
    assert memory.get_fact(FID) is None
    assert immune.match_threat(CLAIM) is not None

    blocked = ingest(
        CLAIM,
        fact_id="ing:blocked-after-erase",
        source="test://replay",
        claim_type="WORLD_FACT",
        source_status="EXTERNAL",
        confidence=0.9,
    )
    assert blocked["accepted"] is False
    assert "Immune:" in (blocked.get("reason") or "")
    assert memory.get_fact(PEER_ID) is not None
    assert audit.verify_audit_log()["ok"]


def test_block_reentry_refuses_privacy_shaped_reasons(monkeypatch):
    _seed(monkeypatch)
    with pytest.raises(ValueError, match="not a privacy/GDPR"):
        erase_fact(
            FID,
            reason="data_subject_request",
            actor="lab-operator",
            block_reentry=True,
        )
    assert memory.get_fact(FID) is not None
    assert immune.match_threat(CLAIM) is None


def test_block_reentry_requires_claim_and_actor(monkeypatch):
    monkeypatch.setenv("VELANTRIM_DEMO_SEED", "0")
    with pytest.raises(ValueError, match="stored claim"):
        erase_fact(
            "ing:never-existed",
            reason="curator_wrong_claim",
            actor="lab-operator",
            block_reentry=True,
        )
    _seed(monkeypatch)
    with pytest.raises(ValueError, match="requires an actor"):
        erase_fact(
            FID,
            reason="curator_wrong_claim",
            actor="   ",
            block_reentry=True,
        )


def test_revoking_erasure_guard_allows_reingest_without_restoring_row(monkeypatch):
    _seed(monkeypatch)
    receipt = erase_fact(
        FID,
        reason="curator_wrong_claim",
        actor="lab-operator",
        block_reentry=True,
    )
    assert immune.forget_threat(receipt["reentry_pattern_id"], actor="lab-operator")
    again = ingest(
        CLAIM,
        fact_id="ing:after-revoke",
        source="test://replay",
        claim_type="WORLD_FACT",
        source_status="EXTERNAL",
        confidence=0.9,
    )
    assert again["accepted"] is True
    assert memory.get_fact(FID) is None  # original row stays erased
    assert memory.get_tombstone(FID) is not None


def test_cli_block_reentry_requires_admin_fact_star(monkeypatch, tmp_path, capsys):
    from core import cli

    monkeypatch.setenv("VELANTRIM_DEMO_SEED", "0")
    monkeypatch.setenv("VELANTRIM_IMMUNE_BLOCK_SEVERITY", "0.5")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "CURATOR")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    _seed(monkeypatch)

    rc = cli.main([
        "erase", FID,
        "--reason", "curator_wrong_claim",
        "--block-reentry",
    ])
    assert rc == 3
    out = capsys.readouterr().out
    assert "authorized" in out
    assert "admin" in out.lower()
    assert memory.get_fact(FID) is not None
    assert immune.match_threat(CLAIM) is None


def test_cli_wires_block_reentry_flag_for_admin(monkeypatch, tmp_path, capsys):
    from core import cli

    monkeypatch.setenv("VELANTRIM_DEMO_SEED", "0")
    monkeypatch.setenv("VELANTRIM_IMMUNE_BLOCK_SEVERITY", "0.5")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "lab-admin")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "ADMIN")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    _seed(monkeypatch)

    rc = cli.main([
        "erase", FID,
        "--reason", "curator_wrong_claim",
        "--block-reentry",
    ])
    assert rc == 0
    out = capsys.readouterr().out
    assert "reentry_pattern_id" in out
    assert memory.get_fact(FID) is None
    blocked = ingest(
        CLAIM,
        fact_id="ing:cli-blocked",
        source="test://replay",
        claim_type="WORLD_FACT",
        source_status="EXTERNAL",
        confidence=0.9,
    )
    assert blocked["accepted"] is False


def test_shared_immune_pattern_upsert_and_forget_is_global(monkeypatch):
    """erasure_reentry may refresh an existing pattern; immune-allow removes the shared rule."""
    _seed(monkeypatch)
    first = immune.record_threat(
        CLAIM, threat_type="manual", severity=0.7, actor="manual-owner",
    )
    receipt = erase_fact(
        FID,
        reason="curator_wrong_claim",
        actor="lab-operator",
        block_reentry=True,
    )
    assert receipt["reentry_pattern_id"] == first["pattern_id"]
    entry = immune.match_threat(CLAIM)
    assert entry is not None
    assert entry["threat_type"] == "erasure_reentry"
    assert entry["severity"] == 1.0
    assert immune.forget_threat(receipt["reentry_pattern_id"], actor="lab-operator")
    assert immune.match_threat(CLAIM) is None


def test_token_containment_can_block_corrective_quotation(monkeypatch):
    """Documents Immune whole-token containment risk for quoted corrections."""
    _seed(monkeypatch)
    erase_fact(
        FID,
        reason="curator_wrong_claim",
        actor="lab-operator",
        block_reentry=True,
    )
    correction = f"Correction: it is false that {CLAIM}"
    blocked = ingest(
        correction,
        fact_id="ing:quoted-correction",
        source="test://correction",
        claim_type="WORLD_FACT",
        source_status="EXTERNAL",
        confidence=0.9,
    )
    assert blocked["accepted"] is False
    assert "Immune:" in (blocked.get("reason") or "")


def test_erase_with_reentry_block_as_principal_denies_non_admin(monkeypatch):
    """Independent-review acceptance: principal path requires ADMIN + fact:*."""
    from core.curator_auth import CuratorPrincipal, CuratorRole
    from core.curator_runtime import erase_with_reentry_block_as_principal

    _seed(monkeypatch)
    curator = CuratorPrincipal(
        "alice", frozenset({CuratorRole.CURATOR}), frozenset({"fact:*"}),
    )
    denied = erase_with_reentry_block_as_principal(
        curator, FID, reason="curator_wrong_claim",
    )
    assert denied == {
        "authorized": False,
        "reason": "workspace-wide reentry blocking requires admin with fact:* scope",
    }
    assert memory.get_fact(FID) is not None
    assert immune.match_threat(CLAIM) is None


def test_erase_with_reentry_block_as_principal_denies_admin_without_fact_star(
    monkeypatch,
):
    from core.curator_auth import CuratorPrincipal, CuratorRole
    from core.curator_runtime import erase_with_reentry_block_as_principal

    _seed(monkeypatch)
    admin_narrow = CuratorPrincipal(
        "alice", frozenset({CuratorRole.ADMIN}), frozenset({"fact:other"}),
    )
    denied = erase_with_reentry_block_as_principal(
        admin_narrow, FID, reason="curator_wrong_claim",
    )
    assert denied["authorized"] is False
    assert memory.get_fact(FID) is not None
    assert immune.match_threat(CLAIM) is None


def test_erase_with_reentry_block_as_principal_admin_fact_star_succeeds(
    monkeypatch,
):
    from core.curator_auth import CuratorPrincipal, CuratorRole
    from core.curator_runtime import erase_with_reentry_block_as_principal

    _seed(monkeypatch)
    admin = CuratorPrincipal(
        "lab-admin", frozenset({CuratorRole.ADMIN}), frozenset({"fact:*"}),
    )
    result = erase_with_reentry_block_as_principal(
        admin, FID, reason="curator_wrong_claim",
    )
    assert result["authorized"] is True
    assert result["erased_now"] is True
    assert result["reentry_pattern_id"]
    assert memory.get_fact(FID) is None
    assert immune.match_threat(CLAIM) is not None


def test_erase_with_reentry_block_as_principal_actor_mismatch_is_zero_mutation(
    monkeypatch,
):
    from core.curator_auth import CuratorPrincipal, CuratorRole
    from core.curator_runtime import erase_with_reentry_block_as_principal

    _seed(monkeypatch)
    admin = CuratorPrincipal(
        "lab-admin", frozenset({CuratorRole.ADMIN}), frozenset({"fact:*"}),
    )
    denied = erase_with_reentry_block_as_principal(
        admin,
        FID,
        reason="curator_wrong_claim",
        requested_actor="mallory",
    )
    assert denied == {
        "authorized": False,
        "reason": "actor assertion does not match authenticated principal",
    }
    assert memory.get_fact(FID) is not None
    assert immune.match_threat(CLAIM) is None


def test_direct_erase_fact_block_reentry_is_library_trust_boundary(monkeypatch):
    """Trusted in-process callers may call erase_fact without curator IAM.

    Independent review called this out as an explicit boundary: CLI/HTTP must
    use erase_with_reentry_block_as_principal; raw Python API does not invent a
    second admission owner and does not claim production IAM.
    """
    _seed(monkeypatch)
    receipt = erase_fact(
        FID,
        reason="curator_wrong_claim",
        actor="trusted-library-caller",
        block_reentry=True,
    )
    assert receipt["erased_now"] is True
    assert receipt["reentry_pattern_id"]
    assert immune.match_threat(CLAIM) is not None
