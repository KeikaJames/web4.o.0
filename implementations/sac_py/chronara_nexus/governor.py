"""Governor: Validation, promotion, and rollback protocol."""

from typing import Optional, Dict, Any
from .types import AdapterRef, ValidationReport, AdapterMode, AdapterSpecialization, AdapterSelection


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

        # Optional deliberation pre-processing
        if self.enable_deliberation:
            deliberation = self._get_deliberation()
            if deliberation:
                try:
                    from .deliberation import DeliberationRequest
                    # Create deliberation input from atom_result
                    delib_obs = {
                        "atom_result": atom_result,
                        "candidate_id": candidate.adapter_id,
                        "candidate_generation": candidate.generation,
                    }
                    request = DeliberationRequest(observation=delib_obs)
                    result = deliberation.deliberate(request)
                    # If deliberation rejects, mark as failed
                    if not result.accepted:
                        report = ValidationReport(
                            adapter_id=candidate.adapter_id,
                            generation=candidate.generation,
                            passed=False,
                            metric_summary={"source": "deliberation_rejected"},
                            reason="deliberation quality check failed",
                            specialization_summary={
                                AdapterSpecialization.CANDIDATE: {"status": "rejected", "source": "deliberation"}
                            }
                        )
                        self.last_validation_report = report
                        return report
                except Exception:
                    # Fallback on deliberation failure
                    pass

        # Check if atom returned validation_result
        validation_result = atom_result.get("validation_result")
        if validation_result:
            # Use atom's validation result
            lineage_valid = validation_result.get("lineage_valid", False)
            output_match = validation_result.get("output_match", False)
            kv_count_match = validation_result.get("kv_count_match", False)
            is_acceptable = validation_result.get("is_acceptable", False)

            generation_advanced = candidate.generation > self.active_adapter.generation
            passed = lineage_valid and is_acceptable and generation_advanced

            metric_summary = {
                "lineage_valid": lineage_valid,
                "output_match": output_match,
                "kv_count_match": kv_count_match,
                "is_acceptable": is_acceptable,
                "generation_advanced": generation_advanced,
                "source": "atom_validation_result",
            }

            reason = None
            if not passed:
                if not lineage_valid:
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

    def validate_from_lineage(self, candidate: AdapterRef, atom_result: Dict[str, Any]) -> ValidationReport:
        """Alias for validate_from_atom_result for backward compatibility."""
        return self.validate_from_atom_result(candidate, atom_result)

    def validate_from_comparison(self, candidate: AdapterRef, comparison_result: Dict[str, Any]) -> ValidationReport:
        """Validate candidate using shadow comparison result."""
        # Ensure candidate has CANDIDATE specialization
        candidate = AdapterRef(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            mode=candidate.mode,
            specialization=AdapterSpecialization.CANDIDATE
        )
        self.candidate_adapter = candidate
        lineage_valid = comparison_result.get("lineage_valid", False)
        output_match = comparison_result.get("output_match", False)
        kv_count_match = comparison_result.get("kv_count_match", False)
        generation_advanced = candidate.generation > self.active_adapter.generation
        if "is_acceptable" in comparison_result:
            is_acceptable = comparison_result["is_acceptable"]
        else:
            is_acceptable = lineage_valid and kv_count_match

        # Strict: must have valid lineage and acceptable behavior
        passed = lineage_valid and is_acceptable and generation_advanced

        metric_summary = {
            "lineage_valid": lineage_valid,
            "output_match": output_match,
            "kv_count_match": kv_count_match,
            "is_acceptable": is_acceptable,
            "generation_advanced": generation_advanced,
        }

        reason = None
        if not passed:
            if not lineage_valid:
                reason = "adapter lineage invalid"
            elif not is_acceptable:
                reason = "shadow behavior not acceptable"
            elif not generation_advanced:
                reason = "generation not advanced"

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
