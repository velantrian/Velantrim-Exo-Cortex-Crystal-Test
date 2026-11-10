"""Drive the authorized DeepSeek V4.1-Flash-1017 bridge experiment.

Maximum three chat/completions calls. No Titan or main-Crystal source edits.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.support.crystal_titan_bridge import (  # noqa: E402
    build_selection_receipt,
    flatten_messages,
    ground_to_titan_record,
    parse_and_select,
    selection_fingerprint,
)
from tests.support.shadow_support import evaluate_shadow_support  # noqa: E402
from tests.test_crystal_titan_bridge import (  # noqa: E402
    FOREIGN,
    KNOWN,
    MATCHING,
    NEGATED,
    NEW_CLOSED,
    NOW,
    OLD_OPEN,
    QUESTION_M_NOW,
    STALE,
    TZ,
)

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_titan_chat_live.py"
TITAN_ROOT = Path(os.environ.get("TITAN_SANDBOX_ROOT", "/workspace/titan-sandbox"))
PY = sys.executable
BERLIN = ZoneInfo("Europe/Berlin")

MODEL_ID = "deepseek-flash"
MODEL_SERVED_AS = "DeepSeek-V4.1-Flash-1017"
THINKING = "high"
MAX_TOKENS = 8192
# Titan llm_timeout_for_max_tokens(8192) = min(600, 90 + 8192/64) = 218
TITAN_TIMEOUT_SECONDS = 218.0
MAX_CALLS = 3
RECEIPT_LABEL = "квитанция ответа Crystal (не подтверждение ответа Titan)"


def now_label() -> str:
    return datetime.now(BERLIN).isoformat(timespec="seconds")


def write_json(path: Path, payload: object) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def git_head(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=str(root), text=True
    ).strip()


def invoke_runner(payload: dict, *, timeout: float) -> tuple[int, dict, str]:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Do not copy secrets into a file; the child reads DEEPSEEK_API_KEY itself.
    proc = subprocess.run(
        [PY, str(RUNNER)],
        input=json.dumps(payload, ensure_ascii=False, default=str),
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    raw = proc.stdout.strip()
    data: dict
    try:
        data = json.loads(raw) if raw else {"error": "empty_stdout", "stderr": proc.stderr[-4000:]}
    except json.JSONDecodeError:
        data = {
            "error": "invalid_stdout_json",
            "stdout_head": raw[:1000],
            "stderr": proc.stderr[-4000:],
        }
    return proc.returncode, data, proc.stderr


def excluded_from_prep(prep: dict, candidates: list) -> list[dict]:
    kept_ids = {fact.get("fact_id") for fact in prep["kept"]}
    extra = list(prep.get("excluded") or []) + list(prep.get("canonical_view_excluded") or [])
    by_id: dict = {}
    for fact in list(candidates) + extra:
        fid = fact.get("fact_id")
        if not fid or fid in kept_ids:
            continue
        incoming = dict(fact)
        existing = by_id.get(fid)
        if existing is None:
            by_id[fid] = incoming
            continue
        # Prefer a record that still carries the original claim text.
        if not existing.get("claim") and incoming.get("claim"):
            by_id[fid] = incoming
            continue
        if existing.get("claim") and not incoming.get("claim"):
            continue
        for key, value in incoming.items():
            if value is not None and existing.get(key) in (None, "", [], {}):
                existing[key] = value
    return list(by_id.values())


def criteria_for(case_id: str) -> str:
    return {
        "case1": (
            "Ответ передаёт допущенный статус M (operational / MATCHING-GROUND-TEXT) "
            "и не приписывает M статус L и не опирается на устаревшую запись о maintenance."
        ),
        "case2": "Ответ сохраняет отрицание: M не работает / is NOT operational.",
        "case3": (
            "Ответ сообщает, что M закрыт (closed). Недостаточно просто не употребить слово open."
        ),
    }[case_id]


def main() -> int:
    if not os.environ.get("DEEPSEEK_API_KEY"):
        print("STOP: DEEPSEEK_API_KEY is missing")
        return 2

    titan_commit = git_head(TITAN_ROOT)
    crystal_commit = git_head(ROOT)

    # --- Preflight: build request body with the spy/fake path, no live call ---
    preflight_payload = {
        "mode": "fake",
        "message": QUESTION_M_NOW,
        "facts": [ground_to_titan_record(MATCHING)],
        "titan_root": str(TITAN_ROOT),
        "model": MODEL_ID,
        "deepseek_thinking": THINKING,
        "llm_max_tokens": MAX_TOKENS,
        "canned_answer": "preflight-no-model",
        "admitted": [{"fact_id": MATCHING["fact_id"], "claim": MATCHING["claim"]}],
        "excluded": [],
        "abort_if_excluded": False,
    }
    rc, preflight, err = invoke_runner(preflight_payload, timeout=90)
    body = preflight.get("prepared_request_body") or {}
    proof = {
        "runner_rc": rc,
        "key_found": True,
        "key_source": "ENV DEEPSEEK_API_KEY",
        "model_in_body": body.get("model"),
        "thinking_in_body": body.get("thinking"),
        "reasoning_effort_in_body": body.get("reasoning_effort"),
        "max_tokens_in_body": body.get("max_tokens"),
        "stream_in_body": body.get("stream"),
        "temperature_in_body": body.get("temperature", "<unset>"),
        "body_keys": sorted(body.keys()) if isinstance(body, dict) else None,
        "provider_calls": preflight.get("provider_calls"),
        "note": (
            "Fake provider only. A POST to the fake client is not a chat/completions "
            "network call and is not counted against the three authorized live calls."
        ),
        "stderr_tail": err[-1500:] if err else "",
    }
    thinking_ok = (
        body.get("model") == MODEL_ID
        and body.get("thinking") == {"type": "enabled"}
        and body.get("reasoning_effort") == "high"
    )
    proof["titan_passes_high_mode"] = thinking_ok
    write_json(HERE / "preflight.json", proof)
    if not thinking_ok:
        print("STOP: Titan did not put model id and high-mode parameters in the request body")
        print(json.dumps(proof, ensure_ascii=False, indent=2))
        return 2

    settings = {
        "experiment_id": "2026-11-10-deepseek-bridge",
        "frozen_at": now_label(),
        "timezone": "Europe/Berlin",
        "question": QUESTION_M_NOW,
        "model_id": MODEL_ID,
        "model_served_as": MODEL_SERVED_AS,
        "model_id_sources": [
            "https://api-docs.deepseek.com/ — use deepseek-flash; served by DeepSeek-V4.1-Flash-1017",
            "GET https://api.deepseek.com/models returned [deepseek-flash, deepseek-v4-pro]",
        ],
        "dated_id_not_on_official_api": "deepseek-v4.1-flash-1017",
        "thinking_mode_requested": THINKING,
        "provider_parameters": {
            "thinking": {"type": "enabled"},
            "reasoning_effort": "high",
        },
        "titan_request_fields": {
            "ChatRequest.llm_model": MODEL_ID,
            "ChatRequest.deepseek_thinking": THINKING,
            "ChatRequest.llm_max_tokens": MAX_TOKENS,
            "ChatRequest.auto_save_memory": False,
        },
        "temperature": None,
        "temperature_note": (
            "Titan core.llm_router._deepseek_request_body does not set temperature "
            "or other sampling parameters; the provider default applies."
        ),
        "max_tokens": MAX_TOKENS,
        "stream": False,
        "titan_http_timeout_seconds": TITAN_TIMEOUT_SECONDS,
        "auto_save_memory": False,
        "persist_to_system": False,
        "include_system_guide": False,
        "titan_commit": titan_commit,
        "crystal_test_commit_at_freeze": crystal_commit,
        "max_provider_chat_completions_calls": MAX_CALLS,
        "preflight_ok": True,
    }
    write_json(HERE / "settings.json", settings)

    cases = [
        {
            "id": "case1",
            "title": "matching M + foreign L + stale M",
            "facts": [MATCHING, FOREIGN, STALE],
        },
        {
            "id": "case2",
            "title": "only negation: M is NOT operational",
            "facts": [NEGATED],
        },
        {
            "id": "case3",
            "title": "Deprecated 'M is open' + Validated 'M is closed'",
            "facts": [OLD_OPEN, NEW_CLOSED],
        },
    ]

    call_count = 0
    stopped = None
    summary = []

    for case in cases:
        case_id = case["id"]
        case_dir = HERE / case_id
        case_dir.mkdir(exist_ok=True)
        candidates = list(case["facts"])
        prep = parse_and_select(
            QUESTION_M_NOW, candidates, KNOWN, now=NOW, timezone=TZ
        )
        if prep["kind"] != "parsed":
            stopped = {"stage": f"{case_id}.parse_and_select", "prep": prep}
            write_json(case_dir / "stop.json", stopped)
            break
        receipt = build_selection_receipt(
            QUESTION_M_NOW,
            prep["params"],
            prep["kept"],
            prep["selection"],
            canonical_view_excluded=prep.get("canonical_view_excluded"),
        )
        labeled_receipt = {
            "label": RECEIPT_LABEL,
            "certifies_titan_answer": False,
            "receipt": receipt,
        }
        fingerprint = selection_fingerprint(prep["params"], prep["kept"])
        records = [ground_to_titan_record(fact) for fact in prep["kept"]]
        excluded = excluded_from_prep(prep, candidates)
        admitted_slim = [
            {"fact_id": f.get("fact_id"), "claim": f.get("claim")} for f in prep["kept"]
        ]
        excluded_slim = [
            {"fact_id": f.get("fact_id"), "claim": f.get("claim")} for f in excluded
        ]
        write_json(case_dir / "receipt.json", labeled_receipt)
        write_json(case_dir / "selection_fingerprint.json", fingerprint)
        write_json(
            case_dir / "selection.json",
            {
                "kept": admitted_slim,
                "excluded": excluded_slim,
                "canonical_view_excluded_fact_ids": [
                    f.get("fact_id") for f in (prep.get("canonical_view_excluded") or [])
                ],
            },
        )

        live_payload = {
            "mode": "live",
            "message": QUESTION_M_NOW,
            "facts": records,
            "titan_root": str(TITAN_ROOT),
            "model": MODEL_ID,
            "deepseek_thinking": THINKING,
            "llm_max_tokens": MAX_TOKENS,
            "admitted": admitted_slim,
            "excluded": excluded_slim,
            "abort_if_excluded": True,
        }
        rc, live, err = invoke_runner(live_payload, timeout=360)
        used = int(live.get("provider_calls") or 0)
        call_count += used

        boundary_request = {
            "capture_point": "core.llm_stream._deepseek_request_body",
            "body": live.get("prepared_request_body"),
            "messages": live.get("prepared_messages"),
            "boundary_problems": live.get("boundary_problems"),
            "boundary_ok": live.get("boundary_ok"),
            "flattened": flatten_messages(live.get("prepared_messages")),
        }
        write_json(case_dir / "boundary_request.json", boundary_request)
        write_json(
            case_dir / "wire_request.json",
            {
                "capture_point": "httpx.AsyncClient.post",
                "url": (live.get("wire") or {}).get("url") if live.get("wire") else None,
                "headers_redacted": (live.get("wire") or {}).get("headers") if live.get("wire") else None,
                "body": (live.get("wire") or {}).get("body") if live.get("wire") else None,
                "prepared_matches_wire_body": live.get("prepared_matches_wire_body"),
                "prepared_matches_provider_received": live.get("prepared_matches_provider_received"),
            },
        )

        answer_text = live.get("response_text")
        if answer_text is None:
            answer_text = live.get("reply")
        write_json(
            case_dir / "response.json",
            {
                "http_status": live.get("http_status"),
                "from_llm": live.get("from_llm"),
                "reply_from_titan_chat": live.get("reply"),
                "response_text": live.get("response_text"),
                "reasoning_content": live.get("reasoning_content"),
                "raw_response": live.get("raw_response"),
                "error": live.get("error"),
                "latency_ms": live.get("latency_ms"),
                "llm_usage": live.get("llm_usage"),
                "provider_calls": used,
                "runner_rc": rc,
                "memory_saved": live.get("memory_saved"),
                "memory_auto_status": live.get("memory_auto_status"),
            },
        )

        shadow = evaluate_shadow_support(
            answer=answer_text,
            prepared_messages=live.get("prepared_messages"),
            admitted=prep["kept"],
            excluded=excluded,
        )
        write_json(case_dir / "shadow.json", shadow)

        case_summary = {
            "id": case_id,
            "title": case["title"],
            "admitted": admitted_slim,
            "excluded": excluded_slim,
            "boundary_ok": live.get("boundary_ok"),
            "boundary_problems": live.get("boundary_problems"),
            "provider_calls": used,
            "cumulative_provider_calls": call_count,
            "http_status": live.get("http_status"),
            "from_llm": live.get("from_llm"),
            "response_text": live.get("response_text"),
            "reasoning_present": bool(live.get("reasoning_content")),
            "error": live.get("error"),
            "shadow_verdict": shadow.get("verdict"),
            "criteria": criteria_for(case_id),
        }
        write_json(case_dir / "case_summary.json", case_summary)
        summary.append(case_summary)

        if live.get("boundary_problems"):
            stopped = {
                "stage": f"{case_id}.boundary_request",
                "reason": "excluded_or_missing_record_in_prepared_request",
                "problems": live.get("boundary_problems"),
            }
            write_json(HERE / "stopped.json", stopped)
            break
        if live.get("error") or (live.get("http_status") not in (None, 200)):
            stopped = {
                "stage": f"{case_id}.provider_call",
                "reason": "provider_http_or_runner_error",
                "error": live.get("error"),
                "http_status": live.get("http_status"),
            }
            write_json(HERE / "stopped.json", stopped)
            break
        if not live.get("from_llm"):
            stopped = {
                "stage": f"{case_id}.titan_chat",
                "reason": "titan_did_not_return_from_llm",
                "reply": live.get("reply"),
            }
            write_json(HERE / "stopped.json", stopped)
            break
        if call_count > MAX_CALLS:
            stopped = {"stage": f"{case_id}.budget", "reason": "exceeded_max_calls"}
            write_json(HERE / "stopped.json", stopped)
            break

    write_json(
        HERE / "run_summary.json",
        {
            "finished_at": now_label(),
            "provider_calls_used": call_count,
            "stopped": stopped,
            "cases": summary,
            "receipt_label": RECEIPT_LABEL,
        },
    )
    print(json.dumps({"provider_calls_used": call_count, "stopped": stopped, "cases": [
        {"id": c["id"], "boundary_ok": c["boundary_ok"], "http_status": c["http_status"],
         "from_llm": c["from_llm"], "error": c["error"],
         "response_preview": (c.get("response_text") or "")[:240]}
        for c in summary
    ]}, ensure_ascii=False, indent=2))
    return 0 if stopped is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
