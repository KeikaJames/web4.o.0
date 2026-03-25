"""Phase 18: Federation-safe parameter memory exchange skeleton.

Provides structured exchange proposal, eligibility, and readiness
without actual parameter merging or federation training.

Safe to call during serve path - never blocks or raises.
"""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field


class ExchangeDecision(Enum):
    """Phase 18: Exchange decision.

    - EXCHANGE_READY: Ready for parameter memory exchange
    - EXCHANGE_HOLD: Hold for further observation
    - EXCHANGE_REJECT: Reject exchange
    """
    EXCHANGE_READY = "exchange_ready"
    EXCHANGE_HOLD = "exchange_hold"
    EXCHANGE_REJECT = "exchange_reject"


@dataclass
class ExchangeCandidate:
    """Phase 18: Candidate for parameter memory exchange."""
    adapter_id: str
    generation: int
    source_node: Optional[str]

    def to_key(self) -> str:
        """Generate unique key for this candidate."""
        return f"{self.adapter_id}:{self.generation}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "generation": self.generation,
            "source_node": self.source_node,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExchangeCandidate":
        return cls(
            adapter_id=data.get("adapter_id", ""),
            generation=data.get("generation", 0),
            source_node=data.get("source_node"),
        )


@dataclass
class ParameterMemoryDescriptor:
    """Phase 18: Descriptor for parameter memory exchange.

    Describes parameter memory without containing actual parameters.
    """
    # Memory metadata
    param_count: int
    memory_size_bytes: int
    compression_ratio: float

    # Delta information
    has_delta: bool
    delta_magnitude: float  # L2 norm of delta
    relative_change: float  # Relative to parent

    # Importance mask info
    importance_threshold: float
    top_k_ratio: float  # Ratio of top-k params

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory": {
                "param_count": self.param_count,
                "size_bytes": self.memory_size_bytes,
                "compression_ratio": round(self.compression_ratio, 4),
            },
            "delta": {
                "has_delta": self.has_delta,
                "magnitude": round(self.delta_magnitude, 6),
                "relative_change": round(self.relative_change, 6),
            },
            "importance": {
                "threshold": round(self.importance_threshold, 4),
                "top_k_ratio": round(self.top_k_ratio, 4),
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ParameterMemoryDescriptor":
        memory = data.get("memory", {})
        delta = data.get("delta", {})
        importance = data.get("importance", {})

        return cls(
            param_count=memory.get("param_count", 0),
            memory_size_bytes=memory.get("size_bytes", 0),
            compression_ratio=memory.get("compression_ratio", 1.0),
            has_delta=delta.get("has_delta", False),
            delta_magnitude=delta.get("magnitude", 0.0),
            relative_change=delta.get("relative_change", 0.0),
            importance_threshold=importance.get("threshold", 0.0),
            top_k_ratio=importance.get("top_k_ratio", 1.0),
        )


@dataclass
class ExchangeEligibility:
    """Phase 18: Exchange eligibility assessment."""
    # Gate results
    lineage_compatible: bool
    specialization_compatible: bool
    validation_passed: bool
    comparison_acceptable: bool
    lifecycle_valid: bool
    conflict_resolved: bool
    execution_ready: bool

    # Overall
    is_eligible: bool
    blocking_factors: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gates": {
                "lineage_compatible": self.lineage_compatible,
                "specialization_compatible": self.specialization_compatible,
                "validation_passed": self.validation_passed,
                "comparison_acceptable": self.comparison_acceptable,
                "lifecycle_valid": self.lifecycle_valid,
                "conflict_resolved": self.conflict_resolved,
                "execution_ready": self.execution_ready,
            },
            "overall": {
                "is_eligible": self.is_eligible,
                "blocking_factors": self.blocking_factors,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExchangeEligibility":
        gates = data.get("gates", {})
        overall = data.get("overall", {})

        return cls(
            lineage_compatible=gates.get("lineage_compatible", False),
            specialization_compatible=gates.get("specialization_compatible", False),
            validation_passed=gates.get("validation_passed", False),
            comparison_acceptable=gates.get("comparison_acceptable", False),
            lifecycle_valid=gates.get("lifecycle_valid", False),
            conflict_resolved=gates.get("conflict_resolved", False),
            execution_ready=gates.get("execution_ready", False),
            is_eligible=overall.get("is_eligible", False),
            blocking_factors=overall.get("blocking_factors", []),
        )


@dataclass
class ExchangeProposal:
    """Phase 18: Proposal for parameter memory exchange.

    Structured proposal without actual parameter data.
    """
    # Identity
    proposal_id: str
    candidate: ExchangeCandidate

    # Exchange intent
    intent: str  # "share_delta", "share_full", "request_merge"
    priority: int  # 0-100

    # Descriptors
    memory_descriptor: ParameterMemoryDescriptor

    # Preconditions summary
    eligibility: ExchangeEligibility

    # Metadata
    proposed_at: str
    version: str
    fallback_used: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {
                "proposal_id": self.proposal_id,
                "candidate": self.candidate.to_dict(),
            },
            "intent": {
                "type": self.intent,
                "priority": self.priority,
            },
            "memory_descriptor": self.memory_descriptor.to_dict(),
            "eligibility": self.eligibility.to_dict(),
            "meta": {
                "proposed_at": self.proposed_at,
                "version": self.version,
                "fallback_used": self.fallback_used,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExchangeProposal":
        identity = data.get("identity", {})
        intent = data.get("intent", {})
        meta = data.get("meta", {})

        return cls(
            proposal_id=identity.get("proposal_id", ""),
            candidate=ExchangeCandidate.from_dict(identity.get("candidate", {})),
            intent=intent.get("type", ""),
            priority=intent.get("priority", 0),
            memory_descriptor=ParameterMemoryDescriptor.from_dict(data.get("memory_descriptor", {})),
            eligibility=ExchangeEligibility.from_dict(data.get("eligibility", {})),
            proposed_at=meta.get("proposed_at", ""),
            version=meta.get("version", "1.0"),
            fallback_used=meta.get("fallback_used", False),
        )


@dataclass
class ExchangeReadiness:
    """Phase 18: Exchange readiness assessment.

    Complete readiness for parameter memory exchange.
    """
    # Identity
    readiness_id: str
    candidate: ExchangeCandidate

    # Decision
    decision: ExchangeDecision
    is_ready: bool

    # Proposal reference
    proposal: ExchangeProposal

    # Readiness factors
    readiness_score: float  # 0.0-1.0
    readiness_factors: Dict[str, float]

    # Reasoning
    reason: str
    recommendation: str

    # Metadata
    assessed_at: str
    version: str
    fallback_used: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {
                "readiness_id": self.readiness_id,
                "candidate": self.candidate.to_dict(),
            },
            "decision": {
                "decision": self.decision.value,
                "is_ready": self.is_ready,
            },
            "proposal": self.proposal.to_dict(),
            "readiness": {
                "score": round(self.readiness_score, 4),
                "factors": self.readiness_factors,
            },
            "reasoning": {
                "reason": self.reason,
                "recommendation": self.recommendation,
            },
            "meta": {
                "assessed_at": self.assessed_at,
                "version": self.version,
                "fallback_used": self.fallback_used,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExchangeReadiness":
        identity = data.get("identity", {})
        decision = data.get("decision", {})
        readiness = data.get("readiness", {})
        reasoning = data.get("reasoning", {})
        meta = data.get("meta", {})

        decision_str = decision.get("decision", "exchange_reject")
        dec = ExchangeDecision(decision_str) if decision_str in [d.value for d in ExchangeDecision] else ExchangeDecision.EXCHANGE_REJECT

        return cls(
            readiness_id=identity.get("readiness_id", ""),
            candidate=ExchangeCandidate.from_dict(identity.get("candidate", {})),
            decision=dec,
            is_ready=decision.get("is_ready", False),
            proposal=ExchangeProposal.from_dict(data.get("proposal", {})),
            readiness_score=readiness.get("score", 0.0),
            readiness_factors=readiness.get("factors", {}),
            reason=reasoning.get("reason", ""),
            recommendation=reasoning.get("recommendation", ""),
            assessed_at=meta.get("assessed_at", ""),
            version=meta.get("version", "1.0"),
            fallback_used=meta.get("fallback_used", False),
        )


class ParameterMemoryExchangeSkeleton:
    """Phase 18: Parameter memory exchange skeleton.

    Provides structured exchange proposal, eligibility, and readiness
    without actual parameter merging.

    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"

    # Thresholds
    MIN_READINESS_SCORE = 0.7
    MIN_ELIGIBLE_GATES = 6  # All 7 gates must pass

    @classmethod
    def create_proposal(
        cls,
        candidate_dict: Dict[str, Any],
        intent: str = "share_delta",
        priority: int = 50,
        fallback_on_error: bool = True,
    ) -> ExchangeProposal:
        """Create exchange proposal for candidate.

        Phase 18: Main entry for proposal creation.
        """
        try:
            return cls._do_create_proposal(candidate_dict, intent, priority)
        except Exception as e:
            if fallback_on_error:
                return cls._fallback_proposal(candidate_dict, str(e))
            raise

    @classmethod
    def _do_create_proposal(
        cls,
        candidate_dict: Dict[str, Any],
        intent: str,
        priority: int,
    ) -> ExchangeProposal:
        """Internal proposal creation."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        proposal_id = f"proposal-{str(uuid.uuid4())[:8]}"

        candidate = ExchangeCandidate.from_dict(candidate_dict)

        # Create default memory descriptor (skeleton only)
        memory_descriptor = ParameterMemoryDescriptor(
            param_count=0,
            memory_size_bytes=0,
            compression_ratio=1.0,
            has_delta=False,
            delta_magnitude=0.0,
            relative_change=0.0,
            importance_threshold=0.0,
            top_k_ratio=1.0,
        )

        # Create default eligibility (not eligible by default)
        eligibility = ExchangeEligibility(
            lineage_compatible=False,
            specialization_compatible=False,
            validation_passed=False,
            comparison_acceptable=False,
            lifecycle_valid=False,
            conflict_resolved=False,
            execution_ready=False,
            is_eligible=False,
            blocking_factors=["skeleton_mode: no actual validation performed"],
        )

        return ExchangeProposal(
            proposal_id=proposal_id,
            candidate=candidate,
            intent=intent,
            priority=priority,
            memory_descriptor=memory_descriptor,
            eligibility=eligibility,
            proposed_at=now,
            version=cls.VERSION,
            fallback_used=False,
        )

    @classmethod
    def _fallback_proposal(
        cls,
        candidate_dict: Dict[str, Any],
        error_message: str,
    ) -> ExchangeProposal:
        """Create fallback proposal on error."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        proposal_id = f"proposal-fallback-{str(uuid.uuid4())[:8]}"

        candidate = ExchangeCandidate.from_dict(candidate_dict)

        return ExchangeProposal(
            proposal_id=proposal_id,
            candidate=candidate,
            intent="share_delta",
            priority=0,
            memory_descriptor=ParameterMemoryDescriptor(
                param_count=0,
                memory_size_bytes=0,
                compression_ratio=1.0,
                has_delta=False,
                delta_magnitude=0.0,
                relative_change=0.0,
                importance_threshold=0.0,
                top_k_ratio=1.0,
            ),
            eligibility=ExchangeEligibility(
                lineage_compatible=False,
                specialization_compatible=False,
                validation_passed=False,
                comparison_acceptable=False,
                lifecycle_valid=False,
                conflict_resolved=False,
                execution_ready=False,
                is_eligible=False,
                blocking_factors=[f"error:{error_message}"],
            ),
            proposed_at=now,
            version=cls.VERSION,
            fallback_used=True,
        )

    @classmethod
    def assess_readiness(
        cls,
        proposal: ExchangeProposal,
        triage_summary: Optional[Dict[str, Any]] = None,
        lifecycle_summary: Optional[Dict[str, Any]] = None,
        conflict_summary: Optional[Dict[str, Any]] = None,
        execution_summary: Optional[Dict[str, Any]] = None,
        fallback_on_error: bool = True,
    ) -> ExchangeReadiness:
        """Assess exchange readiness for proposal.

        Phase 18: Main entry for readiness assessment.
        """
        try:
            return cls._do_assess_readiness(
                proposal, triage_summary, lifecycle_summary, conflict_summary, execution_summary
            )
        except Exception as e:
            if fallback_on_error:
                return cls._fallback_readiness(proposal, str(e))
            raise

    @classmethod
    def _do_assess_readiness(
        cls,
        proposal: ExchangeProposal,
        triage_summary: Optional[Dict[str, Any]],
        lifecycle_summary: Optional[Dict[str, Any]],
        conflict_summary: Optional[Dict[str, Any]],
        execution_summary: Optional[Dict[str, Any]],
    ) -> ExchangeReadiness:
        """Internal readiness assessment."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        readiness_id = f"readiness-{str(uuid.uuid4())[:8]}"

        # Calculate eligibility from summaries
        gates = cls._calculate_gates(
            triage_summary, lifecycle_summary, conflict_summary, execution_summary
        )

        # Calculate readiness score
        readiness_score = sum(gates.values()) / len(gates)

        # Determine decision
        passed_gates = sum(1 for v in gates.values() if v >= 0.7)

        if passed_gates >= cls.MIN_ELIGIBLE_GATES and readiness_score >= cls.MIN_READINESS_SCORE:
            decision = ExchangeDecision.EXCHANGE_READY
            is_ready = True
            reason = "All gates passed - exchange ready"
            recommendation = "proceed_with_exchange"
        elif passed_gates >= 4:
            decision = ExchangeDecision.EXCHANGE_HOLD
            is_ready = False
            reason = "Some gates pending - hold for observation"
            recommendation = "hold_for_further_validation"
        else:
            decision = ExchangeDecision.EXCHANGE_REJECT
            is_ready = False
            reason = "Insufficient gates passed - reject exchange"
            recommendation = "reject_exchange"

        # Update proposal eligibility
        proposal.eligibility = ExchangeEligibility(
            lineage_compatible=gates.get("lineage", 0) >= 0.7,
            specialization_compatible=gates.get("specialization", 0) >= 0.7,
            validation_passed=gates.get("validation", 0) >= 0.7,
            comparison_acceptable=gates.get("comparison", 0) >= 0.7,
            lifecycle_valid=gates.get("lifecycle", 0) >= 0.7,
            conflict_resolved=gates.get("conflict", 0) >= 0.7,
            execution_ready=gates.get("execution", 0) >= 0.7,
            is_eligible=is_ready,
            blocking_factors=[k for k, v in gates.items() if v < 0.7],
        )

        return ExchangeReadiness(
            readiness_id=readiness_id,
            candidate=proposal.candidate,
            decision=decision,
            is_ready=is_ready,
            proposal=proposal,
            readiness_score=readiness_score,
            readiness_factors=gates,
            reason=reason,
            recommendation=recommendation,
            assessed_at=now,
            version=cls.VERSION,
            fallback_used=False,
        )

    @classmethod
    def _calculate_gates(
        cls,
        triage_summary: Optional[Dict[str, Any]],
        lifecycle_summary: Optional[Dict[str, Any]],
        conflict_summary: Optional[Dict[str, Any]],
        execution_summary: Optional[Dict[str, Any]],
    ) -> Dict[str, float]:
        """Calculate gate scores from summaries."""
        gates = {
            "lineage": 0.0,
            "specialization": 0.0,
            "validation": 0.0,
            "comparison": 0.0,
            "lifecycle": 0.0,
            "conflict": 0.0,
            "execution": 0.0,
        }

        if triage_summary:
            gates["lineage"] = 1.0 if triage_summary.get("lineage_compatible") else 0.0
            gates["specialization"] = 1.0 if triage_summary.get("specialization_compatible") else 0.0
            gates["validation"] = triage_summary.get("readiness_score", 0.0)
            gates["comparison"] = 1.0 if triage_summary.get("status") == "ready" else 0.0

        if lifecycle_summary:
            state = lifecycle_summary.get("state", "")
            ttl = lifecycle_summary.get("ttl_remaining", 0.0)
            gates["lifecycle"] = 1.0 if state == "ready" and ttl > 0 else 0.0

        if conflict_summary:
            gates["conflict"] = 1.0 if conflict_summary.get("can_proceed") else 0.0

        if execution_summary:
            gates["execution"] = 1.0 if execution_summary.get("success") else 0.0

        return gates

    @classmethod
    def _fallback_readiness(
        cls,
        proposal: ExchangeProposal,
        error_message: str,
    ) -> ExchangeReadiness:
        """Create fallback readiness on error."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        readiness_id = f"readiness-fallback-{str(uuid.uuid4())[:8]}"

        return ExchangeReadiness(
            readiness_id=readiness_id,
            candidate=proposal.candidate,
            decision=ExchangeDecision.EXCHANGE_REJECT,
            is_ready=False,
            proposal=proposal,
            readiness_score=0.0,
            readiness_factors={},
            reason=f"Error: {error_message}",
            recommendation="reject_due_to_error",
            assessed_at=now,
            version=cls.VERSION,
            fallback_used=True,
        )

    @classmethod
    def quick_exchange_check(
        cls,
        proposal_dict: Dict[str, Any],
    ) -> bool:
        """Quick check if exchange is possible.

        Phase 18: Fast path for exchange eligibility.
        """
        try:
            proposal = ExchangeProposal.from_dict(proposal_dict)
            return proposal.eligibility.is_eligible
        except Exception:
            return False

    @classmethod
    def batch_assess_readiness(
        cls,
        proposals: List[ExchangeProposal],
        triage_summaries: Optional[Dict[str, Dict[str, Any]]] = None,
        lifecycle_summaries: Optional[Dict[str, Dict[str, Any]]] = None,
        conflict_summaries: Optional[Dict[str, Dict[str, Any]]] = None,
        execution_summaries: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[ExchangeReadiness]:
        """Assess readiness for multiple proposals.

        Phase 18: Batch processing for efficiency.
        """
        triage_summaries = triage_summaries or {}
        lifecycle_summaries = lifecycle_summaries or {}
        conflict_summaries = conflict_summaries or {}
        execution_summaries = execution_summaries or {}

        results = []
        for proposal in proposals:
            key = proposal.candidate.to_key()
            readiness = cls.assess_readiness(
                proposal,
                triage_summary=triage_summaries.get(key),
                lifecycle_summary=lifecycle_summaries.get(key),
                conflict_summary=conflict_summaries.get(key),
                execution_summary=execution_summaries.get(key),
                fallback_on_error=True,
            )
            results.append(readiness)

        return results
