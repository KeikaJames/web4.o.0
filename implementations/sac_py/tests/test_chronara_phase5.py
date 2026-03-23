"""Tests for Chronara Phase 5: Adapter Specialization.

Tests specialized adapter protocol objects, Collector/Consolidator/Governor
specialization awareness, and SAC serve path alignment.
"""

import pytest
from implementations.sac_py.chronara_nexus import (
    AdapterRef,
    AdapterManifest,
    AdapterSelection,
    SnapshotRef,
    ValidationReport,
    AdapterMode,
    AdapterSpecialization,
    ObservationType,
    Collector,
    Consolidator,
    Governor,
)


# ============================================================================
# Phase A: Specialized Adapter Protocol Objects
# ============================================================================

def test_adapter_specialization_enum():
    """AdapterSpecialization enum has stable/shared/candidate."""
    assert AdapterSpecialization.STABLE.value == "stable"
    assert AdapterSpecialization.SHARED.value == "shared"
    assert AdapterSpecialization.CANDIDATE.value == "candidate"


def test_adapter_ref_with_specialization():
    """AdapterRef can carry specialization."""
    stable = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    assert stable.specialization == AdapterSpecialization.STABLE

    shared = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.SHARED)
    assert shared.specialization == AdapterSpecialization.SHARED

    candidate = AdapterRef("test", 3, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    assert candidate.specialization == AdapterSpecialization.CANDIDATE


def test_adapter_manifest_with_specialization():
    """AdapterManifest carries specialization."""
    manifest = AdapterManifest(
        adapter_id="test",
        generation=1,
        parent_generation=None,
        snapshot_ref="snap-1",
        created_at=0.0,
        specialization=AdapterSpecialization.STABLE
    )
    assert manifest.specialization == AdapterSpecialization.STABLE


def test_snapshot_ref_with_specialization():
    """SnapshotRef carries specialization."""
    snapshot = SnapshotRef(
        snapshot_id="snap-1",
        adapter_id="test",
        generation=1,
        byte_size=100,
        specialization=AdapterSpecialization.CANDIDATE
    )
    assert snapshot.specialization == AdapterSpecialization.CANDIDATE


def test_adapter_selection_creation():
    """AdapterSelection combines three specializations."""
    stable = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    shared = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.SHARED)
    candidate = AdapterRef("test", 3, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)

    selection = AdapterSelection(stable=stable, shared=shared, candidate=candidate)
    assert selection.stable == stable
    assert selection.shared == shared
    assert selection.candidate == candidate


def test_adapter_selection_get_serve_adapter():
    """AdapterSelection.serve_adapter returns stable (candidate never serves)."""
    stable = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 3, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)

    selection = AdapterSelection(stable=stable, candidate=candidate)
    serve = selection.get_serve_adapter()
    assert serve == stable
    assert serve.specialization == AdapterSpecialization.STABLE


def test_adapter_selection_is_specialization_active():
    """AdapterSelection can check which specializations are active."""
    stable = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    selection = AdapterSelection(stable=stable)

    assert selection.is_specialization_active(AdapterSpecialization.STABLE)
    assert not selection.is_specialization_active(AdapterSpecialization.SHARED)
    assert not selection.is_specialization_active(AdapterSpecialization.CANDIDATE)


def test_validation_report_specialization_summary():
    """ValidationReport includes specialization-aware summary."""
    report = ValidationReport(
        adapter_id="test",
        generation=2,
        passed=True,
        metric_summary={"test": 1},
        specialization_summary={
            AdapterSpecialization.CANDIDATE: {"status": "validated"},
            AdapterSpecialization.STABLE: {"unchanged": True}
        }
    )
    assert AdapterSpecialization.CANDIDATE in report.specialization_summary
    assert report.specialization_summary[AdapterSpecialization.CANDIDATE]["status"] == "validated"


# ============================================================================
# Phase B: Collector Specialization Awareness
# ============================================================================

def test_collector_strategy_goes_to_shared_queue():
    """STRATEGY_ONLY observations are routed to shared_queue."""
    active = AdapterRef("test", 1, AdapterMode.SERVE)
    collector = Collector(active)

    obs = {"strategy_signal": True}
    obs_type = collector.admit_observation(obs)

    assert obs_type == ObservationType.STRATEGY_ONLY
    assert len(collector.strategy_trace) == 1
    assert len(collector.shared_queue) == 1
    assert collector.shared_queue[0]["_specialization_target"] == "shared"


def test_collector_parameter_goes_to_candidate_queue():
    """PARAMETER_CANDIDATE observations are routed to parameter_queue with candidate marker."""
    active = AdapterRef("test", 1, AdapterMode.SERVE)
    collector = Collector(active)

    obs = {"data": 1.0}
    obs_type = collector.admit_observation(obs)

    assert obs_type == ObservationType.PARAMETER_CANDIDATE
    assert len(collector.parameter_queue) == 1
    assert collector.parameter_queue[0]["_specialization_target"] == "candidate"


def test_collector_explicit_does_not_get_specialization_marker():
    """EXPLICIT_ONLY observations don't get specialization marker."""
    active = AdapterRef("test", 1, AdapterMode.SERVE)
    collector = Collector(active)

    obs = {"explicit_feedback": True}
    collector.admit_observation(obs)

    assert "_specialization_target" not in collector.explicit_trace[0]


def test_collector_get_specialization_queue():
    """Collector can retrieve queue by specialization."""
    active = AdapterRef("test", 1, AdapterMode.SERVE)
    collector = Collector(active)

    collector.admit_observation({"strategy_signal": True})
    collector.admit_observation({"data": 1.0})

    shared_queue = collector.get_specialization_queue(AdapterSpecialization.SHARED)
    assert len(shared_queue) == 1

    candidate_queue = collector.get_specialization_queue(AdapterSpecialization.CANDIDATE)
    assert len(candidate_queue) == 1

    stable_queue = collector.get_specialization_queue(AdapterSpecialization.STABLE)
    assert len(stable_queue) == 0


def test_collector_clear_specialization_queue():
    """Collector can clear specific specialization queue."""
    active = AdapterRef("test", 1, AdapterMode.SERVE)
    collector = Collector(active)

    collector.admit_observation({"strategy_signal": True})
    collector.admit_observation({"data": 1.0})

    collector.clear_specialization_queue(AdapterSpecialization.SHARED)
    assert len(collector.shared_queue) == 0
    assert len(collector.parameter_queue) == 1  # candidate queue unchanged


# ============================================================================
# Phase C: Consolidator Specialization Awareness
# ============================================================================

def test_consolidator_creates_candidate_with_specialization():
    """Consolidator creates candidate with CANDIDATE specialization."""
    consolidator = Consolidator()
    base = AdapterRef("test", 1, AdapterMode.SERVE)

    candidate = consolidator.create_candidate(base)
    assert candidate.specialization == AdapterSpecialization.CANDIDATE


def test_consolidator_sets_stable_reference():
    """Consolidator sets stable_adapter when creating candidate."""
    consolidator = Consolidator()
    base = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)

    consolidator.create_candidate(base)
    assert consolidator.stable_adapter is not None
    assert consolidator.stable_adapter.specialization == AdapterSpecialization.STABLE


def test_consolidator_set_shared_adapter():
    """Consolidator can set shared adapter."""
    consolidator = Consolidator()
    ref = AdapterRef("test", 1, AdapterMode.SERVE)

    shared = consolidator.set_shared_adapter(ref)
    assert shared.specialization == AdapterSpecialization.SHARED


def test_consolidator_accumulate_for_specialization():
    """Consolidator accumulates to correct specialization buffer."""
    consolidator = Consolidator()

    obs_shared = {"_specialization_target": "shared", "data": 1.0}
    obs_candidate = {"_specialization_target": "candidate", "data": 2.0}

    consolidator.accumulate_observation(obs_shared)
    consolidator.accumulate_observation(obs_candidate)

    assert len(consolidator.shared_accumulator) == 1
    assert len(consolidator.micro_batch_buffer) == 1


def test_consolidator_explicit_accumulate_for_specialization():
    """Consolidator can explicitly accumulate for specialization."""
    consolidator = Consolidator()

    consolidator.accumulate_for_specialization({"data": 1.0}, AdapterSpecialization.SHARED)
    consolidator.accumulate_for_specialization({"data": 2.0}, AdapterSpecialization.CANDIDATE)

    assert len(consolidator.shared_accumulator) == 1
    assert len(consolidator.micro_batch_buffer) == 1


def test_consolidator_get_specialization_params():
    """Consolidator returns correct params for each specialization."""
    consolidator = Consolidator()

    candidate_params = consolidator.get_specialization_params(AdapterSpecialization.CANDIDATE)
    assert "p0" in candidate_params

    shared_params = consolidator.get_specialization_params(AdapterSpecialization.SHARED)
    assert "s0" in shared_params

    stable_params = consolidator.get_specialization_params(AdapterSpecialization.STABLE)
    assert "p0" in stable_params


def test_consolidator_evolve_for_specialization():
    """Consolidator can evolve specific specialization."""
    consolidator = Consolidator(lr=0.01, gamma=0.001)

    # Fill candidate buffer
    for i in range(10):
        consolidator.accumulate_for_specialization({"data": float(i)}, AdapterSpecialization.CANDIDATE)

    initial = consolidator.phi_candidate.copy()
    consolidator._evolve_for_specialization(AdapterSpecialization.CANDIDATE)

    # Parameters should have changed
    assert consolidator.phi_candidate != initial


def test_consolidator_evolve_shared():
    """Consolidator evolve_shared updates shared params."""
    consolidator = Consolidator(lr=0.01, gamma=0.001)

    # Fill shared buffer
    for i in range(10):
        consolidator.accumulate_for_specialization({"data": float(i)}, AdapterSpecialization.SHARED)

    initial = consolidator.phi_shared.copy()
    consolidator.evolve_shared()

    # Shared params should have changed
    assert consolidator.phi_shared != initial


def test_consolidator_prune_with_specialization():
    """Consolidator prune works with specialization."""
    consolidator = Consolidator()

    # Prune candidate
    pruned = consolidator.prune_candidate()
    assert isinstance(pruned, dict)

    # Prune shared
    pruned_shared = consolidator.prune_shared()
    assert isinstance(pruned_shared, dict)


def test_consolidator_generate_snapshot_with_specialization():
    """Consolidator can generate snapshots for specific specializations."""
    consolidator = Consolidator()
    base = AdapterRef("test", 1, AdapterMode.SERVE)

    consolidator.create_candidate(base)

    candidate_snapshot = consolidator.generate_snapshot(AdapterSpecialization.CANDIDATE)
    assert candidate_snapshot is not None
    assert candidate_snapshot.specialization == AdapterSpecialization.CANDIDATE


def test_consolidator_backward_compatible_phi():
    """Consolidator phi property is backward compatible."""
    consolidator = Consolidator()

    # Access via phi property
    assert consolidator.phi is consolidator.phi_candidate

    # Set via phi property
    consolidator.phi = {"p0": 2.0}
    assert consolidator.phi_candidate == {"p0": 2.0}


# ============================================================================
# Phase D: Governor Specialization Awareness
# ============================================================================

def test_governor_initializes_with_stable_specialization():
    """Governor initializes adapters with STABLE specialization."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    governor = Governor(initial)

    assert governor.active_adapter.specialization == AdapterSpecialization.STABLE
    assert governor.stable_adapter.specialization == AdapterSpecialization.STABLE


def test_governor_get_adapter_selection():
    """Governor returns specialization-aware adapter selection."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    governor = Governor(initial)

    selection = governor.get_adapter_selection()
    assert selection.stable.specialization == AdapterSpecialization.STABLE
    assert selection.shared is None
    assert selection.candidate is None


def test_governor_validation_report_has_specialization_summary():
    """Governor validation report includes specialization summary."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE)
    governor = Governor(initial)

    report = governor.validate_candidate(candidate)

    assert AdapterSpecialization.CANDIDATE in report.specialization_summary
    assert AdapterSpecialization.STABLE in report.specialization_summary


def test_governor_promote_updates_stable():
    """Governor promote updates stable_adapter with promoted candidate."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE)
    governor = Governor(initial)

    governor.validate_candidate(candidate)
    governor.promote_candidate(candidate)

    assert governor.stable_adapter.generation == 2
    assert governor.stable_adapter.specialization == AdapterSpecialization.STABLE


def test_governor_promote_clears_candidate():
    """Governor promote clears candidate after successful promotion."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE)
    governor = Governor(initial)

    governor.validate_candidate(candidate)
    governor.promote_candidate(candidate)

    assert governor.candidate_adapter is None


def test_governor_rollback_preserves_pre_promote_stable():
    """Governor rollback before mark_stable restores pre-promote stable."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE)
    governor = Governor(initial)

    governor.validate_candidate(candidate)
    governor.promote_candidate(candidate)
    assert governor.active_adapter.generation == 2

    # Rollback before mark_stable should restore gen 1
    governor.rollback_to_stable()
    assert governor.active_adapter.generation == 1


def test_governor_rollback_after_mark_stable_keeps_promotion():
    """Governor rollback after mark_stable keeps the promotion."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE)
    governor = Governor(initial)

    governor.validate_candidate(candidate)
    governor.promote_candidate(candidate)
    governor.mark_stable()

    # Rollback after mark_stable should keep gen 2
    governor.rollback_to_stable()
    assert governor.active_adapter.generation == 2


def test_governor_rollback_specialization():
    """Governor can rollback specific specialization."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE)
    governor = Governor(initial)

    governor.validate_candidate(candidate)
    governor.promote_candidate(candidate)

    # Rollback candidate clears it
    governor.rollback_specialization(AdapterSpecialization.CANDIDATE)
    assert governor.candidate_adapter is None


def test_governor_create_shadow_request_includes_specialization():
    """Governor shadow request includes specialization info."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE)
    governor = Governor(initial)

    request = governor.create_shadow_request(candidate, b"test")

    assert request["active_adapter"]["specialization"] == "stable"
    assert request["candidate_adapter"]["specialization"] == "candidate"


# ============================================================================
# Phase E: SAC Serve Path Alignment
# ============================================================================

def test_sac_current_adapter_selection():
    """SAC can get specialization-aware adapter selection."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    selection = sac.current_adapter_selection()
    assert selection.stable.specialization == AdapterSpecialization.STABLE


def test_sac_current_adapter_ref_returns_stable():
    """SAC current_adapter_ref returns stable adapter for serve."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    adapter = sac.current_adapter_ref()
    assert adapter.specialization == AdapterSpecialization.STABLE


# ============================================================================
# Phase F: Failure Protection / Fallback
# ============================================================================

def test_sac_fallback_to_stable():
    """SAC can fallback to stable on specialization failure."""
    from implementations.sac_py.sac import SACContainer
    from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    # Create and promote a candidate
    candidate = AdapterRef("default", 2, AdapterMode.SERVE)
    sac.validate_from_atom_result(candidate, {
        "exec_response": {"adapter_id": "default", "adapter_generation": 2}
    })
    sac.promote_candidate_if_valid(candidate)

    assert sac.current_adapter_ref().generation == 2

    # Fallback should rollback
    sac.fallback_to_stable()
    # After fallback, should still be at stable (gen 2 was promoted)
    assert sac.current_adapter_ref().specialization == AdapterSpecialization.STABLE


def test_specialization_failure_does_not_block_serve():
    """Specialization configuration failure does not block serve path."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    # Serve path should always work
    adapter = sac.current_adapter_ref()
    assert adapter is not None
    assert adapter.specialization == AdapterSpecialization.STABLE

    # Even after fallback
    sac.fallback_to_stable()
    adapter2 = sac.current_adapter_ref()
    assert adapter2 is not None
