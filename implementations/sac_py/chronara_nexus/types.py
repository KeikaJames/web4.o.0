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


class ExchangeStatus(Enum):
    """Phase 11: Federation exchange status.

    - ACCEPT: Remote summary is compatible and accepted for exchange
    - DOWNGRADE: Remote summary has issues but can be downgraded for limited exchange
    - REJECT: Remote summary is incompatible and rejected
    """
    ACCEPT = "accept"
    DOWNGRADE = "downgrade"
    REJECT = "reject"


@dataclass
class LineageCompatibility:
    """Phase 11: Lineage compatibility assessment."""
    compatible: bool
    match_score: float  # 0.0-1.0
    generation_gap: int
    is_parent_child: bool
    lineage_hash_match: bool
    reason: Optional[str] = None


@dataclass
class SpecializationCompatibility:
    """Phase 11: Specialization compatibility assessment."""
    compatible: bool
    local_spec: str
    remote_spec: str
    can_compose: bool
    reason: Optional[str] = None


@dataclass
class ValidationCompatibility:
    """Phase 11: Validation acceptance assessment."""
    acceptable: bool
    local_score: float
    remote_score: float
    score_delta: float
    meets_threshold: bool
    reason: Optional[str] = None


@dataclass
class ComparisonCompatibility:
    """Phase 11: Comparison outcome compatibility assessment."""
    acceptable: bool
    local_status: str
    remote_status: str
    both_acceptable: bool
    reason: Optional[str] = None


@dataclass
class FederationExchangeGate:
    """Phase 11: Federation-ready compatibility and exchange gate.

    Structured result of comparing local and remote federation summaries
    for exchange readiness. Deterministic and testable.

    Fields:
        - local_summary_ref: Reference to local summary identity
        - remote_summary_ref: Reference to remote summary identity
        - lineage: Lineage compatibility assessment
        - specialization: Specialization compatibility assessment
        - validation: Validation acceptance assessment
        - comparison: Comparison outcome compatibility assessment
        - status: Overall exchange status (accept/downgrade/reject)
        - recommendation: Specific recommendation for exchange
        - reason: Human-readable explanation
        - fallback_used: Whether fallback logic was applied
        - version: Gate format version
        - timestamp: Gate creation timestamp
    """
    # Identity references
    local_adapter_id: str
    local_generation: int
    remote_adapter_id: str
    remote_generation: int

    # Compatibility assessments
    lineage: LineageCompatibility
    specialization: SpecializationCompatibility
    validation: ValidationCompatibility
    comparison: ComparisonCompatibility

    # Exchange decision
    status: ExchangeStatus
    recommendation: str
    reason: str

    # Metadata
    fallback_used: bool
    version: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "local": {
                "adapter_id": self.local_adapter_id,
                "generation": self.local_generation,
            },
            "remote": {
                "adapter_id": self.remote_adapter_id,
                "generation": self.remote_generation,
            },
            "lineage": {
                "compatible": self.lineage.compatible,
                "match_score": self.lineage.match_score,
                "generation_gap": self.lineage.generation_gap,
                "is_parent_child": self.lineage.is_parent_child,
                "lineage_hash_match": self.lineage.lineage_hash_match,
                "reason": self.lineage.reason,
            },
            "specialization": {
                "compatible": self.specialization.compatible,
                "local_spec": self.specialization.local_spec,
                "remote_spec": self.specialization.remote_spec,
                "can_compose": self.specialization.can_compose,
                "reason": self.specialization.reason,
            },
            "validation": {
                "acceptable": self.validation.acceptable,
                "local_score": self.validation.local_score,
                "remote_score": self.validation.remote_score,
                "score_delta": self.validation.score_delta,
                "meets_threshold": self.validation.meets_threshold,
                "reason": self.validation.reason,
            },
            "comparison": {
                "acceptable": self.comparison.acceptable,
                "local_status": self.comparison.local_status,
                "remote_status": self.comparison.remote_status,
                "both_acceptable": self.comparison.both_acceptable,
                "reason": self.comparison.reason,
            },
            "status": self.status.value,
            "recommendation": self.recommendation,
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "version": self.version,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FederationExchangeGate":
        """Create from dictionary."""
        local_data = data.get("local", {})
        remote_data = data.get("remote", {})

        lineage_data = data.get("lineage", {})
        lineage = LineageCompatibility(
            compatible=lineage_data.get("compatible", False),
            match_score=lineage_data.get("match_score", 0.0),
            generation_gap=lineage_data.get("generation_gap", 0),
            is_parent_child=lineage_data.get("is_parent_child", False),
            lineage_hash_match=lineage_data.get("lineage_hash_match", False),
            reason=lineage_data.get("reason"),
        )

        spec_data = data.get("specialization", {})
        specialization = SpecializationCompatibility(
            compatible=spec_data.get("compatible", False),
            local_spec=spec_data.get("local_spec", "stable"),
            remote_spec=spec_data.get("remote_spec", "stable"),
            can_compose=spec_data.get("can_compose", False),
            reason=spec_data.get("reason"),
        )

        val_data = data.get("validation", {})
        validation = ValidationCompatibility(
            acceptable=val_data.get("acceptable", False),
            local_score=val_data.get("local_score", 0.0),
            remote_score=val_data.get("remote_score", 0.0),
            score_delta=val_data.get("score_delta", 0.0),
            meets_threshold=val_data.get("meets_threshold", False),
            reason=val_data.get("reason"),
        )

        comp_data = data.get("comparison", {})
        comparison = ComparisonCompatibility(
            acceptable=comp_data.get("acceptable", False),
            local_status=comp_data.get("local_status", "unknown"),
            remote_status=comp_data.get("remote_status", "unknown"),
            both_acceptable=comp_data.get("both_acceptable", False),
            reason=comp_data.get("reason"),
        )

        status_str = data.get("status", "reject")
        status = ExchangeStatus(status_str) if status_str in ["accept", "downgrade", "reject"] else ExchangeStatus.REJECT

        return cls(
            local_adapter_id=local_data.get("adapter_id", ""),
            local_generation=local_data.get("generation", 0),
            remote_adapter_id=remote_data.get("adapter_id", ""),
            remote_generation=remote_data.get("generation", 0),
            lineage=lineage,
            specialization=specialization,
            validation=validation,
            comparison=comparison,
            status=status,
            recommendation=data.get("recommendation", "reject"),
            reason=data.get("reason", "unknown"),
            fallback_used=data.get("fallback_used", False),
            version=data.get("version", "1.0"),
            timestamp=data.get("timestamp", ""),
        )

    def can_exchange(self) -> bool:
        """Check if exchange is permitted (accept or downgrade)."""
        return self.status in (ExchangeStatus.ACCEPT, ExchangeStatus.DOWNGRADE)

    def should_accept(self) -> bool:
        """Check if remote summary should be fully accepted."""
        return self.status == ExchangeStatus.ACCEPT

    def should_downgrade(self) -> bool:
        """Check if remote summary should be downgraded."""
        return self.status == ExchangeStatus.DOWNGRADE

    def should_reject(self) -> bool:
        """Check if remote summary should be rejected."""
        return self.status == ExchangeStatus.REJECT


class StagingDecision(Enum):
    """Phase 12: Remote summary staging decision.

    - STAGE_ACCEPT: Remote summary accepted for full staging
    - STAGE_DOWNGRADE: Remote summary accepted but downgraded
    - STAGE_REJECT: Remote summary rejected, not staged
    """
    STAGE_ACCEPT = "stage_accept"
    STAGE_DOWNGRADE = "stage_downgrade"
    STAGE_REJECT = "stage_reject"


@dataclass
class RemoteSummaryIntake:
    """Phase 12: Remote federation summary intake record.

    Records the intake of a remote summary with validation
    and compatibility check results.
    """
    # Remote identity
    remote_adapter_id: str
    remote_generation: int
    remote_source_node: Optional[str]

    # Intake metadata
    intake_timestamp: str
    intake_version: str

    # Raw summary reference (for audit)
    raw_summary_hash: str  # Deterministic hash of raw summary

    # Intake validation
    structure_valid: bool
    required_fields_present: bool
    validation_errors: List[str]

    # Compatibility result (from Phase 11)
    exchange_gate: Optional[FederationExchangeGate]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "remote": {
                "adapter_id": self.remote_adapter_id,
                "generation": self.remote_generation,
                "source_node": self.remote_source_node,
            },
            "intake": {
                "timestamp": self.intake_timestamp,
                "version": self.intake_version,
            },
            "raw_summary_hash": self.raw_summary_hash,
            "validation": {
                "structure_valid": self.structure_valid,
                "required_fields_present": self.required_fields_present,
                "errors": self.validation_errors,
            },
            "exchange_gate": self.exchange_gate.to_dict() if self.exchange_gate else None,
        }


@dataclass
class StagedRemoteCandidate:
    """Phase 12: Staged remote candidate for potential federation.

    Represents a remote summary that has passed intake and
    is now staged for potential future use.
    """
    # Identity
    adapter_id: str
    generation: int
    source_node: Optional[str]

    # Staging metadata
    staged_at: str
    staging_decision: StagingDecision
    staging_version: str

    # Federation summary (validated and potentially downgraded)
    summary: FederationSummary

    # Exchange gate result that led to staging
    gate_result: FederationExchangeGate

    # Staging status
    is_active: bool  # Whether this staged candidate is active
    is_downgraded: bool  # Whether this was a downgrade staging

    # Trace info
    intake_record_ref: str  # Reference to intake record

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "identity": {
                "adapter_id": self.adapter_id,
                "generation": self.generation,
                "source_node": self.source_node,
            },
            "staging": {
                "decision": self.staging_decision.value,
                "staged_at": self.staged_at,
                "version": self.staging_version,
                "is_active": self.is_active,
                "is_downgraded": self.is_downgraded,
            },
            "summary": self.summary.to_dict(),
            "gate_result": self.gate_result.to_dict(),
            "intake_ref": self.intake_record_ref,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StagedRemoteCandidate":
        """Create from dictionary."""
        identity = data.get("identity", {})
        staging = data.get("staging", {})

        decision_str = staging.get("decision", "stage_reject")
        decision = StagingDecision(decision_str) if decision_str in ["stage_accept", "stage_downgrade", "stage_reject"] else StagingDecision.STAGE_REJECT

        return cls(
            adapter_id=identity.get("adapter_id", ""),
            generation=identity.get("generation", 0),
            source_node=identity.get("source_node"),
            staged_at=staging.get("staged_at", ""),
            staging_decision=decision,
            staging_version=staging.get("version", "1.0"),
            summary=FederationSummary.from_dict(data.get("summary", {})),
            gate_result=FederationExchangeGate.from_dict(data.get("gate_result", {})),
            is_active=staging.get("is_active", False),
            is_downgraded=staging.get("is_downgraded", False),
            intake_record_ref=data.get("intake_ref", ""),
        )


@dataclass
class RemoteIntakeResult:
    """Phase 12: Result of remote summary intake processing.

    Complete result including intake record, staging decision,
    and staged candidate (if accepted).
    """
    # Processing metadata
    processed_at: str
    processor_version: str
    fallback_used: bool

    # Intake record
    intake: RemoteSummaryIntake

    # Staging decision
    decision: StagingDecision
    decision_reason: str
    recommendation: str

    # Staged candidate (if accepted or downgraded)
    staged_candidate: Optional[StagedRemoteCandidate]

    # Rejection trace (if rejected)
    rejection_trace: Optional[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "processed_at": self.processed_at,
            "processor_version": self.processor_version,
            "fallback_used": self.fallback_used,
            "intake": self.intake.to_dict(),
            "decision": self.decision.value,
            "decision_reason": self.decision_reason,
            "recommendation": self.recommendation,
            "staged_candidate": self.staged_candidate.to_dict() if self.staged_candidate else None,
            "rejection_trace": self.rejection_trace,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemoteIntakeResult":
        """Create from dictionary."""
        decision_str = data.get("decision", "stage_reject")
        decision = StagingDecision(decision_str) if decision_str in ["stage_accept", "stage_downgrade", "stage_reject"] else StagingDecision.STAGE_REJECT

        staged_data = data.get("staged_candidate")
        staged = StagedRemoteCandidate.from_dict(staged_data) if staged_data else None

        return cls(
            processed_at=data.get("processed_at", ""),
            processor_version=data.get("processor_version", "1.0"),
            fallback_used=data.get("fallback_used", False),
            intake=RemoteSummaryIntake(**data.get("intake", {})),
            decision=decision,
            decision_reason=data.get("decision_reason", ""),
            recommendation=data.get("recommendation", ""),
            staged_candidate=staged,
            rejection_trace=data.get("rejection_trace"),
        )

    def is_staged(self) -> bool:
        """Check if remote summary was staged (accept or downgrade)."""
        return self.decision in (StagingDecision.STAGE_ACCEPT, StagingDecision.STAGE_DOWNGRADE)

    def is_rejected(self) -> bool:
        """Check if remote summary was rejected."""
        return self.decision == StagingDecision.STAGE_REJECT

    def get_staged_summary(self) -> Optional[FederationSummary]:
        """Get staged summary if available."""
        return self.staged_candidate.summary if self.staged_candidate else None


class TriageStatus(Enum):
    """Phase 13: Triage status for staged remote summary.

    - READY: Remote summary is ready for future federation promotion
    - HOLD: Remote summary should be held for further observation
    - DOWNGRADE: Remote summary must be downgraded before use
    - REJECT: Remote summary should be rejected and removed from staging
    """
    READY = "ready"
    HOLD = "hold"
    DOWNGRADE = "downgrade"
    REJECT = "reject"


@dataclass
class ReadinessSummary:
    """Phase 13: Readiness summary for staged remote candidate.

    Bounded-size readiness assessment for triage decisions.
    """
    # Overall readiness score (0.0-1.0)
    readiness_score: float

    # Component scores (0.0-1.0)
    lineage_score: float
    specialization_score: float
    validation_score: float
    comparison_score: float
    recency_score: float  # Based on generation gap

    # Flags
    is_fresh: bool  # Generation gap within acceptable range
    is_compatible: bool  # All compatibility checks passed
    is_priority: bool  # High priority candidate

    # Reasoning
    score_reason: str


@dataclass
class TriageAssessment:
    """Phase 13: Triage assessment for staged remote summary.

    Complete triage result including status, readiness, and recommendations.
    """
    # Identity
    adapter_id: str
    generation: int
    source_node: Optional[str]

    # Triage decision
    triage_status: TriageStatus
    triage_version: str
    triaged_at: str

    # Readiness information
    readiness: ReadinessSummary

    # Compatibility status (from exchange gate)
    lineage_compatible: bool
    specialization_compatible: bool
    validation_acceptable: bool
    comparison_acceptable: bool

    # Recommendation
    recommendation: str
    reason: str

    # Action hints
    can_promote_later: bool  # Whether this could be promoted in future
    needs_review: bool  # Whether this needs manual review
    expiration_hint: Optional[str]  # When this staging might expire

    # Reference to original staging
    original_staging_ref: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "identity": {
                "adapter_id": self.adapter_id,
                "generation": self.generation,
                "source_node": self.source_node,
            },
            "triage": {
                "status": self.triage_status.value,
                "version": self.triage_version,
                "triaged_at": self.triaged_at,
            },
            "readiness": {
                "score": self.readiness.readiness_score,
                "lineage_score": self.readiness.lineage_score,
                "specialization_score": self.readiness.specialization_score,
                "validation_score": self.readiness.validation_score,
                "comparison_score": self.readiness.comparison_score,
                "recency_score": self.readiness.recency_score,
                "is_fresh": self.readiness.is_fresh,
                "is_compatible": self.readiness.is_compatible,
                "is_priority": self.readiness.is_priority,
                "reason": self.readiness.score_reason,
            },
            "compatibility": {
                "lineage": self.lineage_compatible,
                "specialization": self.specialization_compatible,
                "validation": self.validation_acceptable,
                "comparison": self.comparison_acceptable,
            },
            "recommendation": self.recommendation,
            "reason": self.reason,
            "action_hints": {
                "can_promote_later": self.can_promote_later,
                "needs_review": self.needs_review,
                "expiration_hint": self.expiration_hint,
            },
            "staging_ref": self.original_staging_ref,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriageAssessment":
        """Create from dictionary."""
        identity = data.get("identity", {})
        triage = data.get("triage", {})
        readiness = data.get("readiness", {})
        compat = data.get("compatibility", {})
        action = data.get("action_hints", {})

        status_str = triage.get("status", "reject")
        status = TriageStatus(status_str) if status_str in ["ready", "hold", "downgrade", "reject"] else TriageStatus.REJECT

        return cls(
            adapter_id=identity.get("adapter_id", ""),
            generation=identity.get("generation", 0),
            source_node=identity.get("source_node"),
            triage_status=status,
            triage_version=triage.get("version", "1.0"),
            triaged_at=triage.get("triaged_at", ""),
            readiness=ReadinessSummary(
                readiness_score=readiness.get("score", 0.0),
                lineage_score=readiness.get("lineage_score", 0.0),
                specialization_score=readiness.get("specialization_score", 0.0),
                validation_score=readiness.get("validation_score", 0.0),
                comparison_score=readiness.get("comparison_score", 0.0),
                recency_score=readiness.get("recency_score", 0.0),
                is_fresh=readiness.get("is_fresh", False),
                is_compatible=readiness.get("is_compatible", False),
                is_priority=readiness.get("is_priority", False),
                score_reason=readiness.get("reason", ""),
            ),
            lineage_compatible=compat.get("lineage", False),
            specialization_compatible=compat.get("specialization", False),
            validation_acceptable=compat.get("validation", False),
            comparison_acceptable=compat.get("comparison", False),
            recommendation=data.get("recommendation", "reject"),
            reason=data.get("reason", ""),
            can_promote_later=action.get("can_promote_later", False),
            needs_review=action.get("needs_review", False),
            expiration_hint=action.get("expiration_hint"),
            original_staging_ref=data.get("staging_ref", ""),
        )

    def is_ready(self) -> bool:
        """Check if triage status is ready."""
        return self.triage_status == TriageStatus.READY

    def is_hold(self) -> bool:
        """Check if triage status is hold."""
        return self.triage_status == TriageStatus.HOLD

    def is_downgrade(self) -> bool:
        """Check if triage status is downgrade."""
        return self.triage_status == TriageStatus.DOWNGRADE

    def is_reject(self) -> bool:
        """Check if triage status is reject."""
        return self.triage_status == TriageStatus.REJECT

    def can_use_for_federation(self) -> bool:
        """Check if this staged summary can be used for federation."""
        return self.triage_status in (TriageStatus.READY, TriageStatus.HOLD)


@dataclass
class TriageResult:
    """Phase 13: Complete triage result.

    Includes triage assessment and routing information.
    """
    # Processing metadata
    processed_at: str
    processor_version: str
    fallback_used: bool

    # Triage assessment
    assessment: TriageAssessment

    # Routing information
    target_pool: str  # "ready", "hold", "downgraded", "rejected"
    priority: int  # 0-100 priority score

    # Audit
    trace_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "processed_at": self.processed_at,
            "processor_version": self.processor_version,
            "fallback_used": self.fallback_used,
            "assessment": self.assessment.to_dict(),
            "routing": {
                "target_pool": self.target_pool,
                "priority": self.priority,
            },
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriageResult":
        """Create from dictionary."""
        routing = data.get("routing", {})
        return cls(
            processed_at=data.get("processed_at", ""),
            processor_version=data.get("processor_version", "1.0"),
            fallback_used=data.get("fallback_used", False),
            assessment=TriageAssessment.from_dict(data.get("assessment", {})),
            target_pool=routing.get("target_pool", "rejected"),
            priority=routing.get("priority", 0),
            trace_id=data.get("trace_id", ""),
        )


# Phase 14: Lifecycle types (re-export from lifecycle_engine for convenience)
from .lifecycle_engine import (
    LifecycleDecision,
    LifecycleState,
    LifecycleMeta,
    LifecycleResult,
    TriagePoolLifecycle,
)
