"""Phase 21: Remote federation admission bridge tests."""

from implementations.sac_py.chronara_nexus.coordinator import (
    CoordinationDecision,
    FederationCoordinator,
    StageStatus,
)
from implementations.sac_py.chronara_nexus.governor import Governor, ValidationTrace
from implementations.sac_py.chronara_nexus.remote_execution_bridge import (
    BridgeDecision,
    RemoteExecutionAdmissionBridge,
    prepare_remote_execution_input,
)
from implementations.sac_py.chronara_nexus.types import AdapterMode, AdapterRef
from implementations.sac_py.tests.chronara_test_helpers import (
    create_bridge_payload,
    create_federation_summary,
)


def create_local_summary(adapter_id: str = "bridge-adapter", generation: int = 1):
    return create_federation_summary(
        adapter_id=adapter_id,
        generation=generation,
        source_node="local-node",
        parent_generation=None,
        top_keys=["p1"],
        scores={"p1": 1.0},
        threshold=1.0,
        compression_ratio=0.1,
        max_abs=0.2,
        param_count=10,
        relative_to_parent=None,
        validation_passed=False,
        validation_score=0.0,
        lineage_valid=False,
        specialization_valid=False,
        output_match=False,
        kv_count_match=False,
        generation_advanced=False,
        comparison_status="unknown",
        comparison_recommendation="undecided",
        comparison_acceptable=False,
        quality_score=0.5,
        confidence=0.5,
        consensus_status=None,
        has_disagreement=None,
        lineage_hash=f"{adapter_id}:{generation}:stable",
        min_compatible_generation=0,
        max_compatible_generation=generation + 1,
        min_validation_score=0.5,
    )


class TestRemoteExecutionBridgeObjects:
    def test_bridge_object_is_structured_and_deterministic(self):
        payload = create_bridge_payload()
        bridge_a = RemoteExecutionAdmissionBridge.from_dict(payload)
        bridge_b = RemoteExecutionAdmissionBridge.from_dict(payload)

        assert bridge_a.bridge_decision == BridgeDecision.BRIDGE_ACCEPT
        assert bridge_a.to_dict() == bridge_b.to_dict()
        assert bridge_a.to_trace_summary()["execution_id"] == "exec-bridge_accept"

    def test_prepare_remote_execution_input_is_deterministic(self):
        payload = create_bridge_payload(decision="bridge_hold")
        local_summary = create_local_summary()

        prepared_a = prepare_remote_execution_input(payload, local_summary)
        prepared_b = prepare_remote_execution_input(payload, local_summary)

        assert prepared_a.bridge_decision == BridgeDecision.BRIDGE_HOLD
        assert prepared_a.normalized_summary_dict == prepared_b.normalized_summary_dict


class TestRemoteExecutionBridgeRouting:
    def test_bridge_accept_enters_intake_staging(self):
        governor = Governor(AdapterRef("bridge-adapter", 1, AdapterMode.SERVE))
        result = governor.process_remote_intake(create_bridge_payload(), source_node="caller-node")

        assert result.decision.value == "stage_accept"
        assert result.staged_candidate is not None
        assert result.staged_candidate.summary.identity.adapter_id == "bridge-adapter"

    def test_bridge_hold_enters_conservative_wait_path(self):
        coordinator = FederationCoordinator(intake_processor=True)
        local_summary = create_local_summary()
        result = coordinator.coordinate(
            remote_summary_dict=create_bridge_payload(decision="bridge_hold"),
            local_summary=local_summary,
            source_node="caller-node",
            existing_candidates=[],
        )

        assert result.intake_status == StageStatus.COMPLETED
        assert result.triage_status == StageStatus.HELD
        assert result.decision == CoordinationDecision.COORDINATED_HOLD
        assert result.bridge_summary["bridge_decision"] == "bridge_hold"
        assert result.trace.bridge_summary["bridge_decision"] == "bridge_hold"

    def test_bridge_reject_does_not_enter_main_path(self):
        governor = Governor(AdapterRef("bridge-adapter", 1, AdapterMode.SERVE))
        intake_result = governor.process_remote_intake(
            create_bridge_payload(decision="bridge_reject"),
            source_node="caller-node",
        )

        assert intake_result.decision.value == "stage_reject"
        assert intake_result.staged_candidate is None
        assert intake_result.rejection_trace["bridge_summary"]["bridge_decision"] == "bridge_reject"

        coordinator = FederationCoordinator(intake_processor=True)
        result = coordinator.coordinate(
            remote_summary_dict=create_bridge_payload(decision="bridge_reject"),
            local_summary=create_local_summary(),
            source_node="caller-node",
            existing_candidates=[],
        )

        assert result.intake_status == StageStatus.REJECTED
        assert result.triage_status == StageStatus.PENDING
        assert result.decision == CoordinationDecision.COORDINATED_REJECT

    def test_bad_bridge_fields_degrade_safely(self):
        payload = create_bridge_payload()
        payload["adapter_lineage"]["adapter_generation"] = None
        governor = Governor(AdapterRef("bridge-adapter", 1, AdapterMode.SERVE))

        result = governor.process_remote_intake(payload, source_node="caller-node")

        assert result.decision.value == "stage_reject"
        assert result.staged_candidate is None


class TestGovernorCoordinatorBridgeIntegration:
    def test_governor_and_coordinator_record_bridge_summaries(self):
        active = AdapterRef("bridge-adapter", 1, AdapterMode.SERVE)
        governor = Governor(active)
        governor._validation_traces.append(
            ValidationTrace(
                active=active,
                candidate=None,
                status="phase21",
                passed=True,
            )
        )

        governor.process_remote_intake(create_bridge_payload(), source_node="caller-node")
        trace_dict = governor._validation_traces[-1].to_dict()
        assert trace_dict["remote_execution_bridge_summary"]["bridge_decision"] == "bridge_accept"

        coordination = governor.coordinate_federation_intake(
            create_bridge_payload(),
            source_node="caller-node",
        )
        latest_trace = governor._validation_traces[-1].to_dict()
        assert coordination.bridge_summary["bridge_decision"] == "bridge_accept"
        assert latest_trace["coordination_summary"]["bridge_summary"]["bridge_decision"] == "bridge_accept"

    def test_coordinator_quick_check_accepts_bridge_payload(self):
        coordinator = FederationCoordinator()
        assert coordinator.quick_coordination_check(create_bridge_payload()) is True
        assert coordinator.quick_coordination_check(create_bridge_payload(decision="bridge_reject")) is False
