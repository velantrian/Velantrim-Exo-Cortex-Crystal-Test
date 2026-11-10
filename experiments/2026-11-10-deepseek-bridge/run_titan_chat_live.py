"""In-process Titan /chat runner for the DeepSeek bridge experiment.

Executed as a subprocess with PYTHONPATH pointing at a Titan checkout.
Must not be imported from Crystal-Test (both trees expose ``core``).

Modes:
  fake — FakeAsyncClient, no network (preflight / boundary rehearsal)
  live — real httpx.AsyncClient; captures the wire body without auth headers

The API key is read from DEEPSEEK_API_KEY and never written to stdout.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


EXPECTED_TITAN_COMMIT_PREFIX = "6b45854"
SECRET_RE = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable:{exc}"


def redact(value: Any, secret: str | None) -> Any:
    if isinstance(value, dict):
        return {k: redact(v, secret) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secret) for v in value]
    if isinstance(value, str):
        text = value
        if secret:
            text = text.replace(secret, "<redacted>")
        text = SECRET_RE.sub("<redacted>", text)
        return text
    return value


def flatten_messages(messages: Any) -> str:
    if not messages:
        return ""
    parts = []
    for item in messages:
        if isinstance(item, dict):
            parts.append(str(item.get("content") or ""))
        else:
            parts.append(str(item))
    return "\n".join(parts)


def check_boundary(messages: Any, admitted: list[dict], excluded: list[dict]) -> list[dict[str, Any]]:
    text = flatten_messages(messages)
    problems: list[dict[str, Any]] = []
    marker_names = (
        "FOREIGN-OBJECT-MARKER",
        "STALE-GROUND-MARKER",
        "SUPERSEDED-OPEN-MARKER",
    )
    for fact in excluded:
        fact_id = str(fact.get("fact_id") or "")
        claim = str(fact.get("claim") or "")
        if fact_id and fact_id in text:
            problems.append({"kind": "excluded_fact_id_in_request", "fact_id": fact_id})
        if claim and claim in text:
            problems.append({"kind": "excluded_claim_in_request", "fact_id": fact_id, "claim": claim})
        for marker in marker_names:
            if marker in claim and marker in text:
                problems.append(
                    {"kind": "excluded_marker_in_request", "fact_id": fact_id, "marker": marker}
                )
    for fact in admitted:
        fact_id = str(fact.get("fact_id") or "")
        claim = str(fact.get("claim") or "")
        if fact_id and fact_id not in text:
            problems.append({"kind": "admitted_fact_id_missing", "fact_id": fact_id})
        if claim and claim not in text:
            problems.append({"kind": "admitted_claim_missing", "fact_id": fact_id, "claim": claim})
    return problems


def _redact_headers(headers: Any, secret: str | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if not headers:
        return out
    items = headers.items() if hasattr(headers, "items") else []
    for key, value in items:
        name = str(key)
        if name.lower() in {"authorization", "x-api-key", "api-key"}:
            out[name] = "<redacted>"
        else:
            out[name] = redact(str(value), secret)
    return out


class BoundaryAbort(RuntimeError):
    def __init__(self, problems: list[dict[str, Any]], body: dict[str, Any]):
        super().__init__("excluded_record_in_boundary_request")
        self.problems = problems
        self.body = body


def _install_fake(httpx_mod: Any, canned_answer: str, wire_records: list[dict[str, Any]], secret: str | None):
    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def post(self, url: str, headers: Any = None, json: Any = None):
            wire_records.append(
                {
                    "url": str(url),
                    "headers": _redact_headers(headers, secret),
                    "body": redact(copy.deepcopy(json), secret),
                }
            )
            request = httpx_mod.Request("POST", url)
            return httpx_mod.Response(
                200,
                json={
                    "choices": [{"message": {"content": canned_answer}}],
                    "usage": {},
                    "model": (json or {}).get("model"),
                },
                request=request,
            )

        def stream(self, method: str, url: str, headers: Any = None, json: Any = None):
            raise RuntimeError("streaming is not used by the live experiment runner")

    httpx_mod.AsyncClient = FakeAsyncClient


def _install_recorder(httpx_mod: Any, wire_records: list[dict[str, Any]], secret: str | None):
    orig = httpx_mod.AsyncClient

    class RecordingAsyncClient(orig):  # type: ignore[valid-type,misc]
        async def post(self, url: str, *args: Any, **kwargs: Any):
            headers = kwargs.get("headers")
            body = kwargs.get("json")
            entry: dict[str, Any] = {
                "url": str(url),
                "headers": _redact_headers(headers, secret),
                "body": redact(copy.deepcopy(body), secret),
                "http_status": None,
                "response_json": None,
                "error": None,
            }
            try:
                resp = await super().post(url, *args, **kwargs)
            except Exception as exc:
                entry["error"] = redact(f"{type(exc).__name__}: {exc}", secret)
                wire_records.append(entry)
                raise
            entry["http_status"] = resp.status_code
            try:
                entry["response_json"] = redact(resp.json(), secret)
            except Exception as exc:
                entry["error"] = redact(f"response_parse:{type(exc).__name__}: {exc}", secret)
                entry["response_text"] = redact(resp.text[:4000], secret)
            wire_records.append(entry)
            return resp

    httpx_mod.AsyncClient = RecordingAsyncClient


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    mode = str(payload.get("mode") or "fake")
    if mode not in {"fake", "live"}:
        json.dump({"error": f"unknown_mode:{mode}"}, sys.stdout)
        sys.stdout.write("\n")
        return 2

    titan_root = Path(
        payload.get("titan_root")
        or os.environ.get("TITAN_SANDBOX_ROOT", "/workspace/titan-sandbox")
    ).resolve()
    work = Path(tempfile.mkdtemp(prefix="titan-live-"))
    os.environ["VELANTRIM_ALLOW_OPEN"] = "true"
    os.environ["VELANTRIM_NETWORK_MODE"] = "allow"
    os.environ["VELANTRIM_REMOTE_DATA_MODE"] = "allowed"
    os.environ["VELANTRIM_DB_PATH"] = str(work / "velantrim.db")
    os.environ["VELANTRIM_NGRAM_DB"] = str(work / "ngram.db")
    os.environ["SQLITE_AUDIT_PATH"] = str(work / "response_audit.db")
    os.environ["SLEEP_WORKER_ENABLED"] = "false"
    os.environ["LOG_LEVEL"] = "WARNING"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    os.chdir(work)
    sys.path.insert(0, str(titan_root))

    secret = os.environ.get("DEEPSEEK_API_KEY")
    if mode == "live":
        if not secret:
            json.dump({"error": "missing_deepseek_api_key", "mode": mode}, sys.stdout)
            sys.stdout.write("\n")
            return 2
        api_key = secret
    else:
        api_key = "synthetic-crystal-titan-bridge-0001"

    import httpx
    import server
    import core.llm_router as llm_router
    import core.llm_stream as llm_stream

    prepared_bodies: list[Any] = []
    wire_records: list[dict[str, Any]] = []
    orig_deepseek_body = llm_router._deepseek_request_body
    admitted = list(payload.get("admitted") or [])
    excluded = list(payload.get("excluded") or [])
    abort_if_excluded = bool(payload.get("abort_if_excluded"))

    def _capture_prepared(cfg, messages, **kwargs):
        body = orig_deepseek_body(cfg, messages, **kwargs)
        prepared_bodies.append(copy.deepcopy(body))
        if abort_if_excluded:
            problems = check_boundary(body.get("messages"), admitted, excluded)
            if problems:
                raise BoundaryAbort(problems, copy.deepcopy(body))
        return body

    llm_router._deepseek_request_body = _capture_prepared
    llm_stream._deepseek_request_body = _capture_prepared

    if mode == "fake":
        canned = payload.get("canned_answer")
        if not isinstance(canned, str) or not canned:
            canned = "ok"
        _install_fake(httpx, canned, wire_records, secret)
    else:
        _install_recorder(httpx, wire_records, secret)

    facts = list(payload.get("facts") or [])
    server.pipeline_run = lambda q, mode_, domain: {"facts": facts, "error": None}

    model = payload.get("model") or "deepseek-flash"
    thinking = payload.get("deepseek_thinking") or "high"
    max_tokens = int(payload.get("llm_max_tokens") or 8192)

    req = server.ChatRequest(
        message=payload["message"],
        llm_provider="deepseek",
        llm_api_key=api_key,
        llm_model=model,
        deepseek_thinking=thinking,
        llm_max_tokens=max_tokens,
        use_memory=True,
        auto_save_memory=False,
        persist_to_system=False,
        include_system_guide=False,
        llm_enabled=True,
    )

    boundary_problems = None
    http_error = None
    resp_obj = None
    try:
        resp_obj = asyncio.run(server.chat_endpoint(req))
    except BoundaryAbort as exc:
        boundary_problems = exc.problems
        if not prepared_bodies:
            prepared_bodies.append(exc.body)
    except Exception as exc:
        http_error = redact(f"{type(exc).__name__}: {exc}", secret)

    prepared = prepared_bodies[0] if prepared_bodies else None
    prepared_messages = None if prepared is None else prepared.get("messages")
    if boundary_problems is None and prepared_messages is not None:
        boundary_problems = check_boundary(prepared_messages, admitted, excluded)

    wire = wire_records[0] if wire_records else None
    wire_body = None if wire is None else wire.get("body")
    wire_messages = None if not isinstance(wire_body, dict) else wire_body.get("messages")
    raw_response = None if wire is None else wire.get("response_json")
    message = {}
    if isinstance(raw_response, dict):
        choices = raw_response.get("choices") or []
        if choices and isinstance(choices[0], dict):
            message = choices[0].get("message") or {}

    provider_calls = 0
    for item in wire_records:
        url = str(item.get("url") or "")
        if "chat/completions" in url:
            provider_calls += 1

    reply = None
    from_llm = None
    context_report = None
    memory_saved = None
    memory_auto_status = None
    latency_ms = None
    llm_usage = None
    if resp_obj is not None:
        reply = resp_obj.reply
        from_llm = resp_obj.from_llm
        context_report = resp_obj.context_report
        memory_saved = resp_obj.memory_saved
        memory_auto_status = resp_obj.memory_auto_status
        latency_ms = resp_obj.latency_ms
        llm_usage = getattr(resp_obj, "llm_usage", None)

    out = {
        "mode": mode,
        "titan_root": str(titan_root),
        "titan_commit": _git_head(titan_root),
        "expected_titan_commit_prefix": EXPECTED_TITAN_COMMIT_PREFIX,
        "model": model,
        "deepseek_thinking": thinking,
        "llm_max_tokens": max_tokens,
        "provider_calls": provider_calls,
        "prepared_request_body": redact(prepared, secret),
        "prepared_messages": redact(prepared_messages, secret),
        "provider_received_messages": redact(wire_messages, secret),
        "prepared_matches_provider_received": (
            None
            if prepared_messages is None or wire_messages is None
            else prepared_messages == wire_messages
        ),
        "prepared_matches_wire_body": (
            None if prepared is None or wire_body is None else prepared == wire_body
        ),
        "capture_points": {
            "prepared": "core.llm_stream._deepseek_request_body full body",
            "wire": "httpx.AsyncClient.post(json) after header redaction",
        },
        "boundary_problems": boundary_problems,
        "boundary_ok": not boundary_problems,
        "wire": wire,
        "response_text": None if not isinstance(message, dict) else message.get("content"),
        "reasoning_content": None if not isinstance(message, dict) else message.get("reasoning_content"),
        "raw_response": raw_response,
        "reply": redact(reply, secret),
        "from_llm": from_llm,
        "error": http_error,
        "http_status": None if wire is None else wire.get("http_status"),
        "context_report": context_report,
        "memory_saved": memory_saved,
        "memory_auto_status": memory_auto_status,
        "latency_ms": latency_ms,
        "llm_usage": llm_usage,
        "auto_save_memory": False,
    }
    json.dump(redact(out, secret), sys.stdout, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    if boundary_problems:
        return 3
    if http_error:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
