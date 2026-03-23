"""Test bounded deliberation layer."""

import pytest
from implementations.sac_py.chronara_nexus import (
    BoundedDeliberation,
    DeliberationRequest,
    Planner,
    Critic,
    Verifier,
    Synthesizer,
)


def test_planner_numeric_observation():
    """Planner proposes interpretation for numeric observation."""
    observation = {"data": 0.8}
    proposal = Planner.propose(observation)

    assert proposal["interpretation"] == "numeric_observation"
    assert proposal["value"] == 0.8
    assert proposal["magnitude"] == 0.8
    assert proposal["sign"] == "positive"


def test_critic_reviews_high_quality():
    """Critic reviews high quality proposal."""
    proposal = {"interpretation": "numeric_observation", "magnitude": 0.9}
    observation = {"data": 0.9}
    review = Critic.review(proposal, observation)

    assert review["quality"] == "high"
    assert review["confidence"] == 0.9
    assert len(review["issues"]) == 0


def test_critic_reviews_low_quality():
    """Critic reviews low quality proposal."""
    proposal = {"interpretation": "numeric_observation", "magnitude": 0.2}
    observation = {"data": 0.2}
    review = Critic.review(proposal, observation)

    assert review["quality"] == "low"
    assert "low_magnitude" in review["issues"]


def test_verifier_accepts_high_quality():
    """Phase 8: Verifier produces CANDIDATE_READY for high quality proposal."""
    from implementations.sac_py.chronara_nexus import DeliberationOutcome

    proposal = {"interpretation": "numeric_observation"}
    review = {"quality": "high", "confidence": 0.8, "issues": []}
    observation = {"data": 0.8}

    judgement = Verifier.verify(proposal, review, observation)

    assert judgement["outcome"] == DeliberationOutcome.CANDIDATE_READY
    assert judgement["accepted"] is True
    # With confidence > 0.6 and no issues, reason is "high_quality_candidate"
    assert judgement["reason"] == "high_quality_candidate"
    assert judgement["quality_score"] > 0.5


def test_verifier_rejects_low_quality():
    """Phase 8: Verifier produces REJECT for low quality proposal."""
    from implementations.sac_py.chronara_nexus import DeliberationOutcome

    proposal = {"interpretation": "numeric_observation"}
    review = {"quality": "low", "confidence": 0.2, "issues": ["low_magnitude"]}
    observation = {"data": 0.2}

    judgement = Verifier.verify(proposal, review, observation)

    assert judgement["outcome"] == DeliberationOutcome.REJECT
    assert judgement["accepted"] is False
    assert judgement["reason"] == "quality_failed"


def test_verifier_strategy_only_outcome():
    """Phase 8: Verifier produces STRATEGY_ONLY for strategy signals."""
    from implementations.sac_py.chronara_nexus import DeliberationOutcome

    proposal = {"interpretation": "strategy_signal"}
    review = {"quality": "high", "confidence": 0.5, "issues": []}
    observation = {"strategy_signal": True}

    judgement = Verifier.verify(proposal, review, observation)

    assert judgement["outcome"] == DeliberationOutcome.STRATEGY_ONLY
    assert judgement["accepted"] is True


def test_deliberation_result_structured_outcome():
    """Phase 8: DeliberationResult has structured outcome field."""
    from implementations.sac_py.chronara_nexus import DeliberationOutcome

    deliberation = BoundedDeliberation()
    request = DeliberationRequest(observation={"data": 0.9})  # High quality numeric

    result = deliberation.deliberate(request)

    assert hasattr(result, "outcome")
    assert result.outcome == DeliberationOutcome.CANDIDATE_READY
    assert result.is_candidate_ready is True
    assert result.is_strategy_only is False
    assert result.quality_score > 0.5
    assert result.confidence > 0.5


def test_deliberation_result_to_trace_dict():
    """Phase 8: DeliberationResult can produce trace-compatible dict."""
    from implementations.sac_py.chronara_nexus import DeliberationOutcome

    deliberation = BoundedDeliberation()
    request = DeliberationRequest(observation={"data": 0.9})

    result = deliberation.deliberate(request)
    trace = result.to_trace_dict()

    assert trace["outcome"] == DeliberationOutcome.CANDIDATE_READY.value
    assert "quality_score" in trace
    assert "confidence" in trace
    assert "rounds_used" in trace
    assert "interpretation" in trace
