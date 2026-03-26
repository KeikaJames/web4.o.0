"""Phase 11: Federation exchange gate for compatibility checking.

Provides deterministic comparison between local and remote federation summaries
to determine exchange readiness.
"""

from typing import Optional
from datetime import datetime, timezone

from .types import (
    FederationSummary,
    FederationExchangeGate,
    ExchangeStatus,
    LineageCompatibility,
    SpecializationCompatibility,
    ValidationCompatibility,
    ComparisonCompatibility,
)
from .common import utc_now


class FederationExchangeComparator:
    """Phase 11: Compares federation summaries for exchange compatibility.

    Deterministic, testable comparison logic that respects:
    - Lineage compatibility
    - Specialization constraints
    - Validation thresholds
    - Comparison outcomes

    Safe to call during serve path - never blocks or raises.
    """

    # Thresholds for exchange decisions
    MIN_LINEAGE_MATCH_SCORE = 0.5
    MIN_VALIDATION_SCORE = 0.5
    MAX_GENERATION_GAP_FOR_ACCEPT = 2
    MAX_GENERATION_GAP_FOR_DOWNGRADE = 5

    @staticmethod
    def _utc_now() -> str:
        """Generate UTC timestamp - delegates to common.utc_now for consistency."""
        return utc_now()

    @classmethod
    def compare(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
        fallback_on_error: bool = True,
    ) -> FederationExchangeGate:
        """Compare local and remote summaries for exchange compatibility.

        Phase 11: Main entry point for exchange gate decision.

        Args:
            local: Local federation summary
            remote: Remote federation summary to compare against
            fallback_on_error: Whether to return safe fallback on error

        Returns:
            FederationExchangeGate with full compatibility assessment
        """
        try:
            return cls._do_compare(local, remote)
        except Exception:
            if fallback_on_error:
                return cls._fallback_gate(local, remote)
            raise

    @classmethod
    def _do_compare(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
    ) -> FederationExchangeGate:
        """Internal comparison logic."""
        # Assess lineage compatibility
        lineage = cls._assess_lineage(local, remote)

        # Assess specialization compatibility
        specialization = cls._assess_specialization(local, remote)

        # Assess validation compatibility
        validation = cls._assess_validation(local, remote)

        # Assess comparison outcome compatibility
        comparison = cls._assess_comparison(local, remote)

        # Determine overall status and recommendation
        status, recommendation, reason = cls._determine_status(
            lineage, specialization, validation, comparison
        )

        return FederationExchangeGate(
            local_adapter_id=local.identity.adapter_id,
            local_generation=local.identity.generation,
            remote_adapter_id=remote.identity.adapter_id,
            remote_generation=remote.identity.generation,
            lineage=lineage,
            specialization=specialization,
            validation=validation,
            comparison=comparison,
            status=status,
            recommendation=recommendation,
            reason=reason,
            fallback_used=False,
            version="1.0",
            timestamp=cls._utc_now(),
        )

    @classmethod
    def _assess_lineage(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
    ) -> LineageCompatibility:
        """Assess lineage compatibility between local and remote."""
        # Check adapter ID match
        if local.identity.adapter_id != remote.identity.adapter_id:
            return LineageCompatibility(
                compatible=False,
                match_score=0.0,
                generation_gap=0,
                is_parent_child=False,
                lineage_hash_match=False,
                reason="adapter_id_mismatch",
            )

        # Calculate generation gap
        gen_gap = abs(local.identity.generation - remote.identity.generation)

        # Check parent-child relationship
        is_parent_child = (
            local.identity.parent_generation == remote.identity.generation or
            remote.identity.parent_generation == local.identity.generation
        )

        # Check lineage hash match
        hash_match = (
            local.snapshot_lineage.lineage_hash == remote.snapshot_lineage.lineage_hash
            and local.snapshot_lineage.lineage_hash != ""
        )

        # Compute match score
        if local.identity.generation == remote.identity.generation:
            match_score = 1.0
        elif is_parent_child:
            match_score = 0.9
        elif hash_match:
            match_score = 0.95
        else:
            # Generation distance penalty
            match_score = max(0.0, 0.8 - (gen_gap * 0.1))

        # Determine compatibility
        compatible = match_score >= cls.MIN_LINEAGE_MATCH_SCORE

        reason = None
        if not compatible:
            reason = f"lineage_match_score_too_low:{match_score:.2f}"
        elif is_parent_child:
            reason = "parent_child_relationship"
        elif hash_match:
            reason = "lineage_hash_match"
        elif local.identity.generation == remote.identity.generation:
            reason = "same_generation"
        else:
            reason = f"generation_gap:{gen_gap}"

        return LineageCompatibility(
            compatible=compatible,
            match_score=match_score,
            generation_gap=gen_gap,
            is_parent_child=is_parent_child,
            lineage_hash_match=hash_match,
            reason=reason,
        )

    @classmethod
    def _assess_specialization(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
    ) -> SpecializationCompatibility:
        """Assess specialization compatibility."""
        local_spec = local.identity.specialization
        remote_spec = remote.identity.specialization

        # Same specialization is always compatible
        if local_spec == remote_spec:
            return SpecializationCompatibility(
                compatible=True,
                local_spec=local_spec,
                remote_spec=remote_spec,
                can_compose=True,
                reason="same_specialization",
            )

        # Check if local requires specific specialization
        if local.compatibility.required_specialization:
            if remote_spec != local.compatibility.required_specialization:
                return SpecializationCompatibility(
                    compatible=False,
                    local_spec=local_spec,
                    remote_spec=remote_spec,
                    can_compose=False,
                    reason=f"required_specialization_mismatch:{local.compatibility.required_specialization}",
                )

        # STABLE can compose with SHARED
        can_compose = (
            (local_spec == "stable" and remote_spec == "shared") or
            (local_spec == "shared" and remote_spec == "stable") or
            (local_spec == "candidate" and remote_spec == "candidate")
        )

        compatible = False

        return SpecializationCompatibility(
            compatible=compatible,
            local_spec=local_spec,
            remote_spec=remote_spec,
            can_compose=can_compose,
            reason="can_compose" if can_compose else "specialization_incompatible",
        )

    @classmethod
    def _assess_validation(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
    ) -> ValidationCompatibility:
        """Assess validation acceptance."""
        local_score = local.validation_score.score
        remote_score = remote.validation_score.score
        score_delta = remote_score - local_score

        # Check if remote meets local threshold
        meets_threshold = remote_score >= local.compatibility.min_validation_score

        # Check if remote passed validation
        remote_passed = remote.validation_score.passed

        # Acceptable if passed and meets threshold
        acceptable = remote_passed and meets_threshold

        reason = None
        if not remote_passed:
            reason = "remote_validation_failed"
        elif not meets_threshold:
            reason = f"below_threshold:{remote_score:.2f}<{local.compatibility.min_validation_score:.2f}"
        elif score_delta > 0:
            reason = f"improvement:+{score_delta:.2f}"
        else:
            reason = f"degradation:{score_delta:.2f}"

        return ValidationCompatibility(
            acceptable=acceptable,
            local_score=local_score,
            remote_score=remote_score,
            score_delta=score_delta,
            meets_threshold=meets_threshold,
            reason=reason,
        )

    @classmethod
    def _assess_comparison(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
    ) -> ComparisonCompatibility:
        """Assess comparison outcome compatibility."""
        local_status = local.comparison_outcome.status
        remote_status = remote.comparison_outcome.status

        # Both should be acceptable
        local_acceptable = (
            local.comparison_outcome.is_acceptable and
            local.comparison_outcome.promote_recommendation != "reject"
        )
        remote_acceptable = (
            remote.comparison_outcome.is_acceptable and
            remote.comparison_outcome.promote_recommendation != "reject"
        )

        both_acceptable = local_acceptable and remote_acceptable

        # Acceptable if remote is acceptable
        acceptable = remote_acceptable

        reason = None
        if not remote_acceptable:
            reason = f"remote_not_acceptable:{remote_status}"
        elif not local_acceptable:
            reason = f"local_not_acceptable:{local_status}"
        else:
            reason = "both_acceptable"

        return ComparisonCompatibility(
            acceptable=acceptable,
            local_status=local_status,
            remote_status=remote_status,
            both_acceptable=both_acceptable,
            reason=reason,
        )

    @classmethod
    def _decision_from_components(
        cls,
        lineage: LineageCompatibility,
        specialization: SpecializationCompatibility,
        validation: ValidationCompatibility,
        comparison: ComparisonCompatibility,
    ) -> tuple[ExchangeStatus, str, str]:
        """Shared status decision for full compare and quick accept checks."""
        # Reject if lineage is incompatible
        if not lineage.compatible:
            return (
                ExchangeStatus.REJECT,
                "reject_lineage_incompatible",
                f"Lineage incompatible: {lineage.reason}",
            )

        # Reject if validation failed
        if not validation.acceptable:
            return (
                ExchangeStatus.REJECT,
                "reject_validation_failed",
                f"Validation not acceptable: {validation.reason}",
            )

        # Reject if comparison not acceptable
        if not comparison.acceptable:
            return (
                ExchangeStatus.REJECT,
                "reject_comparison_failed",
                f"Comparison not acceptable: {comparison.reason}",
            )

        # Downgrade if specialization mismatch but can compose
        if not specialization.compatible and specialization.can_compose:
            return (
                ExchangeStatus.DOWNGRADE,
                "downgrade_specialization_mismatch",
                f"Specialization mismatch but can compose: {specialization.reason}",
            )

        # Downgrade if large generation gap
        if lineage.generation_gap > cls.MAX_GENERATION_GAP_FOR_ACCEPT:
            if lineage.generation_gap <= cls.MAX_GENERATION_GAP_FOR_DOWNGRADE:
                return (
                    ExchangeStatus.DOWNGRADE,
                    "downgrade_large_generation_gap",
                    f"Large generation gap: {lineage.generation_gap}",
                )
            return (
                ExchangeStatus.REJECT,
                "reject_generation_gap_too_large",
                f"Generation gap too large: {lineage.generation_gap}",
            )

        # Downgrade if validation score decreased
        if validation.score_delta < -0.2:
            return (
                ExchangeStatus.DOWNGRADE,
                "downgrade_validation_regression",
                f"Validation score regression: {validation.score_delta:.2f}",
            )

        # Accept if all checks pass
        return (
            ExchangeStatus.ACCEPT,
            "accept_compatible",
            "All compatibility checks passed",
        )

    @classmethod
    def _determine_status(
        cls,
        lineage: LineageCompatibility,
        specialization: SpecializationCompatibility,
        validation: ValidationCompatibility,
        comparison: ComparisonCompatibility,
    ) -> tuple[ExchangeStatus, str, str]:
        """Determine overall exchange status.

        Returns: (status, recommendation, reason)
        """
        return cls._decision_from_components(
            lineage=lineage,
            specialization=specialization,
            validation=validation,
            comparison=comparison,
        )

    @classmethod
    def _fallback_gate(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
    ) -> FederationExchangeGate:
        """Return safe fallback gate on error."""
        return FederationExchangeGate(
            local_adapter_id=local.identity.adapter_id,
            local_generation=local.identity.generation,
            remote_adapter_id=remote.identity.adapter_id,
            remote_generation=remote.identity.generation,
            lineage=LineageCompatibility(
                compatible=False,
                match_score=0.0,
                generation_gap=0,
                is_parent_child=False,
                lineage_hash_match=False,
                reason="fallback_error",
            ),
            specialization=SpecializationCompatibility(
                compatible=False,
                local_spec=local.identity.specialization,
                remote_spec=remote.identity.specialization,
                can_compose=False,
                reason="fallback_error",
            ),
            validation=ValidationCompatibility(
                acceptable=False,
                local_score=0.0,
                remote_score=0.0,
                score_delta=0.0,
                meets_threshold=False,
                reason="fallback_error",
            ),
            comparison=ComparisonCompatibility(
                acceptable=False,
                local_status="unknown",
                remote_status="unknown",
                both_acceptable=False,
                reason="fallback_error",
            ),
            status=ExchangeStatus.REJECT,
            recommendation="reject_error_fallback",
            reason="Error during comparison, using safe fallback",
            fallback_used=True,
            version="1.0",
            timestamp=cls._utc_now(),
        )

    @classmethod
    def quick_check(
        cls,
        local: FederationSummary,
        remote: FederationSummary,
    ) -> bool:
        """Quick compatibility check without full gate construction.

        Phase 11: Fast path for simple accept/reject decisions.
        """
        try:
            lineage = cls._assess_lineage(local, remote)
            specialization = cls._assess_specialization(local, remote)
            validation = cls._assess_validation(local, remote)
            comparison = cls._assess_comparison(local, remote)
            status, _, _ = cls._decision_from_components(
                lineage=lineage,
                specialization=specialization,
                validation=validation,
                comparison=comparison,
            )
            return status == ExchangeStatus.ACCEPT
        except Exception:
            return False
