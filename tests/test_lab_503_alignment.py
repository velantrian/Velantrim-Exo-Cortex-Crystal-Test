"""Lab alignment with the accepted main-Crystal #503 contract.

Pinned reference: main Crystal merge ba8e84a (PR #503 head 13a83c2). The lab
port is core/applicability.py (byte-identical) plus the pipeline/query/API/CLI
wiring. These tests pin the lab-specific points:

* date-only ``valid_until`` is an inclusive END of day (the earlier lab branch
  fbd9994 compared a timestamped as_of with the date at midnight);
* the lab's ``store_fact`` has no ``preserve_metadata`` flag, so the recall path
  (build_facts_pack) must carry existing metadata forward and still embed /
  lift ``metadata["applicability"]``;
* temporal_scope normalization and fail-closed explanations.
"""
import pytest

from core import applicability, memory
from core.applicability import _fact_covers_as_of, request_error, select
from core.pipeline import build_facts_pack, generate_answer
from tests.test_generate_answer_temporal_applicability import _pack, _verified


@pytest.mark.parametrize("as_of,covered", [
    ("2026-11-08T00:00:00+01:00", True),
    ("2026-11-08T12:00:00+01:00", True),
    ("2026-11-08T23:30:00+01:00", True),   # fbd9994: treated as expired (midnight)
    ("2026-11-08T23:59:59.999999", True),  # naive as_of vs date-only bound: same-day naive end
    ("2026-11-09T00:00:00+01:00", False),
    ("2026-11-08", True),                  # date-only as_of: whole day inside the interval
    ("2026-11-09", False),
])
def test_date_only_valid_until_is_inclusive_end_of_day(as_of, covered):
    fact = {"valid_from": "2026-11-01", "valid_until": "2026-11-08"}
    assert _fact_covers_as_of(fact, as_of) is covered


def test_end_of_day_through_generate_answer():
    fact = _verified("m", "M works", primary_object="M",
                     valid_from="2026-11-01", valid_until="2026-11-08")
    late = generate_answer(_pack(fact, asked_object="M", as_of="2026-11-08T23:30:00+01:00",
                                 temporal_scope="current"), trace=[])
    assert late["answer"] == "M works"
    nextday = generate_answer(_pack(fact, asked_object="M", as_of="2026-11-09T00:00:00+01:00",
                                    temporal_scope="current"), trace=[])
    assert nextday["answer"] is None
    assert "validity expired before as_of" in nextday["error"]


def test_timestamped_interval_must_cover_whole_date_only_as_of():
    fact = {"valid_from": "2026-11-08T12:00:00+01:00"}
    assert _fact_covers_as_of(fact, "2026-11-08") is False
    assert _fact_covers_as_of(fact, "2026-11-09") is True


@pytest.mark.parametrize("scope", ["current", " CURRENT ", "Current"])
def test_scope_is_stripped_and_casefolded(scope):
    assert request_error("L", "2026-11-08", scope) is None


@pytest.mark.parametrize("scope", ["", " ", "now", "currnet", 1, False])
def test_unknown_blank_or_non_string_scope_fails_closed_with_explanation(scope):
    err = request_error("L", "2026-11-08", scope)
    assert err and "invalid temporal_scope" in err
    kept, info = select([{"fact_id": "a", "claim": "x", "primary_object": "L",
                          "observed_at": "2026-11-08"}], asked_object="L",
                        as_of="2026-11-08", temporal_scope=scope)
    assert kept == [] and info["request_error"] == err


@pytest.mark.parametrize("as_of", [None, "", "2026-11-08oops", "8 ноября"])
def test_current_without_valid_as_of_explains(as_of):
    assert "requires a valid explicit as_of" in request_error("L", as_of, "current")


def test_write_timestamps_are_never_observation_time():
    fact = {"recorded_at": "2026-11-08", "created_at": "2026-11-08", "updated_at": "2026-11-08"}
    assert _fact_covers_as_of(fact, "2026-11-08") is False
    assert "write timestamps are not observation time" in applicability.temporal_exclusion(
        fact, "2026-11-08")


def test_recall_path_embeds_and_lifts_without_erasing_other_metadata():
    # conftest isolates SQLITE_PATH per test.
    memory._L0.clear()
    memory.store_fact({"fact_id": "keep", "claim": "L ready", "source": "fixture",
                       "metadata": {"volition": {"author": "system"},
                                    "applicability": {"primary_object": "L"}}})
    retrieved = [{"id": "keep", "text": "L ready", "source": "fixture", "confidence": 0.9,
                  "epistemic_state": "Observed", "primary_object": "L",
                  "observed_at": "2026-11-08"}]
    pack = build_facts_pack(retrieved, "L")
    memory._L0.clear()
    stored = memory.get_fact("keep")
    assert stored["metadata"]["volition"] == {"author": "system"}
    assert stored["metadata"]["applicability"] == {"primary_object": "L", "observed_at": "2026-11-08"}
    fact = pack["facts"][0]
    assert fact["primary_object"] == "L" and fact["observed_at"] == "2026-11-08"
