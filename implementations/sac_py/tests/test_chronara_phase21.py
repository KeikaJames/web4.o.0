"""Phase 21: Remote federation admission bridge tests."""

from datetime import datetime, timezone

from implementations.sac_py.chronara_nexus.coordinator import (
    CoordinationDecision,
    FederationCoordinator,
    StageStatus,
)
from implementations.sac_py.chronara_nexus.governor import Governor, ValidationTrace
from implementations.sac_py.chronara_nexus.remote_execution_bridge import (
    BRIDGE_KIND,
    BridgeDecision,
    RemoteExecutionAdmissionBridge,
    prepare_remote_execution_input,
)
from implementations.sac_py.chronara_nexus.types import (
    AdapterIdentitySummary,
    AdapterMode,
    AdapterRef,
    ComparisonOutcomeSummary,
    CompatibilityHints,
    DeliberationSummary,
    DeltaNormSummary,
    FederationSummary,
    ImportanceMaskSummary,
    SnapshotLineageSummary,
    SpecializationSummary,
    ValidationScoreSummary,
)


def create_local_summary(adapter_id: str = "bridge-adapter", generation: int = 1) -> FederationSummary:
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return FederationSummary(
        identity=AdapterIdentitySummary(
            adapter_id=adapter_id,
            generation=generation,
            parent_generation=None,
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
            top_keys=["p1"],
            scores={"p1": 1.0},
            threshold=1.0,
            compression_ratio=0.1,
        ),
        delta_norm=DeltaNormSummary(
            l1_norm=1.0,
            l2_norm=0.5,
            max_abs=0.2,
            param_count=10,
            relative_to_parent=None,
        ),
        validation_score=ValidationScoreSummary(
            passed=False,
            lineage_valid=False,
            specialization_valid=False,
            output_match=False,
            kv_count_match=False,
            generation_advanced=False,
            score=0.0,
        ),
        comparison_outcome=ComparisonOutcomeSummary(
            status="unknown",
            promote_recommendation="undecided",
            lineage_valid=False,
            specialization_valid=False,
            is_acceptable=False,
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
            lineage_hash=f"{adapter_id}:{generation}:stable",
        ),
        compatibility=CompatibilityHints(
            min_compatible_generation=0,
            max_compatible_generation=generation + 1,
            required_specialization=None,
            min_validation_score=0.5,
            requires_consensus_accept=False,
            format_version="1.0",
        ),
        export_timestamp=now,
        export_version="1.0",
        source_node="local-node",
    )


def create_bridge_payload(
    decision: str = "bridge_accept",
    adapter_id: str = "bridge-adapter",
    generation: int = 2,
    specialization: str = "stable",
) -> dict:
    acceptable = decision != BridgeDecision.BRIDGE_REJECT.value
    kv_migrated = decision == BridgeDecision.BRIDGE_HOLD.value
    return {
        "bridge_kind": BRIDGE_KIND,
        "identity": {
            "execution_id": f"exec-{decision}",
            "execution_kind": "two_stage_remote_execution",
            "source_node_id": "remote-node",
            "source_tag": "decode",
            "home_node_id": "home-node",
        },
        "stage_summary": {
            "stage": "two_stage",
            "tokens_produced": 8,
            "kv_absorbed": 2,
            "kv_migrated": kv_migrated,
            "receipt": None,
            "prefill_receipt": {
                "stage_id": "atom-1:prefill",
                "stage_kind": "prefill",
                "owner_node_id": "home-node",
                "output_size": 3,
                "kv_chunk_count": 1,
                "kv_total_bytes": 8,
                "handoff_id": "atom-1:prefill",
            },
            "decode_receipt": {
                "stage_id": "atom-1:decode",
                "stage_kind": "decode",
                "owner_node_id": "home-node",
                "output_size": 4,
                "kv_chunk_count": 1,
                "kv_total_bytes": 8,
                "handoff_id": "atom-1:prefill",
            },
        },
        "validation_summary": {
            "receipt_verified": acceptable,
            "handoff_verified": acceptable,
            "output_match": acceptable,
            "lineage_complete": acceptable,
            "lineage_consistent": acceptable,
            "specialization_attached": acceptable,
            "remote_execution_acceptable": acceptable,
        },
        "adapter_lineage": {
            "adapter_id": adapter_id,
            "adapter_generation": generation,
            "specialization": specialization,
        },
        "remote_execution_acceptable": acceptable,
        "bridge_decision": decision,
        "recommendation": "bridge_into_remote_intake" if acceptable else "retain_trace_only",
        "reason": f"phase21_{decision}",
        "fallback_used": False,
        "version": "1.0",
        "timestamp": "1970-01-01T00:00:00Z",
    }


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
