"""Governor: Validation, promotion, and rollback protocol."""

from datetime import datetime
from typing import Optional, Dict, Any, List
from .types import AdapterRef, ValidationReport, AdapterMode, AdapterSpecialization, AdapterSelection
from .deliberation import DeliberationOutcome
from .common import utc_now


# Backwards compatibility: _utc_now is now utc_now from common module
_utc_now = utc_now


class ValidationTrace:
    """Minimal trace for validation/shadow execution with Phase 9 multi-role review.

    Records:
    - active adapter identity
    - candidate adapter identity
    - specialization combination
    - comparison result
    - deliberation outcome (Phase 8)
    - multi_role_review_summary (Phase 9)
    - fail/approve reason
    """
    def __init__(
        self,
        active: AdapterRef,
        candidate: Optional[AdapterRef],
        status: str,
        passed: bool,
        reason: Optional[str] = None,
        deliberation_outcome: Optional[str] = None,
        deliberation_trace: Optional[Dict[str, Any]] = None,
        multi_role_review_summary: Optional[Dict[str, Any]] = None,
    ):
        self.active_id = active.adapter_id
        self.active_generation = active.generation
        self.active_specialization = active.specialization
        self.candidate_id = candidate.adapter_id if candidate else None
        self.candidate_generation = candidate.generation if candidate else None
        self.candidate_specialization = candidate.specialization if candidate else None
        self.status = status
        self.passed = passed
        self.reason = reason
        self.deliberation_outcome = deliberation_outcome
        self.deliberation_trace = deliberation_trace or {}
        self.multi_role_review_summary = multi_role_review_summary or {}
        # Phase 11: Exchange gate summary
        self.exchange_gate_summary: Optional[Dict[str, Any]] = None
        # Phase 12: Staged remote summary
        self.staged_remote_summary: Optional[Dict[str, Any]] = None
        # Phase 13: Triage result summary
        self.triage_result_summary: Optional[Dict[str, Any]] = None
        # Phase 14: Lifecycle result summary
        self.lifecycle_result_summary: Optional[Dict[str, Any]] = None
        # Phase 15: Conflict resolution summary
        self.conflict_resolution_summary: Optional[Dict[str, Any]] = None
        # Phase 16: Promotion execution summary
        self.promotion_execution_summary: Optional[Dict[str, Any]] = None
        # Phase 20: Coordination summary
        self.coordination_summary: Optional[Dict[str, Any]] = None
        # Phase 21: Remote execution bridge summary
        self.remote_execution_bridge_summary: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "active": {
                "id": self.active_id,
                "generation": self.active_generation,
                "specialization": self.active_specialization.value,
            },
            "candidate": {
                "id": self.candidate_id,
                "generation": self.candidate_generation,
                "specialization": self.candidate_specialization.value if self.candidate_specialization else None,
            } if self.candidate_id else None,
            "status": self.status,
            "passed": self.passed,
            "reason": self.reason,
        }
        if self.deliberation_outcome:
            result["deliberation_outcome"] = self.deliberation_outcome
        if self.deliberation_trace:
            result["deliberation_trace"] = self.deliberation_trace
        if self.multi_role_review_summary:
            result["multi_role_review_summary"] = self.multi_role_review_summary
        if self.exchange_gate_summary:
            result["exchange_gate_summary"] = self.exchange_gate_summary
        if self.staged_remote_summary:
            result["staged_remote_summary"] = self.staged_remote_summary
        if self.triage_result_summary:
            result["triage_result_summary"] = self.triage_result_summary
        if self.lifecycle_result_summary:
            result["lifecycle_result_summary"] = self.lifecycle_result_summary
        if self.conflict_resolution_summary:
            result["conflict_resolution_summary"] = self.conflict_resolution_summary
        if self.promotion_execution_summary:
            result["promotion_execution_summary"] = self.promotion_execution_summary
        if self.coordination_summary:
            result["coordination_summary"] = self.coordination_summary
        if self.remote_execution_bridge_summary:
            result["remote_execution_bridge_summary"] = self.remote_execution_bridge_summary
        return result


class Governor:
    """Manages active/candidate/stable adapter lifecycle with specialization awareness.

    Specialization roles:
    - stable: Long-term validated preferences (fallback base)
    - shared: Cross-task shared parameters (optional augmentation)
    - candidate: Current experiment under evaluation (isolated)
    """

    def __init__(self, initial_adapter: AdapterRef, enable_deliberation: bool = False):
        # Initialize with STABLE specialization
        self.active_adapter = AdapterRef(
            adapter_id=initial_adapter.adapter_id,
            generation=initial_adapter.generation,
            mode=initial_adapter.mode,
            specialization=AdapterSpecialization.STABLE
        )
        self.candidate_adapter: Optional[AdapterRef] = None
        self.shared_adapter: Optional[AdapterRef] = None
        self.stable_adapter = self.active_adapter
        self._pre_promote_stable: Optional[AdapterRef] = None  # For rollback
        self.last_validation_report: Optional[ValidationReport] = None
        self.enable_deliberation = enable_deliberation
        self._deliberation = None
        self._validation_traces: List[ValidationTrace] = []

    def get_adapter_selection(self) -> AdapterSelection:
        """Get current specialization-aware adapter selection."""
        return AdapterSelection(
            stable=self.stable_adapter,
            shared=self.shared_adapter,
            candidate=self.candidate_adapter
        )

    def _get_deliberation(self):
        """Lazy load deliberation to avoid circular import."""
        if self._deliberation is None and self.enable_deliberation:
            from .deliberation import BoundedDeliberation
            self._deliberation = BoundedDeliberation()
        return self._deliberation

    def create_shadow_request(self, candidate: AdapterRef, input_data: bytes) -> Dict[str, Any]:
        """Create a shadow eval request for candidate adapter."""
        # Ensure candidate has CANDIDATE specialization
        candidate = AdapterRef(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            mode=candidate.mode,
            specialization=AdapterSpecialization.CANDIDATE
        )
        self.candidate_adapter = candidate
        return {
            "active_adapter": {
                "adapter_id": self.active_adapter.adapter_id,
                "generation": self.active_adapter.generation,
                "mode": self.active_adapter.mode.value,
                "specialization": self.active_adapter.specialization.value,
            },
            "candidate_adapter": {
                "adapter_id": candidate.adapter_id,
                "generation": candidate.generation,
                "mode": AdapterMode.SHADOW_EVAL.value,
                "specialization": AdapterSpecialization.CANDIDATE.value,
            },
            "input": input_data,
        }

    def validate_from_atom_result(self, candidate: AdapterRef, atom_result: Dict[str, Any]) -> ValidationReport:
        """Validate candidate using atom validation_result."""
        # Ensure candidate has CANDIDATE specialization
        candidate = AdapterRef(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            mode=candidate.mode,
            specialization=AdapterSpecialization.CANDIDATE
        )
        self.candidate_adapter = candidate

        # Phase 8: Structured deliberation pre-processing
        deliberation_outcome = None
        deliberation_quality = None
        if self.enable_deliberation:
            deliberation = self._get_deliberation()
            if deliberation:
                try:
                    from .deliberation import DeliberationRequest, DeliberationOutcome
                    # Create deliberation input from atom_result
                    delib_obs = {
                        "atom_result": atom_result,
                        "candidate_id": candidate.adapter_id,
                        "candidate_generation": candidate.generation,
                    }
                    request = DeliberationRequest(observation=delib_obs)
                    result = deliberation.deliberate(request)

                    deliberation_outcome = result.outcome.value
                    deliberation_quality = result.quality_score

                    # Phase 8: Handle structured outcomes
                    if result.outcome == DeliberationOutcome.REJECT:
                        # Reject candidate based on deliberation
                        report = ValidationReport(
                            adapter_id=candidate.adapter_id,
                            generation=candidate.generation,
                            passed=False,
                            metric_summary={
                                "source": "deliberation_rejected",
                                "deliberation_outcome": result.outcome.value,
                                "quality_score": result.quality_score,
                            },
                            reason=f"deliberation quality check failed: {result.verifier_judgement.get('reason', 'unknown')}",
                            specialization_summary={
                                AdapterSpecialization.CANDIDATE: {
                                    "status": "rejected",
                                    "source": "deliberation",
                                    "outcome": result.outcome.value,
                                }
                            },
                            deliberation_outcome=result.outcome.value,
                            deliberation_quality=result.quality_score,
                        )
                        self.last_validation_report = report

                        # Record trace with deliberation info
                        trace = ValidationTrace(
                            active=self.active_adapter,
                            candidate=candidate,
                            status="deliberation_rejected",
                            passed=False,
                            reason="deliberation quality check failed",
                            deliberation_outcome=result.outcome.value,
                            deliberation_trace=result.to_trace_dict(),
                        )
                        self._validation_traces.append(trace)
                        return report
                    elif result.outcome == DeliberationOutcome.STRATEGY_ONLY:
                        # Strategy signal - mark but continue validation
                        # The candidate might still be valid but strategy layer takes priority
                        pass
                    # CANDIDATE_READY continues to normal validation

                except Exception:
                    # Fallback on deliberation failure
                    pass

        # Check if atom returned validation_result
        validation_result = atom_result.get("validation_result")
        if validation_result:
            # Use atom's validation result
            active_match = (
                validation_result.get("active_adapter_id") == self.active_adapter.adapter_id
                and validation_result.get("active_generation") == self.active_adapter.generation
            )
            candidate_match = (
                validation_result.get("candidate_adapter_id") == candidate.adapter_id
                and validation_result.get("candidate_generation") == candidate.generation
            )
            lineage_valid = validation_result.get("lineage_valid", False) and active_match and candidate_match
            output_match = validation_result.get("output_match", False)
            kv_count_match = validation_result.get("kv_count_match", False)
            is_acceptable = (
                validation_result.get("is_acceptable", False)
                and output_match
                and kv_count_match
            )

            generation_advanced = candidate.generation > self.active_adapter.generation
            passed = lineage_valid and is_acceptable and generation_advanced

            metric_summary = {
                "active_match": active_match,
                "candidate_match": candidate_match,
                "lineage_valid": lineage_valid,
                "output_match": output_match,
                "kv_count_match": kv_count_match,
                "is_acceptable": is_acceptable,
                "generation_advanced": generation_advanced,
                "source": "atom_validation_result",
            }

            reason = None
            if not passed:
                if not active_match or not candidate_match or not lineage_valid:
                    reason = "adapter lineage invalid"
                elif not is_acceptable:
                    reason = "validation not acceptable"
                elif not generation_advanced:
                    reason = "generation not advanced"
        else:
            # Fallback to exec_response lineage check
            exec_response = atom_result.get("exec_response", {})
            adapter_id = exec_response.get("adapter_id")
            adapter_generation = exec_response.get("adapter_generation")

            lineage_match = (
                adapter_id == candidate.adapter_id
                and adapter_generation == candidate.generation
            )

            passed = lineage_match and candidate.generation > self.active_adapter.generation

            metric_summary = {
                "lineage_match": lineage_match,
                "generation_advanced": candidate.generation > self.active_adapter.generation,
                "source": "exec_response_lineage",
            }

            reason = None if passed else "lineage mismatch or generation not advanced"

        # Build specialization-aware summary
        specialization_summary = {
            AdapterSpecialization.CANDIDATE: {
                "status": "validated" if passed else "rejected",
                "generation": candidate.generation,
            },
            AdapterSpecialization.STABLE: {
                "generation": self.stable_adapter.generation if self.stable_adapter else None,
                "unchanged": True,
            }
        }
        if self.shared_adapter:
            specialization_summary[AdapterSpecialization.SHARED] = {
                "generation": self.shared_adapter.generation,
                "unchanged": True,
            }

        # Include deliberation info in metric_summary if available
        if deliberation_outcome:
            metric_summary["deliberation_outcome"] = deliberation_outcome
        if deliberation_quality is not None:
            metric_summary["deliberation_quality"] = deliberation_quality

        report = ValidationReport(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            passed=passed,
            metric_summary=metric_summary,
            reason=reason,
            specialization_summary=specialization_summary,
            deliberation_outcome=deliberation_outcome,
            deliberation_quality=deliberation_quality,
        )
        self.last_validation_report = report

        # Record validation trace with deliberation info
        trace = ValidationTrace(
            active=self.active_adapter,
            candidate=candidate,
            status="candidate_validated" if passed else "candidate_rejected",
            passed=passed,
            reason=reason,
            deliberation_outcome=deliberation_outcome,
            deliberation_trace={"quality_score": deliberation_quality} if deliberation_quality else None,
        )
        self._validation_traces.append(trace)

        return report

    def validate_from_lineage(self, candidate: AdapterRef, atom_result: Dict[str, Any]) -> ValidationReport:
        """Alias for validate_from_atom_result for backward compatibility."""
        return self.validate_from_atom_result(candidate, atom_result)

    def validate_from_comparison(self, candidate: AdapterRef, comparison_result: Dict[str, Any]) -> ValidationReport:
        """Validate candidate using shadow comparison result with Phase 7 deepening.

        Consumes structured comparison result including:
        - status (active_only, candidate_observed, lineage_mismatch, etc.)
        - promote_recommendation (approve, reject, undecided, failed)
        - active_summary / candidate_summary with specialization
        - lineage_valid, specialization_valid flags
        """
        # Ensure candidate has CANDIDATE specialization
        candidate = AdapterRef(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            mode=candidate.mode,
            specialization=AdapterSpecialization.CANDIDATE
        )
        self.candidate_adapter = candidate

        # Extract Phase 7 comparison fields
        status = comparison_result.get("status", "unknown")
        promote_rec = comparison_result.get("promote_recommendation", "undecided")

        # Extract adapter summaries if present
        active_summary = comparison_result.get("active_summary", {})
        candidate_summary = comparison_result.get("candidate_summary")

        # Core validation checks
        lineage_valid = comparison_result.get("lineage_valid", False)
        specialization_valid = comparison_result.get("specialization_valid", False)
        output_match = comparison_result.get("output_match", False)
        kv_count_match = comparison_result.get("kv_count_match", False)
        generation_advanced = candidate.generation > self.active_adapter.generation

        # Determine acceptability based on Phase 7 fields (with backward compatibility)
        if "is_acceptable" in comparison_result:
            # Old format: use explicit is_acceptable
            is_acceptable = comparison_result["is_acceptable"] and output_match and kv_count_match
        elif promote_rec == "approve":
            is_acceptable = lineage_valid and specialization_valid and output_match and kv_count_match
        elif promote_rec == "reject":
            is_acceptable = False
        else:
            # Undecided or failed: use heuristic
            is_acceptable = lineage_valid and output_match and kv_count_match

        # Phase 9: Extract multi-role review info for passed determination
        multi_role_review = comparison_result.get("multi_role_review", {})
        consensus_status = multi_role_review.get("consensus_status", "")
        has_disagreement = multi_role_review.get("has_disagreement", False)

        # Multi-role review blocks: consensus_reject, consensus_strategy_only, or disagreement_escalate blocks passed
        multi_role_blocks = False
        if multi_role_review:
            if consensus_status == "consensus_reject":
                multi_role_blocks = True
            elif consensus_status == "consensus_strategy_only":
                # consensus_strategy_only should not permit promotion to stable
                multi_role_blocks = True
            elif consensus_status == "disagreement_escalate" and has_disagreement:
                multi_role_blocks = True

        # Promote gate decision (Phase 7 deepening with backward compatibility)
        # If using old format (no status field), fall back to basic checks
        has_new_format = "status" in comparison_result
        if has_new_format:
            passed = (
                lineage_valid
                and specialization_valid
                and is_acceptable
                and generation_advanced
                and promote_rec != "reject"
                and status not in ("lineage_mismatch", "specialization_mismatch", "unavailable", "active_only")
                and not multi_role_blocks  # Phase 9: multi-role review can block
            )
        else:
            # Backward compatibility: old format
            passed = lineage_valid and is_acceptable and generation_advanced and not multi_role_blocks

        # Build comprehensive metric summary
        metric_summary = {
            "lineage_valid": lineage_valid,
            "specialization_valid": specialization_valid,
            "output_match": output_match,
            "kv_count_match": kv_count_match,
            "is_acceptable": is_acceptable,
            "generation_advanced": generation_advanced,
            "status": status,
            "promote_recommendation": promote_rec,
            "source": "shadow_comparison",
        }

        # Add adapter identity info if available
        if active_summary:
            metric_summary["active_identity"] = {
                "adapter_id": active_summary.get("adapter_id"),
                "generation": active_summary.get("generation"),
                "specialization": active_summary.get("specialization"),
            }
        if candidate_summary:
            metric_summary["candidate_identity"] = {
                "adapter_id": candidate_summary.get("adapter_id"),
                "generation": candidate_summary.get("generation"),
                "specialization": candidate_summary.get("specialization"),
            }

        # Determine reason for failure
        reason = None
        if not passed:
            if not lineage_valid:
                reason = "adapter lineage invalid"
            elif has_new_format and not specialization_valid:
                reason = "specialization mismatch"
            elif has_new_format and status == "lineage_mismatch":
                reason = "lineage mismatch detected"
            elif has_new_format and status == "specialization_mismatch":
                reason = "specialization chain invalid"
            elif not is_acceptable:
                reason = "shadow behavior not acceptable"
            elif not generation_advanced:
                reason = "generation not advanced"
            elif has_new_format and promote_rec == "reject":
                reason = "promote recommendation is reject"
            else:
                reason = "validation failed"

        # Build specialization-aware summary
        specialization_summary = {
            AdapterSpecialization.CANDIDATE: {
                "status": "validated" if passed else "rejected",
                "generation": candidate.generation,
                "specialization_valid": specialization_valid,
            },
            AdapterSpecialization.STABLE: {
                "generation": self.stable_adapter.generation if self.stable_adapter else None,
                "unchanged": True,
            }
        }
        if self.shared_adapter:
            specialization_summary[AdapterSpecialization.SHARED] = {
                "generation": self.shared_adapter.generation,
                "unchanged": True,
            }

        # Extract deliberation info from comparison result
        delib_outcome = comparison_result.get("deliberation_outcome")
        delib_trace = comparison_result.get("deliberation_trace")
        delib_quality = comparison_result.get("deliberation_quality")

        # Phase 9: Extract multi-role review info from comparison result
        multi_role_review = comparison_result.get("multi_role_review", {})
        consensus_status = multi_role_review.get("consensus_status")
        has_disagreement = multi_role_review.get("has_disagreement", False)

        # Add deliberation fields to metric_summary
        if delib_outcome:
            metric_summary["deliberation_outcome"] = delib_outcome
        if delib_quality is not None:
            metric_summary["deliberation_quality"] = delib_quality

        # Phase 9: Add multi-role review fields to metric_summary
        if consensus_status:
            metric_summary["consensus_status"] = consensus_status
        if multi_role_review:
            # Always include has_role_disagreement if multi_role_review is present
            metric_summary["has_role_disagreement"] = has_disagreement

        # Phase 9: Extract consensus info for ValidationReport
        consensus_status_for_report = multi_role_review.get("consensus_status") if multi_role_review else None
        has_disagreement_for_report = multi_role_review.get("has_disagreement") if multi_role_review else None

        report = ValidationReport(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            passed=passed,
            metric_summary=metric_summary,
            reason=reason,
            specialization_summary=specialization_summary,
            deliberation_outcome=delib_outcome,
            deliberation_quality=delib_quality,
            consensus_status=consensus_status_for_report,
            has_role_disagreement=has_disagreement_for_report,
        )
        self.last_validation_report = report

        # Record validation trace (Phase 7 + Phase 8 + Phase 9)
        trace = ValidationTrace(
            active=self.active_adapter,
            candidate=candidate,
            status=status,
            passed=passed,
            reason=reason,
            deliberation_outcome=delib_outcome,
            deliberation_trace=delib_trace,
            multi_role_review_summary=multi_role_review if multi_role_review else None,
        )
        self._validation_traces.append(trace)

        return report

    def validate_candidate(self, candidate: AdapterRef) -> ValidationReport:
        """Minimal validation logic with real metric summary."""
        # Ensure candidate has CANDIDATE specialization
        candidate = AdapterRef(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            mode=candidate.mode,
            specialization=AdapterSpecialization.CANDIDATE
        )
        self.candidate_adapter = candidate

        generation_advanced = candidate.generation > self.active_adapter.generation

        # Real metric: check generation delta
        generation_delta = candidate.generation - self.active_adapter.generation

        passed = generation_advanced and generation_delta == 1

        metric_summary = {
            "generation_delta": generation_delta,
            "generation_advanced": generation_advanced,
            "expected_delta": 1,
        }

        reason = None
        if not passed:
            if not generation_advanced:
                reason = "generation not advanced"
            elif generation_delta != 1:
                reason = f"generation delta {generation_delta} != 1"

        # Build specialization-aware summary
        specialization_summary = {
            AdapterSpecialization.CANDIDATE: {
                "status": "validated" if passed else "rejected",
                "generation": candidate.generation,
            },
            AdapterSpecialization.STABLE: {
                "generation": self.stable_adapter.generation if self.stable_adapter else None,
                "unchanged": True,
            }
        }
        if self.shared_adapter:
            specialization_summary[AdapterSpecialization.SHARED] = {
                "generation": self.shared_adapter.generation,
                "unchanged": True,
            }

        report = ValidationReport(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            passed=passed,
            metric_summary=metric_summary,
            reason=reason,
            specialization_summary=specialization_summary
        )
        self.last_validation_report = report
        return report

    def promote_candidate(self, candidate: AdapterRef) -> bool:
        """Promote candidate to stable/active.

        Candidate (CANDIDATE) -> Stable (STABLE)
        Shared adapter unchanged.
        Saves previous stable for potential rollback.
        """
        report = self.last_validation_report
        if report is None:
            return False
        if not report.passed:
            return False
        if report.adapter_id != candidate.adapter_id or report.generation != candidate.generation:
            return False

        # Save current stable for rollback
        self._pre_promote_stable = self.stable_adapter

        # Promote candidate to stable: upgrade specialization to STABLE
        promoted = AdapterRef(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            mode=candidate.mode,
            specialization=AdapterSpecialization.STABLE
        )

        self.stable_adapter = promoted
        self.active_adapter = promoted
        self.candidate_adapter = None
        self.last_validation_report = None
        return True

    def rollback_to_stable(self):
        """Rollback active to last stable.

        If pre-promote stable exists, restores it.
        Otherwise uses current stable_adapter.
        Preserves shared adapter if exists.
        Clears candidate.
        """
        if self._pre_promote_stable is not None:
            self.stable_adapter = self._pre_promote_stable
            self._pre_promote_stable = None
        self.active_adapter = self.stable_adapter
        self.candidate_adapter = None

    def mark_stable(self):
        """Mark current active as stable.

        Clears pre-promote state as the promotion is now committed.
        """
        self.stable_adapter = AdapterRef(
            adapter_id=self.active_adapter.adapter_id,
            generation=self.active_adapter.generation,
            mode=self.active_adapter.mode,
            specialization=AdapterSpecialization.STABLE
        )
        # Clear pre-promote state as promotion is committed
        self._pre_promote_stable = None

    def rollback_specialization(self, spec: AdapterSpecialization):
        """Rollback specific specialization.

        - STABLE: Rollback to previous stable (if tracked externally)
        - SHARED: Clear shared adapter
        - CANDIDATE: Clear candidate adapter
        """
        if spec == AdapterSpecialization.STABLE:
            self.rollback_to_stable()
        elif spec == AdapterSpecialization.SHARED:
            self.shared_adapter = None
        elif spec == AdapterSpecialization.CANDIDATE:
            self.candidate_adapter = None

    def decide(self, candidate: AdapterRef, validation_report: ValidationReport) -> str:
        """Decide whether to promote or reject candidate."""
        if validation_report.passed:
            return "promote"
        else:
            return "reject"

    def get_validation_traces(self) -> List[ValidationTrace]:
        """Get all validation traces recorded."""
        return self._validation_traces.copy()

    def get_last_validation_trace(self) -> Optional[ValidationTrace]:
        """Get the most recent validation trace."""
        if self._validation_traces:
            return self._validation_traces[-1]
        return None

    def clear_validation_traces(self):
        """Clear all validation traces."""
        self._validation_traces.clear()

    def can_promote_based_on_comparison(self, comparison_result: Dict[str, Any]) -> bool:
        """Check if comparison result permits promotion (Phase 7 + Phase 9 gate).

        Phase 7: Requires:
        - lineage_valid
        - specialization_valid
        - promote_recommendation == "approve"
        - status == "candidate_observed"

        Phase 9: Also checks multi-role review:
        - No role disagreement (or disagreement resolved to accept)
        - consensus_status allows promotion
        """
        # Must have explicit approve recommendation
        if comparison_result.get("promote_recommendation") != "approve":
            return False

        # Must have valid lineage and specialization
        if not comparison_result.get("lineage_valid", False):
            return False
        if not comparison_result.get("specialization_valid", False):
            return False

        # Status must indicate successful observation
        # Phase 9: active_only means "no candidate to compare" - should NOT permit promotion
        status = comparison_result.get("status", "")
        if status != "candidate_observed":
            return False

        # Must have candidate summary present
        if comparison_result.get("candidate_summary") is None:
            return False

        # Phase 9: Check multi-role review for role disagreement
        multi_role_review = comparison_result.get("multi_role_review", {})
        if multi_role_review:
            consensus_status = multi_role_review.get("consensus_status", "")
            has_disagreement = multi_role_review.get("has_disagreement", False)

            # Disagreement_escalate should not permit promotion unless resolved
            if consensus_status == "disagreement_escalate" and has_disagreement:
                # Even with approve recommendation, disagreement blocks promotion
                return False

            # Only consensus_accept permits promotion
            if consensus_status not in ("consensus_accept", "escalated_accept"):
                # Other statuses (consensus_strategy_only, consensus_reject) block promotion
                if consensus_status in ("consensus_strategy_only", "consensus_reject"):
                    return False
                # Unknown consensus status - default deny
                return False

        return True

    def extract_federation_summary(
        self,
        consolidator_params: Optional[Dict[str, float]] = None,
        source_node: Optional[str] = None,
    ) -> "FederationSummary":
        """Extract federation-ready summary from Governor state.

        Phase 10: Creates minimal, structured summary for cross-node exchange.
        Safe to call during serve path - never blocks or raises.
        """
        from datetime import datetime
        from .types import (
            FederationSummary, AdapterIdentitySummary, SpecializationSummary,
            ImportanceMaskSummary, DeltaNormSummary, ValidationScoreSummary,
            ComparisonOutcomeSummary, DeliberationSummary, SnapshotLineageSummary,
            CompatibilityHints,
        )

        try:
            # Extract identity from active adapter
            identity = AdapterIdentitySummary(
                adapter_id=self.active_adapter.adapter_id,
                generation=self.active_adapter.generation,
                parent_generation=(
                    self.stable_adapter.generation
                    if self.stable_adapter and self.stable_adapter.generation != self.active_adapter.generation
                    else None
                ),
                specialization=self.active_adapter.specialization.value,
                mode=self.active_adapter.mode.value,
            )

            # Extract specialization summary
            specialization = SpecializationSummary(
                stable_generation=self.stable_adapter.generation if self.stable_adapter else self.active_adapter.generation,
                shared_generation=self.shared_adapter.generation if self.shared_adapter else None,
                candidate_generation=self.candidate_adapter.generation if self.candidate_adapter else None,
                active_specialization=self.active_adapter.specialization.value,
            )

            # Extract importance mask from params (bounded)
            top_keys = []
            scores = {}
            threshold = 0.0
            compression_ratio = 1.0
            if consolidator_params:
                sorted_params = sorted(
                    consolidator_params.items(),
                    key=lambda x: abs(x[1]),
                    reverse=True
                )
                # Keep top 10 keys max (bounded)
                top_keys = [k for k, v in sorted_params[:10]]
                scores = {k: abs(v) for k, v in sorted_params[:10]}
                if scores:
                    threshold = min(scores.values()) if len(scores) < len(consolidator_params) else 0.0
                    compression_ratio = len(top_keys) / len(consolidator_params) if consolidator_params else 1.0

            importance_mask = ImportanceMaskSummary(
                top_keys=top_keys,
                scores=scores,
                threshold=threshold,
                compression_ratio=compression_ratio,
            )

            # Extract delta norm (minimal)
            delta_norm = DeltaNormSummary(
                l1_norm=sum(abs(v) for v in (consolidator_params or {}).values()),
                l2_norm=(sum(v**2 for v in (consolidator_params or {}).values())) ** 0.5,
                max_abs=max((abs(v) for v in (consolidator_params or {}).values()), default=0.0),
                param_count=len(consolidator_params) if consolidator_params else 0,
                relative_to_parent=None,  # Would need parent params to compute
            )

            # Extract validation score from last report
            report = self.last_validation_report
            if report:
                metric = report.metric_summary
                validation_score = ValidationScoreSummary(
                    passed=report.passed,
                    lineage_valid=metric.get("lineage_valid", False),
                    specialization_valid=metric.get("specialization_valid", False),
                    output_match=metric.get("output_match", False),
                    kv_count_match=metric.get("kv_count_match", False),
                    generation_advanced=metric.get("generation_advanced", False),
                    score=1.0 if report.passed else 0.0,
                )
            else:
                validation_score = ValidationScoreSummary(
                    passed=False,
                    lineage_valid=False,
                    specialization_valid=False,
                    output_match=False,
                    kv_count_match=False,
                    generation_advanced=False,
                    score=0.0,
                )

            # Extract comparison outcome from last trace
            comparison_outcome = ComparisonOutcomeSummary(
                status="unknown",
                promote_recommendation="undecided",
                lineage_valid=False,
                specialization_valid=False,
                is_acceptable=False,
            )

            # Extract deliberation from last report
            deliberation = DeliberationSummary(
                outcome=report.deliberation_outcome if report and report.deliberation_outcome else "candidate_ready",
                quality_score=report.deliberation_quality if report and report.deliberation_quality is not None else 0.5,
                confidence=0.5,
                consensus_status=report.consensus_status if report else None,
                has_disagreement=report.has_role_disagreement if report else None,
                escalation_used=False,
            )

            # Extract snapshot lineage
            lineage_hash = f"{identity.adapter_id}:{identity.generation}:{identity.specialization}"
            snapshot_lineage = SnapshotLineageSummary(
                snapshot_id=f"{identity.adapter_id}-gen{identity.generation}",
                adapter_id=identity.adapter_id,
                generation=identity.generation,
                specialization=identity.specialization,
                parent_snapshot_id=(
                    f"{identity.adapter_id}-gen{identity.parent_generation}"
                    if identity.parent_generation else None
                ),
                lineage_hash=lineage_hash,
            )

            # Compute compatibility hints
            compatibility = CompatibilityHints(
                min_compatible_generation=max(0, identity.generation - 2),
                max_compatible_generation=identity.generation + 1,
                required_specialization=None,  # Allow cross-specialization
                min_validation_score=0.5,
                requires_consensus_accept=False,
                format_version="1.0",
            )

            return FederationSummary(
                identity=identity,
                specialization=specialization,
                importance_mask=importance_mask,
                delta_norm=delta_norm,
                validation_score=validation_score,
                comparison_outcome=comparison_outcome,
                deliberation=deliberation,
                snapshot_lineage=snapshot_lineage,
                compatibility=compatibility,
                export_timestamp=_utc_now(),
                export_version="1.0",
                source_node=source_node,
            )

        except Exception:
            # Failure safety: return minimal safe summary on any error
            return self._minimal_federation_summary(source_node)

    def _minimal_federation_summary(self, source_node: Optional[str] = None) -> "FederationSummary":
        """Return minimal safe federation summary on extraction failure."""
        from datetime import datetime
        from .types import (
            FederationSummary, AdapterIdentitySummary, SpecializationSummary,
            ImportanceMaskSummary, DeltaNormSummary, ValidationScoreSummary,
            ComparisonOutcomeSummary, DeliberationSummary, SnapshotLineageSummary,
            CompatibilityHints,
        )

        identity = AdapterIdentitySummary(
            adapter_id=self.active_adapter.adapter_id if self.active_adapter else "unknown",
            generation=self.active_adapter.generation if self.active_adapter else 0,
            parent_generation=None,
            specialization="stable",
            mode="serve",
        )

        return FederationSummary(
            identity=identity,
            specialization=SpecializationSummary(
                stable_generation=identity.generation,
                shared_generation=None,
                candidate_generation=None,
                active_specialization="stable",
            ),
            importance_mask=ImportanceMaskSummary(
                top_keys=[],
                scores={},
                threshold=0.0,
                compression_ratio=1.0,
            ),
            delta_norm=DeltaNormSummary(
                l1_norm=0.0,
                l2_norm=0.0,
                max_abs=0.0,
                param_count=0,
                relative_to_parent=None,
            ),
            validation_score=ValidationScoreSummary(
                passed=False,
                lineage_valid=False,
                specialization_valid=False,
                output_match=False,
                kv_count_match=False,
                generation_advanced=False,
                score=0.0,
            ),
            comparison_outcome=ComparisonOutcomeSummary(
                status="unknown",
                promote_recommendation="undecided",
                lineage_valid=False,
                specialization_valid=False,
                is_acceptable=False,
            ),
            deliberation=DeliberationSummary(
                outcome="candidate_ready",
                quality_score=0.5,
                confidence=0.5,
                consensus_status=None,
                has_disagreement=None,
                escalation_used=False,
            ),
            snapshot_lineage=SnapshotLineageSummary(
                snapshot_id=f"{identity.adapter_id}-gen{identity.generation}",
                adapter_id=identity.adapter_id,
                generation=identity.generation,
                specialization=identity.specialization,
                parent_snapshot_id=None,
                lineage_hash="",
            ),
            compatibility=CompatibilityHints(
                min_compatible_generation=0,
                max_compatible_generation=0,
                required_specialization=None,
                min_validation_score=0.0,
                requires_consensus_accept=False,
                format_version="1.0",
            ),
            export_timestamp=_utc_now(),
            export_version="1.0",
            source_node=source_node,
        )

    def check_exchange_compatibility(
        self,
        remote_summary: "FederationSummary",
        local_params: Optional[Dict[str, float]] = None,
    ) -> "FederationExchangeGate":
        """Check compatibility with remote federation summary.

        Phase 11: Exchange gate entry point for Governor.
        Safe to call during serve path - never blocks or raises.

        Args:
            remote_summary: Remote federation summary to compare against
            local_params: Optional local parameters for summary extraction

        Returns:
            FederationExchangeGate with full compatibility assessment
        """
        from .exchange_gate import FederationExchangeComparator

        try:
            # Extract local summary
            local_summary = self.extract_federation_summary(
                consolidator_params=local_params
            )

            # Compare using exchange comparator
            return FederationExchangeComparator.compare(
                local=local_summary,
                remote=remote_summary,
                fallback_on_error=True,
            )

        except Exception:
            # Failure safety: return reject gate
            from .types import (
                FederationExchangeGate,
                ExchangeStatus,
                LineageCompatibility,
                SpecializationCompatibility,
                ValidationCompatibility,
                ComparisonCompatibility,
            )
            from datetime import datetime

            return FederationExchangeGate(
                local_adapter_id=self.active_adapter.adapter_id,
                local_generation=self.active_adapter.generation,
                remote_adapter_id=remote_summary.identity.adapter_id,
                remote_generation=remote_summary.identity.generation,
                lineage=LineageCompatibility(
                    compatible=False,
                    match_score=0.0,
                    generation_gap=0,
                    is_parent_child=False,
                    lineage_hash_match=False,
                    reason="extraction_error",
                ),
                specialization=SpecializationCompatibility(
                    compatible=False,
                    local_spec=self.active_adapter.specialization.value,
                    remote_spec=remote_summary.identity.specialization,
                    can_compose=False,
                    reason="extraction_error",
                ),
                validation=ValidationCompatibility(
                    acceptable=False,
                    local_score=0.0,
                    remote_score=remote_summary.validation_score.score,
                    score_delta=0.0,
                    meets_threshold=False,
                    reason="extraction_error",
                ),
                comparison=ComparisonCompatibility(
                    acceptable=False,
                    local_status="unknown",
                    remote_status=remote_summary.comparison_outcome.status,
                    both_acceptable=False,
                    reason="extraction_error",
                ),
                status=ExchangeStatus.REJECT,
                recommendation="reject_extraction_error",
                reason="Error extracting local summary for comparison",
                fallback_used=True,
                version="1.1",
                timestamp=_utc_now(),
            )

    def can_accept_remote_summary(
        self,
        remote_summary: "FederationSummary",
    ) -> bool:
        """Quick check if remote summary can be accepted.

        Phase 11: Fast path for simple accept/reject decisions.
        """
        from .exchange_gate import FederationExchangeComparator

        try:
            local_summary = self.extract_federation_summary()
            gate = FederationExchangeComparator.compare(
                local=local_summary,
                remote=remote_summary,
            )
            return gate.should_accept()
        except Exception:
            return False

    def incorporate_exchange_gate(
        self,
        gate: "FederationExchangeGate",
    ) -> bool:
        """Incorporate exchange gate result into Governor state.

        Phase 11: Updates validation traces with exchange information.
        Does NOT modify adapter state - only records for audit.

        Returns:
            True if incorporation succeeded
        """
        try:
            # Add exchange info to last validation trace if exists
            if self._validation_traces and len(self._validation_traces) > 0:
                last_trace = self._validation_traces[-1]
                if not hasattr(last_trace, 'exchange_gate_summary'):
                    last_trace.exchange_gate_summary = {}
                last_trace.exchange_gate_summary = {
                    "remote_adapter_id": gate.remote_adapter_id,
                    "remote_generation": gate.remote_generation,
                    "status": gate.status.value,
                    "recommendation": gate.recommendation,
                    "lineage_compatible": gate.lineage.compatible,
                    "specialization_compatible": gate.specialization.compatible,
                    "validation_acceptable": gate.validation.acceptable,
                }
            return True
        except Exception:
            return False

    def process_remote_intake(
        self,
        remote_summary_dict: Dict[str, Any],
        source_node: Optional[str] = None,
    ) -> "RemoteIntakeResult":
        """Process remote summary intake with full staging.

        Phase 12: Main entry point for remote summary intake.
        Safe to call during serve path - never blocks or raises.

        Args:
            remote_summary_dict: Remote summary as dictionary
            source_node: Optional source node identifier

        Returns:
            RemoteIntakeResult with full intake and staging information
        """
        from .intake_processor import RemoteIntakeProcessor
        from .remote_execution_bridge import BridgeDecision, prepare_remote_execution_input

        try:
            # Extract local summary for comparison
            local_summary = self.extract_federation_summary()
            prepared = prepare_remote_execution_input(
                remote_payload=remote_summary_dict,
                local_summary=local_summary,
                source_node=source_node,
            )

            if prepared.bridge_summary:
                self._record_remote_execution_bridge(prepared.bridge_summary)

            if prepared.bridge_decision == BridgeDecision.BRIDGE_REJECT:
                return self._bridge_reject_intake_result(prepared)

            # Process intake
            result = RemoteIntakeProcessor.process_intake(
                remote_summary_dict=prepared.normalized_summary_dict,
                local_summary=local_summary,
                source_node=prepared.source_node,
            )

            # Record in traces if staging succeeded
            if result.is_staged():
                self._record_staged_remote(result)

            return result

        except Exception:
            # Failure safety: return reject result
            return self._fallback_intake_result(remote_summary_dict, source_node)

    def _record_remote_execution_bridge(self, bridge_summary: Dict[str, Any]) -> bool:
        """Record remote execution bridge summary in validation traces."""
        try:
            if self._validation_traces:
                self._validation_traces[-1].remote_execution_bridge_summary = bridge_summary
            return True
        except Exception:
            return False

    def _bridge_reject_intake_result(
        self,
        prepared_input: "PreparedRemoteInput",
    ) -> "RemoteIntakeResult":
        """Create structured reject result for bridge_reject payloads."""
        from .types import RemoteIntakeResult, RemoteSummaryIntake, StagingDecision

        processed_at = _utc_now()
        intake = RemoteSummaryIntake(
            remote_adapter_id=prepared_input.adapter_id,
            remote_generation=prepared_input.generation,
            remote_source_node=prepared_input.source_node,
            intake_timestamp=processed_at,
            intake_version="1.0",
            raw_summary_hash=prepared_input.bridge_summary.get("execution_id", "bridge-reject") if prepared_input.bridge_summary else "bridge-reject",
            structure_valid=True,
            required_fields_present=True,
            validation_errors=[prepared_input.reject_reason or "bridge_rejected"],
            exchange_gate=None,
        )
        return RemoteIntakeResult(
            processed_at=processed_at,
            processor_version="1.0",
            fallback_used=False,
            intake=intake,
            decision=StagingDecision.STAGE_REJECT,
            decision_reason=prepared_input.reject_reason or "bridge_rejected",
            recommendation="retain_reject_trace_only",
            staged_candidate=None,
            rejection_trace={
                "bridge_summary": prepared_input.bridge_summary,
                "reason": prepared_input.reject_reason or "bridge_rejected",
            },
        )

    def _record_staged_remote(self, result: "RemoteIntakeResult") -> bool:
        """Record staged remote candidate in validation traces.

        Phase 12: Audit trail for staged remote summaries.
        """
        try:
            if self._validation_traces and len(self._validation_traces) > 0:
                last_trace = self._validation_traces[-1]
                if not hasattr(last_trace, 'staged_remote_summary'):
                    last_trace.staged_remote_summary = {}
                last_trace.staged_remote_summary = {
                    "adapter_id": result.intake.remote_adapter_id,
                    "generation": result.intake.remote_generation,
                    "decision": result.decision.value,
                    "source_node": result.intake.remote_source_node,
                    "is_downgraded": result.staged_candidate.is_downgraded if result.staged_candidate else False,
                    "bridge_decision": (
                        last_trace.remote_execution_bridge_summary.get("bridge_decision")
                        if getattr(last_trace, "remote_execution_bridge_summary", None)
                        else None
                    ),
                }
            return True
        except Exception:
            return False

    def _fallback_intake_result(
        self,
        remote_summary_dict: Dict[str, Any],
        source_node: Optional[str],
    ) -> "RemoteIntakeResult":
        """Create fallback intake result on error."""
        from .types import (
            RemoteIntakeResult,
            RemoteSummaryIntake,
            StagingDecision,
        )

        processed_at = _utc_now()
        remote_identity = remote_summary_dict.get("identity", {}) if isinstance(remote_summary_dict, dict) else {}

        intake = RemoteSummaryIntake(
            remote_adapter_id=remote_identity.get("adapter_id", "unknown"),
            remote_generation=remote_identity.get("generation", 0),
            remote_source_node=source_node,
            intake_timestamp=processed_at,
            intake_version="1.0",
            raw_summary_hash="fallback",
            structure_valid=False,
            required_fields_present=False,
            validation_errors=["governor_processing_error"],
            exchange_gate=None,
        )

        return RemoteIntakeResult(
            processed_at=processed_at,
            processor_version="1.0",
            fallback_used=True,
            intake=intake,
            decision=StagingDecision.STAGE_REJECT,
            decision_reason="governor_processing_exception",
            recommendation="reject_due_to_governor_error",
            staged_candidate=None,
            rejection_trace={"fallback": True},
        )

    def get_staged_remote_summaries(self) -> List[Dict[str, Any]]:
        """Get all staged remote summaries from traces.

        Phase 12: Retrieve staged remote summary audit trail.
        """
        staged = []
        for trace in self._validation_traces:
            if hasattr(trace, 'staged_remote_summary') and trace.staged_remote_summary:
                staged.append(trace.staged_remote_summary)
        return staged

    def triage_staged_candidate(
        self,
        staged_candidate: "StagedRemoteCandidate",
    ) -> "TriageResult":
        """Triage a staged remote candidate for readiness.

        Phase 13: Main entry point for remote summary triage.
        Safe to call during serve path - never blocks or raises.

        Args:
            staged_candidate: Staged remote candidate to triage

        Returns:
            TriageResult with full assessment and routing
        """
        from .triage_engine import RemoteTriageEngine

        try:
            # Extract local summary for comparison
            local_summary = self.extract_federation_summary()

            # Perform triage
            result = RemoteTriageEngine.triage(
                staged_candidate=staged_candidate,
                local_summary=local_summary,
                fallback_on_error=True,
            )

            # Record in traces
            self._record_triage_result(result)

            return result

        except Exception as e:
            # Failure safety: return reject result
            return self._fallback_triage_result(staged_candidate, str(e))

    def _record_triage_result(self, result: "TriageResult") -> bool:
        """Record triage result in validation traces.

        Phase 13: Audit trail for triage decisions.
        """
        try:
            if self._validation_traces and len(self._validation_traces) > 0:
                last_trace = self._validation_traces[-1]
                if not hasattr(last_trace, 'triage_result_summary'):
                    last_trace.triage_result_summary = {}
                last_trace.triage_result_summary = {
                    "adapter_id": result.assessment.adapter_id,
                    "generation": result.assessment.generation,
                    "status": result.assessment.triage_status.value,
                    "readiness_score": result.assessment.readiness.readiness_score,
                    "target_pool": result.target_pool,
                    "priority": result.priority,
                }
            return True
        except Exception:
            return False

    def _fallback_triage_result(
        self,
        staged_candidate: Optional["StagedRemoteCandidate"],
        error_message: str,
    ) -> "TriageResult":
        """Create fallback triage result on error."""
        from datetime import datetime
        from .types import (
            TriageResult,
            TriageAssessment,
            TriageStatus,
            ReadinessSummary,
        )
        import uuid

        processed_at = _utc_now()

        assessment = TriageAssessment(
            adapter_id=staged_candidate.adapter_id if staged_candidate else "unknown",
            generation=staged_candidate.generation if staged_candidate else 0,
            source_node=staged_candidate.source_node if staged_candidate else None,
            triage_status=TriageStatus.REJECT,
            triage_version="1.0",
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
                score_reason=f"governor_error:{error_message}",
            ),
            lineage_compatible=False,
            specialization_compatible=False,
            validation_acceptable=False,
            comparison_acceptable=False,
            recommendation="reject_governor_error",
            reason=f"Governor triage error: {error_message}",
            can_promote_later=False,
            needs_review=False,
            expiration_hint=None,
            original_staging_ref=staged_candidate.intake_record_ref if staged_candidate else "",
        )

        return TriageResult(
            processed_at=processed_at,
            processor_version="1.0",
            fallback_used=True,
            assessment=assessment,
            target_pool="rejected",
            priority=0,
            trace_id=str(uuid.uuid4())[:8],
        )

    def get_ready_remote_candidates(self) -> List[Dict[str, Any]]:
        """Get all ready remote candidates from triage history.

        Phase 13: Retrieve candidates marked as ready for federation.
        """
        ready = []
        for trace in self._validation_traces:
            if hasattr(trace, 'triage_result_summary') and trace.triage_result_summary:
                if trace.triage_result_summary.get('status') == 'ready':
                    ready.append(trace.triage_result_summary)
        return ready

    def quick_readiness_check(
        self,
        staged_candidate: "StagedRemoteCandidate",
    ) -> bool:
        """Quick check if staged candidate is ready for federation.

        Phase 13: Fast path for simple ready/not-ready decisions.
        """
        from .triage_engine import RemoteTriageEngine

        try:
            return RemoteTriageEngine.quick_readiness_check(staged_candidate)
        except Exception:
            return False

    def evaluate_lifecycle(
        self,
        triage_result: "TriageResult",
        previous_meta: Optional["LifecycleMeta"] = None,
    ) -> "LifecycleResult":
        """Evaluate lifecycle for a triaged remote candidate.

        Phase 14: Main entry point for lifecycle evaluation.
        Safe to call during serve path - never blocks or raises.

        Args:
            triage_result: The triage result to evaluate
            previous_meta: Optional previous lifecycle metadata

        Returns:
            LifecycleResult with lifecycle metadata and transition info
        """
        from .lifecycle_engine import TriagePoolLifecycle

        try:
            result = TriagePoolLifecycle.evaluate(
                triage_result=triage_result,
                previous_meta=previous_meta,
                fallback_on_error=True,
            )

            # Ensure we have a trace to record to
            if not self._validation_traces:
                # Create minimal trace for lifecycle recording
                self._validation_traces.append(ValidationTrace(
                    active=self.active_adapter,
                    candidate=None,
                    status="lifecycle",
                    passed=False,
                    reason="Lifecycle-only trace",
                ))

            # Record in traces
            self._record_lifecycle_result(result)

            return result

        except Exception as e:
            return self._fallback_lifecycle_result(triage_result, previous_meta, str(e))

    def _record_lifecycle_result(self, result: "LifecycleResult") -> bool:
        """Record lifecycle result in validation traces.

        Phase 14: Audit trail for lifecycle decisions.
        """
        try:
            if self._validation_traces and len(self._validation_traces) > 0:
                last_trace = self._validation_traces[-1]
                if not hasattr(last_trace, 'lifecycle_result_summary'):
                    last_trace.lifecycle_result_summary = {}
                last_trace.lifecycle_result_summary = {
                    "adapter_id": result.meta.adapter_id,
                    "generation": result.meta.generation,
                    "state": result.meta.state.value,
                    "decision": result.meta.decision.value,
                    "ttl_remaining": result.meta.ttl_remaining,
                    "freshness": result.meta.freshness_score,
                    "priority": result.meta.priority_score,
                    "state_changed": result.state_changed,
                    "needs_cleanup": result.needs_cleanup,
                }
            return True
        except Exception:
            return False

    def _fallback_lifecycle_result(
        self,
        triage_result: Optional["TriageResult"],
        previous_meta: Optional["LifecycleMeta"],
        error_message: str,
    ) -> "LifecycleResult":
        """Create fallback lifecycle result on error."""
        from .lifecycle_engine import LifecycleResult, LifecycleMeta, LifecycleState, LifecycleDecision
        import uuid

        processed_at = _utc_now()

        assessment = triage_result.assessment if triage_result else None

        meta = LifecycleMeta(
            adapter_id=assessment.adapter_id if assessment else "unknown",
            generation=assessment.generation if assessment else 0,
            source_node=assessment.source_node if assessment else None,
            state=LifecycleState.EXPIRED,
            entered_at=processed_at,
            last_reviewed_at=processed_at,
            expires_at=None,
            ttl_hours=0,
            ttl_remaining=0.0,
            freshness_score=0.0,
            priority_score=0,
            priority_changed=False,
            decision=LifecycleDecision.EXPIRE,
            decision_reason=f"Governor lifecycle error: {error_message}",
            fallback_used=True,
            version="1.0",
            reviewed_at=processed_at,
        )

        return LifecycleResult(
            processed_at=processed_at,
            processor_version="1.0",
            fallback_used=True,
            meta=meta,
            previous_state=previous_meta.state if previous_meta else None,
            state_changed=True,
            needs_cleanup=True,
            needs_requeue=False,
            trace_id=str(uuid.uuid4())[:8],
        )

    def get_active_lifecycle_candidates(self) -> List[Dict[str, Any]]:
        """Get all active lifecycle candidates from trace history.

        Phase 14: Retrieve candidates still in active pool.
        """
        active = []
        for trace in self._validation_traces:
            if hasattr(trace, 'lifecycle_result_summary') and trace.lifecycle_result_summary:
                if trace.lifecycle_result_summary.get('state') in ('ready', 'hold', 'downgraded'):
                    active.append(trace.lifecycle_result_summary)
        return active

    def get_expired_candidates(self) -> List[Dict[str, Any]]:
        """Get all expired lifecycle candidates from trace history.

        Phase 14: Retrieve candidates pending cleanup.
        """
        expired = []
        for trace in self._validation_traces:
            if hasattr(trace, 'lifecycle_result_summary') and trace.lifecycle_result_summary:
                if trace.lifecycle_result_summary.get('state') in ('expired', 'evicted'):
                    expired.append(trace.lifecycle_result_summary)
        return expired

    def quick_expiration_check(
        self,
        lifecycle_meta: "LifecycleMeta",
    ) -> bool:
        """Quick check if lifecycle candidate has expired.

        Phase 14: Fast path for expiration checks.
        """
        from .lifecycle_engine import TriagePoolLifecycle

        try:
            return TriagePoolLifecycle.quick_expiration_check(lifecycle_meta)
        except Exception:
            return True  # Conservative: treat errors as expired

    def can_promote_lifecycle_candidate(
        self,
        adapter_id: str,
        generation: int,
    ) -> bool:
        """Check if a lifecycle candidate can be promoted.

        Phase 14: Verify lifecycle state allows promotion.
        """
        for trace in self._validation_traces:
            if hasattr(trace, 'lifecycle_result_summary') and trace.lifecycle_result_summary:
                summary = trace.lifecycle_result_summary
                if (summary.get('adapter_id') == adapter_id and
                    summary.get('generation') == generation):
                    # Must be ready state with positive TTL
                    if summary.get('state') == 'ready' and summary.get('ttl_remaining', 0) > 0:
                        return True
                    return False
        return False

    def resolve_candidate_conflicts(
        self,
        lifecycle_candidates: List[Dict[str, Any]],
    ) -> "ConflictResolutionResult":
        """Resolve conflicts among multiple lifecycle candidates.

        Phase 15: Main entry point for conflict resolution.
        Safe to call during serve path - never blocks or raises.

        Args:
            lifecycle_candidates: List of lifecycle metadata dictionaries

        Returns:
            ConflictResolutionResult with full conflict analysis and resolution
        """
        from .conflict_resolution import RemoteCandidateConflictResolver

        try:
            result = RemoteCandidateConflictResolver.resolve(
                candidates=lifecycle_candidates,
                fallback_on_error=True,
            )

            # Record in traces
            self._record_conflict_resolution(result)

            return result

        except Exception as e:
            return self._fallback_conflict_resolution(lifecycle_candidates, str(e))

    def _record_conflict_resolution(self, result: "ConflictResolutionResult") -> bool:
        """Record conflict resolution result in validation traces.

        Phase 15: Audit trail for conflict resolution decisions.
        """
        try:
            if self._validation_traces and len(self._validation_traces) > 0:
                last_trace = self._validation_traces[-1]
                if not hasattr(last_trace, 'conflict_resolution_summary'):
                    last_trace.conflict_resolution_summary = {}
                last_trace.conflict_resolution_summary = {
                    "set_id": result.conflict_set.set_id,
                    "candidate_count": result.conflict_set.candidate_count,
                    "has_conflicts": result.conflict_set.has_conflicts,
                    "conflict_count": result.conflict_set.conflict_count,
                    "conflict_types": result.conflict_set.conflict_types,
                    "resolution_decision": result.conflict_set.resolution_decision.value,
                    "selected_candidate": result.conflict_set.get_selected_candidate_key(),
                    "can_proceed": result.conflict_set.can_proceed(),
                }
            return True
        except Exception:
            return False

    def _fallback_conflict_resolution(
        self,
        candidates: List[Dict[str, Any]],
        error_message: str,
    ) -> "ConflictResolutionResult":
        """Create fallback conflict resolution result on error."""
        from datetime import datetime
        from .conflict_resolution import (
            ConflictResolutionResult,
            ConflictSet,
            ConflictDetail,
            ConflictType,
            CandidateIdentity,
            CandidateResolution,
            CompatibilitySummary,
            LifecycleSummary,
            ValidationComparisonSummary,
            ResolutionDecision,
        )
        import uuid

        processed_at = _utc_now()
        trace_id = str(uuid.uuid4())[:8]

        # Build minimal identities
        identities = []
        for c in candidates:
            identity = c.get("identity", {})
            identities.append(CandidateIdentity(
                adapter_id=identity.get("adapter_id", "unknown"),
                generation=identity.get("generation", 0),
                source_node=identity.get("source_node"),
            ))

        # Build fallback resolutions (reject all)
        resolutions = []
        for identity in identities:
            resolutions.append(CandidateResolution(
                candidate_key=identity.to_key(),
                adapter_id=identity.adapter_id,
                generation=identity.generation,
                selected=False,
                downgraded=False,
                rejected=True,
                reason=f"Fallback due to error: {error_message}",
            ))

        conflict_set = ConflictSet(
            set_id=f"conflict-fallback-{trace_id}",
            candidate_count=len(candidates),
            candidate_keys=[ci.to_key() for ci in identities],
            has_conflicts=True,
            conflict_count=1,
            conflicts=[ConflictDetail(
                conflict_type=ConflictType.VALIDATION_CONFLICT,
                involved_candidates=[ci.to_key() for ci in identities],
                severity="critical",
                description=f"Resolution error: {error_message}",
                resolution_hint="Fallback to reject all",
            )],
            conflict_types=["validation_conflict"],
            compatibility=CompatibilitySummary(
                lineage_compatible=False,
                specialization_compatible=False,
                validation_consistent=False,
                lifecycle_consistent=False,
                overall_compatible=False,
                compatibility_score=0.0,
            ),
            lifecycle=LifecycleSummary(
                min_freshness=0.0,
                max_freshness=0.0,
                avg_freshness=0.0,
                min_priority=0,
                max_priority=0,
                avg_priority=0.0,
                freshness_range=0.0,
                priority_range=0,
            ),
            validation=ValidationComparisonSummary(
                all_passed_validation=False,
                any_passed_validation=False,
                validation_score_range=0.0,
                min_validation_score=0.0,
                max_validation_score=0.0,
                consensus_on_promotion=False,
                promotion_recommendations=[],
            ),
            resolution_decision=ResolutionDecision.REJECT_ALL,
            selected_candidate=None,
            candidate_resolutions=resolutions,
            resolution_reason=f"Fallback due to error: {error_message}",
            recommendation="reject_all_fallback",
            fallback_used=True,
            version="1.0",
            resolved_at=processed_at,
        )

        return ConflictResolutionResult(
            processed_at=processed_at,
            processor_version="1.0",
            fallback_used=True,
            conflict_set=conflict_set,
            trace_id=trace_id,
        )

    def quick_conflict_check(self, lifecycle_candidates: List[Dict[str, Any]]) -> bool:
        """Quick check if lifecycle candidates have conflicts.

        Phase 15: Fast path for conflict detection.
        """
        from .conflict_resolution import RemoteCandidateConflictResolver

        try:
            return RemoteCandidateConflictResolver.quick_conflict_check(lifecycle_candidates)
        except Exception:
            return True  # Conservative: treat errors as conflict

    def get_conflict_resolution_history(self) -> List[Dict[str, Any]]:
        """Get all conflict resolution results from trace history.

        Phase 15: Retrieve conflict resolution audit trail.
        """
        history = []
        for trace in self._validation_traces:
            if hasattr(trace, 'conflict_resolution_summary') and trace.conflict_resolution_summary:
                history.append(trace.conflict_resolution_summary)
        return history

    def can_promote_after_resolution(
        self,
        adapter_id: str,
        generation: int,
    ) -> bool:
        """Check if a candidate can be promoted after conflict resolution.

        Phase 15: Verify resolution allows promotion of specific candidate.
        """
        for trace in self._validation_traces:
            if hasattr(trace, 'conflict_resolution_summary') and trace.conflict_resolution_summary:
                summary = trace.conflict_resolution_summary
                # Check if this candidate was selected
                selected = summary.get('selected_candidate')
                if selected:
                    selected_parts = selected.split(':')
                    if len(selected_parts) == 2:
                        sel_id, sel_gen = selected_parts
                        if sel_id == adapter_id and int(sel_gen) == generation:
                            # Must be able to proceed
                            return summary.get('can_proceed', False)
        return False

    def execute_promotion(
        self,
        candidate_dict: Dict[str, Any],
        triage_summary: Optional[Dict[str, Any]] = None,
        lifecycle_summary: Optional[Dict[str, Any]] = None,
        conflict_summary: Optional[Dict[str, Any]] = None,
    ) -> "PromotionExecutionResult":
        """Execute promotion for a resolved remote candidate.

        Phase 16: Main entry point for promotion execution.
        Safe to call during serve path - never blocks or raises.

        Args:
            candidate_dict: Candidate identity dictionary
            triage_summary: Optional triage/readiness summary
            lifecycle_summary: Optional lifecycle summary
            conflict_summary: Optional conflict resolution summary

        Returns:
            PromotionExecutionResult with full execution result
        """
        from .promotion_execution import FederationPromotionExecutor

        try:
            result = FederationPromotionExecutor.execute(
                candidate_dict=candidate_dict,
                triage_summary=triage_summary,
                lifecycle_summary=lifecycle_summary,
                conflict_summary=conflict_summary,
                fallback_on_error=True,
            )

            # Record in traces
            self._record_promotion_execution(result)

            return result

        except Exception as e:
            return self._fallback_promotion_execution(candidate_dict, str(e))

    def _record_promotion_execution(self, result: "PromotionExecutionResult") -> bool:
        """Record promotion execution result in validation traces.

        Phase 16: Audit trail for promotion execution decisions.
        """
        try:
            if self._validation_traces and len(self._validation_traces) > 0:
                last_trace = self._validation_traces[-1]
                if not hasattr(last_trace, 'promotion_execution_summary'):
                    last_trace.promotion_execution_summary = {}
                last_trace.promotion_execution_summary = {
                    "execution_id": result.execution.execution_id,
                    "candidate_key": result.execution.candidate.to_key(),
                    "decision": result.execution.decision.value,
                    "status": result.execution.status.value,
                    "success": result.success,
                    "preconditions_met": result.execution.preconditions.all_preconditions_met,
                }
            return True
        except Exception:
            return False

    def _fallback_promotion_execution(
        self,
        candidate_dict: Dict[str, Any],
        error_message: str,
    ) -> "PromotionExecutionResult":
        """Create fallback promotion execution result on error."""
        from datetime import datetime
        from .promotion_execution import (
            PromotionExecutionResult,
            PromotionExecution,
            PromotionCandidate,
            PreconditionSummary,
            ExecutionTrace,
            ExecutionDecision,
            ExecutionStatus,
        )
        import uuid

        processed_at = _utc_now()
        trace_id = str(uuid.uuid4())[:8]
        execution_id = f"exec-gov-fallback-{trace_id}"

        candidate = PromotionCandidate.from_dict(candidate_dict)

        preconditions = PreconditionSummary(
            triage_ready=False,
            readiness_score=0.0,
            lifecycle_valid=False,
            ttl_remaining=0.0,
            state="",
            conflict_resolved=False,
            resolution_decision="",
            can_proceed=False,
            validation_passed=False,
            comparison_acceptable=False,
            lineage_valid=False,
            specialization_valid=False,
            all_preconditions_met=False,
            failed_checks=[f"governor_error:{error_message}"],
        )

        execution = PromotionExecution(
            execution_id=execution_id,
            candidate=candidate,
            preconditions=preconditions,
            decision=ExecutionDecision.REJECT,
            status=ExecutionStatus.REJECTED,
            executed_at=None,
            completed_at=None,
            execution_trace=[
                ExecutionTrace(
                    timestamp=processed_at,
                    action="governor_fallback",
                    details={"error": error_message},
                ),
            ],
            reason=f"Governor execution error: {error_message}",
            recommendation="reject_fallback",
            fallback_used=True,
            version="1.0",
            created_at=processed_at,
        )

        return PromotionExecutionResult(
            processed_at=processed_at,
            processor_version="1.0",
            fallback_used=True,
            execution=execution,
            success=False,
            outcome_status="rejected",
            outcome_details={"error": error_message},
            trace_id=trace_id,
        )

    def quick_promotion_execute_check(
        self,
        candidate_dict: Dict[str, Any],
        lifecycle_summary: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Quick check if candidate can be executed for promotion.

        Phase 16: Fast path for execute eligibility.
        """
        from .promotion_execution import FederationPromotionExecutor

        try:
            return FederationPromotionExecutor.quick_execute_check(
                candidate_dict, lifecycle_summary
            )
        except Exception:
            return False

    def rollback_promotion_execution(
        self,
        execution_result: "PromotionExecutionResult",
        reason: str = "rollback_requested",
    ) -> "PromotionExecutionResult":
        """Rollback a previously executed promotion.

        Phase 16: Rollback an execution that was previously completed.
        """
        from .promotion_execution import FederationPromotionExecutor

        try:
            result = FederationPromotionExecutor.rollback_execution(
                execution_result, reason
            )
            self._record_promotion_execution(result)
            return result
        except Exception:
            # Return original with failure marker
            return execution_result

    def get_promotion_execution_history(self) -> List[Dict[str, Any]]:
        """Get all promotion execution results from trace history.

        Phase 16: Retrieve promotion execution audit trail.
        """
        history = []
        for trace in self._validation_traces:
            if hasattr(trace, 'promotion_execution_summary') and trace.promotion_execution_summary:
                history.append(trace.promotion_execution_summary)
        return history

    def can_execute_promotion(
        self,
        adapter_id: str,
        generation: int,
    ) -> bool:
        """Check if a promotion can be executed for this candidate.

        Phase 16: Verify all gates allow execution.
        """
        # Check lifecycle
        if not self.can_promote_lifecycle_candidate(adapter_id, generation):
            return False

        # Check conflict resolution
        if not self.can_promote_after_resolution(adapter_id, generation):
            return False

        return True

    def emit_federation_event(
        self,
        event_type: str,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        result_data: Dict[str, Any],
    ) -> Optional["FederationEvent"]:
        """Emit federation event for pipeline stage.

        Phase 17: Event emission entry point.
        """
        from .event_stream import FederationEventEmitter, EventType

        try:
            emitter = FederationEventEmitter()

            # Map event type string to EventType
            event_type_map = {
                "summary_intaken": EventType.SUMMARY_INTAKEN,
                "candidate_staged": EventType.CANDIDATE_STAGED,
                "triage_decided": EventType.TRIAGE_DECIDED,
                "lifecycle_updated": EventType.LIFECYCLE_UPDATED,
                "conflict_resolved": EventType.CONFLICT_RESOLVED,
                "promotion_executed": EventType.PROMOTION_EXECUTED,
                "promotion_deferred": EventType.PROMOTION_DEFERRED,
                "promotion_rejected": EventType.PROMOTION_REJECTED,
                "promotion_rolled_back": EventType.PROMOTION_ROLLED_BACK,
            }

            et = event_type_map.get(event_type, EventType.SUMMARY_INTAKEN)

            # Call appropriate emit method
            if et == EventType.SUMMARY_INTAKEN:
                return emitter.emit_summary_intaken(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.CANDIDATE_STAGED:
                return emitter.emit_candidate_staged(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.TRIAGE_DECIDED:
                return emitter.emit_triage_decided(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.LIFECYCLE_UPDATED:
                return emitter.emit_lifecycle_updated(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.CONFLICT_RESOLVED:
                return emitter.emit_conflict_resolved(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.PROMOTION_EXECUTED:
                return emitter.emit_promotion_executed(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.PROMOTION_DEFERRED:
                return emitter.emit_promotion_deferred(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.PROMOTION_REJECTED:
                return emitter.emit_promotion_rejected(
                    adapter_id, generation, source_node, result_data
                )
            elif et == EventType.PROMOTION_ROLLED_BACK:
                return emitter.emit_promotion_rolled_back(
                    adapter_id, generation, source_node, result_data
                )

        except Exception:
            return None

    def get_federation_event_stream(
        self,
        adapter_id: str,
        generation: int,
    ) -> Optional[Dict[str, Any]]:
        """Get federation event stream for candidate.

        Phase 17: Retrieve event history.
        """
        from .event_stream import FederationEventEmitter

        try:
            emitter = FederationEventEmitter()
            stream = emitter.get_stream(adapter_id, generation)
            if stream:
                return stream.to_dict()
            return None
        except Exception:
            return None

    # Phase 20: Federation Coordination

    def coordinate_federation_intake(
        self,
        remote_summary_dict: Dict[str, Any],
        source_node: Optional[str] = None,
        existing_candidates: Optional[List[Dict[str, Any]]] = None,
    ) -> "CoordinationResult":
        """Coordinate full federation pipeline for remote summary intake.

        Phase 20: Main entry point for unified federation coordination.
        Orchestrates: intake → triage → lifecycle → conflict → execution → event → exchange

        Safe to call during serve path - never blocks or raises.

        Args:
            remote_summary_dict: Remote summary as dictionary
            source_node: Optional source node identifier
            existing_candidates: Optional list of existing candidates for conflict check

        Returns:
            CoordinationResult with full coordination information
        """
        from .coordinator import FederationCoordinator

        try:
            # Extract local summary for comparison
            local_summary = self.extract_federation_summary()

            # Create coordinator
            coordinator = FederationCoordinator()

            # Execute coordination
            result = coordinator.coordinate(
                remote_summary_dict=remote_summary_dict,
                local_summary=local_summary,
                source_node=source_node,
                existing_candidates=existing_candidates or [],
                fallback_on_error=True,
            )

            # Record in traces
            self._record_coordination_result(result)

            return result

        except Exception as e:
            return self._fallback_coordination_result(remote_summary_dict, source_node, str(e))

    def _record_coordination_result(self, result: "CoordinationResult") -> bool:
        """Record coordination result in validation traces.

        Phase 20: Audit trail for coordination decisions.
        """
        try:
            if self._validation_traces and len(self._validation_traces) > 0:
                last_trace = self._validation_traces[-1]
                if not hasattr(last_trace, 'coordination_summary'):
                    last_trace.coordination_summary = {}
                last_trace.coordination_summary = {
                    "coordination_id": result.coordination_id,
                    "adapter_id": result.adapter_id,
                    "generation": result.generation,
                    "decision": result.decision.value,
                    "is_ready": result.is_ready,
                    "final_stage": result.get_final_stage(),
                    "fallback_used": result.fallback_used or result.any_stage_fallback,
                    "bridge_summary": result.bridge_summary,
                }
                if result.bridge_summary:
                    last_trace.remote_execution_bridge_summary = result.bridge_summary
            return True
        except Exception:
            return False

    def _fallback_coordination_result(
        self,
        remote_summary_dict: Dict[str, Any],
        source_node: Optional[str],
        error_message: str,
    ) -> "CoordinationResult":
        """Create fallback coordination result on error."""
        from .coordinator import CoordinationResult, CoordinationDecision, CoordinationTrace, StageStatus
        import uuid

        now = _utc_now()
        coordination_id = f"coord-gov-fallback-{str(uuid.uuid4())[:8]}"
        trace_id = str(uuid.uuid4())[:8]

        identity = remote_summary_dict.get("identity", {}) if isinstance(remote_summary_dict, dict) else {}
        adapter_id = identity.get("adapter_id", "unknown")
        generation = identity.get("generation", 0)

        return CoordinationResult(
            coordination_id=coordination_id,
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            decision=CoordinationDecision.COORDINATED_REJECT,
            is_ready=False,
            intake_status=StageStatus.FAILED,
            triage_status=StageStatus.PENDING,
            lifecycle_status=StageStatus.PENDING,
            conflict_status=StageStatus.PENDING,
            execution_status=StageStatus.PENDING,
            event_status=StageStatus.PENDING,
            exchange_status=StageStatus.PENDING,
            reason=f"Governor coordination error: {error_message}",
            recommendation="reject_due_to_error",
            trace=CoordinationTrace(
                trace_id=trace_id,
                stages=[],
                started_at=now,
                completed_at=now,
                short_circuit_at="governor",
                short_circuit_reason=error_message,
            ),
            fallback_used=True,
            any_stage_fallback=True,
            version="1.0",
            coordinated_at=now,
        )

    def consume_coordination_result(
        self,
        result: "CoordinationResult",
    ) -> bool:
        """Consume coordination result and update Governor state if appropriate.

        Phase 20: Integration point for coordination results.
        Only updates state if coordination was successful and ready.

        Args:
            result: CoordinationResult to consume

        Returns:
            True if result was consumed successfully
        """
        from .coordinator import CoordinationDecision

        try:
            if not result.is_successful():
                return False

            # Ensure we have a trace to record to
            if not self._validation_traces:
                # Create minimal trace for coordination recording
                self._validation_traces.append(ValidationTrace(
                    active=self.active_adapter,
                    candidate=None,
                    status="coordination",
                    passed=True,
                    reason="Coordination result consumption",
                ))

            # Record in traces
            self._record_coordination_result(result)

            # Only update state if coordinated_ready
            if result.decision == CoordinationDecision.COORDINATED_READY:
                # Could trigger promotion here if desired
                # For now, just record the successful coordination
                pass

            return True
        except Exception:
            return False

    def get_coordination_history(self) -> List[Dict[str, Any]]:
        """Get all coordination results from trace history.

        Phase 20: Retrieve coordination audit trail.
        """
        history = []
        for trace in self._validation_traces:
            if hasattr(trace, 'coordination_summary') and trace.coordination_summary:
                history.append(trace.coordination_summary)
        return history

    def quick_coordination_check(
        self,
        remote_summary_dict: Dict[str, Any],
    ) -> bool:
        """Quick check if remote summary can be coordinated.

        Phase 20: Fast path for simple coordination decisions.
        """
        from .coordinator import FederationCoordinator

        try:
            return FederationCoordinator().quick_coordination_check(remote_summary_dict)
        except Exception:
            return False

    def is_candidate_coordinated_ready(
        self,
        adapter_id: str,
        generation: int,
    ) -> bool:
        """Check if a candidate has been coordinated as ready.

        Phase 20: Verify coordination result for specific candidate.
        """
        for trace in self._validation_traces:
            if hasattr(trace, 'coordination_summary') and trace.coordination_summary:
                summary = trace.coordination_summary
                if (summary.get('adapter_id') == adapter_id and
                    summary.get('generation') == generation):
                    return summary.get('decision') == 'coordinated_ready' and summary.get('is_ready', False)
        return False
