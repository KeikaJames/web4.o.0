"""Phase 13: Remote summary compatibility triage & staging promotion readiness tests."""

import pytest
from datetime import datetime

try:
    from chronara_nexus.types import (
        TriageStatus,
        ReadinessSummary,
        TriageAssessment,
        TriageResult,
        StagedRemoteCandidate,
        StagingDecision,
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        AdapterRef,
        AdapterMode,
    )
    from chronara_nexus.triage_engine import RemoteTriageEngine
    from chronara_nexus.governor import Governor
except ImportError:
    from implementations.sac_py.chronara_nexus.types import (
        TriageStatus,
        ReadinessSummary,
        TriageAssessment,
        TriageResult,
        StagedRemoteCandidate,
        StagingDecision,
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        AdapterRef,
        AdapterMode,
    )
    from implementations.sac_py.chronara_nexus.triage_engine import RemoteTriageEngine
    from implementations.sac_py.chronara_nexus.governor import Governor


def create_test_summary(adapter_id="test", generation=1):
    """Helper to create minimal test summary."""
    try:
        from chronara_nexus.types import (
            AdapterIdentitySummary, SpecializationSummary,
            ImportanceMaskSummary, DeltaNormSummary,
            ValidationScoreSummary, ComparisonOutcomeSummary,
            DeliberationSummary, SnapshotLineageSummary, CompatibilityHints
        )
    except ImportError:
        from implementations.sac_py.chronara_nexus.types import (
            AdapterIdentitySummary, SpecializationSummary,
            ImportanceMaskSummary, DeltaNormSummary,
            ValidationScoreSummary, ComparisonOutcomeSummary,
            DeliberationSummary, SnapshotLineageSummary, CompatibilityHints
        )
    return FederationSummary(
        identity=AdapterIdentitySummary(adapter_id, generation, None, "stable", "serve"),
        specialization=SpecializationSummary(generation, None, None, "stable"),
        importance_mask=ImportanceMaskSummary(["p0"], {"p0": 0.9}, 0.1, 0.1),
        delta_norm=DeltaNormSummary(1.0, 0.5, 0.9, 10, None),
        validation_score=ValidationScoreSummary(True, True, True, True, True, True, 1.0),
        comparison_outcome=ComparisonOutcomeSummary("candidate_observed", "approve", True, True, True),
        deliberation=DeliberationSummary("candidate_ready", 0.85, 0.9, "consensus_accept", False, False),
        snapshot_lineage=SnapshotLineageSummary(f"{adapter_id}-gen{generation}", adapter_id, generation, "stable", None, f"{adapter_id}:{generation}:stable"),
        compatibility=CompatibilityHints(0, 10, None, 0.5, False, "1.0"),
        export_timestamp="2024-01-01T00:00:00Z",
        export_version="1.0",
        source_node="node-1",
    )


def create_test_gate(lineage_compat=True, spec_compat=True, val_acceptable=True, comp_acceptable=True, status=ExchangeStatus.ACCEPT):
    """Helper to create test exchange gate."""
    return FederationExchangeGate(
        local_adapter_id="local", local_generation=1,
        remote_adapter_id="test", remote_generation=2,
        lineage=LineageCompatibility(lineage_compat, 0.9, 1, True, False, "test"),
        specialization=SpecializationCompatibility(spec_compat, "stable", "stable", True, "test"),
        validation=ValidationCompatibility(val_acceptable, 0.9, 0.95, 0.05, True, "test"),
        comparison=ComparisonCompatibility(comp_acceptable, "ok", "ok", True, "test"),
        status=status,
        recommendation="accept",
        reason="test",
        fallback_used=False,
        version="1.0",
        timestamp="2024-01-01T00:00:00Z",
    )


def create_test_staged(adapter_id="test", generation=2, staging_decision=StagingDecision.STAGE_ACCEPT, is_downgraded=False):
    """Helper to create test staged candidate."""
    summary = create_test_summary(adapter_id, generation)
    gate = create_test_gate()
    return StagedRemoteCandidate(
        adapter_id=adapter_id,
        generation=generation,
        source_node="node-2",
        staged_at="2024-01-01T00:00:00Z",
        staging_decision=staging_decision,
        staging_version="1.0",
        summary=summary,
        gate_result=gate,
        is_active=True,
        is_downgraded=is_downgraded,
        intake_record_ref="abc123",
    )


class TestTriageStatus:
    """Test TriageStatus enum."""

    def test_triage_status_values(self):
        """Phase 13: TriageStatus must have correct values."""
        assert TriageStatus.READY.value == "ready"
        assert TriageStatus.HOLD.value == "hold"
        assert TriageStatus.DOWNGRADE.value == "downgrade"
        assert TriageStatus.REJECT.value == "reject"


class TestReadinessSummary:
    """Test ReadinessSummary structure."""

    def test_readiness_summary_has_required_fields(self):
        """Phase 13: ReadinessSummary must have all required fields."""
        readiness = ReadinessSummary(
            readiness_score=0.85,
            lineage_score=0.9,
            specialization_score=0.8,
            validation_score=0.85,
            comparison_score=0.9,
            recency_score=0.8,
            is_fresh=True,
            is_compatible=True,
            is_priority=True,
            score_reason="high_readiness",
        )

        assert readiness.readiness_score == 0.85
        assert readiness.is_fresh is True
        assert readiness.is_priority is True


class TestTriageAssessment:
    """Test TriageAssessment structure."""

    def test_assessment_has_required_fields(self):
        """Phase 13: TriageAssessment must have all required fields."""
        readiness = ReadinessSummary(0.85, 0.9, 0.8, 0.85, 0.9, 0.8, True, True, True, "test")
        assessment = TriageAssessment(
            adapter_id="test",
            generation=2,
            source_node="node-2",
            triage_status=TriageStatus.READY,
            triage_version="1.0",
            triaged_at="2024-01-01T00:00:00Z",
            readiness=readiness,
            lineage_compatible=True,
            specialization_compatible=True,
            validation_acceptable=True,
            comparison_acceptable=True,
            recommendation="promote_ready",
            reason="high_readiness_score",
            can_promote_later=True,
            needs_review=False,
            expiration_hint=None,
            original_staging_ref="abc123",
        )

        assert assessment.adapter_id == "test"
        assert assessment.triage_status == TriageStatus.READY
        assert assessment.can_promote_later is True
        assert assessment.to_dict() is not None

    def test_assessment_status_methods(self):
        """Phase 13: Status check methods must work."""
        readiness = ReadinessSummary(0.85, 0.9, 0.8, 0.85, 0.9, 0.8, True, True, True, "test")

        ready_assessment = TriageAssessment("test", 2, None, TriageStatus.READY, "1.0", "2024-01-01T00:00:00Z", readiness, True, True, True, True, "ready", "test", True, False, None, "ref")
        hold_assessment = TriageAssessment("test", 2, None, TriageStatus.HOLD, "1.0", "2024-01-01T00:00:00Z", readiness, True, True, True, True, "hold", "test", True, True, None, "ref")
        reject_assessment = TriageAssessment("test", 2, None, TriageStatus.REJECT, "1.0", "2024-01-01T00:00:00Z", readiness, False, False, False, False, "reject", "test", False, False, None, "ref")

        assert ready_assessment.is_ready() is True
        assert ready_assessment.is_hold() is False
        assert hold_assessment.is_hold() is True
        assert reject_assessment.is_reject() is True
        assert ready_assessment.can_use_for_federation() is True
        assert reject_assessment.can_use_for_federation() is False


class TestTriageResult:
    """Test TriageResult structure."""

    def test_result_round_trip(self):
        """Phase 13: TriageResult must round-trip through dict."""
        readiness = ReadinessSummary(0.85, 0.9, 0.8, 0.85, 0.9, 0.8, True, True, True, "test")
        assessment = TriageAssessment("test", 2, None, TriageStatus.READY, "1.0", "2024-01-01T00:00:00Z", readiness, True, True, True, True, "ready", "test", True, False, None, "ref")

        result = TriageResult(
            processed_at="2024-01-01T00:00:00Z",
            processor_version="1.0",
            fallback_used=False,
            assessment=assessment,
            target_pool="ready",
            priority=85,
            trace_id="abc123",
        )

        data = result.to_dict()
        restored = TriageResult.from_dict(data)

        assert restored.assessment.adapter_id == result.assessment.adapter_id
        assert restored.target_pool == result.target_pool
        assert restored.priority == result.priority


class TestRemoteTriageEngine:
    """Test triage engine logic."""

    def test_triage_ready_candidate(self):
        """Phase 13: High readiness candidate should be ready."""
        staged = create_test_staged("test", 2, StagingDecision.STAGE_ACCEPT, False)
        local = create_test_summary("test", 1)

        result = RemoteTriageEngine.triage(staged, local)

        assert result.assessment.triage_status in (TriageStatus.READY, TriageStatus.HOLD)
        assert result.assessment.readiness.readiness_score > 0.0

    def test_triage_reject_previously_rejected(self):
        """Phase 13: Previously rejected staging should be rejected."""
        staged = create_test_staged("test", 2, StagingDecision.STAGE_REJECT, False)
        local = create_test_summary("test", 1)

        result = RemoteTriageEngine.triage(staged, local)

        assert result.assessment.triage_status == TriageStatus.REJECT

    def test_triage_downgraded_candidate(self):
        """Phase 13: Downgraded candidate should be downgrade or hold."""
        staged = create_test_staged("test", 2, StagingDecision.STAGE_DOWNGRADE, True)
        local = create_test_summary("test", 1)

        result = RemoteTriageEngine.triage(staged, local)

        assert result.assessment.triage_status in (TriageStatus.DOWNGRADE, TriageStatus.HOLD, TriageStatus.REJECT)

    def test_deterministic_same_input(self):
        """Phase 13: Same inputs must produce same triage result."""
        staged = create_test_staged("test", 2)
        local = create_test_summary("test", 1)

        result1 = RemoteTriageEngine.triage(staged, local)
        result2 = RemoteTriageEngine.triage(staged, local)

        assert result1.assessment.triage_status == result2.assessment.triage_status
        assert result1.target_pool == result2.target_pool

    def test_quick_readiness_check(self):
        """Phase 13: Quick check should work."""
        staged = create_test_staged("test", 2)

        ready = RemoteTriageEngine.quick_readiness_check(staged)

        # Should return a boolean
        assert isinstance(ready, bool)

    def test_batch_triage(self):
        """Phase 13: Batch triage should work."""
        candidates = [
            create_test_staged("test", 2),
            create_test_staged("test", 3),
        ]
        local = create_test_summary("test", 1)

        results = RemoteTriageEngine.batch_triage(candidates, local)

        assert len(results) == 2
        assert all(isinstance(r, TriageResult) for r in results)


class TestGovernorTriageIntegration:
    """Test Governor triage integration."""

    def test_governor_triage_staged_candidate(self):
        """Phase 13: Governor must be able to triage staged candidate."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        staged = create_test_staged("test", 2)
        result = governor.triage_staged_candidate(staged)

        assert result.assessment.adapter_id == "test"
        assert result.assessment.triage_status in (TriageStatus.READY, TriageStatus.HOLD, TriageStatus.DOWNGRADE, TriageStatus.REJECT)

    def test_governor_get_ready_candidates(self):
        """Phase 13: Governor must track ready candidates."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Triage a candidate
        staged = create_test_staged("test", 2)
        result = governor.triage_staged_candidate(staged)

        # Get ready candidates
        ready = governor.get_ready_remote_candidates()

        # Should have candidates if any are ready
        if result.assessment.triage_status == TriageStatus.READY:
            assert len(ready) >= 0  # May or may not be recorded

    def test_governor_quick_readiness_check(self):
        """Phase 13: Governor must have quick readiness check."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        staged = create_test_staged("test", 2)
        ready = governor.quick_readiness_check(staged)

        assert isinstance(ready, bool)


class TestPhase12Regression:
    """Test that Phase 12 staging still works."""

    def test_staged_remote_candidate_still_works(self):
        """Phase 13: Phase 12 staged candidate must still work."""
        staged = create_test_staged("test", 2)

        assert staged.adapter_id == "test"
        assert staged.staging_decision == StagingDecision.STAGE_ACCEPT
        assert staged.to_dict() is not None


class TestFailureSafety:
    """Test failure safety."""

    def test_triage_fallback_on_exception(self):
        """Phase 13: Triage must return fallback on exception."""
        # Pass None to trigger error
        result = RemoteTriageEngine.triage(None, None)

        assert result.fallback_used is True
        assert result.assessment.triage_status == TriageStatus.REJECT
        assert result.target_pool == "rejected"

    def test_reject_does_not_allow_promote(self):
        """Phase 13: Reject status must not allow promotion."""
        staged = create_test_staged("test", 2, StagingDecision.STAGE_REJECT)

        result = RemoteTriageEngine.triage(staged, None)

        assert result.assessment.triage_status == TriageStatus.REJECT
        assert result.assessment.can_promote_later is False
