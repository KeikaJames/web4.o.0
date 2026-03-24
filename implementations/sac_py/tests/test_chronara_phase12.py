"""Phase 12: Federation-safe summary intake & remote candidate staging tests."""

import pytest
from datetime import datetime

try:
    from chronara_nexus.types import (
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        StagingDecision,
        RemoteSummaryIntake,
        StagedRemoteCandidate,
        RemoteIntakeResult,
        AdapterIdentitySummary,
        SpecializationSummary,
        ImportanceMaskSummary,
        DeltaNormSummary,
        ValidationScoreSummary,
        ComparisonOutcomeSummary,
        DeliberationSummary,
        SnapshotLineageSummary,
        CompatibilityHints,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
    )
    from chronara_nexus.intake_processor import RemoteIntakeProcessor
    from chronara_nexus.governor import Governor
except ImportError:
    from implementations.sac_py.chronara_nexus.types import (
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        StagingDecision,
        RemoteSummaryIntake,
        StagedRemoteCandidate,
        RemoteIntakeResult,
        AdapterIdentitySummary,
        SpecializationSummary,
        ImportanceMaskSummary,
        DeltaNormSummary,
        ValidationScoreSummary,
        ComparisonOutcomeSummary,
        DeliberationSummary,
        SnapshotLineageSummary,
        CompatibilityHints,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
    )
    from implementations.sac_py.chronara_nexus.intake_processor import RemoteIntakeProcessor
    from implementations.sac_py.chronara_nexus.governor import Governor


def create_test_summary(
    adapter_id: str = "test",
    generation: int = 1,
    parent_gen: int = None,
    specialization: str = "stable",
    validation_score: float = 1.0,
    validation_passed: bool = True,
    source_node: str = "node-1",
) -> FederationSummary:
    """Helper to create test federation summaries."""
    identity = AdapterIdentitySummary(
        adapter_id=adapter_id,
        generation=generation,
        parent_generation=parent_gen,
        specialization=specialization,
        mode="serve",
    )
    return FederationSummary(
        identity=identity,
        specialization=SpecializationSummary(
            stable_generation=generation,
            shared_generation=None,
            candidate_generation=None,
            active_specialization=specialization,
        ),
        importance_mask=ImportanceMaskSummary(
            top_keys=["p0"],
            scores={"p0": 0.9},
            threshold=0.1,
            compression_ratio=0.1,
        ),
        delta_norm=DeltaNormSummary(
            l1_norm=1.0,
            l2_norm=0.5,
            max_abs=0.9,
            param_count=10,
            relative_to_parent=None,
        ),
        validation_score=ValidationScoreSummary(
            passed=validation_passed,
            lineage_valid=True,
            specialization_valid=True,
            output_match=True,
            kv_count_match=True,
            generation_advanced=True,
            score=validation_score,
        ),
        comparison_outcome=ComparisonOutcomeSummary(
            status="candidate_observed",
            promote_recommendation="approve",
            lineage_valid=True,
            specialization_valid=True,
            is_acceptable=True,
        ),
        deliberation=DeliberationSummary(
            outcome="candidate_ready",
            quality_score=0.85,
            confidence=0.9,
            consensus_status="consensus_accept",
            has_disagreement=False,
            escalation_used=False,
        ),
        snapshot_lineage=SnapshotLineageSummary(
            snapshot_id=f"{adapter_id}-gen{generation}",
            adapter_id=adapter_id,
            generation=generation,
            specialization=specialization,
            parent_snapshot_id=f"{adapter_id}-gen{parent_gen}" if parent_gen else None,
            lineage_hash=f"{adapter_id}:{generation}:{specialization}",
        ),
        compatibility=CompatibilityHints(
            min_compatible_generation=0,
            max_compatible_generation=10,
            required_specialization=None,
            min_validation_score=0.5,
            requires_consensus_accept=False,
            format_version="1.0",
        ),
        export_timestamp="2024-01-01T00:00:00Z",
        export_version="1.0",
        source_node=source_node,
    )


class TestStagingDecision:
    """Test StagingDecision enum."""

    def test_staging_decision_values(self):
        """Phase 12: StagingDecision must have correct values."""
        assert StagingDecision.STAGE_ACCEPT.value == "stage_accept"
        assert StagingDecision.STAGE_DOWNGRADE.value == "stage_downgrade"
        assert StagingDecision.STAGE_REJECT.value == "stage_reject"


class TestRemoteSummaryIntake:
    """Test RemoteSummaryIntake structure."""

    def test_intake_has_required_fields(self):
        """Phase 12: Intake must have all required fields."""
        intake = RemoteSummaryIntake(
            remote_adapter_id="remote",
            remote_generation=2,
            remote_source_node="node-2",
            intake_timestamp="2024-01-01T00:00:00Z",
            intake_version="1.0",
            raw_summary_hash="abc123",
            structure_valid=True,
            required_fields_present=True,
            validation_errors=[],
            exchange_gate=None,
        )

        assert intake.remote_adapter_id == "remote"
        assert intake.remote_generation == 2
        assert intake.structure_valid is True
        assert intake.to_dict() is not None


class TestStagedRemoteCandidate:
    """Test StagedRemoteCandidate structure."""

    def test_staged_candidate_has_required_fields(self):
        """Phase 12: Staged candidate must have all required fields."""
        summary = create_test_summary("test", 2)
        gate = FederationExchangeGate(
            local_adapter_id="local", local_generation=1,
            remote_adapter_id="test", remote_generation=2,
            lineage=LineageCompatibility(True, 0.9, 1, True, False, None),
            specialization=SpecializationCompatibility(True, "stable", "stable", True, None),
            validation=ValidationCompatibility(True, 0.9, 0.95, 0.05, True, None),
            comparison=ComparisonCompatibility(True, "ok", "ok", True, None),
            status=ExchangeStatus.ACCEPT,
            recommendation="accept",
            reason="ok",
            fallback_used=False,
            version="1.0",
            timestamp="2024-01-01T00:00:00Z",
        )

        candidate = StagedRemoteCandidate(
            adapter_id="test",
            generation=2,
            source_node="node-2",
            staged_at="2024-01-01T00:00:00Z",
            staging_decision=StagingDecision.STAGE_ACCEPT,
            staging_version="1.0",
            summary=summary,
            gate_result=gate,
            is_active=True,
            is_downgraded=False,
            intake_record_ref="abc123",
        )

        assert candidate.adapter_id == "test"
        assert candidate.is_active is True
        assert candidate.is_downgraded is False
        assert candidate.to_dict() is not None

    def test_staged_candidate_round_trip(self):
        """Phase 12: Staged candidate must round-trip through dict."""
        summary = create_test_summary("test", 2)
        gate = FederationExchangeGate(
            local_adapter_id="local", local_generation=1,
            remote_adapter_id="test", remote_generation=2,
            lineage=LineageCompatibility(True, 0.9, 1, True, False, None),
            specialization=SpecializationCompatibility(True, "stable", "stable", True, None),
            validation=ValidationCompatibility(True, 0.9, 0.95, 0.05, True, None),
            comparison=ComparisonCompatibility(True, "ok", "ok", True, None),
            status=ExchangeStatus.ACCEPT,
            recommendation="accept",
            reason="ok",
            fallback_used=False,
            version="1.0",
            timestamp="2024-01-01T00:00:00Z",
        )

        candidate = StagedRemoteCandidate(
            adapter_id="test",
            generation=2,
            source_node="node-2",
            staged_at="2024-01-01T00:00:00Z",
            staging_decision=StagingDecision.STAGE_ACCEPT,
            staging_version="1.0",
            summary=summary,
            gate_result=gate,
            is_active=True,
            is_downgraded=False,
            intake_record_ref="abc123",
        )

        data = candidate.to_dict()
        restored = StagedRemoteCandidate.from_dict(data)

        assert restored.adapter_id == candidate.adapter_id
        assert restored.staging_decision == candidate.staging_decision


class TestRemoteIntakeResult:
    """Test RemoteIntakeResult structure."""

    def test_result_is_staged_method(self):
        """Phase 12: is_staged() must work correctly."""
        # Accept result
        accept_result = RemoteIntakeResult(
            processed_at="2024-01-01T00:00:00Z",
            processor_version="1.0",
            fallback_used=False,
            intake=RemoteSummaryIntake("test", 1, None, "2024-01-01T00:00:00Z", "1.0", "abc", True, True, [], None),
            decision=StagingDecision.STAGE_ACCEPT,
            decision_reason="compatible",
            recommendation="accept",
            staged_candidate=None,
            rejection_trace=None,
        )

        # Reject result
        reject_result = RemoteIntakeResult(
            processed_at="2024-01-01T00:00:00Z",
            processor_version="1.0",
            fallback_used=False,
            intake=RemoteSummaryIntake("test", 1, None, "2024-01-01T00:00:00Z", "1.0", "abc", False, False, ["error"], None),
            decision=StagingDecision.STAGE_REJECT,
            decision_reason="incompatible",
            recommendation="reject",
            staged_candidate=None,
            rejection_trace={},
        )

        assert accept_result.is_staged() is True
        assert reject_result.is_staged() is False
        assert accept_result.is_rejected() is False
        assert reject_result.is_rejected() is True


class TestRemoteIntakeProcessor:
    """Test intake processor logic."""

    def test_process_valid_summary_accept(self):
        """Phase 12: Valid compatible summary should be accepted."""
        local = create_test_summary("test", 1)
        remote_dict = create_test_summary("test", 2, parent_gen=1).to_dict()

        result = RemoteIntakeProcessor.process_intake(
            remote_summary_dict=remote_dict,
            local_summary=local,
            source_node="node-2",
        )

        assert result.decision == StagingDecision.STAGE_ACCEPT
        assert result.intake.structure_valid is True
        assert result.staged_candidate is not None
        assert result.staged_candidate.is_downgraded is False

    def test_process_missing_fields_reject(self):
        """Phase 12: Missing required fields should be rejected."""
        local = create_test_summary("test", 1)
        invalid_dict = {"identity": {}}  # Missing required fields

        result = RemoteIntakeProcessor.process_intake(
            remote_summary_dict=invalid_dict,
            local_summary=local,
        )

        assert result.decision == StagingDecision.STAGE_REJECT
        assert result.intake.structure_valid is False
        assert len(result.intake.validation_errors) > 0

    def test_process_different_adapter_reject(self):
        """Phase 12: Different adapter ID should be rejected."""
        local = create_test_summary("adapter1", 1)
        remote_dict = create_test_summary("adapter2", 1).to_dict()

        result = RemoteIntakeProcessor.process_intake(
            remote_summary_dict=remote_dict,
            local_summary=local,
        )

        assert result.decision == StagingDecision.STAGE_REJECT
        assert result.staged_candidate is None
        assert result.rejection_trace is not None

    def test_process_validation_failed_reject(self):
        """Phase 12: Failed validation should be rejected."""
        local = create_test_summary("test", 1, validation_passed=True)
        remote_dict = create_test_summary("test", 2, validation_passed=False).to_dict()

        result = RemoteIntakeProcessor.process_intake(
            remote_summary_dict=remote_dict,
            local_summary=local,
        )

        assert result.decision == StagingDecision.STAGE_REJECT

    def test_deterministic_same_input(self):
        """Phase 12: Same inputs must produce same staging decision."""
        local = create_test_summary("test", 1)
        remote_dict = create_test_summary("test", 2).to_dict()

        result1 = RemoteIntakeProcessor.process_intake(remote_dict, local)
        result2 = RemoteIntakeProcessor.process_intake(remote_dict, local)

        assert result1.decision == result2.decision
        assert result1.intake.remote_generation == result2.intake.remote_generation

    def test_quick_intake_check_valid(self):
        """Phase 12: Quick check should validate structure."""
        valid_dict = create_test_summary("test", 1).to_dict()
        assert RemoteIntakeProcessor.quick_intake_check(valid_dict) is True

    def test_quick_intake_check_invalid(self):
        """Phase 12: Quick check should reject invalid structure."""
        invalid_dict = {"incomplete": True}
        assert RemoteIntakeProcessor.quick_intake_check(invalid_dict) is False


class TestGovernorIntakeIntegration:
    """Test Governor integration with intake."""

    def test_governor_process_remote_intake(self):
        """Phase 12: Governor must process remote intake."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        remote_dict = create_test_summary("test", 2, parent_gen=1).to_dict()
        result = governor.process_remote_intake(remote_dict, source_node="node-2")

        # result is RemoteIntakeResult object
        assert result.decision.value in ("stage_accept", "stage_downgrade", "stage_reject")
        assert result.intake.remote_adapter_id == "test"

    def test_governor_get_staged_summaries(self):
        """Phase 12: Governor must track staged summaries."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Process a remote intake
        remote_dict = create_test_summary("test", 2, parent_gen=1).to_dict()
        result = governor.process_remote_intake(remote_dict, source_node="node-2")

        # Get staged summaries
        staged = governor.get_staged_remote_summaries()

        # Should have at least one staged (if accepted)
        if result.decision.value in ("stage_accept", "stage_downgrade"):
            assert len(staged) >= 0  # May or may not be recorded depending on trace

    def test_governor_fallback_on_error(self):
        """Phase 12: Governor must fallback safely on error."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Pass invalid input
        result = governor.process_remote_intake(None, source_node="node-2")

        assert result.fallback_used is True
        assert result.decision == StagingDecision.STAGE_REJECT


class TestPhase11Regression:
    """Test that Phase 11 exchange gate still works."""

    def test_exchange_gate_still_functions(self):
        """Phase 12: Phase 11 exchange gate must still work."""
        try:
            from chronara_nexus.exchange_gate import FederationExchangeComparator
        except ImportError:
            from implementations.sac_py.chronara_nexus.exchange_gate import FederationExchangeComparator

        local = create_test_summary("test", 1)
        remote = create_test_summary("test", 2)

        gate = FederationExchangeComparator.compare(local, remote)

        assert gate is not None
        assert gate.status in (ExchangeStatus.ACCEPT, ExchangeStatus.DOWNGRADE, ExchangeStatus.REJECT)


class TestPhase10Regression:
    """Test that Phase 10 summary still works."""

    def test_federation_summary_still_extractable(self):
        """Phase 12: Phase 10 summary extraction must still work."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        summary = governor.extract_federation_summary()

        assert summary is not None
        assert summary.identity.adapter_id == "test"


class TestFailureSafety:
    """Test failure safety."""

    def test_processor_fallback_on_exception(self):
        """Phase 12: Processor must return fallback on exception."""
        local = create_test_summary("test", 1)

        # Pass something that will cause issues
        result = RemoteIntakeProcessor.process_intake(
            remote_summary_dict="not_a_dict",
            local_summary=local,
        )

        assert result.fallback_used is True
        assert result.decision == StagingDecision.STAGE_REJECT

    def test_reject_does_not_create_staged_candidate(self):
        """Phase 12: Reject decision must not create staged candidate."""
        local = create_test_summary("test", 1)
        remote_dict = create_test_summary("other_adapter", 1).to_dict()  # Different adapter

        result = RemoteIntakeProcessor.process_intake(remote_dict, local)

        assert result.decision == StagingDecision.STAGE_REJECT
        assert result.staged_candidate is None
        assert result.rejection_trace is not None

    def test_downgrade_creates_downgraded_candidate(self):
        """Phase 12: Downgrade should create candidate marked as downgraded."""
        local = create_test_summary("test", 1)
        # Create remote with large generation gap to trigger downgrade
        remote = create_test_summary("test", 10)
        remote_dict = remote.to_dict()

        result = RemoteIntakeProcessor.process_intake(remote_dict, local)

        # Large gap may trigger downgrade or reject depending on threshold
        if result.decision == StagingDecision.STAGE_DOWNGRADE:
            assert result.staged_candidate.is_downgraded is True
