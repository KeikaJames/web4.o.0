"""Phase 13: Remote summary triage engine.

Performs secondary triage on staged remote summaries to determine
readiness for future federation promotion.

Safe to call during serve path - never blocks or raises.
"""

import uuid
from typing import Optional
from datetime import datetime

from .types import (
    StagedRemoteCandidate,
    TriageAssessment,
    TriageResult,
    TriageStatus,
    ReadinessSummary,
    FederationSummary,
    FederationExchangeGate,
    ExchangeStatus,
)


class RemoteTriageEngine:
    """Phase 13: Triage engine for staged remote summaries.

    Performs deterministic, bounded triage assessment to determine:
    - Which staged summaries are ready for future federation
    - Which should be held for observation
    - Which should be downgraded
    - Which should be rejected

    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"

    # Thresholds for triage decisions
    READINESS_THRESHOLD_READY = 0.8
    READINESS_THRESHOLD_HOLD = 0.5
    READINESS_THRESHOLD_DOWNGRADE = 0.3

    # Generation gap thresholds
    MAX_FRESH_GENERATION_GAP = 2
    MAX_ACCEPTABLE_GENERATION_GAP = 5

    @classmethod
    def triage(
        cls,
        staged_candidate: StagedRemoteCandidate,
        local_summary: Optional[FederationSummary] = None,
        fallback_on_error: bool = True,
    ) -> TriageResult:
        """Perform triage on a staged remote candidate.

        Phase 13: Main entry point for remote summary triage.

        Args:
            staged_candidate: The staged remote candidate to triage
            local_summary: Optional local summary for comparison
            fallback_on_error: Whether to return safe fallback on error

        Returns:
            TriageResult with full assessment and routing
        """
        try:
            return cls._do_triage(staged_candidate, local_summary)
        except Exception as e:
            if fallback_on_error:
                return cls._fallback_result(staged_candidate, str(e))
            raise

    @classmethod
    def _do_triage(
        cls,
        staged: StagedRemoteCandidate,
        local_summary: Optional[FederationSummary],
    ) -> TriageResult:
        """Internal triage logic."""
        processed_at = datetime.utcnow().isoformat() + "Z"
        trace_id = str(uuid.uuid4())[:8]

        # Extract information from staged candidate
        remote = staged.summary
        gate = staged.gate_result

        # Calculate readiness scores
        readiness = cls._calculate_readiness(staged, local_summary)

        # Determine triage status based on readiness
        status, recommendation, reason = cls._determine_status(
            readiness, staged, gate
        )

        # Determine target pool
        target_pool = cls._determine_target_pool(status)
        priority = cls._calculate_priority(readiness, status)

        # Build assessment
        assessment = TriageAssessment(
            adapter_id=staged.adapter_id,
            generation=staged.generation,
            source_node=staged.source_node,
            triage_status=status,
            triage_version=cls.VERSION,
            triaged_at=processed_at,
            readiness=readiness,
            lineage_compatible=gate.lineage.compatible if gate else False,
            specialization_compatible=gate.specialization.compatible if gate else False,
            validation_acceptable=gate.validation.acceptable if gate else False,
            comparison_acceptable=gate.comparison.acceptable if gate else False,
            recommendation=recommendation,
            reason=reason,
            can_promote_later=status in (TriageStatus.READY, TriageStatus.HOLD),
            needs_review=status == TriageStatus.HOLD,
            expiration_hint=cls._calculate_expiration(staged, readiness),
            original_staging_ref=staged.intake_record_ref,
        )

        return TriageResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=False,
            assessment=assessment,
            target_pool=target_pool,
            priority=priority,
            trace_id=trace_id,
        )

    @classmethod
    def _calculate_readiness(
        cls,
        staged: StagedRemoteCandidate,
        local_summary: Optional[FederationSummary],
    ) -> ReadinessSummary:
        """Calculate readiness scores for staged candidate."""
        gate = staged.gate_result
        remote = staged.summary

        # Lineage score (0.0-1.0)
        lineage_score = cls._calculate_lineage_score(gate, staged)

        # Specialization score
        spec_score = cls._calculate_spec_score(gate, staged)

        # Validation score
        val_score = cls._calculate_validation_score(gate, remote)

        # Comparison score
        comp_score = cls._calculate_comparison_score(gate)

        # Recency score (based on generation gap)
        recency_score = cls._calculate_recency_score(gate, local_summary, staged)

        # Component weights
        weights = {
            "lineage": 0.25,
            "specialization": 0.20,
            "validation": 0.25,
            "comparison": 0.20,
            "recency": 0.10,
        }

        # Weighted overall score
        overall = (
            lineage_score * weights["lineage"] +
            spec_score * weights["specialization"] +
            val_score * weights["validation"] +
            comp_score * weights["comparison"] +
            recency_score * weights["recency"]
        )

        # Determine flags
        is_fresh = recency_score >= 0.7
        is_compatible = all([
            gate.lineage.compatible if gate else False,
            gate.specialization.can_compose if gate else False,
            gate.validation.acceptable if gate else False,
        ])
        is_priority = overall >= cls.READINESS_THRESHOLD_READY and is_fresh

        # Reasoning
        if is_priority:
            reason = "high_readiness_fresh_candidate"
        elif is_compatible:
            reason = "compatible_meets_thresholds"
        elif overall >= cls.READINESS_THRESHOLD_HOLD:
            reason = "marginal_needs_observation"
        else:
            reason = "below_readiness_thresholds"

        return ReadinessSummary(
            readiness_score=round(overall, 2),
            lineage_score=round(lineage_score, 2),
            specialization_score=round(spec_score, 2),
            validation_score=round(val_score, 2),
            comparison_score=round(comp_score, 2),
            recency_score=round(recency_score, 2),
            is_fresh=is_fresh,
            is_compatible=is_compatible,
            is_priority=is_priority,
            score_reason=reason,
        )

    @classmethod
    def _calculate_lineage_score(
        cls,
        gate: Optional[FederationExchangeGate],
        staged: StagedRemoteCandidate,
    ) -> float:
        """Calculate lineage compatibility score."""
        if not gate:
            return 0.0

        # Start with match score
        score = gate.lineage.match_score

        # Penalize if not compatible
        if not gate.lineage.compatible:
            score *= 0.5

        # Bonus for parent-child
        if gate.lineage.is_parent_child:
            score = max(score, 0.9)

        return min(1.0, max(0.0, score))

    @classmethod
    def _calculate_spec_score(
        cls,
        gate: Optional[FederationExchangeGate],
        staged: StagedRemoteCandidate,
    ) -> float:
        """Calculate specialization compatibility score."""
        if not gate:
            return 0.0

        if gate.specialization.compatible:
            return 1.0
        elif gate.specialization.can_compose:
            return 0.6
        else:
            return 0.2

    @classmethod
    def _calculate_validation_score(
        cls,
        gate: Optional[FederationExchangeGate],
        remote: FederationSummary,
    ) -> float:
        """Calculate validation acceptance score."""
        if not gate:
            return remote.validation_score.score

        if not gate.validation.acceptable:
            return 0.2

        # Score based on remote validation and comparison to local
        base_score = gate.validation.remote_score
        delta_bonus = max(0, gate.validation.score_delta * 0.5)

        return min(1.0, base_score + delta_bonus)

    @classmethod
    def _calculate_comparison_score(
        cls,
        gate: Optional[FederationExchangeGate],
    ) -> float:
        """Calculate comparison outcome score."""
        if not gate:
            return 0.5

        if not gate.comparison.acceptable:
            return 0.2

        if gate.comparison.both_acceptable:
            return 1.0

        return 0.7

    @classmethod
    def _calculate_recency_score(
        cls,
        gate: Optional[FederationExchangeGate],
        local_summary: Optional[FederationSummary],
        staged: StagedRemoteCandidate,
    ) -> float:
        """Calculate recency/freshness score."""
        gap = gate.lineage.generation_gap if gate else 0

        if gap == 0:
            return 1.0
        elif gap <= cls.MAX_FRESH_GENERATION_GAP:
            return 0.9 - (gap * 0.1)
        elif gap <= cls.MAX_ACCEPTABLE_GENERATION_GAP:
            return 0.6 - ((gap - cls.MAX_FRESH_GENERATION_GAP) * 0.1)
        else:
            return max(0.0, 0.3 - ((gap - cls.MAX_ACCEPTABLE_GENERATION_GAP) * 0.05))

    @classmethod
    def _determine_status(
        cls,
        readiness: ReadinessSummary,
        staged: StagedRemoteCandidate,
        gate: Optional[FederationExchangeGate],
    ) -> tuple[TriageStatus, str, str]:
        """Determine triage status based on readiness."""
        score = readiness.readiness_score

        # Reject if originally rejected
        if staged.staging_decision.value == "stage_reject":
            return (
                TriageStatus.REJECT,
                "reject_previously_rejected",
                "Original staging was rejected",
            )

        # Reject if critical compatibility failures
        if gate and not gate.lineage.compatible:
            return (
                TriageStatus.REJECT,
                "reject_lineage_incompatible",
                "Lineage incompatibility detected",
            )

        # DOWNGRADE: Previously downgraded candidate must not be promoted
        # This check comes before READY to ensure downgrade flag is respected
        if staged.is_downgraded:
            return (
                TriageStatus.DOWNGRADE,
                "downgrade_previously_flagged",
                "Candidate was previously downgraded",
            )

        # READY: High score, compatible, fresh
        if score >= cls.READINESS_THRESHOLD_READY and readiness.is_fresh and readiness.is_compatible:
            return (
                TriageStatus.READY,
                "promote_ready_candidate",
                f"High readiness score: {score:.2f}",
            )

        # HOLD: Medium score, might improve
        if score >= cls.READINESS_THRESHOLD_HOLD and readiness.is_compatible:
            return (
                TriageStatus.HOLD,
                "hold_for_observation",
                f"Marginal readiness, observe: {score:.2f}",
            )

        # DOWNGRADE: Low score but some potential
        if score >= cls.READINESS_THRESHOLD_DOWNGRADE:
            return (
                TriageStatus.DOWNGRADE,
                "downgrade_low_readiness",
                f"Low readiness, downgrade required: {score:.2f}",
            )

        # REJECT: Too low
        return (
            TriageStatus.REJECT,
            "reject_low_readiness",
            f"Readiness too low: {score:.2f}",
        )

    @classmethod
    def _determine_target_pool(cls, status: TriageStatus) -> str:
        """Determine target pool based on triage status."""
        pool_map = {
            TriageStatus.READY: "ready",
            TriageStatus.HOLD: "hold",
            TriageStatus.DOWNGRADE: "downgraded",
            TriageStatus.REJECT: "rejected",
        }
        return pool_map.get(status, "rejected")

    @classmethod
    def _calculate_priority(cls, readiness: ReadinessSummary, status: TriageStatus) -> int:
        """Calculate priority score (0-100)."""
        base = int(readiness.readiness_score * 100)

        if status == TriageStatus.READY:
            base += 20
        elif status == TriageStatus.HOLD:
            base += 5
        elif status == TriageStatus.REJECT:
            base = 0

        return min(100, max(0, base))

    @classmethod
    def _calculate_expiration(
        cls,
        staged: StagedRemoteCandidate,
        readiness: ReadinessSummary,
    ) -> Optional[str]:
        """Calculate expiration hint for staged candidate."""
        if not readiness.is_fresh:
            return "stale_candidate_review"
        if staged.is_downgraded:
            return "downgraded_candidate_review"
        return None

    @classmethod
    def _fallback_result(
        cls,
        staged: StagedRemoteCandidate,
        error_message: str,
    ) -> TriageResult:
        """Create safe fallback triage result on error."""
        processed_at = datetime.utcnow().isoformat() + "Z"
        trace_id = str(uuid.uuid4())[:8]

        assessment = TriageAssessment(
            adapter_id=staged.adapter_id if staged else "unknown",
            generation=staged.generation if staged else 0,
            source_node=staged.source_node if staged else None,
            triage_status=TriageStatus.REJECT,
            triage_version=cls.VERSION,
            triaged_at=processed_at,
            readiness=ReadinessSummary(
                readiness_score=0.0,
                lineage_score=0.0,
                specialization_score=0.0,
                validation_score=0.0,
                comparison_score=0.0,
                recency_score=0.0,
                is_fresh=False,
                is_compatible=False,
                is_priority=False,
                score_reason=f"error:{error_message}",
            ),
            lineage_compatible=False,
            specialization_compatible=False,
            validation_acceptable=False,
            comparison_acceptable=False,
            recommendation="reject_error_fallback",
            reason=f"Triage error: {error_message}",
            can_promote_later=False,
            needs_review=False,
            expiration_hint=None,
            original_staging_ref=staged.intake_record_ref if staged else "",
        )

        return TriageResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=True,
            assessment=assessment,
            target_pool="rejected",
            priority=0,
            trace_id=trace_id,
        )

    @classmethod
    def batch_triage(
        cls,
        staged_candidates: list[StagedRemoteCandidate],
        local_summary: Optional[FederationSummary] = None,
    ) -> list[TriageResult]:
        """Triage multiple staged candidates.

        Phase 13: Batch processing for efficiency.
        """
        results = []
        for staged in staged_candidates:
            result = cls.triage(staged, local_summary, fallback_on_error=True)
            results.append(result)
        return results

    @classmethod
    def quick_readiness_check(
        cls,
        staged: StagedRemoteCandidate,
    ) -> bool:
        """Quick check if staged candidate is ready.

        Phase 13: Fast path for simple ready/not-ready decisions.
        """
        try:
            # Check original staging
            if staged.staging_decision.value == "stage_reject":
                return False

            # Check exchange gate
            gate = staged.gate_result
            if not gate:
                return False

            if not gate.can_exchange():
                return False

            # Check generation gap
            if gate.lineage.generation_gap > cls.MAX_FRESH_GENERATION_GAP:
                return False

            return True
        except Exception:
            return False
