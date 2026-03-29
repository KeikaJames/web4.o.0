"""Phase 15: Remote candidate conflict resolution layer.

Manages conflict detection and resolution when multiple remote candidates
exist simultaneously. Provides structured conflict analysis and resolution
without actual federation training or adapter merging.

Safe to call during serve path - never blocks or raises.
"""

import uuid
from typing import Optional, Dict, Any, List, Set, Tuple
from datetime import datetime
from enum import Enum
from dataclasses import dataclass


class ConflictType(Enum):
    """Phase 15: Types of conflicts between remote candidates.

    - LINEAGE_CONFLICT: Candidates have incompatible lineage
    - SPECIALIZATION_CONFLICT: Candidates have incompatible specializations
    - VALIDATION_CONFLICT: Validation/comparison conclusions differ
    - LIFECYCLE_CONFLICT: Freshness/priority/lifecycle conclusions differ
    - DUPLICATE_SOURCE: Multiple candidates from same source
    - DUPLICATE_CANDIDATE: Same candidate appears multiple times
    - RECOMMENDATION_CONFLICT: Promotion recommendations conflict
    - PRIORITY_CONFLICT: Priority scores create ambiguity
    """
    LINEAGE_CONFLICT = "lineage_conflict"
    SPECIALIZATION_CONFLICT = "specialization_conflict"
    VALIDATION_CONFLICT = "validation_conflict"
    LIFECYCLE_CONFLICT = "lifecycle_conflict"
    DUPLICATE_SOURCE = "duplicate_source"
    DUPLICATE_CANDIDATE = "duplicate_candidate"
    RECOMMENDATION_CONFLICT = "recommendation_conflict"
    PRIORITY_CONFLICT = "priority_conflict"


class ResolutionDecision(Enum):
    """Phase 15: Resolution decision for conflicting candidates.

    - SELECT_ONE: Select a single optimal candidate
    - HOLD_ALL: Hold all candidates for further observation
    - DOWNGRADE_SOME: Downgrade some candidates, keep others
    - REJECT_ALL: Reject all candidates due to irreconcilable conflict
    """
    SELECT_ONE = "select_one"
    HOLD_ALL = "hold_all"
    DOWNGRADE_SOME = "downgrade_some"
    REJECT_ALL = "reject_all"


@dataclass
class CandidateIdentity:
    """Phase 15: Identity for a candidate in conflict resolution."""
    adapter_id: str
    generation: int
    source_node: Optional[str]

    def to_key(self) -> str:
        """Generate unique key for this candidate."""
        return f"{self.adapter_id}:{self.generation}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "generation": self.generation,
            "source_node": self.source_node,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateIdentity":
        return cls(
            adapter_id=data.get("adapter_id", ""),
            generation=data.get("generation", 0),
            source_node=data.get("source_node"),
        )


@dataclass
class ConflictDetail:
    """Phase 15: Detailed information about a specific conflict.

    Records the type of conflict and which candidates are involved.
    """
    conflict_type: ConflictType
    involved_candidates: List[str]  # List of candidate keys
    severity: str  # "critical", "major", "minor"
    description: str
    resolution_hint: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.conflict_type.value,
            "involved_candidates": self.involved_candidates,
            "severity": self.severity,
            "description": self.description,
            "resolution_hint": self.resolution_hint,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictDetail":
        type_str = data.get("type", "lineage_conflict")
        conflict_type = ConflictType(type_str) if type_str in [t.value for t in ConflictType] else ConflictType.LINEAGE_CONFLICT
        return cls(
            conflict_type=conflict_type,
            involved_candidates=data.get("involved_candidates", []),
            severity=data.get("severity", "major"),
            description=data.get("description", ""),
            resolution_hint=data.get("resolution_hint", ""),
        )


@dataclass
class CompatibilitySummary:
    """Phase 15: Compatibility summary for candidate set.

    Aggregated compatibility information across all candidates.
    """
    lineage_compatible: bool
    specialization_compatible: bool
    validation_consistent: bool
    lifecycle_consistent: bool
    overall_compatible: bool
    compatibility_score: float  # 0.0-1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lineage_compatible": self.lineage_compatible,
            "specialization_compatible": self.specialization_compatible,
            "validation_consistent": self.validation_consistent,
            "lifecycle_consistent": self.lifecycle_consistent,
            "overall_compatible": self.overall_compatible,
            "compatibility_score": round(self.compatibility_score, 2),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompatibilitySummary":
        return cls(
            lineage_compatible=data.get("lineage_compatible", False),
            specialization_compatible=data.get("specialization_compatible", False),
            validation_consistent=data.get("validation_consistent", False),
            lifecycle_consistent=data.get("lifecycle_consistent", False),
            overall_compatible=data.get("overall_compatible", False),
            compatibility_score=data.get("compatibility_score", 0.0),
        )


@dataclass
class LifecycleSummary:
    """Phase 15: Lifecycle summary for candidate set.

    Aggregated lifecycle information across all candidates.
    """
    min_freshness: float
    max_freshness: float
    avg_freshness: float
    min_priority: int
    max_priority: int
    avg_priority: float
    freshness_range: float  # max - min
    priority_range: int  # max - min

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_freshness": round(self.min_freshness, 2),
            "max_freshness": round(self.max_freshness, 2),
            "avg_freshness": round(self.avg_freshness, 2),
            "min_priority": self.min_priority,
            "max_priority": self.max_priority,
            "avg_priority": round(self.avg_priority, 2),
            "freshness_range": round(self.freshness_range, 2),
            "priority_range": self.priority_range,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LifecycleSummary":
        return cls(
            min_freshness=data.get("min_freshness", 0.0),
            max_freshness=data.get("max_freshness", 0.0),
            avg_freshness=data.get("avg_freshness", 0.0),
            min_priority=data.get("min_priority", 0),
            max_priority=data.get("max_priority", 0),
            avg_priority=data.get("avg_priority", 0.0),
            freshness_range=data.get("freshness_range", 0.0),
            priority_range=data.get("priority_range", 0),
        )


@dataclass
class ValidationComparisonSummary:
    """Phase 15: Validation/comparison summary for candidate set.

    Aggregated validation information across all candidates.
    """
    all_passed_validation: bool
    any_passed_validation: bool
    validation_score_range: float  # 0.0-1.0
    min_validation_score: float
    max_validation_score: float
    consensus_on_promotion: bool
    promotion_recommendations: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "all_passed_validation": self.all_passed_validation,
            "any_passed_validation": self.any_passed_validation,
            "validation_score_range": round(self.validation_score_range, 2),
            "min_validation_score": round(self.min_validation_score, 2),
            "max_validation_score": round(self.max_validation_score, 2),
            "consensus_on_promotion": self.consensus_on_promotion,
            "promotion_recommendations": self.promotion_recommendations,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ValidationComparisonSummary":
        return cls(
            all_passed_validation=data.get("all_passed_validation", False),
            any_passed_validation=data.get("any_passed_validation", False),
            validation_score_range=data.get("validation_score_range", 0.0),
            min_validation_score=data.get("min_validation_score", 0.0),
            max_validation_score=data.get("max_validation_score", 0.0),
            consensus_on_promotion=data.get("consensus_on_promotion", False),
            promotion_recommendations=data.get("promotion_recommendations", []),
        )


@dataclass
class CandidateResolution:
    """Phase 15: Resolution for a single candidate.

    Records how this candidate was resolved in the conflict set.
    """
    candidate_key: str
    adapter_id: str
    generation: int
    selected: bool
    downgraded: bool
    rejected: bool
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "candidate_key": self.candidate_key,
            "adapter_id": self.adapter_id,
            "generation": self.generation,
            "selected": self.selected,
            "downgraded": self.downgraded,
            "rejected": self.rejected,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateResolution":
        return cls(
            candidate_key=data.get("candidate_key", ""),
            adapter_id=data.get("adapter_id", ""),
            generation=data.get("generation", 0),
            selected=data.get("selected", False),
            downgraded=data.get("downgraded", False),
            rejected=data.get("rejected", False),
            reason=data.get("reason", ""),
        )


@dataclass
class ConflictSet:
    """Phase 15: Complete conflict set for multiple remote candidates.

    Structured representation of conflicts between candidates.
    """
    # Identity
    set_id: str
    candidate_count: int
    candidate_keys: List[str]

    # Conflict detection
    has_conflicts: bool
    conflict_count: int
    conflicts: List[ConflictDetail]
    conflict_types: List[str]

    # Summaries
    compatibility: CompatibilitySummary
    lifecycle: LifecycleSummary
    validation: ValidationComparisonSummary

    # Resolution
    resolution_decision: ResolutionDecision
    selected_candidate: Optional[CandidateIdentity]
    candidate_resolutions: List[CandidateResolution]

    # Metadata
    resolution_reason: str
    recommendation: str
    fallback_used: bool
    version: str
    resolved_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {
                "set_id": self.set_id,
                "candidate_count": self.candidate_count,
                "candidate_keys": self.candidate_keys,
            },
            "conflicts": {
                "has_conflicts": self.has_conflicts,
                "count": self.conflict_count,
                "types": self.conflict_types,
                "details": [c.to_dict() for c in self.conflicts],
            },
            "summaries": {
                "compatibility": self.compatibility.to_dict(),
                "lifecycle": self.lifecycle.to_dict(),
                "validation": self.validation.to_dict(),
            },
            "resolution": {
                "decision": self.resolution_decision.value,
                "selected_candidate": self.selected_candidate.to_dict() if self.selected_candidate else None,
                "candidate_resolutions": [cr.to_dict() for cr in self.candidate_resolutions],
                "reason": self.resolution_reason,
                "recommendation": self.recommendation,
            },
            "meta": {
                "fallback_used": self.fallback_used,
                "version": self.version,
                "resolved_at": self.resolved_at,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictSet":
        identity = data.get("identity", {})
        conflicts = data.get("conflicts", {})
        summaries = data.get("summaries", {})
        resolution = data.get("resolution", {})
        meta = data.get("meta", {})

        decision_str = resolution.get("decision", "reject_all")
        decision = ResolutionDecision(decision_str) if decision_str in [d.value for d in ResolutionDecision] else ResolutionDecision.REJECT_ALL

        selected_data = resolution.get("selected_candidate")
        selected = CandidateIdentity.from_dict(selected_data) if selected_data else None

        return cls(
            set_id=identity.get("set_id", ""),
            candidate_count=identity.get("candidate_count", 0),
            candidate_keys=identity.get("candidate_keys", []),
            has_conflicts=conflicts.get("has_conflicts", False),
            conflict_count=conflicts.get("count", 0),
            conflicts=[ConflictDetail.from_dict(c) for c in conflicts.get("details", [])],
            conflict_types=conflicts.get("types", []),
            compatibility=CompatibilitySummary.from_dict(summaries.get("compatibility", {})),
            lifecycle=LifecycleSummary.from_dict(summaries.get("lifecycle", {})),
            validation=ValidationComparisonSummary.from_dict(summaries.get("validation", {})),
            resolution_decision=decision,
            selected_candidate=selected,
            candidate_resolutions=[CandidateResolution.from_dict(cr) for cr in resolution.get("candidate_resolutions", [])],
            resolution_reason=resolution.get("reason", ""),
            recommendation=resolution.get("recommendation", ""),
            fallback_used=meta.get("fallback_used", False),
            version=meta.get("version", "1.0"),
            resolved_at=meta.get("resolved_at", ""),
        )

    def is_resolved(self) -> bool:
        """Check if conflict set has been resolved."""
        return self.resolution_decision != ResolutionDecision.REJECT_ALL

    def can_proceed(self) -> bool:
        """Check if resolution allows proceeding with at least one candidate."""
        return self.resolution_decision in (ResolutionDecision.SELECT_ONE, ResolutionDecision.DOWNGRADE_SOME)

    def get_selected_candidate_key(self) -> Optional[str]:
        """Get the key of the selected candidate, if any."""
        if self.selected_candidate:
            return self.selected_candidate.to_key()
        return None


@dataclass
class ConflictResolutionResult:
    """Phase 15: Complete conflict resolution result.

    Includes the conflict set and additional metadata.
    """
    processed_at: str
    processor_version: str
    fallback_used: bool
    conflict_set: ConflictSet
    trace_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "processed_at": self.processed_at,
            "processor_version": self.processor_version,
            "fallback_used": self.fallback_used,
            "conflict_set": self.conflict_set.to_dict(),
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ConflictResolutionResult":
        return cls(
            processed_at=data.get("processed_at", ""),
            processor_version=data.get("processor_version", "1.0"),
            fallback_used=data.get("fallback_used", False),
            conflict_set=ConflictSet.from_dict(data.get("conflict_set", {})),
            trace_id=data.get("trace_id", ""),
        )


class RemoteCandidateConflictResolver:
    """Phase 15: Conflict resolver for remote candidates.

    Detects and resolves conflicts between multiple remote candidates.
    Provides deterministic, structured conflict resolution.

    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"

    # Thresholds for conflict detection
    FRESHNESS_CONFLICT_THRESHOLD = 0.3  # Freshness diff > 0.3 is conflict
    PRIORITY_CONFLICT_THRESHOLD = 20  # Priority diff > 20 is conflict
    VALIDATION_SCORE_CONFLICT_THRESHOLD = 0.3  # Score diff > 0.3 is conflict

    @classmethod
    def resolve(
        cls,
        candidates: List[Dict[str, Any]],
        fallback_on_error: bool = True,
    ) -> ConflictResolutionResult:
        """Resolve conflicts among multiple remote candidates.

        Phase 15: Main entry point for conflict resolution.

        Args:
            candidates: List of candidate dictionaries (from lifecycle results)
            fallback_on_error: Whether to return safe fallback on error

        Returns:
            ConflictResolutionResult with full conflict analysis and resolution
        """
        try:
            return cls._do_resolve(candidates)
        except Exception as e:
            if fallback_on_error:
                return cls._fallback_result(candidates, str(e))
            raise

    @classmethod
    def _do_resolve(
        cls,
        candidates: List[Dict[str, Any]],
    ) -> ConflictResolutionResult:
        """Internal conflict resolution logic."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        processed_at = now.isoformat().replace("+00:00", "Z")
        trace_id = str(uuid.uuid4())[:8]

        # Build candidate identities
        candidate_identities = cls._build_identities(candidates)

        # Detect conflicts
        conflicts = cls._detect_conflicts(candidates, candidate_identities)

        # Build summaries
        compatibility = cls._build_compatibility_summary(candidates)
        lifecycle = cls._build_lifecycle_summary(candidates)
        validation = cls._build_validation_summary(candidates)

        # Determine resolution
        decision, selected, resolutions, reason, recommendation = cls._determine_resolution(
            candidates, candidate_identities, conflicts, compatibility, lifecycle, validation
        )

        # Build conflict set
        conflict_set = ConflictSet(
            set_id=f"conflict-{trace_id}",
            candidate_count=len(candidates),
            candidate_keys=[ci.to_key() for ci in candidate_identities],
            has_conflicts=len(conflicts) > 0,
            conflict_count=len(conflicts),
            conflicts=conflicts,
            conflict_types=list(set(c.conflict_type.value for c in conflicts)),
            compatibility=compatibility,
            lifecycle=lifecycle,
            validation=validation,
            resolution_decision=decision,
            selected_candidate=selected,
            candidate_resolutions=resolutions,
            resolution_reason=reason,
            recommendation=recommendation,
            fallback_used=False,
            version=cls.VERSION,
            resolved_at=processed_at,
        )

        return ConflictResolutionResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=False,
            conflict_set=conflict_set,
            trace_id=trace_id,
        )

    @classmethod
    def _build_identities(cls, candidates: List[Dict[str, Any]]) -> List[CandidateIdentity]:
        """Build candidate identities from candidate data."""
        identities = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            identity = c.get("identity", {}) if c else {}
            ci = CandidateIdentity(
                adapter_id=identity.get("adapter_id", ""),
                generation=identity.get("generation", 0),
                source_node=identity.get("source_node"),
            )
            identities.append(ci)
        return identities

    @classmethod
    def _detect_conflicts(
        cls,
        candidates: List[Dict[str, Any]],
        identities: List[CandidateIdentity],
    ) -> List[ConflictDetail]:
        """Detect conflicts among candidates."""
        conflicts = []

        # Check for duplicate candidates
        seen_keys: Dict[str, int] = {}
        for i, identity in enumerate(identities):
            key = identity.to_key()
            if key in seen_keys:
                conflicts.append(ConflictDetail(
                    conflict_type=ConflictType.DUPLICATE_CANDIDATE,
                    involved_candidates=[key],
                    severity="major",
                    description=f"Duplicate candidate detected: {key}",
                    resolution_hint="Keep only the most recent instance",
                ))
            else:
                seen_keys[key] = i

        # Check for duplicate sources
        seen_sources: Dict[str, str] = {}
        for identity in identities:
            if identity.source_node:
                if identity.source_node in seen_sources:
                    conflicts.append(ConflictDetail(
                        conflict_type=ConflictType.DUPLICATE_SOURCE,
                        involved_candidates=[identity.to_key(), seen_sources[identity.source_node]],
                        severity="minor",
                        description=f"Multiple candidates from same source: {identity.source_node}",
                        resolution_hint="Select highest priority candidate from this source",
                    ))
                else:
                    seen_sources[identity.source_node] = identity.to_key()

        # Check for lineage conflicts
        adapter_ids = set(ci.adapter_id for ci in identities)
        has_adapter_id_conflict = len(adapter_ids) > 1
        if has_adapter_id_conflict:
            conflicts.append(ConflictDetail(
                conflict_type=ConflictType.LINEAGE_CONFLICT,
                involved_candidates=[ci.to_key() for ci in identities],
                severity="critical",
                description=f"Multiple adapter IDs in candidate set: {adapter_ids}",
                resolution_hint="Reject all or hold for manual review",
            ))

        # Check generation compatibility (only if no adapter ID conflict already detected)
        generations = [ci.generation for ci in identities]
        if generations and not has_adapter_id_conflict:
            gen_range = max(generations) - min(generations)
            if gen_range > 2:
                conflicts.append(ConflictDetail(
                    conflict_type=ConflictType.LINEAGE_CONFLICT,
                    involved_candidates=[ci.to_key() for ci in identities],
                    severity="major",
                    description=f"Large generation gap detected: {gen_range}",
                    resolution_hint="Hold all candidates for observation",
                ))

        # Check for lifecycle/priority conflicts
        freshness_scores = []
        priority_scores = []
        for c in candidates:
            scores = c.get("scores", {})
            freshness_scores.append(scores.get("freshness", 0.0))
            priority_scores.append(scores.get("priority", 0))

        if freshness_scores:
            freshness_range = max(freshness_scores) - min(freshness_scores)
            if freshness_range > cls.FRESHNESS_CONFLICT_THRESHOLD:
                conflicts.append(ConflictDetail(
                    conflict_type=ConflictType.LIFECYCLE_CONFLICT,
                    involved_candidates=[ci.to_key() for ci in identities],
                    severity="minor",
                    description=f"Freshness scores vary significantly: {freshness_range:.2f}",
                    resolution_hint="Select candidate with highest freshness",
                ))

        if priority_scores:
            priority_range = max(priority_scores) - min(priority_scores)
            if priority_range > cls.PRIORITY_CONFLICT_THRESHOLD:
                conflicts.append(ConflictDetail(
                    conflict_type=ConflictType.PRIORITY_CONFLICT,
                    involved_candidates=[ci.to_key() for ci in identities],
                    severity="minor",
                    description=f"Priority scores vary significantly: {priority_range}",
                    resolution_hint="Select highest priority candidate",
                ))

        # Check for validation conflicts
        validation_scores = []
        recommendations = []
        for c in candidates:
            decision = c.get("decision", {})
            recommendations.append(decision.get("action", "keep"))
            # Try to extract validation score from various sources
            score = 0.0
            scores = c.get("scores", {})
            if "freshness" in scores:
                score = scores.get("freshness", 0.0)
            validation_scores.append(score)

        if validation_scores:
            score_range = max(validation_scores) - min(validation_scores)
            if score_range > cls.VALIDATION_SCORE_CONFLICT_THRESHOLD:
                conflicts.append(ConflictDetail(
                    conflict_type=ConflictType.VALIDATION_CONFLICT,
                    involved_candidates=[ci.to_key() for ci in identities],
                    severity="major",
                    description=f"Validation scores vary significantly: {score_range:.2f}",
                    resolution_hint="Select candidate with highest validation score",
                ))

        # Check for recommendation conflicts
        unique_recs = set(recommendations)
        if len(unique_recs) > 1:
            conflicts.append(ConflictDetail(
                conflict_type=ConflictType.RECOMMENDATION_CONFLICT,
                involved_candidates=[ci.to_key() for ci in identities],
                severity="major",
                description=f"Mixed recommendations: {unique_recs}",
                resolution_hint="Prioritize candidates with 'keep' or 'ready' status",
            ))

        return conflicts

    @classmethod
    def _build_compatibility_summary(cls, candidates: List[Dict[str, Any]]) -> CompatibilitySummary:
        """Build compatibility summary from candidates."""
        # Check lineage compatibility
        adapter_ids = set()
        for c in candidates:
            identity = c.get("identity", {})
            adapter_ids.add(identity.get("adapter_id", ""))
        lineage_compatible = len(adapter_ids) <= 1

        # Check specialization compatibility (simplified)
        specialization_compatible = lineage_compatible

        # Check validation consistency
        decisions = []
        for c in candidates:
            decision = c.get("decision", {})
            decisions.append(decision.get("action", ""))
        validation_consistent = len(set(decisions)) <= 1

        # Check lifecycle consistency
        states = []
        for c in candidates:
            state = c.get("state", {})
            states.append(state.get("current", ""))
        lifecycle_consistent = len(set(states)) <= 1

        # Calculate overall compatibility score
        score = 1.0
        if not lineage_compatible:
            score -= 0.4
        if not specialization_compatible:
            score -= 0.2
        if not validation_consistent:
            score -= 0.2
        if not lifecycle_consistent:
            score -= 0.1

        return CompatibilitySummary(
            lineage_compatible=lineage_compatible,
            specialization_compatible=specialization_compatible,
            validation_consistent=validation_consistent,
            lifecycle_consistent=lifecycle_consistent,
            overall_compatible=score >= 0.5,
            compatibility_score=max(0.0, score),
        )

    @classmethod
    def _build_lifecycle_summary(cls, candidates: List[Dict[str, Any]]) -> LifecycleSummary:
        """Build lifecycle summary from candidates."""
        freshness_scores = []
        priority_scores = []

        for c in candidates:
            scores = c.get("scores", {})
            freshness_scores.append(scores.get("freshness", 0.0))
            priority_scores.append(scores.get("priority", 0))

        if not freshness_scores:
            freshness_scores = [0.0]
        if not priority_scores:
            priority_scores = [0]

        return LifecycleSummary(
            min_freshness=min(freshness_scores),
            max_freshness=max(freshness_scores),
            avg_freshness=sum(freshness_scores) / len(freshness_scores),
            min_priority=min(priority_scores),
            max_priority=max(priority_scores),
            avg_priority=sum(priority_scores) / len(priority_scores),
            freshness_range=max(freshness_scores) - min(freshness_scores),
            priority_range=max(priority_scores) - min(priority_scores),
        )

    @classmethod
    def _build_validation_summary(cls, candidates: List[Dict[str, Any]]) -> ValidationComparisonSummary:
        """Build validation summary from candidates."""
        scores = []
        recommendations = []

        for c in candidates:
            decision = c.get("decision", {})
            recommendations.append(decision.get("action", "keep"))
            # Extract score from freshness as proxy
            scores_data = c.get("scores", {})
            scores.append(scores_data.get("freshness", 0.0))

        if not scores:
            scores = [0.0]

        all_passed = all(s >= 0.5 for s in scores)
        any_passed = any(s >= 0.5 for s in scores)

        # Check consensus on promotion
        promotion_recs = [r for r in recommendations if r in ("keep", "ready")]
        consensus = len(set(promotion_recs)) <= 1 and len(promotion_recs) > 0

        return ValidationComparisonSummary(
            all_passed_validation=all_passed,
            any_passed_validation=any_passed,
            validation_score_range=max(scores) - min(scores),
            min_validation_score=min(scores),
            max_validation_score=max(scores),
            consensus_on_promotion=consensus,
            promotion_recommendations=list(set(recommendations)),
        )

    @classmethod
    def _determine_resolution(
        cls,
        candidates: List[Dict[str, Any]],
        identities: List[CandidateIdentity],
        conflicts: List[ConflictDetail],
        compatibility: CompatibilitySummary,
        lifecycle: LifecycleSummary,
        validation: ValidationComparisonSummary,
    ) -> Tuple[ResolutionDecision, Optional[CandidateIdentity], List[CandidateResolution], str, str]:
        """Determine resolution for conflict set."""
        # Critical lineage conflict -> reject all
        critical_conflicts = [c for c in conflicts if c.severity == "critical"]
        if critical_conflicts:
            resolutions = []
            for identity in identities:
                resolutions.append(CandidateResolution(
                    candidate_key=identity.to_key(),
                    adapter_id=identity.adapter_id,
                    generation=identity.generation,
                    selected=False,
                    downgraded=False,
                    rejected=True,
                    reason="Critical conflict detected",
                ))
            return (
                ResolutionDecision.REJECT_ALL,
                None,
                resolutions,
                "Critical lineage conflict - cannot reconcile",
                "reject_all_due_to_critical_conflict",
            )

        # Multiple major conflicts -> hold all
        major_conflicts = [c for c in conflicts if c.severity == "major"]
        if len(major_conflicts) >= 2:
            resolutions = []
            for identity in identities:
                resolutions.append(CandidateResolution(
                    candidate_key=identity.to_key(),
                    adapter_id=identity.adapter_id,
                    generation=identity.generation,
                    selected=False,
                    downgraded=False,
                    rejected=False,
                    reason="Multiple major conflicts - holding for observation",
                ))
            return (
                ResolutionDecision.HOLD_ALL,
                None,
                resolutions,
                "Multiple major conflicts detected - holding all candidates",
                "hold_all_for_observation",
            )

        # Calculate composite scores for each candidate
        candidate_scores = []
        for i, (c, identity) in enumerate(zip(candidates, identities)):
            scores = c.get("scores", {})
            freshness = scores.get("freshness", 0.0)
            priority = scores.get("priority", 0)

            # Composite score: freshness * 0.4 + normalized_priority * 0.3 + validation_proxy * 0.3
            composite = (freshness * 0.4) + ((priority / 100.0) * 0.3) + (freshness * 0.3)
            candidate_scores.append((i, identity, composite, c))

        # Sort by composite score descending
        candidate_scores.sort(key=lambda x: x[2], reverse=True)

        # If clear winner with significant margin -> select_one
        if len(candidate_scores) >= 2:
            best_score = candidate_scores[0][2]
            second_score = candidate_scores[1][2]
            score_margin = best_score - second_score

            if score_margin > 0.15:  # 15% margin is significant
                selected = candidate_scores[0][1]
                resolutions = []
                for i, identity, score, c in candidate_scores:
                    is_selected = (i == candidate_scores[0][0])
                    resolutions.append(CandidateResolution(
                        candidate_key=identity.to_key(),
                        adapter_id=identity.adapter_id,
                        generation=identity.generation,
                        selected=is_selected,
                        downgraded=False,
                        rejected=not is_selected,
                        reason="Selected as optimal candidate" if is_selected else "Lower composite score",
                    ))
                return (
                    ResolutionDecision.SELECT_ONE,
                    selected,
                    resolutions,
                    f"Clear winner with {score_margin:.2f} score margin",
                    "select_optimal_candidate",
                )

        # Some conflicts but not severe -> downgrade some
        if conflicts and len(candidate_scores) > 1:
            # Select top candidate, downgrade others
            selected = candidate_scores[0][1]
            resolutions = []
            for i, identity, score, c in candidate_scores:
                is_selected = (i == candidate_scores[0][0])
                resolutions.append(CandidateResolution(
                    candidate_key=identity.to_key(),
                    adapter_id=identity.adapter_id,
                    generation=identity.generation,
                    selected=is_selected,
                    downgraded=not is_selected,
                    rejected=False,
                    reason="Selected as optimal" if is_selected else "Downgraded due to conflict",
                ))
            return (
                ResolutionDecision.DOWNGRADE_SOME,
                selected,
                resolutions,
                "Downgrading non-optimal candidates due to conflicts",
                "downgrade_non_optimal",
            )

        # No clear winner, no severe conflicts -> hold all
        resolutions = []
        for identity in identities:
            resolutions.append(CandidateResolution(
                candidate_key=identity.to_key(),
                adapter_id=identity.adapter_id,
                generation=identity.generation,
                selected=False,
                downgraded=False,
                rejected=False,
                reason="No clear optimal candidate",
            ))
        return (
            ResolutionDecision.HOLD_ALL,
            None,
            resolutions,
            "No clear optimal candidate - holding for observation",
            "hold_all_no_clear_winner",
        )

    @classmethod
    def _fallback_result(
        cls,
        candidates: List[Dict[str, Any]],
        error_message: str,
    ) -> ConflictResolutionResult:
        """Create fallback resolution result on error."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        processed_at = now.isoformat().replace("+00:00", "Z")
        trace_id = str(uuid.uuid4())[:8]

        # Build minimal identities
        identities = []
        for c in candidates:
            if not isinstance(c, dict):
                continue
            identity = c.get("identity", {}) if c else {}
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
            version=cls.VERSION,
            resolved_at=processed_at,
        )

        return ConflictResolutionResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=True,
            conflict_set=conflict_set,
            trace_id=trace_id,
        )

    @classmethod
    def quick_conflict_check(
        cls,
        candidates: List[Dict[str, Any]],
    ) -> bool:
        """Quick check if candidates have conflicts.

        Phase 15: Fast path for conflict detection.
        Returns True if conflicts detected, False otherwise.
        """
        try:
            if len(candidates) <= 1:
                return False

            # Check for duplicate sources
            sources = set()
            for c in candidates:
                if not isinstance(c, dict):
                    return True  # Invalid candidate is a conflict
                identity = c.get("identity", {})
                source = identity.get("source_node")
                if source:
                    if source in sources:
                        return True
                    sources.add(source)

            # Check for multiple adapter IDs
            adapter_ids = set()
            for c in candidates:
                if not isinstance(c, dict):
                    return True
                identity = c.get("identity", {})
                adapter_ids.add(identity.get("adapter_id", ""))
            if len(adapter_ids) > 1:
                return True

            # Check for large freshness/priority variance
            freshness_scores = []
            priority_scores = []
            for c in candidates:
                if not isinstance(c, dict):
                    return True
                scores = c.get("scores", {})
                freshness_scores.append(scores.get("freshness", 0.0))
                priority_scores.append(scores.get("priority", 0))

            if freshness_scores:
                if max(freshness_scores) - min(freshness_scores) > cls.FRESHNESS_CONFLICT_THRESHOLD:
                    return True

            if priority_scores:
                if max(priority_scores) - min(priority_scores) > cls.PRIORITY_CONFLICT_THRESHOLD:
                    return True

            return False
        except Exception:
            return True  # Conservative: treat errors as conflict

    @classmethod
    def batch_resolve(
        cls,
        candidate_sets: List[List[Dict[str, Any]]],
    ) -> List[ConflictResolutionResult]:
        """Resolve conflicts for multiple candidate sets.

        Phase 15: Batch processing for efficiency.
        """
        results = []
        for candidates in candidate_sets:
            result = cls.resolve(candidates, fallback_on_error=True)
            results.append(result)
        return results
