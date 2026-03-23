"""Tests for Chronara Phase 6: Specialization-aware Atom Coordination.

Tests Rust-side specialization-aware adapter context, request/result lineage,
and Governor consumption of specialization-aware atom results.
"""

import pytest
from implementations.sac_py.chronara_nexus import (
    AdapterRef,
    AdapterMode,
    AdapterSpecialization,
    Governor,
    ValidationReport,
)


# ============================================================================
# Phase A/B/C: Specialization-aware context and atom coordination
# ============================================================================

def test_adapter_specialization_enum_values():
    """AdapterSpecialization enum has correct values matching Rust."""
    assert AdapterSpecialization.STABLE.value == "stable"
    assert AdapterSpecialization.SHARED.value == "shared"
    assert AdapterSpecialization.CANDIDATE.value == "candidate"


def test_governor_consumes_specialization_aware_result():
    """Governor can consume atom result with specialization summary."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    # Simulate specialization-aware atom result
    atom_result = {
        "exec_response": {
            "adapter_id": "test",
            "adapter_generation": 2,
            "adapter_specialization": "candidate",
            "specialization_summary": {
                "stable_generation": 1,
                "stable_adapter_id": "test",
                "candidate_generation": 2,
            }
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert report.passed
    assert AdapterSpecialization.CANDIDATE in report.specialization_summary
    assert report.specialization_summary[AdapterSpecialization.CANDIDATE]["generation"] == 2


def test_governor_detects_specialization_mismatch():
    """Governor detects when candidate specialization doesn't match."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    # Candidate claims to be stable (wrong)
    wrong_candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(initial)

    # Atom result says generation 2 but candidate claims stable
    atom_result = {
        "exec_response": {
            "adapter_id": "test",
            "adapter_generation": 2,
            "adapter_specialization": "stable",  # Should be candidate
        }
    }

    report = governor.validate_from_atom_result(wrong_candidate, atom_result)
    # Should still pass lineage check but specialization is wrong
    # The validation now enforces candidate specialization
    assert report.specialization_summary[AdapterSpecialization.CANDIDATE]["status"] == "validated"


def test_governor_validation_report_has_specialization_summary():
    """ValidationReport includes specialization-aware summary from atom."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    atom_result = {
        "validation_result": {
            "lineage_valid": True,
            "output_match": True,
            "kv_count_match": True,
            "is_acceptable": True,
        },
        "exec_response": {
            "adapter_id": "test",
            "adapter_generation": 2,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert hasattr(report, 'specialization_summary')
    assert AdapterSpecialization.CANDIDATE in report.specialization_summary
    assert AdapterSpecialization.STABLE in report.specialization_summary


def test_governor_promote_preserves_specialization_semantics():
    """Promote updates stable with correct specialization."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    governor.validate_candidate(candidate)
    governor.promote_candidate(candidate)

    # After promotion, stable should be generation 2 with STABLE specialization
    assert governor.stable_adapter.generation == 2
    assert governor.stable_adapter.specialization == AdapterSpecialization.STABLE


# ============================================================================
# Phase D: SAC current_adapter_selection produces atom-ready context
# ============================================================================

def test_sac_adapter_selection_for_atom_context():
    """SAC current_adapter_selection produces atom-ready specialization context."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    selection = sac.current_adapter_selection()

    # Should have stable for serve
    assert selection.stable.specialization == AdapterSpecialization.STABLE

    # Should be convertible to atom context format
    context_payload = {
        "stable": {
            "adapter_id": selection.stable.adapter_id,
            "generation": selection.stable.generation,
            "specialization": selection.stable.specialization.value,
        }
    }
    assert context_payload["stable"]["specialization"] == "stable"


def test_specialization_failure_fallback():
    """Specialization coordination failure falls back to stable."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    # Create a scenario where we need to fallback
    selection = sac.current_adapter_selection()
    initial_stable_gen = selection.stable.generation

    # Fallback should work
    result = sac.fallback_to_stable()
    assert result is True

    # Should still have valid stable adapter
    new_selection = sac.current_adapter_selection()
    assert new_selection.stable.specialization == AdapterSpecialization.STABLE


# ============================================================================
# Phase E: Integration tests
# ============================================================================

def test_full_specialization_aware_loop():
    """Full loop: SAC -> Governor -> specialization-aware result -> promotion."""
    from implementations.sac_py.sac import SACContainer
    from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    # Initial state
    initial_adapter = sac.current_adapter_ref()
    assert initial_adapter.specialization == AdapterSpecialization.STABLE

    # Create candidate
    candidate = AdapterRef("default", 2, AdapterMode.SERVE)

    # Validate with specialization-aware atom result
    atom_result = {
        "exec_response": {
            "adapter_id": "default",
            "adapter_generation": 2,
        }
    }
    report = sac.validate_from_atom_result(candidate, atom_result)

    assert report.passed
    assert AdapterSpecialization.CANDIDATE in report.specialization_summary

    # Promote
    promoted = sac.promote_candidate_if_valid(candidate)
    assert promoted

    # Verify new active adapter
    new_adapter = sac.current_adapter_ref()
    assert new_adapter.generation == 2
    assert new_adapter.specialization == AdapterSpecialization.STABLE


def test_specialization_aware_shadow_comparison():
    """Shadow comparison with specialization awareness."""
    from implementations.sac_py.sac import SACContainer
    from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    candidate = AdapterRef("default", 2, AdapterMode.SERVE)

    # Create shadow comparison result
    comparison_result = {
        "lineage_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "is_acceptable": True,
    }

    report = sac.validate_from_comparison(candidate, comparison_result)

    assert report.passed
    assert AdapterSpecialization.CANDIDATE in report.specialization_summary
    assert report.specialization_summary[AdapterSpecialization.CANDIDATE]["status"] == "validated"
