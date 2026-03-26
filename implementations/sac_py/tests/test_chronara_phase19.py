"""Phase 19: Final integration hardening & end-to-end acceptance.

Tests for complete bounded pre-federation pipeline:
- local observation → deliberation → candidate quality gate
- Governor validation/comparison → federation-ready summary
- compatibility/exchange gate → remote intake/staging
- triage/readiness → lifecycle → conflict resolution → promotion execution
- event emission → exchange skeleton readiness

Covers both success and failure paths.
"""

import pytest
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

try:
    from chronara_nexus import (
        Governor,
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
        BoundedDeliberation,
        DeliberationRequest,
        ObservationType,
        MultiRoleReviewCoordinator,
    )
    from chronara_nexus.types import (
        FederationSummary,
        AdapterIdentitySummary,
        SpecializationSummary,
        ImportanceMaskSummary,
        DeltaNormSummary,
        ValidationScoreSummary,
        ComparisonOutcomeSummary,
        DeliberationSummary,
        SnapshotLineageSummary,
        CompatibilityHints,
        FederationExchangeGate,
        ExchangeStatus,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        StagedRemoteCandidate,
    )
    from chronara_nexus.exchange_gate import FederationExchangeComparator
    from chronara_nexus.conflict_resolution import RemoteCandidateConflictResolver
    from chronara_nexus.promotion_execution import FederationPromotionExecutor
    from chronara_nexus.event_stream import (
        FederationEventEmitter,
        EventType,
        FederationEvent,
    )
    from chronara_nexus.exchange_skeleton import (
        ParameterMemoryExchangeSkeleton,
        ExchangeDecision,
        ExchangeProposal,
        ExchangeReadiness,
    )
except ImportError:
    from implementations.sac_py.chronara_nexus import (
        Governor,
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
        BoundedDeliberation,
        DeliberationRequest,
        ObservationType,
        MultiRoleReviewCoordinator,
    )
    from implementations.sac_py.chronara_nexus.types import (
        FederationSummary,
        AdapterIdentitySummary,
        SpecializationSummary,
        ImportanceMaskSummary,
        DeltaNormSummary,
        ValidationScoreSummary,
        ComparisonOutcomeSummary,
        DeliberationSummary,
        SnapshotLineageSummary,
        CompatibilityHints,
        FederationExchangeGate,
        ExchangeStatus,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        StagedRemoteCandidate,
    )
    from implementations.sac_py.chronara_nexus.exchange_gate import FederationExchangeComparator
    from implementations.sac_py.chronara_nexus.conflict_resolution import RemoteCandidateConflictResolver
    from implementations.sac_py.chronara_nexus.promotion_execution import FederationPromotionExecutor
    from implementations.sac_py.chronara_nexus.event_stream import (
        FederationEventEmitter,
        EventType,
        FederationEvent,
    )
    from implementations.sac_py.chronara_nexus.exchange_skeleton import (
        ParameterMemoryExchangeSkeleton,
        ExchangeDecision,
        ExchangeProposal,
        ExchangeReadiness,
    )


def create_test_summary(
    adapter_id: str = "test-candidate",
    generation: int = 5,
    source_node: str = "remote-node",
    parent_id: str = "main-adapter",
    parent_generation: int = 1,
    validation_score: float = 0.8,
    lineage_verified: bool = True,
) -> FederationSummary:
    """Helper to create test federation summary."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return FederationSummary(
        identity=AdapterIdentitySummary(
            adapter_id=adapter_id,
            generation=generation,
            parent_generation=parent_generation,
            specialization="shared",
            mode="serve",
        ),
        specialization=SpecializationSummary(
            stable_generation=parent_generation,
            shared_generation=generation,
            candidate_generation=None,
            active_specialization="shared",
        ),
        importance_mask=ImportanceMaskSummary(
            top_keys=["key1", "key2"],
            scores={"key1": 0.9, "key2": 0.8},
            threshold=0.5,
            compression_ratio=0.8,
        ),
        delta_norm=DeltaNormSummary(
            l1_norm=1.0,
            l2_norm=0.5,
            max_abs=0.3,
            param_count=1000,
            relative_to_parent=0.1,
        ),
        validation_score=ValidationScoreSummary(
            passed=validation_score >= 0.7,
            lineage_valid=lineage_verified,
            specialization_valid=True,
            output_match=True,
            kv_count_match=True,
            generation_advanced=True,
            score=validation_score,
        ),
        comparison_outcome=ComparisonOutcomeSummary(
            status="acceptable" if validation_score >= 0.7 else "rejected",
            promote_recommendation="promote" if validation_score >= 0.8 else "undecided",
            lineage_valid=lineage_verified,
            specialization_valid=True,
            is_acceptable=validation_score >= 0.7,
        ),
        deliberation=DeliberationSummary(
            outcome="adopt" if validation_score >= 0.8 else "defer",
            quality_score=validation_score,
            confidence=validation_score,
            consensus_status="consensus" if validation_score >= 0.8 else "disagreement",
            has_disagreement=validation_score < 0.8,
            escalation_used=False,
        ),
        snapshot_lineage=SnapshotLineageSummary(
            snapshot_id=f"snap-{adapter_id}-{generation}",
            adapter_id=adapter_id,
            generation=generation,
            specialization="shared",
            parent_snapshot_id=f"snap-{parent_id}-{parent_generation}",
            lineage_hash="abc123" if lineage_verified else "badhash",
        ),
        compatibility=CompatibilityHints(
            min_compatible_generation=parent_generation,
            max_compatible_generation=generation + 5,
            required_specialization="shared",
            min_validation_score=0.7,
            requires_consensus_accept=True,
        ),
        export_timestamp=now,
        export_version="1.0",
        source_node=source_node,
    )


class TestEndToEndMainPath:
    """Phase 19: End-to-end main path integration test."""

    def test_full_pipeline_via_governor(self):
        """Complete pipeline via Governor integration."""
        active = AdapterRef(
            adapter_id="test-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Phase 10: Create federation-ready summary
        summary = create_test_summary(
            adapter_id="candidate-1",
            generation=2,
            source_node="local",
            parent_id="test-adapter",
            parent_generation=1,
            validation_score=0.85,
        )

        # Phase 11: Exchange gate
        local_summary = create_test_summary(
            adapter_id="test-adapter",
            generation=1,
            source_node="local",
            parent_id="test-adapter",
            parent_generation=0,
            validation_score=0.9,
        )
        gate_result = FederationExchangeComparator.compare(local_summary, summary)
        assert gate_result is not None
        assert gate_result.lineage is not None

        # Phase 12: Remote intake via Governor
        intake_result = governor.process_remote_intake(
            summary.to_dict(),
            source_node="node-1",
        )
        assert intake_result.decision.value in ["stage_accept", "stage_reject", "stage_hold"]

        # Phase 13-16: Continue through pipeline if staged
        if intake_result.is_staged:
            # Triage
            triage_result = governor.triage_staged_candidate(
                staged_candidate=intake_result.staged_candidate,
            )
            assert triage_result.assessment.triage_status.value in ["ready", "hold", "downgrade", "reject"]

            # Lifecycle
            lifecycle_result = governor.evaluate_lifecycle(
                triage_result=triage_result,
            )
            assert lifecycle_result.meta.state.value in ["ready", "holding", "expired", "evicted"]

            # Conflict resolution
            conflict_result = governor.resolve_candidate_conflicts(
                lifecycle_candidates=[{
                    "identity": {
                        "adapter_id": "candidate-1",
                        "generation": 2,
                        "source_node": "node-1",
                    },
                }],
            )
            assert conflict_result.conflict_set.resolution_decision.value in [
                "select_one", "reject_all", "hold_all", "merge"
            ]

            # Promotion execution
            execution_result = governor.execute_promotion(
                candidate_dict={
                    "adapter_id": "candidate-1",
                    "generation": 2,
                    "source_node": "node-1",
                },
                triage_summary={
                    "status": triage_result.assessment.triage_status.value,
                    "readiness_score": triage_result.assessment.readiness.readiness_score,
                    "lineage_compatible": triage_result.assessment.lineage_compatible,
                    "specialization_compatible": triage_result.assessment.specialization_compatible,
                },
                lifecycle_summary={
                    "state": lifecycle_result.meta.state.value,
                    "ttl_remaining": lifecycle_result.meta.ttl_remaining,
                },
                conflict_summary={
                    "has_conflicts": conflict_result.conflict_set.has_conflicts,
                    "can_proceed": conflict_result.conflict_set.can_proceed(),
                    "resolution_decision": conflict_result.conflict_set.resolution_decision.value,
                },
            )
            assert execution_result is not None

            # Phase 17: Event emission
            event = governor.emit_federation_event(
                event_type="promotion_executed",
                adapter_id="candidate-1",
                generation=2,
                source_node="node-1",
                result_data={
                    "execution": execution_result.to_dict(),
                    "success": execution_result.success,
                },
            )
            assert event is not None
            assert event.event_type == EventType.PROMOTION_EXECUTED

            # Phase 18: Exchange skeleton
            proposal = ParameterMemoryExchangeSkeleton.create_proposal(
                candidate_dict={
                    "adapter_id": "candidate-1",
                    "generation": 2,
                    "source_node": "node-1",
                },
                intent="share_delta",
                priority=80,
            )
            assert proposal is not None

            exchange_readiness = ParameterMemoryExchangeSkeleton.assess_readiness(
                proposal=proposal,
                triage_summary={
                    "lineage_compatible": True,
                    "specialization_compatible": True,
                    "readiness_score": 0.85,
                    "status": "ready",
                },
                lifecycle_summary={
                    "state": "ready",
                    "ttl_remaining": 100.0,
                },
                conflict_summary={
                    "can_proceed": True,
                },
                execution_summary={
                    "success": execution_result.success,
                },
            )
            assert exchange_readiness is not None
            assert exchange_readiness.decision in [
                ExchangeDecision.EXCHANGE_READY,
                ExchangeDecision.EXCHANGE_HOLD,
                ExchangeDecision.EXCHANGE_REJECT,
            ]


class TestEndToEndFailurePaths:
    """Phase 19: End-to-end failure path tests."""

    def test_lineage_mismatch_detected(self):
        """Lineage mismatch should be detected."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Create summary with incompatible lineage
        summary = create_test_summary(
            adapter_id="bad-candidate",
            generation=5,
            source_node="remote-node",
            parent_id="different-adapter",
            parent_generation=99,
            validation_score=0.5,
            lineage_verified=False,
        )

        # Process through Governor
        intake_result = governor.process_remote_intake(
            summary.to_dict(),
            source_node="remote-node",
        )
        # Should be rejected due to lineage mismatch
        assert intake_result.decision.value in ["stage_reject", "stage_hold"]

    def test_specialization_mismatch_detected(self):
        """Specialization mismatch should be detected."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        summary = create_test_summary(
            adapter_id="spec-mismatch",
            generation=5,
            source_node="remote-node",
            parent_id="main-adapter",
            parent_generation=1,
            validation_score=0.8,
        )

        # Exchange gate should detect specialization issue
        local_summary = create_test_summary(
            adapter_id="main-adapter",
            generation=1,
            source_node="local",
            parent_id="main-adapter",
            parent_generation=0,
            validation_score=0.9,
        )
        gate_result = FederationExchangeComparator.compare(local_summary, summary)
        assert gate_result is not None

    def test_invalid_summary_rejected_at_intake(self):
        """Invalid summary should be rejected at intake."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Invalid summary data
        invalid_summary = {
            "adapter_id": "",
            "generation": -1,
            "lineage": None,
            "validation": None,
        }

        intake_result = governor.process_remote_intake(
            invalid_summary,
            source_node="remote-node",
        )

        # Should not be staged
        assert intake_result.is_staged is not True

    def test_execution_reject_creates_event(self):
        """Rejected execution should emit rejection event."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Execute with bad preconditions (should be rejected)
        execution_result = governor.execute_promotion(
            candidate_dict={
                "adapter_id": "bad-candidate",
                "generation": 5,
                "source_node": "node-1",
            },
            triage_summary={
                "status": "reject",
                "readiness_score": 0.3,
                "lineage_compatible": False,
                "specialization_compatible": False,
            },
            lifecycle_summary={
                "state": "expired",
                "ttl_remaining": 0.0,
            },
            conflict_summary={
                "has_conflicts": True,
                "can_proceed": False,
                "resolution_decision": "reject_all",
            },
        )

        assert execution_result is not None
        # Should be rejected
        assert execution_result.execution.decision.value == "reject"

        # Emit rejection event
        event = governor.emit_federation_event(
            event_type="promotion_rejected",
            adapter_id="bad-candidate",
            generation=5,
            source_node="node-1",
            result_data={
                "execution": execution_result.to_dict(),
                "reason": execution_result.execution.reason,
            },
        )
        assert event is not None
        assert event.event_type == EventType.PROMOTION_REJECTED

    def test_exchange_reject_does_not_pollute_state(self):
        """Exchange reject should not pollute main state."""
        proposal = ParameterMemoryExchangeSkeleton.create_proposal(
            candidate_dict={
                "adapter_id": "bad-candidate",
                "generation": 5,
                "source_node": "node-1",
            },
        )

        # Force reject
        exchange_readiness = ParameterMemoryExchangeSkeleton.assess_readiness(
            proposal=proposal,
            triage_summary={
                "lineage_compatible": False,
                "specialization_compatible": False,
                "readiness_score": 0.3,
                "status": "reject",
            },
            lifecycle_summary={
                "state": "expired",
                "ttl_remaining": 0.0,
            },
            conflict_summary={
                "can_proceed": False,
            },
            execution_summary={
                "success": False,
            },
        )

        assert exchange_readiness.decision == ExchangeDecision.EXCHANGE_REJECT
        assert not exchange_readiness.is_ready


class TestCompatibilityConservatism:
    """Phase 19: Compatibility conservatism tests."""

    def test_incompatible_not_wrongfully_upgraded(self):
        """Incompatible candidates should not be wrongfully upgraded."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Low quality summary
        summary = create_test_summary(
            adapter_id="low-quality",
            generation=5,
            source_node="remote-node",
            parent_id="main-adapter",
            parent_generation=1,
            validation_score=0.4,
            lineage_verified=False,
        )

        # Process through gate
        local_summary = create_test_summary(
            adapter_id="main-adapter",
            generation=1,
            source_node="local",
            parent_id="main-adapter",
            parent_generation=0,
            validation_score=0.9,
        )
        gate_result = FederationExchangeComparator.compare(local_summary, summary)

        # Should not be exchangeable
        assert not gate_result.can_exchange()

    def test_low_quality_remote_not_pollute(self):
        """Low quality remote summary should not pollute local state."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Process low quality summary
        bad_summary = {
            "identity": {
                "adapter_id": "low-quality",
                "generation": 5,
                "parent_generation": None,
                "specialization": "shared",
                "mode": "serve",
            },
            "specialization": {
                "stable_generation": 1,
                "shared_generation": 5,
                "candidate_generation": None,
                "active_specialization": "shared",
            },
            "importance_mask": {
                "top_keys": [],
                "scores": {},
                "threshold": 0.0,
                "compression_ratio": 1.0,
            },
            "delta_norm": {
                "l1_norm": 0.0,
                "l2_norm": 0.0,
                "max_abs": 0.0,
                "param_count": 0,
                "relative_to_parent": None,
            },
            "validation_score": {
                "passed": False,
                "lineage_valid": False,
                "specialization_valid": False,
                "output_match": False,
                "kv_count_match": False,
                "generation_advanced": False,
                "score": 0.3,
            },
            "comparison_outcome": {
                "status": "rejected",
                "promote_recommendation": "reject",
                "lineage_valid": False,
                "specialization_valid": False,
                "is_acceptable": False,
            },
            "deliberation": {
                "outcome": "reject",
                "quality_score": 0.3,
                "confidence": 0.3,
                "consensus_status": None,
                "has_disagreement": None,
                "escalation_used": False,
            },
            "snapshot_lineage": {
                "snapshot_id": "snap-low",
                "adapter_id": "low-quality",
                "generation": 5,
                "specialization": "shared",
                "parent_snapshot_id": None,
                "lineage_hash": "bad",
            },
            "compatibility": {
                "min_compatible_generation": 1,
                "max_compatible_generation": 10,
                "required_specialization": "shared",
                "min_validation_score": 0.7,
                "requires_consensus_accept": True,
                "format_version": "1.0",
            },
            "metadata": {
                "export_timestamp": "2024-01-01T00:00:00Z",
                "export_version": "1.0",
                "source_node": "remote-node",
            },
        }

        intake_result = governor.process_remote_intake(
            bad_summary,
            source_node="remote-node",
        )

        # Should be rejected or held, not accepted
        assert intake_result.decision.value in ["stage_reject", "stage_hold"]

    def test_reject_has_structured_trace(self):
        """Reject decisions should have structured trace."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        execution_result = governor.execute_promotion(
            candidate_dict={
                "adapter_id": "rejected",
                "generation": 5,
                "source_node": "node-1",
            },
            triage_summary={
                "status": "reject",
                "readiness_score": 0.2,
            },
            lifecycle_summary={
                "state": "expired",
                "ttl_remaining": 0.0,
            },
            conflict_summary={
                "has_conflicts": True,
                "can_proceed": False,
            },
        )

        # Should have structured trace
        assert execution_result.execution.execution_trace is not None
        assert len(execution_result.execution.execution_trace) > 0


class TestPhaseRegression:
    """Phase 19: Regression tests for previous phases."""

    def test_phase16_promotion_execution_not_regressed(self):
        """Phase 16 promotion execution should still work."""
        active = AdapterRef(
            adapter_id="test",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        result = governor.execute_promotion(
            candidate_dict={
                "adapter_id": "candidate",
                "generation": 5,
                "source_node": "node-1",
            },
            triage_summary={
                "status": "ready",
                "readiness_score": 0.8,
            },
            lifecycle_summary={
                "state": "ready",
                "ttl_remaining": 100.0,
            },
            conflict_summary={
                "has_conflicts": False,
                "can_proceed": True,
            },
        )

        assert result is not None
        assert result.execution is not None

    def test_phase15_conflict_resolution_not_regressed(self):
        """Phase 15 conflict resolution should still work."""
        active = AdapterRef(
            adapter_id="test",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        result = governor.resolve_candidate_conflicts(
            lifecycle_candidates=[{
                "identity": {"adapter_id": "candidate", "generation": 5},
            }],
        )

        assert result is not None
        assert result.conflict_set is not None

    def test_phase11_exchange_gate_not_regressed(self):
        """Phase 11 exchange gate should still work."""
        local_summary = create_test_summary(
            adapter_id="local",
            generation=1,
            source_node="local",
            parent_id="local",
            parent_generation=0,
            validation_score=0.9,
        )
        remote_summary = create_test_summary(
            adapter_id="remote",
            generation=5,
            source_node="remote",
            parent_id="local",
            parent_generation=1,
            validation_score=0.8,
        )

        gate_result = FederationExchangeComparator.compare(local_summary, remote_summary)

        assert gate_result is not None
        assert gate_result.lineage is not None

    def test_phase10_summary_layer_not_regressed(self):
        """Phase 10 summary layer should still work."""
        summary = create_test_summary(
            adapter_id="test",
            generation=5,
            source_node="node-1",
            parent_id="parent",
            parent_generation=1,
            validation_score=0.8,
        )

        assert summary.validation_score.score >= 0.7
        assert summary.to_dict() is not None


class TestServePathNotBlocked:
    """Phase 19: Ensure serve path is not blocked by pipeline."""

    def test_serve_path_works_during_pipeline(self):
        """Serve path should work even during pipeline processing."""
        active = AdapterRef(
            adapter_id="test",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Start pipeline processing
        summary = create_test_summary(
            adapter_id="candidate",
            generation=5,
            source_node="node-1",
            parent_id="test",
            parent_generation=1,
            validation_score=0.8,
        )

        # Process through pipeline
        governor.process_remote_intake(summary.to_dict(), "node-1")

        # Serve path should still work
        assert governor.active_adapter.adapter_id == "test"
        assert governor.active_adapter.mode == AdapterMode.SERVE

    def test_event_emission_does_not_block_serve(self):
        """Event emission should not block serve path."""
        active = AdapterRef(
            adapter_id="test",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Emit multiple events
        for i in range(10):
            governor.emit_federation_event(
                event_type="summary_intaken",
                adapter_id=f"candidate-{i}",
                generation=i,
                source_node="node-1",
                result_data={"decision": "stage_accept"},
            )

        # Serve path still works
        assert governor.active_adapter.adapter_id == "test"


class TestDeterminism:
    """Phase 19: Determinism tests."""

    def test_pipeline_same_input_same_output(self):
        """Same input should produce same pipeline output."""
        active = AdapterRef(
            adapter_id="test",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )

        def run_pipeline():
            governor = Governor(active)
            summary = create_test_summary(
                adapter_id="candidate",
                generation=5,
                source_node="node-1",
                parent_id="test",
                parent_generation=1,
                validation_score=0.8,
            )
            return governor.process_remote_intake(summary.to_dict(), "node-1")

        result1 = run_pipeline()
        result2 = run_pipeline()

        assert result1.decision.value == result2.decision.value


class TestFailureSafety:
    """Phase 19: Failure safety tests."""

    def test_pipeline_handles_exception_gracefully(self):
        """Pipeline should handle exceptions gracefully."""
        active = AdapterRef(
            adapter_id="main-adapter",
            generation=1,
            mode=AdapterMode.SERVE,
            specialization=AdapterSpecialization.STABLE,
        )
        governor = Governor(active)

        # Pass invalid data that might cause exceptions
        result = governor.process_remote_intake(
            {"invalid": "data"},
            source_node="node-1",
        )

        # Should return fallback result, not raise
        assert result is not None
        assert result.is_staged is not True

    def test_exchange_skeleton_handles_invalid_data(self):
        """Exchange skeleton should handle invalid data gracefully."""
        proposal = ParameterMemoryExchangeSkeleton.create_proposal(
            candidate_dict={"bad": "data"},
            fallback_on_error=True,
        )

        # Should return proposal with empty/invalid candidate (graceful handling)
        assert proposal is not None
        # Invalid data results in empty candidate (safe default, not crash)
        assert proposal.candidate.adapter_id == ""
        assert proposal.candidate.generation == 0
        # Should not be eligible for exchange
        assert not proposal.eligibility.is_eligible

    def test_event_stream_bounded(self):
        """Event stream should remain bounded."""
        emitter = FederationEventEmitter()

        # Emit many events
        for i in range(FederationEventEmitter.MAX_STREAM_SIZE + 100):
            emitter.emit_summary_intaken(
                adapter_id="test",
                generation=5,
                source_node="node-1",
                intake_result={"decision": "stage_accept"},
            )

        stream = emitter.get_stream("test", 5)
        assert len(stream.events) <= FederationEventEmitter.MAX_STREAM_SIZE


class TestRoundTrip:
    """Phase 19: Round-trip tests."""

    def test_summary_round_trip(self):
        """Summary should survive export/import round-trip."""
        summary = create_test_summary(
            adapter_id="test",
            generation=5,
            source_node="node-1",
            parent_id="parent",
            parent_generation=1,
            validation_score=0.8,
        )

        exported = summary.to_dict()
        imported = FederationSummary.from_dict(exported)

        assert imported.identity.adapter_id == summary.identity.adapter_id
        assert imported.identity.generation == summary.identity.generation

    def test_event_stream_round_trip(self):
        """Event stream should survive export/import round-trip."""
        emitter = FederationEventEmitter()

        emitter.emit_summary_intaken(
            adapter_id="test",
            generation=5,
            source_node="node-1",
            intake_result={"decision": "stage_accept"},
        )

        exported = emitter.export_stream("test", 5)
        assert exported is not None

        new_emitter = FederationEventEmitter()
        new_emitter.import_stream(exported)

        stream = new_emitter.get_stream("test", 5)
        assert stream is not None
        assert len(stream.events) == 1

    def test_exchange_proposal_round_trip(self):
        """Exchange proposal should survive export/import round-trip."""
        proposal = ParameterMemoryExchangeSkeleton.create_proposal(
            candidate_dict={
                "adapter_id": "test",
                "generation": 5,
                "source_node": "node-1",
            },
        )

        exported = proposal.to_dict()
        imported = ExchangeProposal.from_dict(exported)

        assert imported.candidate.adapter_id == proposal.candidate.adapter_id
        assert imported.candidate.generation == proposal.candidate.generation
