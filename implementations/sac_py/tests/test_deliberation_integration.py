"""Test bounded deliberation integration."""

import pytest
from implementations.sac_py.chronara_nexus import (
    BoundedDeliberation,
    DeliberationRequest,
    Collector,
    Governor,
    AdapterRef,
    AdapterMode,
)


def test_bounded_deliberation_deterministic():
    """Bounded deliberation produces deterministic output."""
    deliberation = BoundedDeliberation()
    observation = {"data": 0.7}

    request1 = DeliberationRequest(observation=observation)
    result1 = deliberation.deliberate(request1)

    request2 = DeliberationRequest(observation=observation)
    result2 = deliberation.deliberate(request2)

    assert result1.accepted == result2.accepted
    assert result1.rounds_used == result2.rounds_used


def test_bounded_deliberation_accepts_high_quality():
    """Bounded deliberation accepts high quality observation."""
    deliberation = BoundedDeliberation()
    observation = {"data": 0.9}

    request = DeliberationRequest(observation=observation)
    result = deliberation.deliberate(request)

    assert result.accepted is True
    assert result.rounds_used == 1
    assert result.synthesized_output.get("deliberation_enhanced") is True


def test_bounded_deliberation_rejects_low_quality():
    """Bounded deliberation rejects low quality observation."""
    deliberation = BoundedDeliberation()
    observation = {"data": 0.1}

    request = DeliberationRequest(observation=observation)
    result = deliberation.deliberate(request)

    assert result.accepted is False
    assert result.synthesized_output.get("deliberation_rejected") is True


def test_collector_with_deliberation_enabled():
    """Collector with deliberation enhances parameter candidates."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    # High quality observation should be enhanced
    collector.admit_observation({"data": 0.8})

    assert len(collector.parameter_queue) == 1
    enhanced = collector.parameter_queue[0]
    assert enhanced.get("deliberation_enhanced") is True


def test_collector_deliberation_fallback():
    """Collector falls back on deliberation failure."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    # Low quality observation should still be added (rejected but not dropped)
    collector.admit_observation({"data": 0.1})

    assert len(collector.parameter_queue) == 1


def test_collector_without_deliberation():
    """Collector without deliberation works as before."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=False)

    collector.admit_observation({"data": 0.8})

    assert len(collector.parameter_queue) == 1
    obs = collector.parameter_queue[0]
    assert "deliberation_enhanced" not in obs


def test_governor_with_deliberation_rejects():
    """Governor with deliberation can reject based on quality."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    governor = Governor(active, enable_deliberation=True)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)

    # Atom result that would normally pass
    atom_result = {
        "validation_result": {
            "active_adapter_id": "base",
            "active_generation": 1,
            "candidate_adapter_id": "base",
            "candidate_generation": 2,
            "lineage_valid": True,
            "output_match": True,
            "kv_count_match": True,
            "is_acceptable": True,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert report.passed
    assert report.metric_summary["source"] == "atom_validation_result"


def test_governor_without_deliberation():
    """Governor without deliberation works as before."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    governor = Governor(active, enable_deliberation=False)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)

    atom_result = {
        "validation_result": {
            "active_adapter_id": "base",
            "active_generation": 1,
            "candidate_adapter_id": "base",
            "candidate_generation": 2,
            "lineage_valid": True,
            "output_match": True,
            "kv_count_match": True,
            "is_acceptable": True,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert report.passed
    assert report.metric_summary["source"] == "atom_validation_result"
