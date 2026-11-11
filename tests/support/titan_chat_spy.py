"""Run Titan /chat against a fake HTTP provider and print the captured request.

This script is executed in a subprocess with PYTHONPATH pointing at a Titan
checkout (default: /workspace/titan-sandbox). It must not be imported from
Crystal-Test: both trees expose a top-level ``core`` package.

No real model is called. The API key is synthetic. Titan retrieval is replaced
by the supplied memory records; auto-save is turned off.
"""
from __future__ import annotations

import asyncio
import copy
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SYNTHETIC_KEY = "sk-synthetic-crystal-titan-bridge-0001"
EXPECTED_TITAN_COMMIT_PREFIX = "6b45854"


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(root),
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        return f"unavailable:{exc}"


class FakeProvider:
    def __init__(self, canned_answer: str) -> None:
        self.requests: list[dict[str, Any]] = []
        self.canned_answer = canned_answer


def _install_fake(httpx_mod: Any, canned_answer: str) -> FakeProvider:
    provider = FakeProvider(canned_answer)

    class FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> FakeAsyncClient:
            return self

        async def __aexit__(self, *exc: object) -> bool:
            return False

        async def post(self, url: str, headers: Any = None, json: Any = None):
            provider.requests.append({"url": url, "body": copy.deepcopy(json)})
            request = httpx_mod.Request("POST", url)
            return httpx_mod.Response(
                200,
                json={
                    "choices": [{"message": {"content": provider.canned_answer}}],
                    "usage": {},
                },
                request=request,
            )

        def stream(self, method: str, url: str, headers: Any = None, json: Any = None):
            raise RuntimeError("streaming is not used by the Crystal-Titan bridge spy")

    httpx_mod.AsyncClient = FakeAsyncClient
    return provider


def _evaluate_response_checks(reply: str, source_facts: list[dict[str, Any]]) -> dict[str, Any]:
    """Call Titan checkers standalone. /chat does not run them on the LLM reply."""
    from core.output_faithfulness import (
        OutputFaithfulnessChecker,
        check_response_faithfulness,
        is_output_faithfulness_enabled,
    )
    from core.response_audit import is_response_audit_enabled
    from core.response_guardian import (
        ResponseGuardian,
        apply_response_guardian,
        is_response_guardian_enabled,
    )

    trace = [{"fact_id": f.get("fact_id")} for f in source_facts if f.get("fact_id")]
    avg_conf = 0.0
    if source_facts:
        def _conf(fact):
            raw = fact.get("confidence")
            return float(raw) if raw is not None else 0.5
        avg_conf = sum(_conf(f) for f in source_facts) / len(source_facts)

    gated_guardian = apply_response_guardian(reply, source_facts, trace)
    gated_faith = check_response_faithfulness(reply, source_facts)
    standalone_guardian = ResponseGuardian().validate(
        response=reply,
        confidence=avg_conf if source_facts else 1.0,
        trace=[str(t["fact_id"]) for t in trace],
        sources=source_facts,
    )
    standalone_faith = OutputFaithfulnessChecker().check(reply, source_facts)

    def _flagged_faith(result: Any) -> bool | None:
        if result is None:
            return None
        data = result if isinstance(result, dict) else result.to_dict()
        return bool(data.get("unsupported")) or float(data.get("score") or 0) < 0.5

    return {
        "wired_on_chat_llm_reply": {
            "response_guardian": False,
            "output_faithfulness": False,
            "response_audit": False,
            "note": (
                "At Titan 6b45854, chat_endpoint does not call ResponseGuardian, "
                "OutputFaithfulnessChecker or ResponseAuditWorker on the LLM reply. "
                "Those run inside core.pipeline.run on that pipeline's own "
                "generate_answer, not on /chat's model text. Defaults: all three "
                "feature flags are false."
            ),
        },
        "feature_flags": {
            "enable_response_guardian": is_response_guardian_enabled(),
            "enable_output_faithfulness": is_output_faithfulness_enabled(),
            "enable_response_audit": is_response_audit_enabled(),
        },
        "gated_as_configured": {
            "response_guardian": gated_guardian.to_dict(),
            "output_faithfulness": None if gated_faith is None else gated_faith.to_dict(),
        },
        "standalone_enabled": {
            "response_guardian": standalone_guardian.to_dict(),
            "output_faithfulness": standalone_faith.to_dict(),
        },
        "flagged": {
            "gated_response_guardian": gated_guardian.decision.value != "approve",
            "gated_output_faithfulness": _flagged_faith(gated_faith),
            "standalone_response_guardian": standalone_guardian.decision.value != "approve",
            "standalone_output_faithfulness": _flagged_faith(standalone_faith),
        },
    }


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    titan_root = Path(payload.get("titan_root") or os.environ.get(
        "TITAN_SANDBOX_ROOT", "/workspace/titan-sandbox"
    )).resolve()
    work = Path(tempfile.mkdtemp(prefix="titan-bridge-"))
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

    import httpx
    import server
    import core.llm_router as llm_router
    import core.llm_stream as llm_stream

    prepared_payloads: list[Any] = []
    orig_deepseek_body = llm_router._deepseek_request_body

    def _capture_prepared(cfg, messages, **kwargs):
        """Independent send-boundary capture: Titan's constructed provider body."""
        body = orig_deepseek_body(cfg, messages, **kwargs)
        prepared_payloads.append(copy.deepcopy(body.get("messages")))
        return body

    llm_router._deepseek_request_body = _capture_prepared
    llm_stream._deepseek_request_body = _capture_prepared

    canned = payload.get("canned_answer")
    if not isinstance(canned, str) or not canned:
        canned = "ok"
    fake = _install_fake(httpx, canned)
    facts = list(payload.get("facts") or [])
    server.pipeline_run = lambda q, mode, domain: {"facts": facts, "error": None}

    request_kwargs: dict[str, Any] = {}
    console_instructions = payload.get("console_instructions")
    if isinstance(console_instructions, str) and console_instructions:
        # Titan's own operator-instructions field; appended to the system
        # message after the memory records. Titan is not patched.
        request_kwargs["console_instructions"] = console_instructions
    req = server.ChatRequest(
        message=payload["message"],
        llm_provider="deepseek",
        llm_api_key=SYNTHETIC_KEY,
        llm_model=payload.get("model") or "deepseek-v4-flash",
        use_memory=True,
        auto_save_memory=False,
        persist_to_system=False,
        include_system_guide=False,
        llm_enabled=True,
        **request_kwargs,
    )
    resp = asyncio.run(server.chat_endpoint(req))
    bodies = [r["body"] for r in fake.requests]
    received = bodies[0].get("messages") if bodies else None
    prepared = prepared_payloads[0] if prepared_payloads else None
    checks = _evaluate_response_checks(resp.reply, facts)
    out = {
        "titan_root": str(titan_root),
        "titan_commit": _git_head(titan_root),
        "expected_titan_commit_prefix": EXPECTED_TITAN_COMMIT_PREFIX,
        "provider_calls": len(fake.requests),
        "prepared_messages": prepared,
        "provider_received_messages": received,
        "prepared_matches_provider_received": (
            None if prepared is None or received is None else prepared == received
        ),
        "capture_points": {
            "prepared": "core.llm_stream._deepseek_request_body body['messages']",
            "received": "FakeAsyncClient.post(json) body['messages']",
        },
        "messages": prepared if prepared is not None else received,
        "request_bodies": bodies,
        "context_report": resp.context_report,
        "reply": resp.reply,
        "from_llm": resp.from_llm,
        "facts_count": resp.facts_count,
        "memory_saved": resp.memory_saved,
        "memory_auto_status": resp.memory_auto_status,
        "titan_response_checks": checks,
    }
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
