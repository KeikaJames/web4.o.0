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
    """Verifier accepts high quality proposal."""
    proposal = {"interpretation": "numeric_observation"}
    review = {"quality": "high", "confidence": 0.8, "issues": []}
    observation = {"data": 0.8}

    judgement = Verifier.verify(proposal, review, observation)

    assert judgement["accepted"] is True
    assert judgement["reason"] == "quality_passed"


def test_verifier_rejects_low_quality():
    """Verifier rejects low quality proposal."""
    proposal = {"interpretation": "numeric_observation"}
    review = {"quality": "low", "confidence": 0.2, "issues": ["low_magnitude"]}
    observation = {"data": 0.2}

    judgement = Verifier.verify(proposal, review, observation)

    assert judgement["accepted"] is False
    assert judgement["reason"] == "quality_failed"
