"""Governor: Validation, promotion, and rollback protocol."""

from typing import Optional, Dict, Any
from .types import AdapterRef, ValidationReport, AdapterMode


class Governor:
    """Manages active/candidate/stable adapter lifecycle."""

    def __init__(self, initial_adapter: AdapterRef):
        self.active_adapter = initial_adapter
        self.candidate_adapter: Optional[AdapterRef] = None
        self.stable_adapter = initial_adapter

    def create_shadow_request(self, candidate: AdapterRef, input_data: bytes) -> Dict[str, Any]:
        """Create a shadow eval request for candidate adapter."""
        return {
            "active_adapter": {
                "adapter_id": self.active_adapter.adapter_id,
                "generation": self.active_adapter.generation,
                "mode": self.active_adapter.mode.value,
            },
            "candidate_adapter": {
                "adapter_id": candidate.adapter_id,
                "generation": candidate.generation,
                "mode": AdapterMode.SHADOW_EVAL.value,
            },
            "input": input_data,
        }

    def validate_from_lineage(self, candidate: AdapterRef, atom_result: Dict[str, Any]) -> ValidationReport:
        """Validate candidate using atom execution lineage."""
        exec_response = atom_result.get("exec_response", {})
        adapter_id = exec_response.get("adapter_id")
        adapter_generation = exec_response.get("adapter_generation")

        # Check lineage consistency
        lineage_match = (
            adapter_id == candidate.adapter_id
            and adapter_generation == candidate.generation
        )

        passed = lineage_match and candidate.generation > self.active_adapter.generation

        return ValidationReport(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            passed=passed,
            metric_summary={
                "lineage_match": lineage_match,
                "generation_advanced": candidate.generation > self.active_adapter.generation,
            },
            reason=None if passed else "lineage mismatch or generation not advanced"
        )

    def validate_candidate(self, candidate: AdapterRef) -> ValidationReport:
        """Minimal validation logic."""
        passed = candidate.generation > self.active_adapter.generation
        return ValidationReport(
            adapter_id=candidate.adapter_id,
            generation=candidate.generation,
            passed=passed,
            metric_summary={"placeholder": True},
            reason=None if passed else "generation not advanced"
        )

    def promote_candidate(self, candidate: AdapterRef) -> bool:
        """Promote candidate to active."""
        report = self.validate_candidate(candidate)
        if not report.passed:
            return False
        self.active_adapter = candidate
        return True

    def rollback_to_stable(self):
        """Rollback active to last stable."""
        self.active_adapter = self.stable_adapter

    def mark_stable(self):
        """Mark current active as stable."""
        self.stable_adapter = self.active_adapter
