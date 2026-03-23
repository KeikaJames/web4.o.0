"""Bounded deliberation layer for observation and validation quality enhancement."""

from typing import Dict, Any, Optional, List
from dataclasses import dataclass


@dataclass
class DeliberationRequest:
    """Input to bounded deliberation."""
    observation: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    budget: int = 1  # Max rounds


@dataclass
class DeliberationResult:
    """Output from bounded deliberation."""
    original_observation: Dict[str, Any]
    planner_proposal: Dict[str, Any]
    critic_review: Dict[str, Any]
    verifier_judgement: Dict[str, Any]
    synthesized_output: Dict[str, Any]
    accepted: bool
    rounds_used: int


class Planner:
    """Proposes initial interpretation of observation."""

    @staticmethod
    def propose(observation: Dict[str, Any]) -> Dict[str, Any]:
        """Generate proposal from observation."""
        validation_result = None
        if isinstance(observation.get("validation_result"), dict):
            validation_result = observation["validation_result"]
        elif isinstance(observation.get("atom_result"), dict):
            nested = observation["atom_result"].get("validation_result")
            if isinstance(nested, dict):
                validation_result = nested

        if validation_result is not None:
            lineage_valid = bool(validation_result.get("lineage_valid", False))
            output_match = bool(validation_result.get("output_match", False))
            kv_count_match = bool(validation_result.get("kv_count_match", False))
            confidence = sum((lineage_valid, output_match, kv_count_match)) / 3.0
            return {
                "interpretation": "atom_validation_result",
                "lineage_valid": lineage_valid,
                "output_match": output_match,
                "kv_count_match": kv_count_match,
                "confidence": confidence,
            }

        # Extract numeric features
        if isinstance(observation.get("data"), (int, float)):
            value = float(observation["data"])
            return {
                "interpretation": "numeric_observation",
                "value": value,
                "magnitude": abs(value),
                "sign": "positive" if value >= 0 else "negative",
            }
        elif "explicit_feedback" in observation:
            return {
                "interpretation": "explicit_feedback",
                "signal_strength": 1.0,
            }
        elif "strategy_signal" in observation:
            return {
                "interpretation": "strategy_signal",
                "signal_strength": 0.5,
            }
        else:
            return {
                "interpretation": "unknown",
                "signal_strength": 0.0,
            }


class Critic:
    """Reviews planner proposal for quality."""

    @staticmethod
    def review(proposal: Dict[str, Any], observation: Dict[str, Any]) -> Dict[str, Any]:
        """Review proposal quality."""
        interpretation = proposal.get("interpretation", "unknown")

        if interpretation == "atom_validation_result":
            issues = []
            if not proposal.get("lineage_valid", False):
                issues.append("lineage_invalid")
            if not proposal.get("output_match", False):
                issues.append("output_mismatch")
            if not proposal.get("kv_count_match", False):
                issues.append("kv_mismatch")
            quality = "high" if not issues else "low"
            return {
                "quality": quality,
                "confidence": proposal.get("confidence", 0.0),
                "issues": issues,
            }
        if interpretation == "numeric_observation":
            magnitude = proposal.get("magnitude", 0.0)
            quality = "high" if magnitude > 0.5 else "low"
            return {
                "quality": quality,
                "confidence": magnitude,
                "issues": [] if quality == "high" else ["low_magnitude"],
            }
        elif interpretation in ("explicit_feedback", "strategy_signal"):
            return {
                "quality": "high",
                "confidence": proposal.get("signal_strength", 0.0),
                "issues": [],
            }
        else:
            return {
                "quality": "low",
                "confidence": 0.0,
                "issues": ["unknown_interpretation"],
            }


class Verifier:
    """Verifies consistency and makes accept/reject decision."""

    @staticmethod
    def verify(
        proposal: Dict[str, Any],
        review: Dict[str, Any],
        observation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Verify and decide acceptance."""
        quality = review.get("quality", "low")
        confidence = review.get("confidence", 0.0)
        issues = review.get("issues", [])

        # Accept if high quality and no issues
        accepted = quality == "high" and len(issues) == 0 and confidence > 0.3

        return {
            "accepted": accepted,
            "confidence": confidence,
            "reason": "quality_passed" if accepted else "quality_failed",
        }


class Synthesizer:
    """Synthesizes final output from deliberation."""

    @staticmethod
    def synthesize(
        observation: Dict[str, Any],
        proposal: Dict[str, Any],
        review: Dict[str, Any],
        judgement: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Synthesize final deliberation output."""
        if judgement.get("accepted", False):
            # Enhanced observation
            return {
                **observation,
                "deliberation_enhanced": True,
                "quality_score": review.get("confidence", 0.0),
                "interpretation": proposal.get("interpretation", "unknown"),
            }
        else:
            # Return original with rejection marker
            return {
                **observation,
                "deliberation_rejected": True,
                "reason": judgement.get("reason", "unknown"),
            }


class BoundedDeliberation:
    """Bounded deliberation coordinator."""

    def __init__(self):
        self.planner = Planner()
        self.critic = Critic()
        self.verifier = Verifier()
        self.synthesizer = Synthesizer()

    def deliberate(self, request: DeliberationRequest) -> DeliberationResult:
        """Execute bounded deliberation (max 1 round)."""
        observation = request.observation

        # Round 1: Planner
        proposal = self.planner.propose(observation)

        # Round 1: Critic
        review = self.critic.review(proposal, observation)

        # Round 1: Verifier
        judgement = self.verifier.verify(proposal, review, observation)

        # Round 1: Synthesizer
        synthesized = self.synthesizer.synthesize(observation, proposal, review, judgement)

        return DeliberationResult(
            original_observation=observation,
            planner_proposal=proposal,
            critic_review=review,
            verifier_judgement=judgement,
            synthesized_output=synthesized,
            accepted=judgement.get("accepted", False),
            rounds_used=1,
        )
