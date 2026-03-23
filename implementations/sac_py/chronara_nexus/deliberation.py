"""Bounded deliberation layer for observation and validation quality enhancement.

Phase 9: Multi-role review with bounded escalation for candidate quality deepening.
"""

from typing import Dict, Any, Optional, List, Set
from dataclasses import dataclass, field
from enum import Enum


class DeliberationOutcome(Enum):
    """Structured outcome classification from deliberation.

    - CANDIDATE_READY: Observation is high quality, ready for candidate queue
    - STRATEGY_ONLY: Observation contains strategy signal but not parameter-worthy
    - REJECT: Observation fails quality checks, do not use
    """
    CANDIDATE_READY = "candidate_ready"
    STRATEGY_ONLY = "strategy_only"
    REJECT = "reject"


class ReviewConsensusStatus(Enum):
    """Phase 9: Multi-role review consensus status.

    - CONSENSUS_ACCEPT: All roles agree on candidate_ready
    - CONSENSUS_STRATEGY_ONLY: All roles agree on strategy_only
    - CONSENSUS_REJECT: All roles agree on reject
    - DISAGREEMENT_ESCALATE: Roles disagree, requires bounded escalation
    """
    CONSENSUS_ACCEPT = "consensus_accept"
    CONSENSUS_STRATEGY_ONLY = "consensus_strategy_only"
    CONSENSUS_REJECT = "consensus_reject"
    DISAGREEMENT_ESCALATE = "disagreement_escalate"


@dataclass
class RoleDecision:
    """Phase 9: Individual role decision with reasoning."""
    role: str
    decision: str  # "candidate_ready", "strategy_only", "reject"
    confidence: float
    reasoning: str


@dataclass
class MultiRoleReviewResult:
    """Phase 9: Structured multi-role review result.

    Fields:
        - request_id: Unique identifier for this review
        - observation: Original observation reviewed
        - role_decisions: List of RoleDecision from each role
        - consensus_status: Overall consensus state
        - final_outcome: The decided outcome after review
        - agreement_summary: Dict mapping decisions to roles that made them
        - disagreement_details: If escalation occurred, details of the disagreement
        - escalation_used: Whether bounded escalation was triggered
        - fallback_used: Whether fallback path was taken
        - budget_consumed: How much of the review budget was used
        - review_trace: Detailed trace for audit/debugging
    """
    request_id: str
    observation: Dict[str, Any]
    role_decisions: List[RoleDecision]
    consensus_status: ReviewConsensusStatus
    final_outcome: DeliberationOutcome
    agreement_summary: Dict[str, List[str]] = field(default_factory=dict)
    disagreement_details: Optional[Dict[str, Any]] = None
    escalation_used: bool = False
    fallback_used: bool = False
    budget_consumed: int = 1
    review_trace: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_consensus(self) -> bool:
        """Check if all roles reached consensus."""
        return self.consensus_status != ReviewConsensusStatus.DISAGREEMENT_ESCALATE

    @property
    def has_disagreement(self) -> bool:
        """Check if roles disagreed."""
        return self.consensus_status == ReviewConsensusStatus.DISAGREEMENT_ESCALATE

    @property
    def roles_in_agreement(self) -> Set[str]:
        """Get set of roles that agree with final outcome."""
        return set(self.agreement_summary.get(self.final_outcome.value, []))

    @property
    def roles_in_disagreement(self) -> Set[str]:
        """Get set of roles that disagree with final outcome."""
        all_roles = {d.role for d in self.role_decisions}
        agreeing = self.roles_in_agreement
        return all_roles - agreeing

    def to_trace_dict(self) -> Dict[str, Any]:
        """Convert to trace-compatible dictionary."""
        return {
            "request_id": self.request_id,
            "consensus_status": self.consensus_status.value,
            "final_outcome": self.final_outcome.value,
            "role_count": len(self.role_decisions),
            "agreement_summary": self.agreement_summary,
            "has_disagreement": self.has_disagreement,
            "escalation_used": self.escalation_used,
            "fallback_used": self.fallback_used,
            "budget_consumed": self.budget_consumed,
        }


@dataclass
class DeliberationRequest:
    """Input to bounded deliberation."""
    observation: Dict[str, Any]
    context: Optional[Dict[str, Any]] = None
    budget: int = 1  # Max rounds


@dataclass
class DeliberationResult:
    """Output from bounded deliberation with Phase 8 structured outcomes.

    Fields:
        - outcome: Structured classification (candidate_ready, strategy_only, reject)
        - quality_score: 0.0-1.0 quality assessment
        - confidence: Confidence in the outcome classification
        - original_observation: Original input observation
        - planner_proposal: Initial interpretation
        - critic_review: Quality review results
        - verifier_judgement: Final verification decision
        - synthesized_output: Enhanced/rejected observation
        - rounds_used: Number of deliberation rounds executed
        - deliberation_trace: Optional trace for audit/debugging
    """
    outcome: DeliberationOutcome
    quality_score: float
    confidence: float
    original_observation: Dict[str, Any]
    planner_proposal: Dict[str, Any]
    critic_review: Dict[str, Any]
    verifier_judgement: Dict[str, Any]
    synthesized_output: Dict[str, Any]
    rounds_used: int
    deliberation_trace: Dict[str, Any] = field(default_factory=dict)

    @property
    def accepted(self) -> bool:
        """Backward compatibility: accepted if not rejected."""
        return self.outcome != DeliberationOutcome.REJECT

    @property
    def is_candidate_ready(self) -> bool:
        """Check if observation is ready for candidate queue."""
        return self.outcome == DeliberationOutcome.CANDIDATE_READY

    @property
    def is_strategy_only(self) -> bool:
        """Check if observation should be strategy-only."""
        return self.outcome == DeliberationOutcome.STRATEGY_ONLY

    def to_trace_dict(self) -> Dict[str, Any]:
        """Convert to trace-compatible dictionary."""
        return {
            "outcome": self.outcome.value,
            "quality_score": self.quality_score,
            "confidence": self.confidence,
            "rounds_used": self.rounds_used,
            "interpretation": self.planner_proposal.get("interpretation", "unknown"),
            "quality": self.critic_review.get("quality", "unknown"),
            "issues": self.critic_review.get("issues", []),
        }


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
    """Verifies consistency and makes structured outcome decision."""

    @staticmethod
    def verify(
        proposal: Dict[str, Any],
        review: Dict[str, Any],
        observation: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Verify and decide structured outcome.

        Returns dict with:
        - outcome: DeliberationOutcome value
        - confidence: 0.0-1.0 confidence score
        - quality_score: 0.0-1.0 quality assessment
        - reason: Explanation string
        """
        quality = review.get("quality", "low")
        confidence = review.get("confidence", 0.0)
        issues = review.get("issues", [])
        interpretation = proposal.get("interpretation", "unknown")

        # Calculate quality score
        issue_penalty = len(issues) * 0.2
        quality_score = max(0.0, confidence - issue_penalty)

        # Determine outcome based on quality and observation type
        if quality == "high" and len(issues) == 0 and confidence > 0.6:
            # High quality -> candidate_ready
            outcome = DeliberationOutcome.CANDIDATE_READY
            reason = "high_quality_candidate"
        elif quality == "high" and confidence > 0.4:
            # Medium-high quality with strategy signal -> strategy_only
            if interpretation in ("strategy_signal", "explicit_feedback"):
                outcome = DeliberationOutcome.STRATEGY_ONLY
                reason = "strategy_signal_qualified"
            else:
                outcome = DeliberationOutcome.CANDIDATE_READY
                reason = "qualified_candidate"
        elif confidence > 0.3 and len(issues) <= 1:
            # Marginal quality -> strategy_only if it has strategy signal
            if interpretation in ("strategy_signal", "explicit_feedback"):
                outcome = DeliberationOutcome.STRATEGY_ONLY
                reason = "marginal_strategy_signal"
            else:
                outcome = DeliberationOutcome.REJECT
                reason = "quality_below_candidate_threshold"
        else:
            # Low quality -> reject
            outcome = DeliberationOutcome.REJECT
            reason = "quality_failed"

        return {
            "outcome": outcome,
            "confidence": confidence,
            "quality_score": quality_score,
            "reason": reason,
            "accepted": outcome != DeliberationOutcome.REJECT,  # Backward compat
        }


class Synthesizer:
    """Synthesizes final output from deliberation with Phase 8 structured outcomes."""

    @staticmethod
    def synthesize(
        observation: Dict[str, Any],
        proposal: Dict[str, Any],
        review: Dict[str, Any],
        judgement: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Synthesize final deliberation output with outcome classification."""
        outcome = judgement.get("outcome", DeliberationOutcome.REJECT)
        quality_score = judgement.get("quality_score", 0.0)
        confidence = judgement.get("confidence", 0.0)

        if outcome == DeliberationOutcome.CANDIDATE_READY:
            # High quality observation - enhanced for candidate queue
            return {
                **observation,
                "deliberation_enhanced": True,
                "deliberation_outcome": outcome.value,
                "quality_score": quality_score,
                "confidence": confidence,
                "interpretation": proposal.get("interpretation", "unknown"),
            }
        elif outcome == DeliberationOutcome.STRATEGY_ONLY:
            # Strategy signal - route to shared queue
            return {
                **observation,
                "deliberation_enhanced": True,
                "deliberation_outcome": outcome.value,
                "quality_score": quality_score,
                "confidence": confidence,
                "interpretation": proposal.get("interpretation", "unknown"),
                "_strategy_signal": True,
            }
        else:
            # Rejected - mark but preserve original
            return {
                **observation,
                "deliberation_rejected": True,
                "deliberation_outcome": outcome.value,
                "quality_score": quality_score,
                "confidence": confidence,
                "reason": judgement.get("reason", "unknown"),
            }


class MultiRoleReviewCoordinator:
    """Phase 9: Coordinates multi-role review with bounded escalation.

    Runs planner, critic, verifier in parallel-like fashion,
    detects agreement/disagreement, and handles bounded escalation.
    """

    def __init__(self, max_budget: int = 2):
        self.planner = Planner()
        self.critic = Critic()
        self.verifier = Verifier()
        self.max_budget = max_budget
        self._review_counter = 0

    def _next_request_id(self) -> str:
        """Generate unique request ID."""
        self._review_counter += 1
        return f"mrr_{self._review_counter}_{hash(str(self._review_counter)) % 10000}"

    def review(self, observation: Dict[str, Any]) -> MultiRoleReviewResult:
        """Execute multi-role review with consensus detection and bounded escalation.

        Phase 9:
        1. Each role produces individual decision
        2. Detect agreement/disagreement
        3. If disagreement, bounded escalation (max 1 extra step)
        4. Produce consensus or escalate result
        """
        request_id = self._next_request_id()
        budget = 1

        # Phase 9: Each role produces proposal/review/judgement
        proposal = self.planner.propose(observation)
        review = self.critic.review(proposal, observation)
        judgement = self.verifier.verify(proposal, review, observation)

        # Phase 9: Extract individual role decisions with reasoning
        role_decisions = []

        # Planner decision
        planner_decision = self._map_interpretation_to_decision(proposal.get("interpretation", "unknown"))
        role_decisions.append(RoleDecision(
            role="planner",
            decision=planner_decision,
            confidence=proposal.get("confidence", 0.5),
            reasoning=f"interpretation: {proposal.get('interpretation', 'unknown')}"
        ))

        # Critic decision
        critic_decision = self._map_quality_to_decision(review.get("quality", "low"))
        role_decisions.append(RoleDecision(
            role="critic",
            decision=critic_decision,
            confidence=review.get("confidence", 0.0),
            reasoning=f"quality: {review.get('quality', 'low')}, issues: {review.get('issues', [])}"
        ))

        # Verifier decision (always used as final in consensus)
        verifier_outcome = judgement.get("outcome", DeliberationOutcome.REJECT)
        role_decisions.append(RoleDecision(
            role="verifier",
            decision=verifier_outcome.value,
            confidence=judgement.get("confidence", 0.0),
            reasoning=judgement.get("reason", "unknown")
        ))

        # Phase 9: Detect consensus
        consensus_status, final_outcome, agreement_summary = self._detect_consensus(role_decisions)

        # Phase 9: Bounded escalation if disagreement
        escalation_used = False
        fallback_used = False
        disagreement_details = None

        if consensus_status == ReviewConsensusStatus.DISAGREEMENT_ESCALATE:
            if budget < self.max_budget:
                # Bounded escalation: one additional consensus attempt
                budget += 1
                escalation_used = True
                # Escalation: conservatively downgrade to strategy_only if possible
                if "strategy_only" in agreement_summary:
                    final_outcome = DeliberationOutcome.STRATEGY_ONLY
                    consensus_status = ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY
                else:
                    # No agreement even on strategy - must reject
                    final_outcome = DeliberationOutcome.REJECT
                    consensus_status = ReviewConsensusStatus.CONSENSUS_REJECT

                disagreement_details = {
                    "original_disagreement": agreement_summary,
                    "escalation_action": "downgrade_conservative",
                    "final_consensus": consensus_status.value,
                }
            else:
                # Budget exhausted - use fallback
                fallback_used = True
                # Conservative fallback: reject if no consensus
                final_outcome = DeliberationOutcome.REJECT
                consensus_status = ReviewConsensusStatus.CONSENSUS_REJECT
                disagreement_details = {
                    "original_disagreement": agreement_summary,
                    "fallback_action": "budget_exhausted_reject",
                }

        # Build review trace
        review_trace = {
            "planner_proposal": proposal,
            "critic_review": review,
            "verifier_judgement": judgement,
            "role_decisions": [
                {"role": d.role, "decision": d.decision, "confidence": d.confidence}
                for d in role_decisions
            ],
        }

        return MultiRoleReviewResult(
            request_id=request_id,
            observation=observation,
            role_decisions=role_decisions,
            consensus_status=consensus_status,
            final_outcome=final_outcome,
            agreement_summary=agreement_summary,
            disagreement_details=disagreement_details,
            escalation_used=escalation_used,
            fallback_used=fallback_used,
            budget_consumed=budget,
            review_trace=review_trace,
        )

    def _map_interpretation_to_decision(self, interpretation: str) -> str:
        """Map planner interpretation to decision."""
        if interpretation == "atom_validation_result":
            return "candidate_ready"
        elif interpretation in ("strategy_signal", "explicit_feedback"):
            return "strategy_only"
        elif interpretation == "numeric_observation":
            return "candidate_ready"
        else:
            return "reject"

    def _map_quality_to_decision(self, quality: str) -> str:
        """Map critic quality to decision."""
        if quality == "high":
            return "candidate_ready"
        elif quality == "medium":
            return "strategy_only"
        else:
            return "reject"

    def _detect_consensus(
        self, role_decisions: List[RoleDecision]
    ) -> tuple[ReviewConsensusStatus, DeliberationOutcome, Dict[str, List[str]]]:
        """Detect consensus among role decisions.

        Returns: (consensus_status, final_outcome, agreement_summary)
        """
        # Build agreement summary: decision -> list of roles
        agreement_summary: Dict[str, List[str]] = {}
        for rd in role_decisions:
            if rd.decision not in agreement_summary:
                agreement_summary[rd.decision] = []
            agreement_summary[rd.decision].append(rd.role)

        # Check for unanimous consensus
        if len(agreement_summary) == 1:
            decision = list(agreement_summary.keys())[0]
            if decision == "candidate_ready":
                return ReviewConsensusStatus.CONSENSUS_ACCEPT, DeliberationOutcome.CANDIDATE_READY, agreement_summary
            elif decision == "strategy_only":
                return ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY, DeliberationOutcome.STRATEGY_ONLY, agreement_summary
            else:
                return ReviewConsensusStatus.CONSENSUS_REJECT, DeliberationOutcome.REJECT, agreement_summary

        # Check for majority consensus (verifier is tie-breaker)
        verifier_decision = next((rd.decision for rd in role_decisions if rd.role == "verifier"), "reject")

        # If verifier agrees with any other role, use that
        verifier_agreement_count = len(agreement_summary.get(verifier_decision, []))
        if verifier_agreement_count >= 2:  # Verifier + at least one other
            if verifier_decision == "candidate_ready":
                return ReviewConsensusStatus.CONSENSUS_ACCEPT, DeliberationOutcome.CANDIDATE_READY, agreement_summary
            elif verifier_decision == "strategy_only":
                return ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY, DeliberationOutcome.STRATEGY_ONLY, agreement_summary
            else:
                return ReviewConsensusStatus.CONSENSUS_REJECT, DeliberationOutcome.REJECT, agreement_summary

        # No clear consensus - escalate
        return ReviewConsensusStatus.DISAGREEMENT_ESCALATE, DeliberationOutcome.REJECT, agreement_summary


class BoundedDeliberation:
    """Bounded deliberation coordinator with Phase 9 multi-role review."""

    def __init__(self, max_budget: int = 1):
        self.planner = Planner()
        self.critic = Critic()
        self.verifier = Verifier()
        self.synthesizer = Synthesizer()
        self.max_budget = max_budget
        # Phase 9: Add multi-role review coordinator
        self._review_coordinator = MultiRoleReviewCoordinator(max_budget=2)

    def deliberate(self, request: DeliberationRequest) -> DeliberationResult:
        """Execute bounded deliberation with structured outcome classification.

        Phase 8: Returns DeliberationResult with outcome field:
        - CANDIDATE_READY: High quality, route to parameter_queue
        - STRATEGY_ONLY: Strategy signal, route to shared_queue
        - REJECT: Failed quality checks, drop or handle specially
        """
        observation = request.observation
        budget = min(request.budget, self.max_budget)

        # Round 1: Planner
        proposal = self.planner.propose(observation)

        # Round 1: Critic
        review = self.critic.review(proposal, observation)

        # Round 1: Verifier (Phase 8: structured outcome)
        judgement = self.verifier.verify(proposal, review, observation)

        # Round 1: Synthesizer
        synthesized = self.synthesizer.synthesize(observation, proposal, review, judgement)

        # Build deliberation trace for audit/debugging
        trace = {
            "observation_type": proposal.get("interpretation", "unknown"),
            "quality_assessment": review.get("quality", "unknown"),
            "issues": review.get("issues", []),
            "reason": judgement.get("reason", "unknown"),
        }

        return DeliberationResult(
            outcome=judgement.get("outcome", DeliberationOutcome.REJECT),
            quality_score=judgement.get("quality_score", 0.0),
            confidence=judgement.get("confidence", 0.0),
            original_observation=observation,
            planner_proposal=proposal,
            critic_review=review,
            verifier_judgement=judgement,
            synthesized_output=synthesized,
            rounds_used=budget,
            deliberation_trace=trace,
        )

    def multi_role_review(self, observation: Dict[str, Any]) -> MultiRoleReviewResult:
        """Phase 9: Execute multi-role review with bounded escalation.

        This is the new entry point for Phase 9 quality deepening.
        """
        return self._review_coordinator.review(observation)
