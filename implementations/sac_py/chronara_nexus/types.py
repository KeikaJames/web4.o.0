"""Core types for Chronara adapter evolution."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any, List
from datetime import datetime


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


@dataclass
class AdapterIdentitySummary:
    """Minimal adapter identity for federation exchange.

    Phase 10: FIL/federation-ready identity summary.
    """
    adapter_id: str
    generation: int
    parent_generation: Optional[int]
    specialization: str
    mode: str


@dataclass
class SpecializationSummary:
    """Minimal specialization state summary for federation.

    Phase 10: Captures stable/shared/candidate states.
    """
    stable_generation: int
    shared_generation: Optional[int]
    candidate_generation: Optional[int]
    active_specialization: str


@dataclass
class ImportanceMaskSummary:
    """Minimal importance mask summary for federation.

    Phase 10: Bounded-size mask for parameter importance.
    """
    # Top-K important parameter keys with scores
    top_keys: List[str]
    scores: Dict[str, float]
    threshold: float
    compression_ratio: float


@dataclass
class DeltaNormSummary:
    """Minimal delta norm summary for federation comparison.

    Phase 10: Allows comparison without sharing full parameters.
    """
    l1_norm: float
    l2_norm: float
    max_abs: float
    param_count: int
    relative_to_parent: Optional[float] = None


@dataclass
class ValidationScoreSummary:
    """Minimal validation score summary for federation.

    Phase 10: Abstract validation outcomes for cross-node comparison.
    """
    passed: bool
    lineage_valid: bool
    specialization_valid: bool
    output_match: bool
    kv_count_match: bool
    generation_advanced: bool
    score: float  # 0.0-1.0 aggregate score


@dataclass
class ComparisonOutcomeSummary:
    """Minimal comparison outcome summary for federation.

    Phase 10: Shadow comparison results abstracted for exchange.
    """
    status: str
    promote_recommendation: str
    lineage_valid: bool
    specialization_valid: bool
    is_acceptable: bool


@dataclass
class DeliberationSummary:
    """Minimal deliberation/multi-role review summary for federation.

    Phase 10: Quality assessment abstracted for cross-node comparison.
    """
    outcome: str
    quality_score: float
    confidence: float
    consensus_status: Optional[str]
    has_disagreement: Optional[bool]
    escalation_used: bool


@dataclass
class SnapshotLineageSummary:
    """Minimal snapshot lineage summary for federation.

    Phase 10: Deterministic lineage for compatibility checking.
    """
    snapshot_id: str
    adapter_id: str
    generation: int
    specialization: str
    parent_snapshot_id: Optional[str]
    lineage_hash: str  # Deterministic hash for quick comparison


@dataclass
class CompatibilityHints:
    """Compatibility hints for federation exchange.

    Phase 10: Minimal hints for cross-node adapter compatibility.
    """
    # Generation compatibility
    min_compatible_generation: int
    max_compatible_generation: int

    # Specialization compatibility
    required_specialization: Optional[str]

    # Validation threshold hints
    min_validation_score: float

    # Comparison acceptance hints
    requires_consensus_accept: bool

    # Format version for forward compatibility
    format_version: str = "1.0"


@dataclass
class FederationSummary:
    """Federation-ready summary layer for Chronara.

    Phase 10: Minimal, structured, deterministic summary for
    cross-node exchange without full parameter sharing.

    Fields:
        - identity: Adapter identity (id, generation, specialization)
        - specialization: Specialization state summary
        - importance_mask: Top-K parameter importance
        - delta_norm: Norm summary for change comparison
        - validation_score: Validation outcome summary
        - comparison_outcome: Shadow comparison summary
        - deliberation: Deliberation/review quality summary
        - snapshot_lineage: Deterministic lineage info
        - compatibility: Exchange-ready compatibility hints
        - metadata: Export timestamp, version, source info
    """
    # Core identity
    identity: AdapterIdentitySummary

    # Specialization state
    specialization: SpecializationSummary

    # Parameter importance (bounded size)
    importance_mask: ImportanceMaskSummary

    # Change magnitude (for comparison without full params)
    delta_norm: DeltaNormSummary

    # Validation outcome
    validation_score: ValidationScoreSummary

    # Comparison outcome
    comparison_outcome: ComparisonOutcomeSummary

    # Deliberation/multi-role review outcome
    deliberation: DeliberationSummary

    # Snapshot lineage
    snapshot_lineage: SnapshotLineageSummary

    # Compatibility hints
    compatibility: CompatibilityHints

    # Export metadata
    export_timestamp: str
    export_version: str
    source_node: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "identity": {
                "adapter_id": self.identity.adapter_id,
                "generation": self.identity.generation,
                "parent_generation": self.identity.parent_generation,
                "specialization": self.identity.specialization,
                "mode": self.identity.mode,
            },
            "specialization": {
                "stable_generation": self.specialization.stable_generation,
                "shared_generation": self.specialization.shared_generation,
                "candidate_generation": self.specialization.candidate_generation,
                "active_specialization": self.specialization.active_specialization,
            },
            "importance_mask": {
                "top_keys": self.importance_mask.top_keys,
                "scores": self.importance_mask.scores,
                "threshold": self.importance_mask.threshold,
                "compression_ratio": self.importance_mask.compression_ratio,
            },
            "delta_norm": {
                "l1_norm": self.delta_norm.l1_norm,
                "l2_norm": self.delta_norm.l2_norm,
                "max_abs": self.delta_norm.max_abs,
                "param_count": self.delta_norm.param_count,
                "relative_to_parent": self.delta_norm.relative_to_parent,
            },
            "validation_score": {
                "passed": self.validation_score.passed,
                "lineage_valid": self.validation_score.lineage_valid,
                "specialization_valid": self.validation_score.specialization_valid,
                "output_match": self.validation_score.output_match,
                "kv_count_match": self.validation_score.kv_count_match,
                "generation_advanced": self.validation_score.generation_advanced,
                "score": self.validation_score.score,
            },
            "comparison_outcome": {
                "status": self.comparison_outcome.status,
                "promote_recommendation": self.comparison_outcome.promote_recommendation,
                "lineage_valid": self.comparison_outcome.lineage_valid,
                "specialization_valid": self.comparison_outcome.specialization_valid,
                "is_acceptable": self.comparison_outcome.is_acceptable,
            },
            "deliberation": {
                "outcome": self.deliberation.outcome,
                "quality_score": self.deliberation.quality_score,
                "confidence": self.deliberation.confidence,
                "consensus_status": self.deliberation.consensus_status,
                "has_disagreement": self.deliberation.has_disagreement,
                "escalation_used": self.deliberation.escalation_used,
            },
            "snapshot_lineage": {
                "snapshot_id": self.snapshot_lineage.snapshot_id,
                "adapter_id": self.snapshot_lineage.adapter_id,
                "generation": self.snapshot_lineage.generation,
                "specialization": self.snapshot_lineage.specialization,
                "parent_snapshot_id": self.snapshot_lineage.parent_snapshot_id,
                "lineage_hash": self.snapshot_lineage.lineage_hash,
            },
            "compatibility": {
                "min_compatible_generation": self.compatibility.min_compatible_generation,
                "max_compatible_generation": self.compatibility.max_compatible_generation,
                "required_specialization": self.compatibility.required_specialization,
                "min_validation_score": self.compatibility.min_validation_score,
                "requires_consensus_accept": self.compatibility.requires_consensus_accept,
                "format_version": self.compatibility.format_version,
            },
            "metadata": {
                "export_timestamp": self.export_timestamp,
                "export_version": self.export_version,
                "source_node": self.source_node,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FederationSummary":
        """Create from dictionary."""
        identity_data = data.get("identity", {})
        identity = AdapterIdentitySummary(
            adapter_id=identity_data.get("adapter_id", ""),
            generation=identity_data.get("generation", 0),
            parent_generation=identity_data.get("parent_generation"),
            specialization=identity_data.get("specialization", "stable"),
            mode=identity_data.get("mode", "serve"),
        )

        spec_data = data.get("specialization", {})
        specialization = SpecializationSummary(
            stable_generation=spec_data.get("stable_generation", 0),
            shared_generation=spec_data.get("shared_generation"),
            candidate_generation=spec_data.get("candidate_generation"),
            active_specialization=spec_data.get("active_specialization", "stable"),
        )

        mask_data = data.get("importance_mask", {})
        importance_mask = ImportanceMaskSummary(
            top_keys=mask_data.get("top_keys", []),
            scores=mask_data.get("scores", {}),
            threshold=mask_data.get("threshold", 0.0),
            compression_ratio=mask_data.get("compression_ratio", 1.0),
        )

        delta_data = data.get("delta_norm", {})
        delta_norm = DeltaNormSummary(
            l1_norm=delta_data.get("l1_norm", 0.0),
            l2_norm=delta_data.get("l2_norm", 0.0),
            max_abs=delta_data.get("max_abs", 0.0),
            param_count=delta_data.get("param_count", 0),
            relative_to_parent=delta_data.get("relative_to_parent"),
        )

        val_data = data.get("validation_score", {})
        validation_score = ValidationScoreSummary(
            passed=val_data.get("passed", False),
            lineage_valid=val_data.get("lineage_valid", False),
            specialization_valid=val_data.get("specialization_valid", False),
            output_match=val_data.get("output_match", False),
            kv_count_match=val_data.get("kv_count_match", False),
            generation_advanced=val_data.get("generation_advanced", False),
            score=val_data.get("score", 0.0),
        )

        comp_data = data.get("comparison_outcome", {})
        comparison_outcome = ComparisonOutcomeSummary(
            status=comp_data.get("status", "unknown"),
            promote_recommendation=comp_data.get("promote_recommendation", "undecided"),
            lineage_valid=comp_data.get("lineage_valid", False),
            specialization_valid=comp_data.get("specialization_valid", False),
            is_acceptable=comp_data.get("is_acceptable", False),
        )

        delib_data = data.get("deliberation", {})
        deliberation = DeliberationSummary(
            outcome=delib_data.get("outcome", "reject"),
            quality_score=delib_data.get("quality_score", 0.0),
            confidence=delib_data.get("confidence", 0.0),
            consensus_status=delib_data.get("consensus_status"),
            has_disagreement=delib_data.get("has_disagreement"),
            escalation_used=delib_data.get("escalation_used", False),
        )

        lineage_data = data.get("snapshot_lineage", {})
        snapshot_lineage = SnapshotLineageSummary(
            snapshot_id=lineage_data.get("snapshot_id", ""),
            adapter_id=lineage_data.get("adapter_id", ""),
            generation=lineage_data.get("generation", 0),
            specialization=lineage_data.get("specialization", "stable"),
            parent_snapshot_id=lineage_data.get("parent_snapshot_id"),
            lineage_hash=lineage_data.get("lineage_hash", ""),
        )

        compat_data = data.get("compatibility", {})
        compatibility = CompatibilityHints(
            min_compatible_generation=compat_data.get("min_compatible_generation", 0),
            max_compatible_generation=compat_data.get("max_compatible_generation", 0),
            required_specialization=compat_data.get("required_specialization"),
            min_validation_score=compat_data.get("min_validation_score", 0.0),
            requires_consensus_accept=compat_data.get("requires_consensus_accept", False),
            format_version=compat_data.get("format_version", "1.0"),
        )

        metadata = data.get("metadata", {})

        return cls(
            identity=identity,
            specialization=specialization,
            importance_mask=importance_mask,
            delta_norm=delta_norm,
            validation_score=validation_score,
            comparison_outcome=comparison_outcome,
            deliberation=deliberation,
            snapshot_lineage=snapshot_lineage,
            compatibility=compatibility,
            export_timestamp=metadata.get("export_timestamp", ""),
            export_version=metadata.get("export_version", "1.0"),
            source_node=metadata.get("source_node"),
        )

    def is_compatible_with(self, other: "FederationSummary") -> bool:
        """Check if this summary is compatible with another for federation.

        Phase 10: Quick compatibility check without full parameter comparison.
        """
        # Check adapter identity compatibility
        if self.identity.adapter_id != other.identity.adapter_id:
            return False

        # Check generation compatibility
        if other.identity.generation < self.compatibility.min_compatible_generation:
            return False
        if other.identity.generation > self.compatibility.max_compatible_generation:
            return False

        # Check specialization compatibility
        if self.compatibility.required_specialization:
            if other.identity.specialization != self.compatibility.required_specialization:
                return False

        # Check validation score threshold
        if other.validation_score.score < self.compatibility.min_validation_score:
            return False

        # Check consensus requirement
        if self.compatibility.requires_consensus_accept:
            if other.deliberation.consensus_status != "consensus_accept":
                return False

        return True

    def compute_lineage_match(self, other: "FederationSummary") -> float:
        """Compute lineage match score with another summary.

        Phase 10: 0.0-1.0 score for lineage similarity.
        """
        if self.identity.adapter_id != other.identity.adapter_id:
            return 0.0

        # Same generation is perfect match
        if self.identity.generation == other.identity.generation:
            return 1.0

        # Parent-child relationship
        if (self.identity.parent_generation == other.identity.generation or
            other.identity.parent_generation == self.identity.generation):
            return 0.9

        # Same lineage hash
        if self.snapshot_lineage.lineage_hash == other.snapshot_lineage.lineage_hash:
            return 0.95

        # Generation distance penalty
        gen_diff = abs(self.identity.generation - other.identity.generation)
        return max(0.0, 0.8 - (gen_diff * 0.1))

    @staticmethod
    def _minimal_safe_summary(
        adapter_id: str = "unknown",
        generation: int = 0,
        source_node: Optional[str] = None,
    ) -> "FederationSummary":
        """Return absolute minimal safe summary for failure recovery.

        Phase 10: Static factory for emergency summary creation.
        """
        from datetime import datetime

        identity = AdapterIdentitySummary(
            adapter_id=adapter_id,
            generation=generation,
            parent_generation=None,
            specialization="stable",
            mode="serve",
        )

        return FederationSummary(
            identity=identity,
            specialization=SpecializationSummary(
                stable_generation=generation,
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
                passed=True,
                lineage_valid=True,
                specialization_valid=True,
                output_match=True,
                kv_count_match=True,
                generation_advanced=True,
                score=1.0,
            ),
            comparison_outcome=ComparisonOutcomeSummary(
                status="unknown",
                promote_recommendation="undecided",
                lineage_valid=True,
                specialization_valid=True,
                is_acceptable=True,
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
                snapshot_id=f"{adapter_id}-gen{generation}",
                adapter_id=adapter_id,
                generation=generation,
                specialization="stable",
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
            export_timestamp=datetime.utcnow().isoformat() + "Z",
            export_version="1.0",
            source_node=source_node,
        )
