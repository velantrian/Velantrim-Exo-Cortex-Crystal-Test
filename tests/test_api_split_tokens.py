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


def test_empty_curator_token_env_does_not_fallback_to_writer(monkeypatch):
    """Present-but-empty CURATOR_TOKEN must not silently reopen single-token mode."""
    monkeypatch.setenv("VELANTRIM_API_TOKEN", "writer-secret")
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "CURATOR")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    called = []
    monkeypatch.setattr(
        "core.curator_runtime.review.approve",
        lambda *args, **kwargs: called.append(1) or {"found": True, "approved": True},
    )
    client = TestClient(api.create_app())
    response = client.post(
        "/review/approve",
        headers={"Authorization": "Bearer writer-secret"},
        json={"fact_id": "fact-1"},
    )
    assert response.status_code == 401
    assert "empty" in response.json()["detail"] or "invalid" in response.json()["detail"].lower()
    assert not called


def test_empty_curator_token_blocks_unauth_local(monkeypatch):
    monkeypatch.delenv("VELANTRIM_API_TOKEN", raising=False)
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "")
    monkeypatch.setenv("VELANTRIM_API_ALLOW_UNAUTH_LOCAL", "1")
    called = []
    monkeypatch.setattr(
        "core.curator_runtime.review.approve",
        lambda *args, **kwargs: called.append(1) or {"found": True},
    )
    client = TestClient(api.create_app())
    response = client.post(
        "/review/approve",
        json={"fact_id": "fact-1"},
    )
    assert response.status_code == 401
    assert not called


@pytest.mark.parametrize("unauth_local", [False, True])
@pytest.mark.parametrize(
    ("route", "body"),
    [
        ("/review/approve", {"fact_id": "fact-1"}),
        ("/review/reject", {"fact_id": "fact-1", "reason": "no"}),
        (
            "/review/resolve-conflict",
            {
                "fact_id": "fact-1",
                "disposition": "COEXIST",
                "reason": "independent contexts",
                "expected_report_id": "r1",
            },
        ),
        ("/ingest", {"text": "must not reach the memory core"}),
    ],
)
def test_empty_curator_token_denies_every_http_write_route(
    monkeypatch, unauth_local, route, body
):
    """Present-but-empty token is a 401 with zero mutation in both auth modes."""
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "ADMIN")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    if unauth_local:
        monkeypatch.delenv("VELANTRIM_API_TOKEN", raising=False)
        monkeypatch.setenv("VELANTRIM_API_ALLOW_UNAUTH_LOCAL", "1")
        headers = {}
    else:
        monkeypatch.setenv("VELANTRIM_API_TOKEN", "writer-secret")
        monkeypatch.delenv("VELANTRIM_API_ALLOW_UNAUTH_LOCAL", raising=False)
        headers = {"Authorization": "Bearer writer-secret"}

    mutations = []

    def mutating_review(*args, **kwargs):
        mutations.append(("review", args, kwargs))
        return {"found": True, "approved": True}

    async def mutating_ingest(*args, **kwargs):
        mutations.append(("ingest", args, kwargs))
        return {"accepted": True}

    for name in ("approve", "reject", "resolve_conflict"):
        monkeypatch.setattr("core.curator_runtime.review." + name, mutating_review)
    monkeypatch.setattr("core.aio.aingest", mutating_ingest)
    monkeypatch.setattr(
        "core.curator_runtime.review.review_item",
        lambda fact_id: {"found": True, "diagnosis": {
            "contradiction_report": {"report_id": "r1"},
        }},
    )

    response = TestClient(api.create_app()).post(route, headers=headers, json=body)
    assert response.status_code == 401, response.text
    assert "VELANTRIM_API_CURATOR_TOKEN" in response.json()["detail"]
    assert mutations == []


def test_curator_token_can_reject_and_resolve_conflict(monkeypatch):
    """Independent-review matrix: curator bearer owns reject + conflict writes."""
    client, writer, curator = _dual_client(monkeypatch, role="ADMIN")
    seen = []

    def reject(fact_id, **kwargs):
        seen.append(("reject", fact_id, kwargs))
        return {"found": True, "rejected": True}

    def resolve_conflict(fact_id, **kwargs):
        seen.append(("resolve", fact_id, kwargs))
        return {"found": True, "resolved": True}

    monkeypatch.setattr("core.curator_runtime.review.reject", reject)
    monkeypatch.setattr(
        "core.curator_runtime.review.resolve_conflict", resolve_conflict,
    )
    monkeypatch.setattr(
        "core.curator_runtime.review.review_item",
        lambda _fid: {
            "found": True,
            "diagnosis": {"contradiction_report": {"report_id": "r1"}},
        },
    )

    rejected = client.post(
        "/review/reject",
        headers=curator,
        json={"fact_id": "fact-1", "reason": "noise"},
    )
    resolved = client.post(
        "/review/resolve-conflict",
        headers=curator,
        json={
            "fact_id": "fact-1",
            "disposition": "COEXIST",
            "reason": "contexts",
            "expected_report_id": "r1",
        },
    )
    assert rejected.status_code == 200, rejected.text
    assert resolved.status_code == 200, resolved.text
    assert [item[0] for item in seen] == ["reject", "resolve"]
    assert all(item[2].get("actor") == "alice" for item in seen)

    # Writer still cannot perform the same curator writes.
    assert client.post(
        "/review/reject",
        headers=writer,
        json={"fact_id": "fact-1", "reason": "noise"},
    ).status_code == 401


def test_dual_mode_ask_and_receipt_use_writer_token_only(monkeypatch):
    """Read paths stay on writer bearer; curator token is not a substitute."""
    client, writer, curator = _dual_client(monkeypatch)
    seen_queries = []

    async def fake_arun(query, **kwargs):
        seen_queries.append(query)
        return {"answer": "ok", "query": query, **kwargs}

    def fake_receipt(result):
        return {"receipt_for": result.get("query"), "ok": True}

    monkeypatch.setattr("core.aio.arun", fake_arun)
    monkeypatch.setattr("core.provenance.build_receipt", fake_receipt)

    asked = client.post(
        "/ask",
        headers=writer,
        json={"query": "what is known?"},
    )
    assert asked.status_code == 200, asked.text
    assert asked.json()["answer"] == "ok"

    receipt = client.get(
        "/receipt",
        headers=writer,
        params={"q": "receipt query"},
    )
    assert receipt.status_code == 200, receipt.text
    assert receipt.json()["receipt_for"] == "receipt query"
    assert seen_queries == ["what is known?", "receipt query"]

    # Curator bearer alone is not the read/query credential.
    denied_ask = client.post(
        "/ask",
        headers=curator,
        json={"query": "should fail"},
    )
    denied_receipt = client.get(
        "/receipt",
        headers=curator,
        params={"q": "should fail"},
    )
    assert denied_ask.status_code == 401
    assert denied_receipt.status_code == 401
    assert seen_queries == ["what is known?", "receipt query"]


def test_whitespace_only_curator_token_fails_closed_on_writes(monkeypatch):
    """Present whitespace-only CURATOR_TOKEN must never reopen writer-as-curator."""
    monkeypatch.setenv("VELANTRIM_API_TOKEN", "writer-secret")
    monkeypatch.setenv("VELANTRIM_API_CURATOR_TOKEN", "   ")
    monkeypatch.setenv("VELANTRIM_CURATOR_ACTOR", "alice")
    monkeypatch.setenv("VELANTRIM_CURATOR_ROLES", "ADMIN")
    monkeypatch.setenv("VELANTRIM_CURATOR_SCOPES", "fact:*")
    monkeypatch.delenv("VELANTRIM_API_ALLOW_UNAUTH_LOCAL", raising=False)
    mutations = []
    monkeypatch.setattr(
        "core.curator_runtime.review.approve",
        lambda *args, **kwargs: mutations.append("approve") or {"found": True},
    )
    async def mutating_ingest(*args, **kwargs):
        mutations.append("ingest")
        return {"accepted": True}

    monkeypatch.setattr("core.aio.aingest", mutating_ingest)
    client = TestClient(api.create_app())
    writer = {"Authorization": "Bearer writer-secret"}

    approve = client.post(
        "/review/approve", headers=writer, json={"fact_id": "fact-1"},
    )
    ingest = client.post(
        "/ingest", headers=writer, json={"text": "must not mutate"},
    )
    assert approve.status_code == 401
    assert ingest.status_code == 401
    assert "whitespace" in approve.json()["detail"].lower() or \
        "empty" in approve.json()["detail"].lower() or \
        "invalid" in approve.json()["detail"].lower()
    assert mutations == []
