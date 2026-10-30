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


def test_cli_wires_block_reentry_flag(monkeypatch, tmp_path, capsys):
    from core import cli

    monkeypatch.setenv("VELANTRIM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VELANTRIM_DEMO_SEED", "0")
    monkeypatch.setenv("VELANTRIM_IMMUNE_BLOCK_SEVERITY", "0.5")
    memory.store_fact({
        "fact_id": FID,
        "claim": CLAIM,
        "source": "test://cli",
        "confidence": 0.9,
        "epistemic_state": "Validated",
        "claim_type": "WORLD_FACT",
        "source_status": "EXTERNAL",
    })
    get_l3_graph().merge_fact(memory.get_fact(FID))

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
