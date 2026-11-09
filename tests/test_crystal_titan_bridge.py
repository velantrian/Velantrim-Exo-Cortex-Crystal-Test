"""Crystal-Test → Titan bridge: selected grounds survive into Titan messages.

No real model is called. Titan is exercised in-process via a subprocess spy
with a fake HTTP provider (same pattern as Titan
``tests/test_llm_context_no_silent_truncation.py``).
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from tests.support.crystal_titan_bridge import (
    flatten_messages,
    provenance_of,
    run_bridge,
)

TZ = "Europe/Berlin"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=ZoneInfo(TZ))
KNOWN = (
    {"id": "M", "names": ["M"]},
    {"id": "L", "names": ["L"]},
)
QUESTION_M_NOW = "Какой статус у M сейчас?"
QUESTION_AMBIGUOUS = "Какой статус?"

MATCHING = {
    "fact_id": "g-m-current",
    "claim": "M is operational MATCHING-GROUND-TEXT",
    "source": "operator-log:m-current",
    "confidence": 1.0,
    "primary_object": "M",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-CURRENT"}},
}
FOREIGN = {
    "fact_id": "g-l-foreign",
    "claim": "L is offline FOREIGN-OBJECT-MARKER",
    "source": "operator-log:l-foreign",
    "confidence": 1.0,
    "primary_object": "L",
    "observed_at": "2026-11-09T12:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-L-FOREIGN"}},
}
STALE = {
    "fact_id": "g-m-stale",
    "claim": "M was in maintenance STALE-GROUND-MARKER",
    "source": "operator-log:m-stale",
    "confidence": 1.0,
    "primary_object": "M",
    "observed_at": "2026-10-01T10:00:00+01:00",
    "metadata": {"provenance": {"origin": "fixture", "record": "PROV-M-STALE"}},
}


def _run(question, facts, spy=None):
    return run_bridge(
        question,
        facts,
        KNOWN,
        now=NOW,
        timezone=TZ,
        invoke_titan=spy,
    )


def test_matching_ground_is_present_in_final_messages():
    result = _run(QUESTION_M_NOW, [MATCHING])
    assert result["kind"] == "answer_request"
    assert result["titan_invoked"] is True
    assert result["provider_calls"] == 1
    assert [f["fact_id"] for f in result["kept"]] == ["g-m-current"]
    assert result["excluded"] == []
    blob = flatten_messages(result["final_messages"])
    assert MATCHING["claim"] in blob
    assert "object=M" in blob
    assert MATCHING["observed_at"] in blob
    assert MATCHING["source"] in blob
    assert "PROV-M-CURRENT" in blob
    assert provenance_of(MATCHING) in blob
    user_msg = result["final_messages"][-1]
    assert user_msg["role"] == "user"
    assert user_msg["content"] == QUESTION_M_NOW
    report = result["context_report"]
    assert report["memory_records_sent"] == 1
    assert report["memory_records_total"] == 1
    assert report["memory_records_omitted"] == []
    assert "sent_facts" not in report
    assert "sent_fact_positions" not in report
    assert result["titan"]["titan_commit"].startswith("6b45854")
    assert result["titan"]["memory_auto_status"] == "off"
    assert result["titan"]["memory_saved"] == []


def test_foreign_or_stale_ground_is_absent_from_final_messages():
    result = _run(QUESTION_M_NOW, [FOREIGN, STALE])
    assert result["kind"] == "answer_request"
    assert result["titan_invoked"] is True
    assert result["provider_calls"] == 1
    assert result["kept"] == []
    excluded_ids = {item["fact_id"] for item in result["excluded"]}
    assert excluded_ids == {"g-l-foreign", "g-m-stale"}
    blob = flatten_messages(result["final_messages"])
    assert "FOREIGN-OBJECT-MARKER" not in blob
    assert "STALE-GROUND-MARKER" not in blob
    assert FOREIGN["claim"] not in blob
    assert STALE["claim"] not in blob
    assert "PROV-L-FOREIGN" not in blob
    assert "PROV-M-STALE" not in blob
    assert "g-l-foreign" not in blob
    assert "g-m-stale" not in blob
    report = result["context_report"]
    assert report["memory_records_sent"] == 0
    assert report["memory_records_total"] == 0
    user_msg = result["final_messages"][-1]
    assert user_msg["content"] == QUESTION_M_NOW


def test_ambiguous_question_clarifies_without_provider_call():
    calls = []

    def spy(message, records):
        calls.append((message, records))
        raise AssertionError("Titan must not be invoked for a clarification")

    result = _run(QUESTION_AMBIGUOUS, [MATCHING, FOREIGN, STALE], spy=spy)
    assert result["kind"] == "needs_clarification"
    assert result["titan_invoked"] is False
    assert result["provider_calls"] == 0
    assert result["final_messages"] is None
    assert calls == []
    clarification = result["clarification"]
    assert clarification["kind"] == "needs_clarification"
    assert clarification["reason"] == "объект не назван"
    assert "M" in clarification["question"]
