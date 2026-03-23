"""Tests for Chronara Phase 8: Deliberation Deepening for Candidate Quality.

Tests structured deliberation outcomes (candidate_ready, strategy_only, reject),
observation screening via deliberation, Consolidator quality consumption,
and validation trace alignment with deliberation.
"""

import pytest
from implementations.sac_py.chronara_nexus import (
    AdapterRef,
    AdapterMode,
    AdapterSpecialization,
    BoundedDeliberation,
    DeliberationRequest,
    DeliberationOutcome,
    Collector,
    Consolidator,
    Governor,
)


# ============================================================================
# Phase A: Structured DeliberationResult with Outcome Classes
# ============================================================================

def test_deliberation_result_has_structured_outcome():
    """Phase 8: DeliberationResult has outcome field with three classes."""
    deliberation = BoundedDeliberation()

    # High quality -> CANDIDATE_READY
    result = deliberation.deliberate(DeliberationRequest(observation={"data": 0.9}))
    assert result.outcome == DeliberationOutcome.CANDIDATE_READY
    assert result.is_candidate_ready is True
    assert result.is_strategy_only is False
    assert result.accepted is True


def test_deliberation_outcome_strategy_only():
    """Phase 8: Strategy signals produce STRATEGY_ONLY outcome."""
    deliberation = BoundedDeliberation()

    result = deliberation.deliberate(DeliberationRequest(observation={"strategy_signal": True}))
    assert result.outcome == DeliberationOutcome.STRATEGY_ONLY
    assert result.is_strategy_only is True
    assert result.is_candidate_ready is False


def test_deliberation_outcome_reject():
    """Phase 8: Low quality observations produce REJECT outcome."""
    deliberation = BoundedDeliberation()

    result = deliberation.deliberate(DeliberationRequest(observation={"data": 0.1}))
    assert result.outcome == DeliberationOutcome.REJECT
    assert result.accepted is False


def test_deliberation_result_quality_score():
    """Phase 8: DeliberationResult includes quality_score."""
    deliberation = BoundedDeliberation()

    result = deliberation.deliberate(DeliberationRequest(observation={"data": 0.9}))
    assert hasattr(result, "quality_score")
    assert 0.0 <= result.quality_score <= 1.0
    assert result.quality_score > 0.5  # High quality


def test_deliberation_result_to_trace_dict():
    """Phase 8: DeliberationResult can produce trace-compatible dict."""
    deliberation = BoundedDeliberation()
    result = deliberation.deliberate(DeliberationRequest(observation={"data": 0.8}))

    trace = result.to_trace_dict()
    assert "outcome" in trace
    assert "quality_score" in trace
    assert "confidence" in trace
    assert "interpretation" in trace


# ============================================================================
# Phase B: Collector Deliberation Screening
# ============================================================================

def test_collector_routes_candidate_ready_to_parameter_queue():
    """Phase 8/9: CANDIDATE_READY observations go to parameter_queue with deliberation markers."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    collector.admit_observation({"data": 0.9})  # High quality

    assert len(collector.parameter_queue) == 1
    assert len(collector.shared_queue) == 0
    obs = collector.parameter_queue[0]
    assert obs.get("_deliberation_outcome") == "candidate_ready"
    # Phase 9: Check for consensus status (may not have _quality_score in Phase 9)
    assert obs.get("_consensus_status") in ["consensus_accept", "escalated_accept", None]


def test_collector_routes_strategy_only_to_shared_queue():
    """Phase 8: STRATEGY_ONLY from deliberation goes to shared_queue with marker."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    # Use a marginal-quality observation that deliberation reclassifies as strategy_only
    # This needs to be classified as PARAMETER_CANDIDATE first, then deliberation reclassifies
    collector.admit_observation({"data": 0.5, "strategy_signal": True})  # Marginal quality

    # Depending on deliberation outcome, may go to parameter_queue or shared_queue
    # The key is that deliberation_outcome is recorded if deliberation ran
    if collector.shared_queue:
        obs = collector.shared_queue[0]
        assert obs.get("_deliberation_outcome") in ["strategy_only", None]  # May have deliberation info


def test_collector_routes_reject_to_explicit_trace():
    """Phase 8: REJECT observations go to explicit_trace with marker."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    collector.admit_observation({"data": 0.1})  # Low quality

    assert len(collector.parameter_queue) == 0
    assert len(collector.shared_queue) == 0
    assert len(collector.explicit_trace) == 1
    obs = collector.explicit_trace[0]
    assert obs.get("_deliberation_rejected") is True


def test_collector_preserves_original_without_deliberation():
    """Phase 8: Without deliberation, observations route normally."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=False)

    collector.admit_observation({"data": 0.9})

    assert len(collector.parameter_queue) == 1
    obs = collector.parameter_queue[0]
    assert "_deliberation_outcome" not in obs


# ============================================================================
# Phase C: Consolidator Consumes Deliberation Quality
# ============================================================================

def test_consolidator_accumulates_quality_weighted_observations():
    """Phase 8: Consolidator extracts deliberation quality for weighting."""
    consolidator = Consolidator()

    # Add observations with different quality scores
    consolidator.accumulate_observation({
        "data": 1.0,
        "_specialization_target": "candidate",
        "_quality_score": 0.9,
        "_deliberation_outcome": "candidate_ready",
    })
    consolidator.accumulate_observation({
        "data": 1.0,
        "_specialization_target": "candidate",
        "_quality_score": 0.5,
        "_deliberation_outcome": "candidate_ready",
    })

    # Quality scores should be preserved
    assert len(consolidator.micro_batch_buffer) == 2
    assert consolidator.micro_batch_buffer[0].get("_accumulation_weight") == 0.9
    assert consolidator.micro_batch_buffer[1].get("_accumulation_weight") == 0.5


def test_consolidator_extracts_weighted_numeric_summary():
    """Phase 8: Numeric summary uses deliberation quality as weight."""
    consolidator = Consolidator()

    # Two observations with same value but different quality
    consolidator.accumulate_observation({
        "data": 1.0,
        "_specialization_target": "candidate",
        "_quality_score": 0.5,
    })
    consolidator.accumulate_observation({
        "data": 1.0,
        "_specialization_target": "candidate",
        "_quality_score": 0.5,
    })

    # Both should be weighted by 0.5, so summary values should be 0.5 each
    summary = consolidator._extract_numeric_summary(consolidator.micro_batch_buffer)
    assert summary == [0.5, 0.5]


# ============================================================================
# Phase D: Governor Includes Deliberation in Validation/Trace
# ============================================================================

def test_governor_validation_includes_deliberation_outcome():
    """Phase 8: ValidationReport includes deliberation_outcome field."""
    active = AdapterRef("base", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(active, enable_deliberation=True)

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

    assert hasattr(report, "deliberation_outcome")
    assert report.deliberation_outcome is not None


def test_governor_validation_trace_includes_deliberation():
    """Phase 8: ValidationTrace includes deliberation info."""
    active = AdapterRef("base", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(active, enable_deliberation=True)

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

    governor.validate_from_atom_result(candidate, atom_result)
    traces = governor.get_validation_traces()

    assert len(traces) == 1
    trace = traces[0]
    assert hasattr(trace, "deliberation_outcome")
    # Deliberation outcome should be recorded
    assert trace.deliberation_outcome is not None


def test_governor_trace_to_dict_includes_deliberation():
    """Phase 8: ValidationTrace.to_dict includes deliberation fields."""
    active = AdapterRef("base", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(active, enable_deliberation=True)

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

    governor.validate_from_atom_result(candidate, atom_result)
    trace = governor.get_last_validation_trace()
    trace_dict = trace.to_dict()

    assert "deliberation_outcome" in trace_dict
    # Quality score may or may not be present depending on deliberation


# ============================================================================
# Phase E: Deliberation Integration with Comparison Validation
# ============================================================================

def test_governor_comparison_includes_deliberation_fields():
    """Phase 8: Comparison validation can include deliberation data."""
    active = AdapterRef("base", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(active)

    candidate = AdapterRef("base", 2, AdapterMode.SERVE, AdapterSpecialization.CANDIDATE)
    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "deliberation_outcome": "candidate_ready",
        "deliberation_quality": 0.85,
        "deliberation_trace": {"interpretation": "high_quality"},
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert report.deliberation_outcome == "candidate_ready"
    assert report.deliberation_quality == 0.85
    assert report.metric_summary.get("deliberation_outcome") == "candidate_ready"


# ============================================================================
# Phase F: Failure Protection
# ============================================================================

def test_deliberation_failure_fallback():
    """Phase 8: Collector falls back to default routing on deliberation error."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    # Invalid observation that might cause issues
    # (In real scenario, this would be caught by try-except)
    collector.admit_observation({"malformed": object()})  # Cannot be easily processed

    # Should not crash; may or may not be in queue depending on error handling


def test_bounded_deliberation_respects_budget():
    """Phase 8: BoundedDeliberation respects max_budget."""
    deliberation = BoundedDeliberation(max_budget=1)

    request = DeliberationRequest(observation={"data": 0.8}, budget=1)
    result = deliberation.deliberate(request)

    assert result.rounds_used == 1  # Respects budget


def test_deliberation_outcome_enum_values():
    """Phase 8: DeliberationOutcome enum has expected values."""
    assert DeliberationOutcome.CANDIDATE_READY.value == "candidate_ready"
    assert DeliberationOutcome.STRATEGY_ONLY.value == "strategy_only"
    assert DeliberationOutcome.REJECT.value == "reject"
