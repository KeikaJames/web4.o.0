"""Core types for Chronara adapter evolution."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any


class AdapterMode(Enum):
    """Adapter execution mode."""
    SERVE = "serve"
    VALIDATION = "validation"
    SHADOW_EVAL = "shadow_eval"


class ObservationType(Enum):
    """Observation classes used for Chronara routing."""

    EXPLICIT_ONLY = "explicit_only"
    STRATEGY_ONLY = "strategy_only"
    PARAMETER_CANDIDATE = "parameter_candidate"


class AdapterSpecialization(Enum):
    """Adapter specialization role.

    - STABLE: Long-term stable preferences, validated over time
    - SHARED: Cross-task/cross-observation shared preference layer
    - CANDIDATE: Current experiment/promotion candidate under evaluation
    """
    STABLE = "stable"
    SHARED = "shared"
    CANDIDATE = "candidate"


@dataclass
class AdapterRef:
    """Reference to a specific adapter generation."""
    adapter_id: str
    generation: int
    mode: AdapterMode = AdapterMode.SERVE
    specialization: AdapterSpecialization = AdapterSpecialization.STABLE


@dataclass
class AdapterManifest:
    """Adapter metadata and lineage."""
    adapter_id: str
    generation: int
    parent_generation: Optional[int]
    snapshot_ref: Optional[str]
    created_at: float
    specialization: AdapterSpecialization = AdapterSpecialization.STABLE


@dataclass
class SnapshotRef:
    """Reference to adapter parameter snapshot."""
    snapshot_id: str
    adapter_id: str
    generation: int
    byte_size: int
    specialization: AdapterSpecialization = AdapterSpecialization.STABLE


@dataclass
class AdapterSelection:
    """Active adapter selection combining specialization layers.

    Represents the current serve-time adapter composition:
    - stable: Long-term validated preferences (fallback base)
    - shared: Cross-task shared parameters (optional augmentation)
    - candidate: Experimental candidate (isolated, not yet promoted)
    """
    stable: AdapterRef
    shared: Optional[AdapterRef] = None
    candidate: Optional[AdapterRef] = None

    def get_serve_adapter(self) -> AdapterRef:
        """Get the adapter to use for serving.

        Returns stable adapter, as candidate never directly serves.
        Shared may be composed in future iterations.
        """
        return self.stable

    def is_specialization_active(self, spec: AdapterSpecialization) -> bool:
        """Check if given specialization has a defined adapter."""
        if spec == AdapterSpecialization.STABLE:
            return self.stable is not None
        if spec == AdapterSpecialization.SHARED:
            return self.shared is not None
        if spec == AdapterSpecialization.CANDIDATE:
            return self.candidate is not None
        return False


@dataclass
class ValidationReport:
    """Validation result for candidate adapter with Phase 9 multi-role review.

    Fields:
        - adapter_id: ID of validated adapter
        - generation: Generation of validated adapter
        - passed: Whether validation passed
        - metric_summary: Detailed metrics from validation
        - reason: Explanation if validation failed
        - specialization_summary: Per-specialization status
        - deliberation_outcome: Phase 8 deliberation result (candidate_ready, etc.)
        - deliberation_quality: Quality score from deliberation (0.0-1.0)
        - consensus_status: Phase 9 multi-role review consensus status
        - has_role_disagreement: Whether roles disagreed during review
    """
    adapter_id: str
    generation: int
    passed: bool
    metric_summary: dict
    reason: Optional[str] = None
    specialization_summary: Dict[AdapterSpecialization, Dict[str, Any]] = field(default_factory=dict)
    deliberation_outcome: Optional[str] = None
    deliberation_quality: Optional[float] = None
    consensus_status: Optional[str] = None
    has_role_disagreement: Optional[bool] = None
