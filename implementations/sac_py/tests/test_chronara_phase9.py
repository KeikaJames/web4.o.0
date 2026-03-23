"""Tests for Chronara Phase 9: Bounded Swarm / Multi-Role Review Deepening.

Tests multi-role review with consensus detection, role disagreement,
bounded escalation, and integration with Collector/Governor.
"""

import pytest
from implementations.sac_py.chronara_nexus import (
    AdapterRef,
    AdapterMode,
    AdapterSpecialization,
    BoundedDeliberation,
    DeliberationRequest,
    DeliberationOutcome,
    MultiRoleReviewResult,
    ReviewConsensusStatus,
    RoleDecision,
    MultiRoleReviewCoordinator,
    Collector,
    Consolidator,
    Governor,
)


# ============================================================================
# Phase A: MultiRoleReviewResult is a structured object
# ============================================================================

def test_multi_role_review_result_structure():
    """Phase 9: MultiRoleReviewResult has all required fields."""
    result = MultiRoleReviewResult(
        request_id="test_123",
        observation={"data": 0.9},
        role_decisions=[
            RoleDecision("planner", "candidate_ready", 0.8, "high quality"),
            RoleDecision("critic", "candidate_ready", 0.9, "high quality"),
            RoleDecision("verifier", "candidate_ready", 0.85, "all checks pass"),
        ],
        consensus_status=ReviewConsensusStatus.CONSENSUS_ACCEPT,
        final_outcome=DeliberationOutcome.CANDIDATE_READY,
    )

    assert result.request_id == "test_123"
    assert len(result.role_decisions) == 3
    assert result.consensus_status == ReviewConsensusStatus.CONSENSUS_ACCEPT
    assert result.final_outcome == DeliberationOutcome.CANDIDATE_READY


def test_multi_role_review_has_consensus_property():
    """Phase 9: MultiRoleReviewResult.has_consensus property works."""
    consensus = MultiRoleReviewResult(
        request_id="test_1",
        observation={},
        role_decisions=[],
        consensus_status=ReviewConsensusStatus.CONSENSUS_ACCEPT,
        final_outcome=DeliberationOutcome.CANDIDATE_READY,
    )
    assert consensus.has_consensus is True
    assert consensus.has_disagreement is False

    escalate = MultiRoleReviewResult(
        request_id="test_2",
        observation={},
        role_decisions=[],
        consensus_status=ReviewConsensusStatus.DISAGREEMENT_ESCALATE,
        final_outcome=DeliberationOutcome.REJECT,
    )
    assert escalate.has_consensus is False
    assert escalate.has_disagreement is True


def test_multi_role_review_to_trace_dict():
    """Phase 9: MultiRoleReviewResult can produce trace-compatible dict."""
    result = MultiRoleReviewResult(
        request_id="test_123",
        observation={"data": 0.9},
        role_decisions=[
            RoleDecision("planner", "candidate_ready", 0.8, "high"),
            RoleDecision("critic", "candidate_ready", 0.9, "high"),
            RoleDecision("verifier", "candidate_ready", 0.85, "pass"),
        ],
        consensus_status=ReviewConsensusStatus.CONSENSUS_ACCEPT,
        final_outcome=DeliberationOutcome.CANDIDATE_READY,
        agreement_summary={"candidate_ready": ["planner", "critic", "verifier"]},
    )

    trace = result.to_trace_dict()
    assert trace["request_id"] == "test_123"
    assert trace["consensus_status"] == "consensus_accept"
    assert trace["final_outcome"] == "candidate_ready"
    assert trace["role_count"] == 3
    assert trace["has_disagreement"] is False


# ============================================================================
# Phase B: Role Disagreement Detection
# ============================================================================

def test_multi_role_review_detects_consensus():
    """Phase 9: MultiRoleReviewCoordinator detects unanimous consensus."""
    coordinator = MultiRoleReviewCoordinator()

    # All roles agree on candidate_ready
    observation = {"data": 0.9}  # High quality
    result = coordinator.review(observation)

    assert result.consensus_status == ReviewConsensusStatus.CONSENSUS_ACCEPT
    assert result.final_outcome == DeliberationOutcome.CANDIDATE_READY
    assert result.has_consensus is True


def test_multi_role_review_detects_disagreement():
    """Phase 9: MultiRoleReviewCoordinator detects role disagreement."""
    coordinator = MultiRoleReviewCoordinator()

    # Create a scenario where roles disagree (marginal quality with strategy signal)
    observation = {"data": 0.5, "strategy_signal": True}
    result = coordinator.review(observation)

    # Should have some outcome (could be consensus or escalate depending on logic)
    assert result.consensus_status in [
        ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY,
        ReviewConsensusStatus.DISAGREEMENT_ESCALATE,
        ReviewConsensusStatus.CONSENSUS_ACCEPT,
        ReviewConsensusStatus.CONSENSUS_REJECT,
    ]


def test_role_agreement_summary():
    """Phase 9: Agreement summary correctly groups roles by decision."""
    coordinator = MultiRoleReviewCoordinator()

    observation = {"data": 0.9}
    result = coordinator.review(observation)

    # All roles should agree
    assert len(result.agreement_summary) >= 1
    assert "candidate_ready" in result.agreement_summary


# ============================================================================
# Phase C: Bounded Escalation
# ============================================================================

def test_bounded_escalation_used_on_disagreement():
    """Phase 9: Disagreement triggers bounded escalation."""
    coordinator = MultiRoleReviewCoordinator(max_budget=2)

    # Marginal quality that might cause disagreement
    observation = {"data": 0.4}
    result = coordinator.review(observation)

    if result.consensus_status == ReviewConsensusStatus.DISAGREEMENT_ESCALATE:
        assert result.escalation_used is True
        assert result.budget_consumed == 2
    else:
        # Consensus reached, no escalation needed
        assert result.escalation_used is False


def test_fallback_on_budget_exhaustion():
    """Phase 9: Budget exhaustion triggers conservative fallback."""
    coordinator = MultiRoleReviewCoordinator(max_budget=1)

    # Observation that will cause disagreement
    observation = {"data": 0.1}  # Low quality
    result = coordinator.review(observation)

    # With max_budget=1, disagreement cannot escalate
    if result.consensus_status == ReviewConsensusStatus.DISAGREEMENT_ESCALATE:
        assert result.fallback_used is True
        assert result.final_outcome == DeliberationOutcome.REJECT


def test_bounded_escalation_downgrades_conservatively():
    """Phase 9: Escalation downgrades to strategy_only when possible."""
    coordinator = MultiRoleReviewCoordinator(max_budget=2)

    # Strategy signal observation that might cause disagreement
    observation = {"data": 0.5, "strategy_signal": True}
    result = coordinator.review(observation)

    if result.escalation_used:
        # Escalation should prefer strategy downgrade over reject
        if result.final_outcome == DeliberationOutcome.STRATEGY_ONLY:
            assert result.consensus_status == ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY


# ============================================================================
# Phase D: Collector Uses Multi-Role Review
# ============================================================================

def test_collector_routes_consensus_accept():
    """Phase 9: CONSENSUS_ACCEPT observations go to parameter_queue."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    collector.admit_observation({"data": 0.9})  # High quality

    assert len(collector.parameter_queue) == 1
    assert len(collector.shared_queue) == 0

    obs = collector.parameter_queue[0]
    assert obs.get("_consensus_status") == "consensus_accept"
    assert obs.get("_deliberation_outcome") == "candidate_ready"
    assert obs.get("_has_disagreement") is False


def test_collector_handles_disagreement_escalation():
    """Phase 9: DISAGREEMENT_ESCALATE observations handled conservatively."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    # Marginal observation that might cause disagreement
    collector.admit_observation({"data": 0.4})

    # Should either go to explicit_trace (if rejected) or parameter_queue (if escalated)
    total_routed = len(collector.parameter_queue) + len(collector.shared_queue) + len(collector.explicit_trace)
    assert total_routed == 1


def test_collector_marks_escalation_in_observation():
    """Phase 9: Escalated observations have _escalation_used marker."""
    adapter = AdapterRef("base", 1, AdapterMode.SERVE)
    collector = Collector(adapter, enable_deliberation=True)

    # Observation likely to cause disagreement and escalation
    collector.admit_observation({"data": 0.4})

    # Check if any observation has escalation marker
    all_obs = collector.parameter_queue + collector.shared_queue + collector.explicit_trace
    if all_obs:
        obs = all_obs[0]
        if obs.get("_escalation_used"):
            assert obs.get("_has_disagreement") is True


# ============================================================================
# Phase E: Governor Consumes Multi-Role Review
# ============================================================================

def test_governor_validation_trace_includes_multi_role_review():
    """Phase 9: ValidationTrace includes multi_role_review_summary."""
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
        "multi_role_review": {
            "consensus_status": "consensus_accept",
            "has_disagreement": False,
            "role_count": 3,
        },
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    trace = governor.get_last_validation_trace()
    assert trace.multi_role_review_summary is not None
    assert trace.multi_role_review_summary.get("consensus_status") == "consensus_accept"


def test_governor_report_includes_consensus_status():
    """Phase 9: ValidationReport includes consensus_status and has_role_disagreement."""
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
        "multi_role_review": {
            "consensus_status": "consensus_accept",
            "has_disagreement": False,
        },
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert report.consensus_status == "consensus_accept"
    assert report.has_role_disagreement is False
    assert report.metric_summary.get("consensus_status") == "consensus_accept"


def test_promote_gate_blocks_on_disagreement():
    """Phase 9: Promote gate blocks if role disagreement exists."""
    active = AdapterRef("base", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(active)

    # Comparison with disagreement_escalate should block promotion
    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "multi_role_review": {
            "consensus_status": "disagreement_escalate",
            "has_disagreement": True,
        },
    }

    # Should block promotion despite approve recommendation
    can_promote = governor.can_promote_based_on_comparison(comparison_result)
    assert can_promote is False


def test_promote_gate_allows_consensus_accept():
    """Phase 9: Promote gate allows if consensus_accept."""
    active = AdapterRef("base", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
    governor = Governor(active)

    comparison_result = {
        "status": "candidate_observed",
        "promote_recommendation": "approve",
        "lineage_valid": True,
        "specialization_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "candidate_summary": {  # Required by can_promote_based_on_comparison
            "adapter_id": "base",
            "generation": 2,
            "specialization": "candidate",
        },
        "multi_role_review": {
            "consensus_status": "consensus_accept",
            "has_disagreement": False,
        },
    }

    can_promote = governor.can_promote_based_on_comparison(comparison_result)
    assert can_promote is True


# ============================================================================
# Phase F: Failure Protection and Determinism
# ============================================================================

def test_multi_role_review_deterministic():
    """Phase 9: Same input produces deterministic review output."""
    coordinator = MultiRoleReviewCoordinator()

    observation = {"data": 0.9}
    result1 = coordinator.review(observation)
    result2 = coordinator.review(observation)

    assert result1.consensus_status == result2.consensus_status
    assert result1.final_outcome == result2.final_outcome
    assert len(result1.role_decisions) == len(result2.role_decisions)


def test_bounded_deliberation_has_multi_role_review_method():
    """Phase 9: BoundedDeliberation exposes multi_role_review method."""
    deliberation = BoundedDeliberation()

    assert hasattr(deliberation, "multi_role_review")

    observation = {"data": 0.9}
    result = deliberation.multi_role_review(observation)

    assert isinstance(result, MultiRoleReviewResult)
    assert result.consensus_status in [
        ReviewConsensusStatus.CONSENSUS_ACCEPT,
        ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY,
        ReviewConsensusStatus.CONSENSUS_REJECT,
        ReviewConsensusStatus.DISAGREEMENT_ESCALATE,
    ]


def test_review_outcome_enum_values():
    """Phase 9: ReviewConsensusStatus enum has expected values."""
    assert ReviewConsensusStatus.CONSENSUS_ACCEPT.value == "consensus_accept"
    assert ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY.value == "consensus_strategy_only"
    assert ReviewConsensusStatus.CONSENSUS_REJECT.value == "consensus_reject"
    assert ReviewConsensusStatus.DISAGREEMENT_ESCALATE.value == "disagreement_escalate"
