"""Admission gate: observation classification and routing."""

from enum import Enum


class ObservationType(Enum):
    """Three types of observations."""
    EXPLICIT_ONLY = "explicit_only"
    STRATEGY_ONLY = "strategy_only"
    PARAMETER_CANDIDATE = "parameter_candidate"


class AdmissionGate:
    """Classifies observations into three types."""

    def classify(self, observation: dict) -> ObservationType:
        """Classify observation based on content."""
        if observation.get("explicit_feedback"):
            return ObservationType.EXPLICIT_ONLY
        elif observation.get("strategy_signal"):
            return ObservationType.STRATEGY_ONLY
        else:
            return ObservationType.PARAMETER_CANDIDATE
