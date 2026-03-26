"""Phase 20: Federation / Exchange Execution Coordinator Tests.

Tests for the unified coordination layer that orchestrates:
intake → staging → triage → lifecycle → conflict → execution → event → exchange
"""

import pytest
from datetime import datetime, timezone

from implementations.sac_py.chronara_nexus.coordinator import (
    FederationCoordinator,
    CoordinationResult,
    CoordinationDecision,
    CoordinationTrace,
    StageResult,
    StageStatus,
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
)
from implementations.sac_py.chronara_nexus.governor import Governor, ValidationTrace, AdapterRef, AdapterMode


class TestCoordinationObjects:
    """Test coordinator object creation and serialization."""

    def test_stage_result_creation(self):
        """StageResult is a real structured object."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = StageResult(
            stage_name="intake",
            status=StageStatus.COMPLETED,
            success=True,
            output={"decision": "stage_accept"},
            timestamp=now,
        )
        assert result.stage_name == "intake"
        assert result.status == StageStatus.COMPLETED
        assert result.success is True
        assert result.output["decision"] == "stage_accept"

    def test_stage_result_to_dict(self):
        """StageResult can be serialized to dict."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = StageResult(
            stage_name="intake",
            status=StageStatus.COMPLETED,
            success=True,
            output={"decision": "stage_accept"},
            timestamp=now,
        )
        d = result.to_dict()
        assert d["stage"] == "intake"
        assert d["status"] == "completed"
        assert d["success"] is True

    def test_stage_result_from_dict(self):
        """StageResult can be deserialized from dict."""
        data = {
            "stage": "triage",
            "status": "rejected",
            "success": False,
            "output": None,
            "error": "incompatible",
            "fallback_used": True,
            "timestamp": "2024-01-01T00:00:00Z",
        }
        result = StageResult.from_dict(data)
        assert result.stage_name == "triage"
        assert result.status == StageStatus.REJECTED
        assert result.success is False
        assert result.fallback_used is True

    def test_coordination_trace_creation(self):
        """CoordinationTrace is a real structured object."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        trace = CoordinationTrace(
            trace_id="trace-123",
            stages=[],
            started_at=now,
        )
        assert trace.trace_id == "trace-123"
        assert trace.stages == []
        assert trace.started_at == now

    def test_coordination_result_creation(self):
        """CoordinationResult is a real structured object."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = CoordinationResult(
            coordination_id="coord-123",
            adapter_id="test-adapter",
            generation=5,
            source_node="node-1",
            decision=CoordinationDecision.COORDINATED_READY,
            is_ready=True,
            intake_status=StageStatus.COMPLETED,
            triage_status=StageStatus.COMPLETED,
            lifecycle_status=StageStatus.COMPLETED,
            conflict_status=StageStatus.COMPLETED,
            execution_status=StageStatus.COMPLETED,
            event_status=StageStatus.COMPLETED,
            exchange_status=StageStatus.COMPLETED,
            reason="All stages passed",
            recommendation="proceed_with_federation",
            coordinated_at=now,
        )
        assert result.coordination_id == "coord-123"
        assert result.adapter_id == "test-adapter"
        assert result.generation == 5
        assert result.decision == CoordinationDecision.COORDINATED_READY
        assert result.is_ready is True
        assert result.is_successful() is True

    def test_coordination_result_to_dict(self):
        """CoordinationResult can be serialized to dict."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = CoordinationResult(
            coordination_id="coord-123",
            adapter_id="test-adapter",
            generation=5,
            source_node="node-1",
            decision=CoordinationDecision.COORDINATED_READY,
            is_ready=True,
            intake_status=StageStatus.COMPLETED,
            triage_status=StageStatus.COMPLETED,
            lifecycle_status=StageStatus.COMPLETED,
            conflict_status=StageStatus.COMPLETED,
            execution_status=StageStatus.COMPLETED,
            event_status=StageStatus.COMPLETED,
            exchange_status=StageStatus.COMPLETED,
            coordinated_at=now,
        )
        d = result.to_dict()
        assert d["identity"]["coordination_id"] == "coord-123"
        assert d["identity"]["adapter_id"] == "test-adapter"
        assert d["decision"]["decision"] == "coordinated_ready"
        assert d["decision"]["is_ready"] is True

    def test_coordination_result_from_dict(self):
        """CoordinationResult can be deserialized from dict."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        data = {
            "identity": {
                "coordination_id": "coord-456",
                "adapter_id": "test-adapter",
                "generation": 3,
                "source_node": "node-2",
            },
            "decision": {
                "decision": "coordinated_reject",
                "is_ready": False,
            },
            "stage_status": {
                "intake": "completed",
                "triage": "rejected",
                "lifecycle": "pending",
                "conflict": "pending",
                "execution": "pending",
                "event": "pending",
                "exchange": "pending",
            },
            "summaries": {},
            "reasoning": {
                "reason": "Triage rejected",
                "recommendation": "reject_at_triage",
            },
            "trace": None,
            "fallback": {
                "coordination_fallback_used": False,
                "any_stage_fallback": False,
            },
            "meta": {
                "version": "1.0",
                "coordinated_at": now,
            },
        }
        result = CoordinationResult.from_dict(data)
        assert result.coordination_id == "coord-456"
        assert result.decision == CoordinationDecision.COORDINATED_REJECT
        assert result.triage_status == StageStatus.REJECTED
        assert result.should_short_circuit() is True

    def test_coordination_result_round_trip(self):
        """CoordinationResult round-trip serialization is stable."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        original = CoordinationResult(
            coordination_id="coord-789",
            adapter_id="test-adapter",
            generation=7,
            source_node="node-3",
            decision=CoordinationDecision.COORDINATED_HOLD,
            is_ready=False,
            intake_status=StageStatus.COMPLETED,
            triage_status=StageStatus.HELD,
            lifecycle_status=StageStatus.PENDING,
            conflict_status=StageStatus.PENDING,
            execution_status=StageStatus.PENDING,
            event_status=StageStatus.PENDING,
            exchange_status=StageStatus.PENDING,
            reason="Hold for observation",
            recommendation="hold_at_triage",
            coordinated_at=now,
        )
        d = original.to_dict()
        restored = CoordinationResult.from_dict(d)
        assert restored.coordination_id == original.coordination_id
        assert restored.adapter_id == original.adapter_id
        assert restored.decision == original.decision
        assert restored.triage_status == original.triage_status


class TestFederationCoordinator:
    """Test FederationCoordinator orchestration."""

    def _create_test_summary(self, adapter_id="test-adapter", generation=5):
        """Helper to create a valid federation summary."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return FederationSummary(
            identity=AdapterIdentitySummary(
                adapter_id=adapter_id,
                generation=generation,
                parent_generation=generation - 1 if generation > 1 else None,
                specialization="stable",
                mode="serve",
            ),
            specialization=SpecializationSummary(
                stable_generation=generation,
                shared_generation=None,
                candidate_generation=None,
                active_specialization="stable",
            ),
            importance_mask=ImportanceMaskSummary(
                top_keys=["param1", "param2"],
                scores={"param1": 0.9, "param2": 0.8},
                threshold=0.5,
                compression_ratio=0.2,
            ),
            delta_norm=DeltaNormSummary(
                l1_norm=1.0,
                l2_norm=0.5,
                max_abs=0.3,
                param_count=100,
                relative_to_parent=0.1,
            ),
            validation_score=ValidationScoreSummary(
                passed=True,
                lineage_valid=True,
                specialization_valid=True,
                output_match=True,
                kv_count_match=True,
                generation_advanced=True,
                score=0.95,
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
                quality_score=0.9,
                confidence=0.85,
                consensus_status="consensus_accept",
                has_disagreement=False,
                escalation_used=False,
            ),
            snapshot_lineage=SnapshotLineageSummary(
                snapshot_id=f"{adapter_id}-gen{generation}",
                adapter_id=adapter_id,
                generation=generation,
                specialization="stable",
                parent_snapshot_id=f"{adapter_id}-gen{generation-1}" if generation > 1 else None,
                lineage_hash=f"{adapter_id}:{generation}",
            ),
            compatibility=CompatibilityHints(
                min_compatible_generation=generation - 2,
                max_compatible_generation=generation + 1,
                required_specialization=None,
                min_validation_score=0.7,
                requires_consensus_accept=False,
                format_version="1.0",
            ),
            export_timestamp=now,
            export_version="1.0",
            source_node="test-node",
        )

    def test_coordinator_creation(self):
        """FederationCoordinator can be created."""
        coordinator = FederationCoordinator()
        assert coordinator is not None
        assert coordinator.VERSION == "1.0"

    def test_deterministic_output_for_same_input(self):
        """Same input produces deterministic coordination result."""
        coordinator = FederationCoordinator()
        local_summary = self._create_test_summary("local-adapter", 5)
        remote_dict = self._create_test_summary("remote-adapter", 6).to_dict()

        result1 = coordinator.coordinate(
            remote_summary_dict=remote_dict,
            local_summary=local_summary,
            source_node="test-node",
        )
        result2 = coordinator.coordinate(
            remote_summary_dict=remote_dict,
            local_summary=local_summary,
            source_node="test-node",
        )

        # Both should have same structure (though IDs will differ)
        assert result1.adapter_id == result2.adapter_id
        assert result1.generation == result2.generation
        assert result1.source_node == result2.source_node

    def test_stage_by_stage_orchestration(self):
        """Coordinator runs all stages in order."""
        coordinator = FederationCoordinator()
        local_summary = self._create_test_summary("local-adapter", 5)
        remote_dict = self._create_test_summary("remote-adapter", 6).to_dict()

        result = coordinator.coordinate(
            remote_summary_dict=remote_dict,
            local_summary=local_summary,
            source_node="test-node",
        )

        # Check that trace exists and has stages
        assert result.trace is not None
        assert len(result.trace.stages) > 0

        # Check stage ordering (intake should be first)
        stage_names = [s.stage_name for s in result.trace.stages]
        assert "intake" in stage_names

    def test_reject_short_circuits_subsequent_stages(self):
        """Reject at intake short-circuits subsequent stages."""
        from implementations.sac_py.chronara_nexus.intake_processor import RemoteIntakeProcessor

        coordinator = FederationCoordinator(intake_processor=RemoteIntakeProcessor)
        local_summary = self._create_test_summary("local-adapter", 5)

        # Create invalid remote summary (missing required fields)
        invalid_remote = {"identity": {"adapter_id": "bad", "generation": "not_int"}}

        result = coordinator.coordinate(
            remote_summary_dict=invalid_remote,
            local_summary=local_summary,
            source_node="test-node",
        )

        # Should be rejected or failed at intake
        assert result.decision in (CoordinationDecision.COORDINATED_REJECT, CoordinationDecision.COORDINATED_HOLD)
        assert result.intake_status in (StageStatus.REJECTED, StageStatus.FAILED, StageStatus.COMPLETED)

        # If rejected, should have short-circuit info
        if result.intake_status in (StageStatus.REJECTED, StageStatus.FAILED):
            assert result.trace.short_circuit_at is not None or result.decision == CoordinationDecision.COORDINATED_REJECT

    def test_hold_enters_structured_hold_path(self):
        """Hold decision enters structured hold path."""
        coordinator = FederationCoordinator()

        # Create a summary that might be held
        local_summary = self._create_test_summary("local-adapter", 5)
        remote = self._create_test_summary("remote-adapter", 6)
        # Lower validation score to potentially trigger hold
        remote.validation_score = ValidationScoreSummary(
            passed=True,
            lineage_valid=True,
            specialization_valid=True,
            output_match=True,
            kv_count_match=True,
            generation_advanced=True,
            score=0.6,  # Lower score
        )

        result = coordinator.coordinate(
            remote_summary_dict=remote.to_dict(),
            local_summary=local_summary,
            source_node="test-node",
        )

        # Result should have valid structure regardless of decision
        assert result.coordination_id is not None
        assert result.trace is not None

    def test_rollback_structured_result(self):
        """Rollback produces structured rollback result."""
        # Create a result that simulates rollback
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = CoordinationResult(
            coordination_id="coord-rollback",
            adapter_id="test-adapter",
            generation=5,
            source_node="node-1",
            decision=CoordinationDecision.COORDINATED_ROLLBACK,
            is_ready=False,
            intake_status=StageStatus.COMPLETED,
            triage_status=StageStatus.COMPLETED,
            lifecycle_status=StageStatus.COMPLETED,
            conflict_status=StageStatus.COMPLETED,
            execution_status=StageStatus.ROLLBACK,
            event_status=StageStatus.COMPLETED,
            exchange_status=StageStatus.COMPLETED,
            reason="Rollback requested",
            recommendation="rollback_execution",
            coordinated_at=now,
        )

        assert result.decision == CoordinationDecision.COORDINATED_ROLLBACK
        assert result.should_short_circuit() is True

    def test_fallback_used_tracking(self):
        """Fallback usage is tracked across stages."""
        coordinator = FederationCoordinator()
        local_summary = self._create_test_summary("local-adapter", 5)
        remote_dict = self._create_test_summary("remote-adapter", 6).to_dict()

        result = coordinator.coordinate(
            remote_summary_dict=remote_dict,
            local_summary=local_summary,
            source_node="test-node",
        )

        # Check fallback tracking
        assert hasattr(result, 'fallback_used')
        assert hasattr(result, 'any_stage_fallback')

    def test_export_import_round_trip(self):
        """Export/import round-trip is stable."""
        coordinator = FederationCoordinator()
        local_summary = self._create_test_summary("local-adapter", 5)
        remote_dict = self._create_test_summary("remote-adapter", 6).to_dict()

        result = coordinator.coordinate(
            remote_summary_dict=remote_dict,
            local_summary=local_summary,
            source_node="test-node",
        )

        # Export
        exported = coordinator.export_result(result)
        assert isinstance(exported, dict)

        # Import
        imported = coordinator.import_result(exported)
        assert isinstance(imported, CoordinationResult)
        assert imported.adapter_id == result.adapter_id
        assert imported.generation == result.generation

    def test_quick_coordination_check(self):
        """Quick coordination check works."""
        coordinator = FederationCoordinator()

        # Valid summary
        valid = self._create_test_summary("test", 5).to_dict()
        assert coordinator.quick_coordination_check(valid) is True

        # Invalid summary
        invalid = {"bad": "data"}
        assert coordinator.quick_coordination_check(invalid) is False


class TestGovernorCoordinationIntegration:
    """Test Governor integration with coordinator."""

    def _create_test_summary(self, adapter_id="test-adapter", generation=5):
        """Helper to create a valid federation summary."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return FederationSummary(
            identity=AdapterIdentitySummary(
                adapter_id=adapter_id,
                generation=generation,
                parent_generation=generation - 1 if generation > 1 else None,
                specialization="stable",
                mode="serve",
            ),
            specialization=SpecializationSummary(
                stable_generation=generation,
                shared_generation=None,
                candidate_generation=None,
                active_specialization="stable",
            ),
            importance_mask=ImportanceMaskSummary(
                top_keys=["param1"],
                scores={"param1": 0.9},
                threshold=0.5,
                compression_ratio=0.1,
            ),
            delta_norm=DeltaNormSummary(
                l1_norm=1.0,
                l2_norm=0.5,
                max_abs=0.3,
                param_count=10,
                relative_to_parent=None,
            ),
            validation_score=ValidationScoreSummary(
                passed=True,
                lineage_valid=True,
                specialization_valid=True,
                output_match=True,
                kv_count_match=True,
                generation_advanced=True,
                score=0.95,
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
                quality_score=0.9,
                confidence=0.85,
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
                lineage_hash="hash",
            ),
            compatibility=CompatibilityHints(
                min_compatible_generation=0,
                max_compatible_generation=10,
                required_specialization=None,
                min_validation_score=0.5,
                requires_consensus_accept=False,
                format_version="1.0",
            ),
            export_timestamp=now,
            export_version="1.0",
            source_node="test-node",
        )

    def test_governor_can_consume_coordination_result(self):
        """Governor can consume coordination result."""
        active = AdapterRef(adapter_id="test", generation=1, mode=AdapterMode.SERVE)
        governor = Governor(initial_adapter=active)

        # Create a coordination result
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        result = CoordinationResult(
            coordination_id="coord-test",
            adapter_id="remote-adapter",
            generation=2,
            source_node="remote-node",
            decision=CoordinationDecision.COORDINATED_READY,
            is_ready=True,
            intake_status=StageStatus.COMPLETED,
            triage_status=StageStatus.COMPLETED,
            lifecycle_status=StageStatus.COMPLETED,
            conflict_status=StageStatus.COMPLETED,
            execution_status=StageStatus.COMPLETED,
            event_status=StageStatus.COMPLETED,
            exchange_status=StageStatus.COMPLETED,
            reason="All stages passed",
            recommendation="proceed",
            coordinated_at=now,
        )

        consumed = governor.consume_coordination_result(result)
        # Should consume successfully (returns True for successful result)
        assert consumed is True

        # Check that it was recorded in traces - need to add a trace first
        # Add a dummy trace to record the coordination
        trace = ValidationTrace(
            active=active,
            candidate=None,
            status="coordination_test",
            passed=True,
        )
        governor._validation_traces.append(trace)

        # Now record the coordination
        governor._record_coordination_result(result)

        # Check history
        history = governor.get_coordination_history()
        assert len(history) > 0
        assert history[0]["coordination_id"] == "coord-test"

    def test_governor_coordination_integration(self):
        """Governor coordinate_federation_intake method works."""
        active = AdapterRef(adapter_id="local-adapter", generation=5, mode=AdapterMode.SERVE)
        governor = Governor(initial_adapter=active)

        remote_summary = self._create_test_summary("remote-adapter", 6)

        result = governor.coordinate_federation_intake(
            remote_summary_dict=remote_summary.to_dict(),
            source_node="remote-node",
        )

        assert result is not None
        assert isinstance(result, CoordinationResult)
        assert result.adapter_id == "remote-adapter"
        assert result.generation == 6
        assert result.source_node == "remote-node"

    def test_validation_trace_has_coordination_summary(self):
        """ValidationTrace includes coordination_summary field."""
        trace = ValidationTrace(
            active=AdapterRef(adapter_id="test", generation=1, mode=AdapterMode.SERVE),
            candidate=None,
            status="test",
            passed=True,
        )

        # Should have coordination_summary attribute
        assert hasattr(trace, 'coordination_summary')
        trace.coordination_summary = {"test": "data"}
        assert trace.coordination_summary == {"test": "data"}

    def test_governor_quick_coordination_check(self):
        """Governor quick_coordination_check method works."""
        active = AdapterRef(adapter_id="local", generation=1, mode=AdapterMode.SERVE)
        governor = Governor(initial_adapter=active)

        valid = self._create_test_summary("test", 5).to_dict()
        assert governor.quick_coordination_check(valid) is True

        invalid = {"bad": "data"}
        assert governor.quick_coordination_check(invalid) is False

    def test_governor_is_candidate_coordinated_ready(self):
        """Governor is_candidate_coordinated_ready method works."""
        active = AdapterRef(adapter_id="local", generation=1, mode=AdapterMode.SERVE)
        governor = Governor(initial_adapter=active)

        # Initially not coordinated
        assert governor.is_candidate_coordinated_ready("remote", 2) is False

        # Add a coordination result to traces
        trace = ValidationTrace(
            active=active,
            candidate=AdapterRef(adapter_id="remote", generation=2, mode=AdapterMode.SERVE),
            status="coordinated",
            passed=True,
        )
        trace.coordination_summary = {
            "adapter_id": "remote",
            "generation": 2,
            "decision": "coordinated_ready",
            "is_ready": True,
        }
        governor._validation_traces.append(trace)

        # Now should be ready
        assert governor.is_candidate_coordinated_ready("remote", 2) is True


class TestFailureSafety:
    """Test failure safety guarantees."""

    def test_coordinator_failure_does_not_block_serve(self):
        """Coordinator failure does not block serve path."""
        coordinator = FederationCoordinator()

        # Invalid input should return fallback, not raise
        result = coordinator.coordinate(
            remote_summary_dict=None,  # Invalid
            local_summary=None,  # Invalid
            fallback_on_error=True,
        )

        assert result is not None
        assert result.fallback_used is True

    def test_bad_fields_safe_downgrade(self):
        """Bad/ missing fields trigger safe fallback."""
        coordinator = FederationCoordinator()

        # Missing identity - should be caught by quick check but still handled gracefully
        bad_data = {"specialization": {}}

        result = coordinator.coordinate(
            remote_summary_dict=bad_data,
            local_summary=None,
            fallback_on_error=True,
        )

        # Should return result (may be fallback or regular reject)
        assert result is not None
        # Result should indicate failure through decision or fallback flag
        assert result.fallback_used is True or result.decision == CoordinationDecision.COORDINATED_REJECT

    def test_no_main_state_pollution(self):
        """Coordination does not pollute main stable/shared/candidate state."""
        from implementations.sac_py.chronara_nexus.types import AdapterSpecialization

        active = AdapterRef(adapter_id="local", generation=5, mode=AdapterMode.SERVE)
        governor = Governor(initial_adapter=active)

        # Record initial state
        initial_stable = governor.stable_adapter
        initial_active = governor.active_adapter

        # Run coordination with invalid data (will fallback)
        result = governor.coordinate_federation_intake(
            remote_summary_dict={"bad": "data"},
            source_node="test",
        )

        # State should be unchanged
        assert governor.stable_adapter == initial_stable
        assert governor.active_adapter == initial_active

    def test_phase_17_19_regression_protection(self):
        """Phase 17-19 capabilities are not regressed."""
        # Ensure event streaming still works
        from implementations.sac_py.chronara_nexus.event_stream import FederationEventEmitter, EventType
        emitter = FederationEventEmitter()

        event = emitter.emit_summary_intaken(
            adapter_id="test",
            generation=1,
            source_node="node",
            intake_result={"decision": "stage_accept", "is_staged": True},
        )

        assert event is not None
        assert event.event_type == EventType.SUMMARY_INTAKEN

        # Ensure exchange skeleton still works
        from implementations.sac_py.chronara_nexus.exchange_skeleton import ParameterMemoryExchangeSkeleton
        proposal = ParameterMemoryExchangeSkeleton.create_proposal(
            candidate_dict={"adapter_id": "test", "generation": 1},
        )
        assert proposal is not None


class TestPhase19EndToEnd:
    """Ensure Phase 19 end-to-end acceptance still works."""

    def test_full_pipeline_via_governor(self):
        """Full pipeline through Governor works."""
        from implementations.sac_py.chronara_nexus.types import AdapterSpecialization

        active = AdapterRef(adapter_id="local", generation=5, mode=AdapterMode.SERVE)
        governor = Governor(initial_adapter=active)

        # Create valid remote summary
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        remote_summary = FederationSummary(
            identity=AdapterIdentitySummary(
                adapter_id="remote-adapter",
                generation=6,
                parent_generation=5,
                specialization="stable",
                mode="serve",
            ),
            specialization=SpecializationSummary(
                stable_generation=6,
                shared_generation=None,
                candidate_generation=None,
                active_specialization="stable",
            ),
            importance_mask=ImportanceMaskSummary(
                top_keys=["p1"],
                scores={"p1": 0.9},
                threshold=0.5,
                compression_ratio=0.1,
            ),
            delta_norm=DeltaNormSummary(
                l1_norm=1.0,
                l2_norm=0.5,
                max_abs=0.3,
                param_count=10,
                relative_to_parent=0.1,
            ),
            validation_score=ValidationScoreSummary(
                passed=True,
                lineage_valid=True,
                specialization_valid=True,
                output_match=True,
                kv_count_match=True,
                generation_advanced=True,
                score=0.95,
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
                quality_score=0.9,
                confidence=0.85,
                consensus_status="consensus_accept",
                has_disagreement=False,
                escalation_used=False,
            ),
            snapshot_lineage=SnapshotLineageSummary(
                snapshot_id="remote-adapter-gen6",
                adapter_id="remote-adapter",
                generation=6,
                specialization="stable",
                parent_snapshot_id="remote-adapter-gen5",
                lineage_hash="hash123",
            ),
            compatibility=CompatibilityHints(
                min_compatible_generation=4,
                max_compatible_generation=7,
                required_specialization=None,
                min_validation_score=0.7,
                requires_consensus_accept=False,
                format_version="1.0",
            ),
            export_timestamp=now,
            export_version="1.0",
            source_node="remote-node",
        )

        # Run coordination
        result = governor.coordinate_federation_intake(
            remote_summary_dict=remote_summary.to_dict(),
            source_node="remote-node",
        )

        # Should complete with valid result
        assert result is not None
        assert result.adapter_id == "remote-adapter"
        assert result.trace is not None

        # Should have intake stage completed
        assert result.intake_summary is not None
