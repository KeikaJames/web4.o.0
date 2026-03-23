"""Tests for Chronara Phase 7: Shadow Comparison & Promote Gate Deepening.

Tests deeper shadow comparison with structured ComparisonResult,
promote gate based on comparison status/recommendation, and
validation trace completeness.
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
# Phase A: Comparison Result Object
# ============================================================================

def test_governor_consumes_structured_comparison():
    """Governor consumes structured comparison result with Phase 7 fields."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    # Phase 7 structured comparison result
    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "is_acceptable": True,
        "active_summary": {
            "adapter_id": "test",
            "generation": 1,
            "specialization": "stable",
        },
        "candidate_summary": {
            "adapter_id": "test",
            "generation": 2,
            "specialization": "candidate",
        },
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert report.passed
    assert report.metric_summary["status"] == "candidate_observed"
    assert report.metric_summary["promote_recommendation"] == "approve"
    assert report.metric_summary["specialization_valid"] is True


def test_governor_rejects_lineage_mismatch():
    """Governor rejects candidate on lineage mismatch."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    comparison_result = {
        "status": "lineage_mismatch",
        "promote_recommendation": "reject",
        "lineage_valid": False,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "active_summary": {
            "adapter_id": "test",
            "generation": 1,
            "specialization": "stable",
        },
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert not report.passed
    assert "lineage" in report.reason.lower() or report.metric_summary["status"] == "lineage_mismatch"


def test_governor_rejects_specialization_mismatch():
    """Governor rejects candidate on specialization mismatch."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    comparison_result = {
        "status": "specialization_mismatch",
        "promote_recommendation": "reject",
        "lineage_valid": True,
        "specialization_valid": False,  # Specialization check failed
        "output_match": True,
        "kv_count_match": True,
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert not report.passed
    assert report.metric_summary["specialization_valid"] is False


def test_governor_undecided_when_no_clear_recommendation():
    """Governor marks undecided when promote_recommendation is not approve."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "undecided",  # Not approve
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": False,  # Output doesn't match
        "kv_count_match": True,
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    # Should not pass because promote_recommendation != approve
    assert not report.passed
    assert report.metric_summary["promote_recommendation"] == "undecided"


# ============================================================================
# Phase D: Validation Trace
# ============================================================================

def test_governor_records_validation_trace():
    """Governor records validation trace with full identity info."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
    }

    governor.validate_from_comparison(candidate, comparison_result)

    traces = governor.get_validation_traces()
    assert len(traces) == 1

    trace = traces[0]
    assert trace.active_id == "test"
    assert trace.active_generation == 1
    assert trace.active_specialization == AdapterSpecialization.STABLE
    assert trace.candidate_id == "test"
    assert trace.candidate_generation == 2
    assert trace.candidate_specialization == AdapterSpecialization.CANDIDATE
    assert trace.status == "candidate_observed"
    assert trace.passed is True


def test_governor_trace_on_failure():
    """Governor records trace even on validation failure."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    comparison_result = {
        "status": "lineage_mismatch",
        "promote_recommendation": "reject",
        "lineage_valid": False,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
    }

    governor.validate_from_comparison(candidate, comparison_result)

    trace = governor.get_last_validation_trace()
    assert trace is not None
    assert trace.passed is False
    assert trace.reason is not None


def test_governor_clear_validation_traces():
    """Governor can clear validation traces."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
    }

    governor.validate_from_comparison(candidate, comparison_result)
    assert len(governor.get_validation_traces()) == 1

    governor.clear_validation_traces()
    assert len(governor.get_validation_traces()) == 0


# ============================================================================
# Phase C: Promote Gate Deepening
# ============================================================================

def test_governor_can_promote_based_on_comparison():
    """Governor can check if comparison permits promotion."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(initial)

    # Approve case
    can_promote = governor.can_promote_based_on_comparison({
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "status": "candidate_observed",
        "candidate_summary": {"adapter_id": "test", "generation": 2},
    })
    assert can_promote is True

    # Reject case
    can_promote = governor.can_promote_based_on_comparison({
        "promote_recommendation": "reject",
        "lineage_valid": True,
        "specialization_valid": True,
        "status": "candidate_observed",
    })
    assert can_promote is False

    # Missing lineage_valid
    can_promote = governor.can_promote_based_on_comparison({
        "promote_recommendation": "approve",
        "lineage_valid": False,
        "specialization_valid": True,
        "status": "candidate_observed",
        "candidate_summary": {"adapter_id": "test", "generation": 2},
    })
    assert can_promote is False


def test_promote_gate_requires_all_checks():
    """Promote gate requires all Phase 7 checks to pass."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    # Valid comparison
    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "active_summary": {
            "adapter_id": "test",
            "generation": 1,
            "specialization": "stable",
        },
        "candidate_summary": {
            "adapter_id": "test",
            "generation": 2,
            "specialization": "candidate",
        },
    }

    report = governor.validate_from_comparison(candidate, comparison_result)
    assert report.passed

    # Should be able to promote
    promoted = governor.promote_candidate(candidate)
    assert promoted
    assert governor.active_adapter.generation == 2
    assert governor.active_adapter.specialization == AdapterSpecialization.STABLE


# ============================================================================
# Phase E: Failure Protection
# ============================================================================

def test_comparison_unavailable_safe_fallback():
    """Governor safely handles unavailable comparison."""
    initial = AdapterRef("test", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    candidate = AdapterRef("test", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    governor = Governor(initial)

    comparison_result = {
        "status": "unavailable",
        "promote_recommendation": "failed",
        "lineage_valid": False,
        "specialization_valid": False,
        "output_match": False,
        "kv_count_match": False,
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    # Should fail validation
    assert not report.passed
    # Should not crash
    assert report.reason is not None

    # Fallback should still work (using rollback_to_stable)
    governor.rollback_to_stable()
    assert governor.active_adapter.generation == 1


def test_fallback_preserves_stable_after_failed_promote():
    """Fallback works after failed promotion attempt."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/test-mem")
    sac.init_chronara()

    # Try to validate with failing comparison
    candidate = AdapterRef("default", 2, AdapterMode.SERVE)
    comparison_result = {
        "status": "lineage_mismatch",
        "promote_recommendation": "reject",
        "lineage_valid": False,
    }

    report = sac.validate_from_comparison(candidate, comparison_result)
    assert not report.passed

    # Fallback should restore stable
    sac.fallback_to_stable()
    assert sac.current_adapter_ref().specialization == AdapterSpecialization.STABLE
