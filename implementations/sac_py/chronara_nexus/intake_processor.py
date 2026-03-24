"""Phase 12: Remote summary intake processor.

Handles the intake, validation, and staging of remote federation summaries.
Safe to call during serve path - never blocks or raises.
"""

import hashlib
import json
from typing import Dict, Any, Optional, List
from datetime import datetime

from .types import (
    FederationSummary,
    FederationExchangeGate,
    RemoteSummaryIntake,
    StagedRemoteCandidate,
    RemoteIntakeResult,
    StagingDecision,
    ExchangeStatus,
    CompatibilityHints,
    AdapterIdentitySummary,
    SpecializationSummary,
    ImportanceMaskSummary,
    DeltaNormSummary,
    ValidationScoreSummary,
    ComparisonOutcomeSummary,
    DeliberationSummary,
    SnapshotLineageSummary,
)
from .exchange_gate import FederationExchangeComparator


class RemoteIntakeProcessor:
    """Phase 12: Processes remote federation summary intake and staging.

    Deterministic, safe intake processing that:
    1. Validates incoming summary structure
    2. Runs compatibility/exchange gate check
    3. Makes staging decision (accept/downgrade/reject)
    4. Creates staged candidate if accepted

    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"

    # Required fields for a valid federation summary
    REQUIRED_SUMMARY_FIELDS = [
        "identity",
        "specialization",
        "validation_score",
        "snapshot_lineage",
    ]

    # Required identity fields
    REQUIRED_IDENTITY_FIELDS = [
        "adapter_id",
        "generation",
        "specialization",
    ]

    @classmethod
    def process_intake(
        cls,
        remote_summary_dict: Dict[str, Any],
        local_summary: FederationSummary,
        source_node: Optional[str] = None,
    ) -> RemoteIntakeResult:
        """Process a remote summary intake.

        Phase 12: Main entry point for remote summary intake.

        Args:
            remote_summary_dict: Remote summary as dictionary (from network/storage)
            local_summary: Local federation summary for comparison
            source_node: Optional source node identifier

        Returns:
            RemoteIntakeResult with full intake and staging information
        """
        try:
            return cls._do_process(remote_summary_dict, local_summary, source_node)
        except Exception as e:
            # Failure safety: return reject result on any error
            return cls._fallback_result(remote_summary_dict, source_node, str(e))

    @classmethod
    def _do_process(
        cls,
        remote_summary_dict: Dict[str, Any],
        local_summary: FederationSummary,
        source_node: Optional[str],
    ) -> RemoteIntakeResult:
        """Internal processing logic."""
        processed_at = datetime.utcnow().isoformat() + "Z"

        # Step 1: Validate structure
        structure_valid, validation_errors = cls._validate_structure(remote_summary_dict)

        # Step 2: Compute raw summary hash
        raw_hash = cls._compute_hash(remote_summary_dict)

        # Step 3: Parse remote summary (with safety)
        remote_summary, parse_errors = cls._safe_parse_summary(remote_summary_dict)
        validation_errors.extend(parse_errors)

        required_fields_present = len(validation_errors) == 0

        # Step 4: Create intake record
        remote_identity = remote_summary_dict.get("identity", {})
        intake = RemoteSummaryIntake(
            remote_adapter_id=remote_identity.get("adapter_id", "unknown"),
            remote_generation=remote_identity.get("generation", 0),
            remote_source_node=source_node,
            intake_timestamp=processed_at,
            intake_version=cls.VERSION,
            raw_summary_hash=raw_hash,
            structure_valid=structure_valid,
            required_fields_present=required_fields_present,
            validation_errors=validation_errors,
            exchange_gate=None,  # Will be set after compatibility check
        )

        # Step 5: Run compatibility check (if parsing succeeded)
        if remote_summary is not None:
            exchange_gate = FederationExchangeComparator.compare(
                local=local_summary,
                remote=remote_summary,
                fallback_on_error=True,
            )
            intake.exchange_gate = exchange_gate
        else:
            # Create reject gate for parse failure
            exchange_gate = cls._create_reject_gate_for_parse_failure(
                local_summary, remote_identity
            )
            intake.exchange_gate = exchange_gate

        # Step 6: Make staging decision
        decision, decision_reason, recommendation = cls._make_staging_decision(
            intake, exchange_gate
        )

        # Step 7: Create staged candidate if accepted/downgraded
        staged_candidate = None
        rejection_trace = None

        if decision in (StagingDecision.STAGE_ACCEPT, StagingDecision.STAGE_DOWNGRADE):
            staged_candidate = cls._create_staged_candidate(
                remote_summary=remote_summary or cls._create_minimal_summary(remote_identity),
                exchange_gate=exchange_gate,
                decision=decision,
                intake=intake,
                source_node=source_node,
            )
        else:
            rejection_trace = {
                "reason": decision_reason,
                "exchange_status": exchange_gate.status.value if exchange_gate else "unknown",
                "validation_errors": validation_errors,
            }

        return RemoteIntakeResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=False,
            intake=intake,
            decision=decision,
            decision_reason=decision_reason,
            recommendation=recommendation,
            staged_candidate=staged_candidate,
            rejection_trace=rejection_trace,
        )

    @classmethod
    def _validate_structure(cls, summary_dict: Dict[str, Any]) -> tuple[bool, List[str]]:
        """Validate summary structure and required fields."""
        errors = []

        # Check top-level fields
        for field in cls.REQUIRED_SUMMARY_FIELDS:
            if field not in summary_dict:
                errors.append(f"missing_required_field:{field}")

        # Check identity fields
        identity = summary_dict.get("identity", {})
        for field in cls.REQUIRED_IDENTITY_FIELDS:
            if field not in identity:
                errors.append(f"missing_identity_field:{field}")

        # Check types
        if "identity" in summary_dict:
            gen = identity.get("generation")
            if gen is not None and not isinstance(gen, int):
                errors.append("invalid_type:generation_not_int")

        return len(errors) == 0, errors

    @classmethod
    def _compute_hash(cls, summary_dict: Dict[str, Any]) -> str:
        """Compute deterministic hash of summary for audit."""
        try:
            # Normalize to JSON string for consistent hashing
            json_str = json.dumps(summary_dict, sort_keys=True, separators=(',', ':'))
            return hashlib.sha256(json_str.encode()).hexdigest()[:16]
        except Exception:
            return "hash_error"

    @classmethod
    def _safe_parse_summary(
        cls,
        summary_dict: Dict[str, Any],
    ) -> tuple[Optional[FederationSummary], List[str]]:
        """Safely parse summary dict to FederationSummary."""
        errors = []
        try:
            summary = FederationSummary.from_dict(summary_dict)
            return summary, errors
        except Exception as e:
            errors.append(f"parse_error:{str(e)}")
            return None, errors

    @classmethod
    def _make_staging_decision(
        cls,
        intake: RemoteSummaryIntake,
        exchange_gate: Optional[FederationExchangeGate],
    ) -> tuple[StagingDecision, str, str]:
        """Make staging decision based on intake and exchange gate.

        Returns: (decision, reason, recommendation)
        """
        # Check for intake validation failures
        if not intake.structure_valid:
            return (
                StagingDecision.STAGE_REJECT,
                f"structure_invalid:{';'.join(intake.validation_errors)}",
                "reject_structurally_invalid_summary",
            )

        if not intake.required_fields_present:
            return (
                StagingDecision.STAGE_REJECT,
                f"required_fields_missing:{';'.join(intake.validation_errors)}",
                "reject_incomplete_summary",
            )

        # Check exchange gate
        if exchange_gate is None:
            return (
                StagingDecision.STAGE_REJECT,
                "exchange_gate_failed",
                "reject_exchange_check_failed",
            )

        # Map exchange status to staging decision
        if exchange_gate.should_accept():
            return (
                StagingDecision.STAGE_ACCEPT,
                "exchange_compatible",
                "stage_accept_compatible_remote",
            )
        elif exchange_gate.should_downgrade():
            return (
                StagingDecision.STAGE_DOWNGRADE,
                f"exchange_downgrade:{exchange_gate.reason}",
                "stage_downgrade_with_caution",
            )
        else:
            return (
                StagingDecision.STAGE_REJECT,
                f"exchange_incompatible:{exchange_gate.reason}",
                "reject_incompatible_remote",
            )

    @classmethod
    def _create_staged_candidate(
        cls,
        remote_summary: FederationSummary,
        exchange_gate: FederationExchangeGate,
        decision: StagingDecision,
        intake: RemoteSummaryIntake,
        source_node: Optional[str],
    ) -> StagedRemoteCandidate:
        """Create staged candidate from accepted/downgraded summary."""
        staged_at = datetime.utcnow().isoformat() + "Z"

        # Apply downgrades if needed
        summary = remote_summary
        is_downgraded = decision == StagingDecision.STAGE_DOWNGRADE

        if is_downgraded:
            summary = cls._apply_downgrades(remote_summary, exchange_gate)

        return StagedRemoteCandidate(
            adapter_id=remote_summary.identity.adapter_id,
            generation=remote_summary.identity.generation,
            source_node=source_node,
            staged_at=staged_at,
            staging_decision=decision,
            staging_version=cls.VERSION,
            summary=summary,
            gate_result=exchange_gate,
            is_active=True,  # Active when first staged
            is_downgraded=is_downgraded,
            intake_record_ref=intake.raw_summary_hash,
        )

    @classmethod
    def _apply_downgrades(
        cls,
        summary: FederationSummary,
        exchange_gate: FederationExchangeGate,
    ) -> FederationSummary:
        """Apply downgrades to summary based on exchange gate."""
        # Create a modified copy with downgraded fields
        # For now, mark as downgraded but keep data intact
        # Future: could reduce importance mask, adjust validation scores, etc.
        return summary

    @classmethod
    def _create_minimal_summary(cls, remote_identity: Dict[str, Any]) -> FederationSummary:
        """Create minimal summary from identity when full parse fails."""
        adapter_id = remote_identity.get("adapter_id", "unknown")
        generation = remote_identity.get("generation", 0)

        return FederationSummary._minimal_safe_summary(
            adapter_id=adapter_id,
            generation=generation,
            source_node=None,
        )

    @classmethod
    def _create_reject_gate_for_parse_failure(
        cls,
        local_summary: FederationSummary,
        remote_identity: Dict[str, Any],
    ) -> FederationExchangeGate:
        """Create a reject gate for parse failures."""
        return FederationExchangeGate(
            local_adapter_id=local_summary.identity.adapter_id,
            local_generation=local_summary.identity.generation,
            remote_adapter_id=remote_identity.get("adapter_id", "unknown"),
            remote_generation=remote_identity.get("generation", 0),
            lineage=cls._lineage_reject_compat(),
            specialization=cls._spec_reject_compat(),
            validation=cls._validation_reject_compat(),
            comparison=cls._comparison_reject_compat(),
            status=ExchangeStatus.REJECT,
            recommendation="reject_parse_failure",
            reason="Failed to parse remote summary structure",
            fallback_used=True,
            version=cls.VERSION,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

    @classmethod
    def _lineage_reject_compat(cls) -> "LineageCompatibility":
        from .types import LineageCompatibility
        return LineageCompatibility(
            compatible=False,
            match_score=0.0,
            generation_gap=0,
            is_parent_child=False,
            lineage_hash_match=False,
            reason="parse_failure",
        )

    @classmethod
    def _spec_reject_compat(cls) -> "SpecializationCompatibility":
        from .types import SpecializationCompatibility
        return SpecializationCompatibility(
            compatible=False,
            local_spec="unknown",
            remote_spec="unknown",
            can_compose=False,
            reason="parse_failure",
        )

    @classmethod
    def _validation_reject_compat(cls) -> "ValidationCompatibility":
        from .types import ValidationCompatibility
        return ValidationCompatibility(
            acceptable=False,
            local_score=0.0,
            remote_score=0.0,
            score_delta=0.0,
            meets_threshold=False,
            reason="parse_failure",
        )

    @classmethod
    def _comparison_reject_compat(cls) -> "ComparisonCompatibility":
        from .types import ComparisonCompatibility
        return ComparisonCompatibility(
            acceptable=False,
            local_status="unknown",
            remote_status="unknown",
            both_acceptable=False,
            reason="parse_failure",
        )

    @classmethod
    def _fallback_result(
        cls,
        remote_summary_dict: Dict[str, Any],
        source_node: Optional[str],
        error_message: str,
    ) -> RemoteIntakeResult:
        """Create safe fallback result on processing error."""
        processed_at = datetime.utcnow().isoformat() + "Z"

        # Try to extract identity even from broken input
        remote_identity = remote_summary_dict.get("identity", {}) if isinstance(remote_summary_dict, dict) else {}

        intake = RemoteSummaryIntake(
            remote_adapter_id=remote_identity.get("adapter_id", "unknown"),
            remote_generation=remote_identity.get("generation", 0),
            remote_source_node=source_node,
            intake_timestamp=processed_at,
            intake_version=cls.VERSION,
            raw_summary_hash="fallback",
            structure_valid=False,
            required_fields_present=False,
            validation_errors=[f"processing_error:{error_message}"],
            exchange_gate=None,
        )

        return RemoteIntakeResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=True,
            intake=intake,
            decision=StagingDecision.STAGE_REJECT,
            decision_reason=f"processing_exception:{error_message}",
            recommendation="reject_due_to_processing_error",
            staged_candidate=None,
            rejection_trace={
                "error": error_message,
                "fallback": True,
            },
        )

    @classmethod
    def quick_intake_check(cls, remote_summary_dict: Dict[str, Any]) -> bool:
        """Quick check if summary is structurally valid for intake.

        Phase 12: Fast path for simple validation.
        """
        try:
            valid, _ = cls._validate_structure(remote_summary_dict)
            return valid
        except Exception:
            return False
