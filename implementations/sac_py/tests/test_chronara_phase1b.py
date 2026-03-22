"""Test Chronara Phase 1B: deterministic and real behavior."""

import pytest
from implementations.sac_py.chronara_nexus import (
    AdapterRef, AdapterMode, Collector, Consolidator, Governor,
    SnapshotManager, InMemorySink
)


def test_consolidator_deterministic_update():
    """Consolidator update is deterministic, not random."""
    consolidator1 = Consolidator(lr=0.01, gamma=0.001)
    consolidator2 = Consolidator(lr=0.01, gamma=0.001)

    observations = [{"data": i} for i in range(10)]

    for obs in observations:
        consolidator1.accumulate_observation(obs)
        consolidator2.accumulate_observation(obs)

    consolidator1.evolve_micro_batch()
    consolidator2.evolve_micro_batch()

    # Same observations should produce same phi
    for key in consolidator1.phi:
        assert consolidator1.phi[key] == consolidator2.phi[key]


def test_consolidator_same_batch_same_result():
    """Same batch of observations produces same candidate update."""
    consolidator = Consolidator(lr=0.01, gamma=0.001)
    initial_phi = consolidator.phi.copy()

    batch = [{"data": i * 0.1} for i in range(10)]
    for obs in batch:
        consolidator.accumulate_observation(obs)

    consolidator.evolve_micro_batch()
    first_phi = consolidator.phi.copy()

    # Reset and run again
    consolidator.phi = initial_phi.copy()
    for obs in batch:
        consolidator.accumulate_observation(obs)

    consolidator.evolve_micro_batch()
    second_phi = consolidator.phi.copy()

    for key in first_phi:
        assert first_phi[key] == second_phi[key]


def test_governor_real_metric_summary():
    """Governor validation uses real metric summary, not placeholder."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    report = governor.validate_candidate(candidate)

    assert "generation_delta" in report.metric_summary
    assert "generation_advanced" in report.metric_summary
    assert "expected_delta" in report.metric_summary
    assert report.metric_summary["generation_delta"] == 1
    assert report.metric_summary["generation_advanced"] is True


def test_governor_rejects_invalid_generation_delta():
    """Governor rejects candidate with invalid generation delta."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 3, AdapterMode.SERVE)  # Skip generation 2
    governor = Governor(active)

    report = governor.validate_candidate(candidate)

    assert not report.passed
    assert "generation delta 2 != 1" in report.reason


def test_snapshot_manager_three_tier_protocol():
    """SnapshotManager maintains candidate/window/stable three-tier protocol."""
    mgr = SnapshotManager()
    adapter_base = AdapterRef("base", 1, AdapterMode.SERVE)

    # Save multiple window snapshots
    for gen in range(1, 5):
        adapter = AdapterRef("base", gen, AdapterMode.SERVE)
        mgr.save_window_snapshot(adapter)

    # Should keep only recent 3
    assert len(mgr.get_window_snapshots()) == 3
    assert mgr.get_window_snapshots()[0].generation == 2
    assert mgr.get_window_snapshots()[-1].generation == 4

    # Save multiple stable snapshots
    for gen in range(1, 7):
        adapter = AdapterRef("base", gen, AdapterMode.SERVE)
        mgr.save_stable_snapshot(adapter)

    # Should keep only recent 5
    assert len(mgr.get_stable_snapshots()) == 5
    assert mgr.get_stable_snapshots()[0].generation == 2
    assert mgr.get_stable_snapshots()[-1].generation == 6


def test_snapshot_manager_rollback_target_selection():
    """SnapshotManager rollback target selection is real."""
    mgr = SnapshotManager()

    # No stable snapshot yet
    assert mgr.get_rollback_target() is None

    # Add stable snapshots
    adapter1 = AdapterRef("base", 1, AdapterMode.SERVE)
    adapter2 = AdapterRef("base", 2, AdapterMode.SERVE)

    mgr.save_stable_snapshot(adapter1)
    assert mgr.get_rollback_target().generation == 1

    mgr.save_stable_snapshot(adapter2)
    assert mgr.get_rollback_target().generation == 2


def test_memory_sink_interface():
    """Collector uses memory sink interface, not raw list."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter)

    # Verify memory sinks are InMemorySink instances
    assert isinstance(collector.explicit_trace, InMemorySink)
    assert isinstance(collector.strategy_trace, InMemorySink)
    assert isinstance(collector.parameter_queue, InMemorySink)

    # Verify interface methods work
    collector.explicit_trace.append({"test": 1})
    assert len(collector.explicit_trace.get_all()) == 1

    collector.explicit_trace.clear()
    assert len(collector.explicit_trace.get_all()) == 0


def test_sac_chronara_real_loop():
    """SAC Chronara mount drives real minimal loop."""
    from implementations.sac_py.sac import SACContainer
    from implementations.sac_py.chronara_nexus import ObservationType

    sac = SACContainer.create("/tmp/mem")
    sac.init_chronara()

    # Record observations
    obs_type = sac.record_observation({"explicit_feedback": True})
    assert obs_type == ObservationType.EXPLICIT_ONLY

    # Get current adapter
    adapter = sac.current_adapter_ref()
    assert adapter.generation == 1
    assert adapter.adapter_id == "default"

    # Create and validate candidate
    from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode
    candidate = AdapterRef("default", 2, AdapterMode.SERVE)

    # Validate
    report = sac.validate_from_atom_result(candidate, {
        "exec_response": {
            "adapter_id": "default",
            "adapter_generation": 2,
        }
    })
    assert report.passed

    # Promote
    promoted = sac.promote_candidate_if_valid(candidate)
    assert promoted

    # Verify active adapter updated
    current = sac.current_adapter_ref()
    assert current.generation == 2

