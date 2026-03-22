"""Test Chronara Phase 1: pure SAC-side minimal loop."""

import pytest
from implementations.sac_py.chronara_nexus import (
    AdapterRef, AdapterMode, Collector, Consolidator, Governor,
    AdmissionGate, ObservationType, SnapshotManager
)


def test_chronara_core_objects_initialize():
    """Chronara core objects can initialize."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter)
    consolidator = Consolidator(lr=0.01, gamma=0.001)
    governor = Governor(adapter)
    gate = AdmissionGate()
    snapshot_mgr = SnapshotManager()

    assert collector.active_adapter.adapter_id == "base"
    assert consolidator.lr == 0.01
    assert consolidator.gamma == 0.001
    assert governor.active_adapter.generation == 1
    assert gate is not None
    assert snapshot_mgr is not None


def test_observation_admission_gate_routing():
    """Observation can be classified and routed."""
    gate = AdmissionGate()

    obs1 = {"explicit_feedback": True}
    obs2 = {"strategy_signal": True}
    obs3 = {"data": "parameter"}

    assert gate.classify(obs1) == ObservationType.EXPLICIT_ONLY
    assert gate.classify(obs2) == ObservationType.STRATEGY_ONLY
    assert gate.classify(obs3) == ObservationType.PARAMETER_CANDIDATE


def test_collector_routes_to_traces():
    """Collector routes observations to different traces."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter)

    collector.admit_observation({"explicit_feedback": True})
    collector.admit_observation({"strategy_signal": True})
    collector.admit_observation({"data": "param"})

    assert len(collector.explicit_trace.get_all()) == 1
    assert len(collector.strategy_trace.get_all()) == 1
    assert len(collector.parameter_queue.get_all()) == 1


def test_snapshot_manager_semantics():
    """Snapshot manager provides candidate/window/stable semantics."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    mgr = SnapshotManager()

    candidate_snap = mgr.save_candidate_snapshot(adapter)
    window_snap = mgr.save_window_snapshot(adapter)
    stable_snap = mgr.save_stable_snapshot(adapter)

    assert candidate_snap.snapshot_id.endswith("-candidate")
    assert window_snap.snapshot_id.endswith("-window")
    assert stable_snap.snapshot_id.endswith("-stable")
    assert mgr.get_rollback_target() == stable_snap


def test_consolidator_micro_batch_evolve():
    """Consolidator has minimal callable training step."""
    consolidator = Consolidator(lr=0.01, gamma=0.001)

    for i in range(5):
        consolidator.accumulate_observation({"data": i})

    assert not consolidator.evolve_micro_batch()

    for i in range(5):
        consolidator.accumulate_observation({"data": i})

    assert consolidator.evolve_micro_batch()
    assert len(consolidator.micro_batch_buffer) == 0


def test_consolidator_prune_quantile():
    """Consolidator uses quantile 0.1 for pruning."""
    consolidator = Consolidator()
    phi = {f"p{i}": float(i) for i in range(100)}

    pruned = consolidator.prune_parameters(phi)
    assert len(pruned) < len(phi)


def test_consolidator_prune_empty_parameters():
    """Consolidator returns an empty dict for empty inputs."""
    consolidator = Consolidator()
    assert consolidator.prune_parameters({}) == {}


def test_governor_validation_and_decision():
    """Governor generates ValidationReport and makes promote/rollback decision."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)
    governor = Governor(active)

    report = governor.validate_candidate(candidate)
    assert report.passed
    assert report.generation == 2

    decision = governor.decide(candidate, report)
    assert decision == "promote"


def test_governor_promote_rollback():
    """Governor can promote and rollback."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    governor.validate_candidate(candidate)
    assert governor.promote_candidate(candidate)
    assert governor.active_adapter.generation == 2

    governor.mark_stable()
    governor.rollback_to_stable()
    assert governor.active_adapter.generation == 2


def test_sac_chronara_mount():
    """SAC minimal mount interface works."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/mem")
    sac.init_chronara()

    obs_type = sac.record_observation({"explicit_feedback": True})
    assert obs_type == ObservationType.EXPLICIT_ONLY

    adapter = sac.current_adapter_ref()
    assert adapter.generation == 1
