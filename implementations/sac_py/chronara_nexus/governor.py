"""Governor: Validation, promotion, and rollback protocol."""

from typing import Optional, Dict, Any, List
from .types import AdapterRef, ValidationReport, AdapterMode, AdapterSpecialization, AdapterSelection
from .deliberation import DeliberationOutcome


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
                and status not in ("lineage_mismatch", "specialization_mismatch", "unavailable")
            )
        else:
            # Backward compatibility: old format
            passed = lineage_valid and is_acceptable and generation_advanced

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
        if has_disagreement:
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

    def compute_drift_score(self, metric_summary: dict) -> float:
        """Compute drift score for future gamma adjustment."""
        # Placeholder for future dynamic learning rate scheduling
        return 0.0

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
        status = comparison_result.get("status", "")
        if status not in ("candidate_observed", "active_only"):
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

        return True
