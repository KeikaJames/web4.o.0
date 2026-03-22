"""Governor: Validation, promotion, and rollback protocol."""

from typing import Optional
from .types import AdapterRef, ValidationReport, AdapterMode


class Governor:
    """Manages active/candidate/stable adapter lifecycle."""

    def __init__(self, initial_adapter: AdapterRef):
        self.active_adapter = initial_adapter
        self.candidate_adapter: Optional[AdapterRef] = None
        self.stable_adapter = initial_adapter

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
