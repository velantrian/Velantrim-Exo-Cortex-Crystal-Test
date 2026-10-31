"""Crystal-Test LAB: optional distinct curator bearer for review writes."""

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from core import api  # noqa: E402


def _dual_client(monkeypatch, *, role="CURATOR", scopes="fact:*"):
    monkeypatch.setenv("VELANTRIM_API_TOKEN", "writer-secret")
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "curator-secret")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", role)
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", scopes)
    monkeypatch.delenv("VELANTRIM_API_ALLOW_UNAUTH_LOCAL", raising=False)
    client = TestClient(api.create_app())
    return (
        client,
        {"Authorization": "Bearer writer-secret"},
        {"Authorization": "Bearer curator-secret"},
    )


def test_single_token_mode_unchanged_when_curator_token_unset(monkeypatch):
    monkeypatch.setenv("VELANTRIM_API_TOKEN", "secret")
    monkeypatch.delenv("VELANTRIM_API_CURATOR_TOKEN", raising=False)
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "CURATOR")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    seen = {}

    def approve(fact_id, **kwargs):
        seen.update({"fact_id": fact_id, **kwargs})
        return {"found": True, "approved": True}

    monkeypatch.setattr("core.curator_runtime.review.approve", approve)
    client = TestClient(api.create_app())
    response = client.post(
        "/review/approve",
        headers={"Authorization": "Bearer secret"},
        json={"fact_id": "fact-1"},
    )
    assert response.status_code == 200
    assert seen["actor"] == "alice"


def test_writer_token_cannot_approve_in_dual_token_mode(monkeypatch):
    client, writer, _curator = _dual_client(monkeypatch)
    called = []
    monkeypatch.setattr(
        "core.curator_runtime.review.approve",
        lambda *args, **kwargs: called.append((args, kwargs)) or {"found": True},
    )
    response = client.post(
        "/review/approve",
        headers=writer,
        json={"fact_id": "fact-1"},
    )
    assert response.status_code == 401
    assert "curator bearer" in response.json()["detail"]
    assert not called


def test_writer_token_cannot_reject_or_resolve_conflict(monkeypatch):
    client, writer, _curator = _dual_client(monkeypatch, role="ADMIN")
    called = []
    monkeypatch.setattr(
        "core.curator_runtime.review.reject",
        lambda *args, **kwargs: called.append("reject") or {"found": True},
    )
    monkeypatch.setattr(
        "core.curator_runtime.review.resolve_conflict",
        lambda *args, **kwargs: called.append("resolve") or {"found": True},
    )
    monkeypatch.setattr(
        "core.curator_runtime.review.review_item",
        lambda _fid: {
            "found": True,
            "diagnosis": {"contradiction_report": {"report_id": "r1"}},
        },
    )
    reject = client.post(
        "/review/reject",
        headers=writer,
        json={"fact_id": "fact-1", "reason": "noise"},
    )
    resolve = client.post(
        "/review/resolve-conflict",
        headers=writer,
        json={
            "fact_id": "fact-1",
            "disposition": "COEXIST",
            "reason": "contexts",
            "expected_report_id": "r1",
        },
    )
    assert reject.status_code == 401
    assert resolve.status_code == 401
    assert called == []


def test_curator_token_can_approve_while_writer_can_ingest(monkeypatch):
    client, writer, curator = _dual_client(monkeypatch)
    seen = {}

    def approve(fact_id, **kwargs):
        seen.update({"fact_id": fact_id, **kwargs})
        return {"found": True, "approved": True}

    async def fake_ingest(text, **kwargs):
        return {"accepted": True, "text": text, **kwargs}

    monkeypatch.setattr("core.curator_runtime.review.approve", approve)
    monkeypatch.setattr("core.aio.aingest", fake_ingest)

    approved = client.post(
        "/review/approve",
        headers=curator,
        json={"fact_id": "fact-1"},
    )
    assert approved.status_code == 200
    assert seen["actor"] == "alice"

    ingested = client.post(
        "/ingest",
        headers=writer,
        json={"text": "hello from writer"},
    )
    assert ingested.status_code == 200
    assert ingested.json()["accepted"] is True

    # Curator bearer is not the ingest credential.
    denied_ingest = client.post(
        "/ingest",
        headers=curator,
        json={"text": "hello from curator token"},
    )
    assert denied_ingest.status_code == 401


def test_equal_tokens_fail_closed(monkeypatch):
    monkeypatch.setenv("VELANTRIM_API_TOKEN", "same-secret")
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "same-secret")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "CURATOR")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    client = TestClient(api.create_app())
    response = client.post(
        "/ingest",
        headers={"Authorization": "Bearer same-secret"},
        json={"text": "should not pass dual misconfig"},
    )
    assert response.status_code == 401
    assert "must differ" in response.json()["detail"]


def test_whitespace_curator_token_fails_closed(monkeypatch):
    monkeypatch.setenv("VELANTRIM_API_TOKEN", "writer-secret")
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "  curator  ")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "CURATOR")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    called = []
    monkeypatch.setattr(
        "core.curator_runtime.review.approve",
        lambda *args, **kwargs: called.append(1) or {"found": True},
    )
    client = TestClient(api.create_app())
    response = client.post(
        "/review/approve",
        headers={"Authorization": "Bearer curator"},
        json={"fact_id": "fact-1"},
    )
    assert response.status_code == 401
    assert "configuration is invalid" in response.json()["detail"]
    assert not called


def test_curator_token_without_api_token_fails_closed(monkeypatch):
    monkeypatch.delenv("VELANTRIM_API_TOKEN", raising=False)
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "curator-secret")
    monkeypatch.setenv("VELANTRIM_API_ALLOW_UNAUTH_LOCAL", "1")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "CURATOR")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    client = TestClient(api.create_app())
    response = client.post(
        "/review/approve",
        headers={"Authorization": "Bearer curator-secret"},
        json={"fact_id": "fact-1"},
    )
    assert response.status_code == 401
    assert "requires VELANTRIM_API_TOKEN" in response.json()["detail"]
