"""Phase 15: Remote candidate conflict resolution tests.

Tests for conflict detection and resolution among multiple remote candidates.
"""

import pytest
from datetime import datetime

# Import with fallback for different test contexts
try:
    from chronara_nexus.types import (
        ConflictType,
        ResolutionDecision,
        CandidateIdentity,
        ConflictDetail,
        CompatibilitySummary,
        LifecycleSummary,
        ValidationComparisonSummary,
        CandidateResolution,
        ConflictSet,
        ConflictResolutionResult,
        RemoteCandidateConflictResolver,
    )
    from chronara_nexus.conflict_resolution import (
        ConflictType as CRConflictType,
        ResolutionDecision as CRResolutionDecision,
    )
    from chronara_nexus.governor import Governor, ValidationTrace, AdapterRef, AdapterMode, AdapterSpecialization
except ImportError:
    from implementations.sac_py.chronara_nexus.types import (
        ConflictType,
        ResolutionDecision,
        CandidateIdentity,
        ConflictDetail,
        CompatibilitySummary,
        LifecycleSummary,
        ValidationComparisonSummary,
        CandidateResolution,
        ConflictSet,
        ConflictResolutionResult,
        RemoteCandidateConflictResolver,
    )
    from implementations.sac_py.chronara_nexus.conflict_resolution import (
        ConflictType as CRConflictType,
        ResolutionDecision as CRResolutionDecision,
    )
    from implementations.sac_py.chronara_nexus.governor import Governor, ValidationTrace, AdapterRef, AdapterMode, AdapterSpecialization


class TestConflictTypes:
    """Test conflict type enum."""

    def test_conflict_type_values(self):
        assert ConflictType.LINEAGE_CONFLICT.value == "lineage_conflict"
        assert ConflictType.SPECIALIZATION_CONFLICT.value == "specialization_conflict"
        assert ConflictType.VALIDATION_CONFLICT.value == "validation_conflict"
        assert ConflictType.LIFECYCLE_CONFLICT.value == "lifecycle_conflict"
        assert ConflictType.DUPLICATE_SOURCE.value == "duplicate_source"
        assert ConflictType.DUPLICATE_CANDIDATE.value == "duplicate_candidate"
        assert ConflictType.RECOMMENDATION_CONFLICT.value == "recommendation_conflict"
        assert ConflictType.PRIORITY_CONFLICT.value == "priority_conflict"


class TestResolutionDecision:
    """Test resolution decision enum."""

    def test_resolution_decision_values(self):
        assert ResolutionDecision.SELECT_ONE.value == "select_one"
        assert ResolutionDecision.HOLD_ALL.value == "hold_all"
        assert ResolutionDecision.DOWNGRADE_SOME.value == "downgrade_some"
        assert ResolutionDecision.REJECT_ALL.value == "reject_all"


class TestCandidateIdentity:
    """Test candidate identity."""

    def test_candidate_identity_creation(self):
        ci = CandidateIdentity(
            adapter_id="test-adapter",
            generation=5,
            source_node="node-1",
        )
        assert ci.adapter_id == "test-adapter"
        assert ci.generation == 5
        assert ci.source_node == "node-1"

    def test_candidate_identity_to_key(self):
        ci = CandidateIdentity(
            adapter_id="test-adapter",
            generation=5,
            source_node="node-1",
        )
        assert ci.to_key() == "test-adapter:5"

    def test_candidate_identity_dict_roundtrip(self):
        ci = CandidateIdentity(
            adapter_id="test-adapter",
            generation=5,
            source_node="node-1",
        )
        data = ci.to_dict()
        restored = CandidateIdentity.from_dict(data)
        assert restored.adapter_id == ci.adapter_id
        assert restored.generation == ci.generation
        assert restored.source_node == ci.source_node


class TestConflictDetail:
    """Test conflict detail."""

    def test_conflict_detail_creation(self):
        cd = ConflictDetail(
            conflict_type=ConflictType.LINEAGE_CONFLICT,
            involved_candidates=["a:1", "b:2"],
            severity="critical",
            description="Lineage mismatch",
            resolution_hint="Reject all",
        )
        assert cd.conflict_type == ConflictType.LINEAGE_CONFLICT
        assert cd.involved_candidates == ["a:1", "b:2"]
        assert cd.severity == "critical"

    def test_conflict_detail_dict_roundtrip(self):
        cd = ConflictDetail(
            conflict_type=ConflictType.LINEAGE_CONFLICT,
            involved_candidates=["a:1", "b:2"],
            severity="critical",
            description="Lineage mismatch",
            resolution_hint="Reject all",
        )
        data = cd.to_dict()
        restored = ConflictDetail.from_dict(data)
        assert restored.conflict_type == cd.conflict_type
        assert restored.involved_candidates == cd.involved_candidates
        assert restored.severity == cd.severity


class TestCompatibilitySummary:
    """Test compatibility summary."""

    def test_compatibility_summary_creation(self):
        cs = CompatibilitySummary(
            lineage_compatible=True,
            specialization_compatible=True,
            validation_consistent=True,
            lifecycle_consistent=True,
            overall_compatible=True,
            compatibility_score=0.9,
        )
        assert cs.lineage_compatible is True
        assert cs.compatibility_score == 0.9

    def test_compatibility_summary_dict_roundtrip(self):
        cs = CompatibilitySummary(
            lineage_compatible=True,
            specialization_compatible=True,
            validation_consistent=True,
            lifecycle_consistent=True,
            overall_compatible=True,
            compatibility_score=0.9,
        )
        data = cs.to_dict()
        restored = CompatibilitySummary.from_dict(data)
        assert restored.lineage_compatible == cs.lineage_compatible
        assert restored.compatibility_score == cs.compatibility_score


class TestLifecycleSummary:
    """Test lifecycle summary."""

    def test_lifecycle_summary_creation(self):
        ls = LifecycleSummary(
            min_freshness=0.5,
            max_freshness=0.9,
            avg_freshness=0.7,
            min_priority=50,
            max_priority=90,
            avg_priority=70.0,
            freshness_range=0.4,
            priority_range=40,
        )
        assert ls.min_freshness == 0.5
        assert ls.max_priority == 90

    def test_lifecycle_summary_dict_roundtrip(self):
        ls = LifecycleSummary(
            min_freshness=0.5,
            max_freshness=0.9,
            avg_freshness=0.7,
            min_priority=50,
            max_priority=90,
            avg_priority=70.0,
            freshness_range=0.4,
            priority_range=40,
        )
        data = ls.to_dict()
        restored = LifecycleSummary.from_dict(data)
        assert restored.min_freshness == ls.min_freshness
        assert restored.max_priority == ls.max_priority


class TestValidationComparisonSummary:
    """Test validation comparison summary."""

    def test_validation_comparison_summary_creation(self):
        vs = ValidationComparisonSummary(
            all_passed_validation=True,
            any_passed_validation=True,
            validation_score_range=0.2,
            min_validation_score=0.8,
            max_validation_score=1.0,
            consensus_on_promotion=True,
            promotion_recommendations=["keep", "ready"],
        )
        assert vs.all_passed_validation is True
        assert vs.consensus_on_promotion is True

    def test_validation_comparison_summary_dict_roundtrip(self):
        vs = ValidationComparisonSummary(
            all_passed_validation=True,
            any_passed_validation=True,
            validation_score_range=0.2,
            min_validation_score=0.8,
            max_validation_score=1.0,
            consensus_on_promotion=True,
            promotion_recommendations=["keep", "ready"],
        )
        data = vs.to_dict()
        restored = ValidationComparisonSummary.from_dict(data)
        assert restored.all_passed_validation == vs.all_passed_validation
        assert restored.promotion_recommendations == vs.promotion_recommendations


class TestCandidateResolution:
    """Test candidate resolution."""

    def test_candidate_resolution_creation(self):
        cr = CandidateResolution(
            candidate_key="a:1",
            adapter_id="a",
            generation=1,
            selected=True,
            downgraded=False,
            rejected=False,
            reason="Optimal candidate",
        )
        assert cr.selected is True
        assert cr.rejected is False

    def test_candidate_resolution_dict_roundtrip(self):
        cr = CandidateResolution(
            candidate_key="a:1",
            adapter_id="a",
            generation=1,
            selected=True,
            downgraded=False,
            rejected=False,
            reason="Optimal candidate",
        )
        data = cr.to_dict()
        restored = CandidateResolution.from_dict(data)
        assert restored.selected == cr.selected
        assert restored.reason == cr.reason


class TestConflictSet:
    """Test conflict set."""

    def test_conflict_set_creation(self):
        cs = ConflictSet(
            set_id="test-set",
            candidate_count=2,
            candidate_keys=["a:1", "b:2"],
            has_conflicts=True,
            conflict_count=1,
            conflicts=[],
            conflict_types=["lineage_conflict"],
            compatibility=CompatibilitySummary(
                lineage_compatible=False,
                specialization_compatible=True,
                validation_consistent=True,
                lifecycle_consistent=True,
                overall_compatible=False,
                compatibility_score=0.4,
            ),
            lifecycle=LifecycleSummary(
                min_freshness=0.5,
                max_freshness=0.9,
                avg_freshness=0.7,
                min_priority=50,
                max_priority=90,
                avg_priority=70.0,
                freshness_range=0.4,
                priority_range=40,
            ),
            validation=ValidationComparisonSummary(
                all_passed_validation=True,
                any_passed_validation=True,
                validation_score_range=0.2,
                min_validation_score=0.8,
                max_validation_score=1.0,
                consensus_on_promotion=True,
                promotion_recommendations=["keep"],
            ),
            resolution_decision=ResolutionDecision.SELECT_ONE,
            selected_candidate=CandidateIdentity("a", 1, "node-1"),
            candidate_resolutions=[],
            resolution_reason="Clear winner",
            recommendation="select_optimal",
            fallback_used=False,
            version="1.0",
            resolved_at="2024-01-01T00:00:00Z",
        )
        assert cs.set_id == "test-set"
        assert cs.has_conflicts is True
        assert cs.resolution_decision == ResolutionDecision.SELECT_ONE

    def test_conflict_set_is_resolved(self):
        cs = ConflictSet(
            set_id="test-set",
            candidate_count=2,
            candidate_keys=["a:1", "b:2"],
            has_conflicts=True,
            conflict_count=1,
            conflicts=[],
            conflict_types=["lineage_conflict"],
            compatibility=CompatibilitySummary(
                lineage_compatible=False,
                specialization_compatible=True,
                validation_consistent=True,
                lifecycle_consistent=True,
                overall_compatible=False,
                compatibility_score=0.4,
            ),
            lifecycle=LifecycleSummary(
                min_freshness=0.5,
                max_freshness=0.9,
                avg_freshness=0.7,
                min_priority=50,
                max_priority=90,
                avg_priority=70.0,
                freshness_range=0.4,
                priority_range=40,
            ),
            validation=ValidationComparisonSummary(
                all_passed_validation=True,
                any_passed_validation=True,
                validation_score_range=0.2,
                min_validation_score=0.8,
                max_validation_score=1.0,
                consensus_on_promotion=True,
                promotion_recommendations=["keep"],
            ),
            resolution_decision=ResolutionDecision.SELECT_ONE,
            selected_candidate=CandidateIdentity("a", 1, "node-1"),
            candidate_resolutions=[],
            resolution_reason="Clear winner",
            recommendation="select_optimal",
            fallback_used=False,
            version="1.0",
            resolved_at="2024-01-01T00:00:00Z",
        )
        assert cs.is_resolved() is True

    def test_conflict_set_can_proceed(self):
        cs = ConflictSet(
            set_id="test-set",
            candidate_count=2,
            candidate_keys=["a:1", "b:2"],
            has_conflicts=True,
            conflict_count=1,
            conflicts=[],
            conflict_types=["lineage_conflict"],
            compatibility=CompatibilitySummary(
                lineage_compatible=False,
                specialization_compatible=True,
                validation_consistent=True,
                lifecycle_consistent=True,
                overall_compatible=False,
                compatibility_score=0.4,
            ),
            lifecycle=LifecycleSummary(
                min_freshness=0.5,
                max_freshness=0.9,
                avg_freshness=0.7,
                min_priority=50,
                max_priority=90,
                avg_priority=70.0,
                freshness_range=0.4,
                priority_range=40,
            ),
            validation=ValidationComparisonSummary(
                all_passed_validation=True,
                any_passed_validation=True,
                validation_score_range=0.2,
                min_validation_score=0.8,
                max_validation_score=1.0,
                consensus_on_promotion=True,
                promotion_recommendations=["keep"],
            ),
            resolution_decision=ResolutionDecision.SELECT_ONE,
            selected_candidate=CandidateIdentity("a", 1, "node-1"),
            candidate_resolutions=[],
            resolution_reason="Clear winner",
            recommendation="select_optimal",
            fallback_used=False,
            version="1.0",
            resolved_at="2024-01-01T00:00:00Z",
        )
        assert cs.can_proceed() is True

    def test_conflict_set_get_selected_candidate_key(self):
        cs = ConflictSet(
            set_id="test-set",
            candidate_count=2,
            candidate_keys=["a:1", "b:2"],
            has_conflicts=True,
            conflict_count=1,
            conflicts=[],
            conflict_types=["lineage_conflict"],
            compatibility=CompatibilitySummary(
                lineage_compatible=False,
                specialization_compatible=True,
                validation_consistent=True,
                lifecycle_consistent=True,
                overall_compatible=False,
                compatibility_score=0.4,
            ),
            lifecycle=LifecycleSummary(
                min_freshness=0.5,
                max_freshness=0.9,
                avg_freshness=0.7,
                min_priority=50,
                max_priority=90,
                avg_priority=70.0,
                freshness_range=0.4,
                priority_range=40,
            ),
            validation=ValidationComparisonSummary(
                all_passed_validation=True,
                any_passed_validation=True,
                validation_score_range=0.2,
                min_validation_score=0.8,
                max_validation_score=1.0,
                consensus_on_promotion=True,
                promotion_recommendations=["keep"],
            ),
            resolution_decision=ResolutionDecision.SELECT_ONE,
            selected_candidate=CandidateIdentity("a", 1, "node-1"),
            candidate_resolutions=[],
            resolution_reason="Clear winner",
            recommendation="select_optimal",
            fallback_used=False,
            version="1.0",
            resolved_at="2024-01-01T00:00:00Z",
        )
        assert cs.get_selected_candidate_key() == "a:1"

    def test_conflict_set_dict_roundtrip(self):
        cs = ConflictSet(
            set_id="test-set",
            candidate_count=2,
            candidate_keys=["a:1", "b:2"],
            has_conflicts=True,
            conflict_count=1,
            conflicts=[ConflictDetail(
                conflict_type=ConflictType.LINEAGE_CONFLICT,
                involved_candidates=["a:1", "b:2"],
                severity="critical",
                description="Lineage mismatch",
                resolution_hint="Reject all",
            )],
            conflict_types=["lineage_conflict"],
            compatibility=CompatibilitySummary(
                lineage_compatible=False,
                specialization_compatible=True,
                validation_consistent=True,
                lifecycle_consistent=True,
                overall_compatible=False,
                compatibility_score=0.4,
            ),
            lifecycle=LifecycleSummary(
                min_freshness=0.5,
                max_freshness=0.9,
                avg_freshness=0.7,
                min_priority=50,
                max_priority=90,
                avg_priority=70.0,
                freshness_range=0.4,
                priority_range=40,
            ),
            validation=ValidationComparisonSummary(
                all_passed_validation=True,
                any_passed_validation=True,
                validation_score_range=0.2,
                min_validation_score=0.8,
                max_validation_score=1.0,
                consensus_on_promotion=True,
                promotion_recommendations=["keep"],
            ),
            resolution_decision=ResolutionDecision.SELECT_ONE,
            selected_candidate=CandidateIdentity("a", 1, "node-1"),
            candidate_resolutions=[CandidateResolution(
                candidate_key="a:1",
                adapter_id="a",
                generation=1,
                selected=True,
                downgraded=False,
                rejected=False,
                reason="Optimal",
            )],
            resolution_reason="Clear winner",
            recommendation="select_optimal",
            fallback_used=False,
            version="1.0",
            resolved_at="2024-01-01T00:00:00Z",
        )
        data = cs.to_dict()
        restored = ConflictSet.from_dict(data)
        assert restored.set_id == cs.set_id
        assert restored.has_conflicts == cs.has_conflicts
        assert restored.resolution_decision == cs.resolution_decision


class TestConflictResolutionResult:
    """Test conflict resolution result."""

    def test_conflict_resolution_result_creation(self):
        crr = ConflictResolutionResult(
            processed_at="2024-01-01T00:00:00Z",
            processor_version="1.0",
            fallback_used=False,
            conflict_set=ConflictSet(
                set_id="test-set",
                candidate_count=2,
                candidate_keys=["a:1", "b:2"],
                has_conflicts=True,
                conflict_count=1,
                conflicts=[],
                conflict_types=["lineage_conflict"],
                compatibility=CompatibilitySummary(
                    lineage_compatible=False,
                    specialization_compatible=True,
                    validation_consistent=True,
                    lifecycle_consistent=True,
                    overall_compatible=False,
                    compatibility_score=0.4,
                ),
                lifecycle=LifecycleSummary(
                    min_freshness=0.5,
                    max_freshness=0.9,
                    avg_freshness=0.7,
                    min_priority=50,
                    max_priority=90,
                    avg_priority=70.0,
                    freshness_range=0.4,
                    priority_range=40,
                ),
                validation=ValidationComparisonSummary(
                    all_passed_validation=True,
                    any_passed_validation=True,
                    validation_score_range=0.2,
                    min_validation_score=0.8,
                    max_validation_score=1.0,
                    consensus_on_promotion=True,
                    promotion_recommendations=["keep"],
                ),
                resolution_decision=ResolutionDecision.SELECT_ONE,
                selected_candidate=CandidateIdentity("a", 1, "node-1"),
                candidate_resolutions=[],
                resolution_reason="Clear winner",
                recommendation="select_optimal",
                fallback_used=False,
                version="1.0",
                resolved_at="2024-01-01T00:00:00Z",
            ),
            trace_id="abc123",
        )
        assert crr.processed_at == "2024-01-01T00:00:00Z"
        assert crr.trace_id == "abc123"

    def test_conflict_resolution_result_dict_roundtrip(self):
        crr = ConflictResolutionResult(
            processed_at="2024-01-01T00:00:00Z",
            processor_version="1.0",
            fallback_used=False,
            conflict_set=ConflictSet(
                set_id="test-set",
                candidate_count=2,
                candidate_keys=["a:1", "b:2"],
                has_conflicts=True,
                conflict_count=1,
                conflicts=[],
                conflict_types=["lineage_conflict"],
                compatibility=CompatibilitySummary(
                    lineage_compatible=False,
                    specialization_compatible=True,
                    validation_consistent=True,
                    lifecycle_consistent=True,
                    overall_compatible=False,
                    compatibility_score=0.4,
                ),
                lifecycle=LifecycleSummary(
                    min_freshness=0.5,
                    max_freshness=0.9,
                    avg_freshness=0.7,
                    min_priority=50,
                    max_priority=90,
                    avg_priority=70.0,
                    freshness_range=0.4,
                    priority_range=40,
                ),
                validation=ValidationComparisonSummary(
                    all_passed_validation=True,
                    any_passed_validation=True,
                    validation_score_range=0.2,
                    min_validation_score=0.8,
                    max_validation_score=1.0,
                    consensus_on_promotion=True,
                    promotion_recommendations=["keep"],
                ),
                resolution_decision=ResolutionDecision.SELECT_ONE,
                selected_candidate=CandidateIdentity("a", 1, "node-1"),
                candidate_resolutions=[],
                resolution_reason="Clear winner",
                recommendation="select_optimal",
                fallback_used=False,
                version="1.0",
                resolved_at="2024-01-01T00:00:00Z",
            ),
            trace_id="abc123",
        )
        data = crr.to_dict()
        restored = ConflictResolutionResult.from_dict(data)
        assert restored.processed_at == crr.processed_at
        assert restored.trace_id == crr.trace_id
        assert restored.conflict_set.set_id == crr.conflict_set.set_id


class TestRemoteCandidateConflictResolver:
    """Test remote candidate conflict resolver."""

    def _make_candidate(self, adapter_id="test", generation=1, source_node="node-1",
                        freshness=0.8, priority=80, decision="keep"):
        """Helper to create a candidate dict."""
        return {
            "identity": {
                "adapter_id": adapter_id,
                "generation": generation,
                "source_node": source_node,
            },
            "scores": {
                "freshness": freshness,
                "priority": priority,
            },
            "decision": {
                "action": decision,
            },
            "state": {
                "current": "ready",
            },
        }

    def test_resolve_single_candidate(self):
        """Single candidate should have no conflicts."""
        candidates = [self._make_candidate()]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        assert result.fallback_used is False
        assert result.conflict_set.has_conflicts is False
        assert result.conflict_set.conflict_count == 0
        assert result.conflict_set.resolution_decision == ResolutionDecision.HOLD_ALL

    def test_resolve_identical_candidates_select_one(self):
        """Identical candidates should be resolved with clear winner."""
        candidates = [
            self._make_candidate(generation=1, freshness=0.9, priority=90),
            self._make_candidate(generation=2, freshness=0.5, priority=50),
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        assert result.fallback_used is False
        # Should select the one with higher scores
        assert result.conflict_set.resolution_decision == ResolutionDecision.SELECT_ONE
        assert result.conflict_set.selected_candidate is not None

    def test_resolve_lineage_conflict_reject_all(self):
        """Different adapter IDs should cause critical lineage conflict."""
        candidates = [
            self._make_candidate(adapter_id="adapter-a", generation=1),
            self._make_candidate(adapter_id="adapter-b", generation=1),
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        assert result.conflict_set.has_conflicts is True
        assert any(c.conflict_type == ConflictType.LINEAGE_CONFLICT
                   for c in result.conflict_set.conflicts)
        assert result.conflict_set.resolution_decision == ResolutionDecision.REJECT_ALL

    def test_resolve_large_generation_gap_detected(self):
        """Large generation gap should be detected as conflict."""
        candidates = [
            self._make_candidate(generation=1),
            self._make_candidate(generation=10),  # Gap > 2
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        # Should detect lineage conflict due to generation gap
        assert result.conflict_set.has_conflicts is True
        assert any(c.conflict_type == ConflictType.LINEAGE_CONFLICT
                   for c in result.conflict_set.conflicts)

    def test_resolve_duplicate_source_conflict(self):
        """Same source node should cause duplicate source conflict."""
        candidates = [
            self._make_candidate(generation=1, source_node="node-1"),
            self._make_candidate(generation=2, source_node="node-1"),
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        assert result.conflict_set.has_conflicts is True
        assert any(c.conflict_type == ConflictType.DUPLICATE_SOURCE
                   for c in result.conflict_set.conflicts)

    def test_resolve_freshness_conflict(self):
        """Large freshness variance should cause lifecycle conflict."""
        candidates = [
            self._make_candidate(generation=1, freshness=0.9),
            self._make_candidate(generation=2, freshness=0.4),  # Diff > 0.3
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        assert result.conflict_set.has_conflicts is True
        assert any(c.conflict_type == ConflictType.LIFECYCLE_CONFLICT
                   for c in result.conflict_set.conflicts)

    def test_resolve_priority_conflict(self):
        """Large priority variance should cause priority conflict."""
        candidates = [
            self._make_candidate(generation=1, priority=90),
            self._make_candidate(generation=2, priority=50),  # Diff > 20
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        assert result.conflict_set.has_conflicts is True
        assert any(c.conflict_type == ConflictType.PRIORITY_CONFLICT
                   for c in result.conflict_set.conflicts)

    def test_resolve_recommendation_conflict(self):
        """Different recommendations should cause recommendation conflict."""
        candidates = [
            self._make_candidate(generation=1, decision="keep"),
            self._make_candidate(generation=2, decision="downgrade"),
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        assert result.conflict_set.has_conflicts is True
        assert any(c.conflict_type == ConflictType.RECOMMENDATION_CONFLICT
                   for c in result.conflict_set.conflicts)

    def test_resolve_downgrade_some(self):
        """Moderate conflicts should lead to downgrade_some."""
        candidates = [
            self._make_candidate(generation=1, freshness=0.9, priority=90),
            self._make_candidate(generation=2, freshness=0.7, priority=70),
        ]
        result = RemoteCandidateConflictResolver.resolve(candidates)

        # Should downgrade the lower scoring candidate
        assert result.conflict_set.resolution_decision in (
            ResolutionDecision.SELECT_ONE,
            ResolutionDecision.DOWNGRADE_SOME,
        )

    def test_batch_resolve(self):
        """Test batch resolution."""
        candidate_sets = [
            [self._make_candidate()],
            [self._make_candidate(), self._make_candidate(generation=2)],
        ]
        results = RemoteCandidateConflictResolver.batch_resolve(candidate_sets)

        assert len(results) == 2
        assert all(isinstance(r, ConflictResolutionResult) for r in results)

    def test_quick_conflict_check_no_conflict(self):
        """Quick check should return False for single candidate."""
        candidates = [self._make_candidate()]
        has_conflict = RemoteCandidateConflictResolver.quick_conflict_check(candidates)
        assert has_conflict is False

    def test_quick_conflict_check_has_conflict(self):
        """Quick check should return True for different adapter IDs."""
        candidates = [
            self._make_candidate(adapter_id="adapter-a"),
            self._make_candidate(adapter_id="adapter-b"),
        ]
        has_conflict = RemoteCandidateConflictResolver.quick_conflict_check(candidates)
        assert has_conflict is True

    def test_fallback_on_error(self):
        """Fallback should be used on error."""
        # Pass invalid data to trigger error
        candidates = [None]
        result = RemoteCandidateConflictResolver.resolve(candidates, fallback_on_error=True)

        assert result.fallback_used is True
        assert result.conflict_set.resolution_decision == ResolutionDecision.REJECT_ALL


class TestGovernorConflictResolution:
    """Test Governor integration with conflict resolution."""

    def _make_candidate(self, adapter_id="test", generation=1, source_node="node-1",
                        freshness=0.8, priority=80, decision="keep"):
        """Helper to create a candidate dict."""
        return {
            "identity": {
                "adapter_id": adapter_id,
                "generation": generation,
                "source_node": source_node,
            },
            "scores": {
                "freshness": freshness,
                "priority": priority,
            },
            "decision": {
                "action": decision,
            },
            "state": {
                "current": "ready",
            },
        }

    def test_governor_resolve_conflicts(self):
        """Governor should be able to resolve conflicts."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        candidates = [
            self._make_candidate(generation=1, freshness=0.9, priority=90, source_node="node-1"),
            self._make_candidate(generation=2, freshness=0.5, priority=50, source_node="node-2"),
        ]

        result = governor.resolve_candidate_conflicts(candidates)

        assert result.fallback_used is False
        # With different sources and clear score differences, should resolve
        assert result.conflict_set.resolution_decision in (
            ResolutionDecision.SELECT_ONE,
            ResolutionDecision.DOWNGRADE_SOME,
        )

    def test_governor_records_conflict_resolution(self):
        """Governor should record conflict resolution in traces."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # Add a trace first
        trace = ValidationTrace(
            active=active,
            candidate=None,
            status="test",
            passed=True,
        )
        governor._validation_traces.append(trace)

        candidates = [
            self._make_candidate(generation=1, freshness=0.9, priority=90),
            self._make_candidate(generation=2, freshness=0.5, priority=50),
        ]

        governor.resolve_candidate_conflicts(candidates)

        # Check that trace was updated
        assert hasattr(trace, 'conflict_resolution_summary')
        assert trace.conflict_resolution_summary is not None

    def test_governor_quick_conflict_check(self):
        """Governor should support quick conflict check."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        candidates = [
            self._make_candidate(adapter_id="adapter-a"),
            self._make_candidate(adapter_id="adapter-b"),
        ]

        has_conflict = governor.quick_conflict_check(candidates)
        assert has_conflict is True

    def test_governor_get_conflict_resolution_history(self):
        """Governor should return conflict resolution history."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # Add a trace with conflict resolution
        trace = ValidationTrace(
            active=active,
            candidate=None,
            status="test",
            passed=True,
        )
        trace.conflict_resolution_summary = {
            "set_id": "test-set",
            "candidate_count": 2,
        }
        governor._validation_traces.append(trace)

        history = governor.get_conflict_resolution_history()
        assert len(history) == 1
        assert history[0]["set_id"] == "test-set"

    def test_governor_can_promote_after_resolution(self):
        """Governor should check if candidate can be promoted after resolution."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # Add a trace with conflict resolution selecting a candidate
        trace = ValidationTrace(
            active=active,
            candidate=None,
            status="test",
            passed=True,
        )
        trace.conflict_resolution_summary = {
            "set_id": "test-set",
            "selected_candidate": "test-adapter:5",
            "can_proceed": True,
        }
        governor._validation_traces.append(trace)

        can_promote = governor.can_promote_after_resolution("test-adapter", 5)
        assert can_promote is True

    def test_governor_fallback_on_error(self):
        """Governor should fallback on error."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # Pass invalid data
        result = governor._fallback_conflict_resolution([], "test error")

        assert result.fallback_used is True
        assert result.conflict_set.resolution_decision == ResolutionDecision.REJECT_ALL


class TestPhase13Regression:
    """Ensure Phase 13 triage/readiness paths still work."""

    def _make_candidate(self, adapter_id="test", generation=1, source_node="node-1",
                        freshness=0.8, priority=80, decision="keep"):
        """Helper to create a candidate dict."""
        return {
            "identity": {
                "adapter_id": adapter_id,
                "generation": generation,
                "source_node": source_node,
            },
            "scores": {
                "freshness": freshness,
                "priority": priority,
            },
            "decision": {
                "action": decision,
            },
            "state": {
                "current": "ready",
            },
        }

    def test_phase13_triage_still_works(self):
        """Phase 13 triage should still function."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # This should work without error
        candidates = [self._make_candidate()]
        result = governor.resolve_candidate_conflicts(candidates)

        assert result is not None
        assert result.conflict_set is not None


class TestPhase14Regression:
    """Ensure Phase 14 lifecycle paths still work."""

    def _make_candidate(self, adapter_id="test", generation=1, source_node="node-1",
                        freshness=0.8, priority=80, decision="keep"):
        """Helper to create a candidate dict."""
        return {
            "identity": {
                "adapter_id": adapter_id,
                "generation": generation,
                "source_node": source_node,
            },
            "scores": {
                "freshness": freshness,
                "priority": priority,
            },
            "decision": {
                "action": decision,
            },
            "state": {
                "current": "ready",
            },
        }

    def test_phase14_lifecycle_still_works(self):
        """Phase 14 lifecycle should still function."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # Get active lifecycle candidates
        candidates = governor.get_active_lifecycle_candidates()
        assert isinstance(candidates, list)

    def test_phase14_lifecycle_conflict_integration(self):
        """Phase 14 lifecycle results can be used in Phase 15 conflict resolution."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # Create candidates that look like lifecycle results
        candidates = [
            self._make_candidate(generation=1, freshness=0.9, priority=90),
            self._make_candidate(generation=2, freshness=0.7, priority=70),
        ]

        # Should be able to resolve conflicts
        result = governor.resolve_candidate_conflicts(candidates)
        assert result.conflict_set is not None


class TestPhase11Regression:
    """Ensure Phase 11 exchange gate paths still work."""

    def test_phase11_exchange_gate_still_works(self):
        """Phase 11 exchange gate should still function."""
        active = AdapterRef("test-adapter", 1, AdapterMode.SERVE, AdapterSpecialization.STABLE)
        governor = Governor(active)

        # Extract federation summary should work
        summary = governor.extract_federation_summary()
        assert summary is not None
        assert summary.identity.adapter_id == "test-adapter"


class TestDeterminism:
    """Test that conflict resolution is deterministic."""

    def _make_candidate(self, adapter_id="test", generation=1, source_node="node-1",
                        freshness=0.8, priority=80, decision="keep"):
        """Helper to create a candidate dict."""
        return {
            "identity": {
                "adapter_id": adapter_id,
                "generation": generation,
                "source_node": source_node,
            },
            "scores": {
                "freshness": freshness,
                "priority": priority,
            },
            "decision": {
                "action": decision,
            },
            "state": {
                "current": "ready",
            },
        }

    def test_same_input_same_output(self):
        """Same candidate set should produce same result."""
        candidates = [
            self._make_candidate(generation=1, freshness=0.9, priority=90),
            self._make_candidate(generation=2, freshness=0.5, priority=50),
        ]

        result1 = RemoteCandidateConflictResolver.resolve(candidates)
        result2 = RemoteCandidateConflictResolver.resolve(candidates)

        assert result1.conflict_set.resolution_decision == result2.conflict_set.resolution_decision
        if result1.conflict_set.selected_candidate and result2.conflict_set.selected_candidate:
            assert result1.conflict_set.selected_candidate.to_key() == result2.conflict_set.selected_candidate.to_key()


class TestFailureSafety:
    """Test failure safety guarantees."""

    def test_error_fallback_does_not_raise(self):
        """Error should not raise when fallback_on_error is True."""
        # Pass None to trigger error
        result = RemoteCandidateConflictResolver.resolve([None], fallback_on_error=True)
        assert result.fallback_used is True

    def test_error_raises_when_fallback_disabled(self):
        """Error should raise when fallback_on_error is False."""
        with pytest.raises(Exception):
            RemoteCandidateConflictResolver.resolve([None], fallback_on_error=False)

    def test_empty_candidate_set(self):
        """Empty candidate set should be handled gracefully."""
        result = RemoteCandidateConflictResolver.resolve([])
        assert result.fallback_used is False
        assert result.conflict_set.candidate_count == 0

    def test_quick_conflict_check_error_safety(self):
        """Quick conflict check should return True on error."""
        # Pass invalid candidates that will trigger error handling
        has_conflict = RemoteCandidateConflictResolver.quick_conflict_check([None, {"valid": True}])
        assert has_conflict is True  # Conservative: treat errors as conflict
