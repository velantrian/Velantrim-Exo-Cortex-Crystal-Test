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
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []


def _install_fake(httpx_mod: Any) -> FakeProvider:
    provider = FakeProvider()

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
                json={"choices": [{"message": {"content": "ok"}}], "usage": {}},
                request=request,
            )

        def stream(self, method: str, url: str, headers: Any = None, json: Any = None):
            raise RuntimeError("streaming is not used by the Crystal-Titan bridge spy")

    httpx_mod.AsyncClient = FakeAsyncClient
    return provider


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
    os.environ["SLEEP_WORKER_ENABLED"] = "false"
    os.environ["LOG_LEVEL"] = "WARNING"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    # Isolate relative paths (Titan defaults to ./data/...) from the checkout.
    os.chdir(work)
    sys.path.insert(0, str(titan_root))

    import httpx
    import server

    fake = _install_fake(httpx)
    facts = list(payload.get("facts") or [])
    server.pipeline_run = lambda q, mode, domain: {"facts": facts, "error": None}

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
    )
    resp = asyncio.run(server.chat_endpoint(req))
    bodies = [r["body"] for r in fake.requests]
    report = resp.context_report
    out = {
        "titan_root": str(titan_root),
        "titan_commit": _git_head(titan_root),
        "expected_titan_commit_prefix": EXPECTED_TITAN_COMMIT_PREFIX,
        "provider_calls": len(fake.requests),
        "messages": (bodies[0].get("messages") if bodies else None),
        "request_bodies": bodies,
        "context_report": report,
        "reply": resp.reply,
        "from_llm": resp.from_llm,
        "facts_count": resp.facts_count,
        "memory_saved": resp.memory_saved,
        "memory_auto_status": resp.memory_auto_status,
    }
    json.dump(out, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
