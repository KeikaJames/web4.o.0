"""Tests for Chronara Nexus minimal skeleton."""

import pytest
from implementations.sac_py.chronara_nexus import (
    AdapterRef,
    AdapterMode,
    Collector,
    Consolidator,
    Governor,
    ObservationType,
)


def test_adapter_ref_creation():
    ref = AdapterRef(adapter_id="test-adapter", generation=1, mode=AdapterMode.SERVE)
    assert ref.adapter_id == "test-adapter"
    assert ref.generation == 1


def test_collector_admission_gate():
    active = AdapterRef("active-1", 1, AdapterMode.SERVE)
    collector = Collector(active)

    obs_explicit = {"explicit_feedback": True}
    obs_type = collector.admit_observation(obs_explicit)
    assert obs_type == ObservationType.EXPLICIT_ONLY


def test_consolidator_candidate_lifecycle():
    consolidator = Consolidator()
    base = AdapterRef("base", 1, AdapterMode.SERVE)

    candidate = consolidator.create_candidate(base)
    assert candidate.generation == 2


def test_governor_promote_rollback():
    initial = AdapterRef("adapter-1", 1, AdapterMode.SERVE)
    governor = Governor(initial)

    candidate = AdapterRef("adapter-1", 2, AdapterMode.SERVE)
    report = governor.validate_from_lineage(
        candidate,
        {
            "exec_response": {
                "adapter_id": "adapter-1",
                "adapter_generation": 2,
            }
        },
    )
    assert report.passed
    promoted = governor.promote_candidate(candidate)
    assert promoted
    assert governor.active_adapter.generation == 2

    governor.rollback_to_stable()
    assert governor.active_adapter.generation == 1
