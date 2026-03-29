"""Tests for Chronara boundary helpers and compact external projections."""

from implementations.sac_py.chronara_nexus.boundary import (
    BoundarySurface,
    build_compatibility_hint,
    build_readiness_hint,
    get_boundary_descriptor,
    list_boundary_object_kinds,
)
from implementations.sac_py.chronara_nexus.governor import Governor, ValidationTrace
from implementations.sac_py.chronara_nexus.types import (
    AdapterMode,
    AdapterRef,
    ComparisonCompatibility,
    ExchangeStatus,
    FederationExchangeGate,
    LineageCompatibility,
    ReadinessSummary,
    SpecializationCompatibility,
    TriageAssessment,
    TriageResult,
    TriageStatus,
    ValidationCompatibility,
)


def create_test_gate() -> FederationExchangeGate:
    return FederationExchangeGate(
        local_adapter_id="local",
        local_generation=5,
        remote_adapter_id="remote",
        remote_generation=6,
        lineage=LineageCompatibility(True, 0.9, 1, True, False, "compatible"),
        specialization=SpecializationCompatibility(True, "stable", "stable", True, "compatible"),
        validation=ValidationCompatibility(True, 0.91, 0.94, 0.03, True, "acceptable"),
        comparison=ComparisonCompatibility(True, "candidate_ready", "candidate_ready", True, "aligned"),
        status=ExchangeStatus.ACCEPT,
        recommendation="accept",
        reason="compatible_remote_summary",
        fallback_used=False,
        version="1.0",
        timestamp="2024-01-01T00:00:00Z",
    )


def create_test_triage_result() -> TriageResult:
    return TriageResult(
        processed_at="2024-01-01T00:00:00Z",
        processor_version="1.0",
        fallback_used=False,
        assessment=TriageAssessment(
            adapter_id="remote",
            generation=6,
            source_node="remote-node",
            triage_status=TriageStatus.READY,
            triage_version="1.0",
            triaged_at="2024-01-01T00:00:00Z",
            readiness=ReadinessSummary(
                readiness_score=0.86,
                lineage_score=0.9,
                specialization_score=0.88,
                validation_score=0.9,
                comparison_score=0.87,
                recency_score=0.82,
                is_fresh=True,
                is_compatible=True,
                is_priority=True,
                score_reason="ready",
            ),
            lineage_compatible=True,
            specialization_compatible=True,
            validation_acceptable=True,
            comparison_acceptable=True,
            recommendation="promote_ready",
            reason="ready_for_federation",
            can_promote_later=True,
            needs_review=False,
            expiration_hint=None,
            original_staging_ref="intake-1",
        ),
        target_pool="ready",
        priority=86,
        trace_id="trace-1",
    )


class TestBoundaryRegistry:
    def test_boundary_registry_distinguishes_control_plane_and_mesh(self):
        control_plane = set(list_boundary_object_kinds(BoundarySurface.CONTROL_PLANE))
        mesh = set(list_boundary_object_kinds(BoundarySurface.P2P_MESH))
        local = set(list_boundary_object_kinds(BoundarySurface.LOCAL_INTERNAL))

        assert "federation_summary" in control_plane
        assert "federation_summary" in mesh
        assert "coordination_result" in control_plane
        assert "coordination_result" not in mesh
        assert "validation_trace" in local
        assert "validation_trace" not in control_plane
        assert local.isdisjoint(control_plane)

    def test_bridge_descriptor_marks_receipt_boundary(self):
        descriptor = get_boundary_descriptor("remote_execution_admission_bridge")
        assert descriptor.boundary_role == "receipt"
        assert BoundarySurface.CONTROL_PLANE in descriptor.surfaces
        assert BoundarySurface.P2P_MESH in descriptor.surfaces


class TestBoundaryHints:
    def test_build_compatibility_hint_preserves_gate_semantics(self):
        hint = build_compatibility_hint(create_test_gate())

        assert hint["remote_adapter_id"] == "remote"
        assert hint["remote_generation"] == 6
        assert hint["status"] == "accept"
        assert hint["lineage_compatible"] is True
        assert hint["validation_acceptable"] is True
        assert hint["comparison_acceptable"] is True

    def test_build_readiness_hint_preserves_triage_semantics(self):
        hint = build_readiness_hint(create_test_triage_result())

        assert hint["adapter_id"] == "remote"
        assert hint["generation"] == 6
        assert hint["status"] == "ready"
        assert hint["readiness_score"] == 0.86
        assert hint["can_promote_later"] is True
        assert hint["needs_review"] is False


class TestGovernorBoundaryRecording:
    def test_governor_records_compact_hints_on_existing_trace(self):
        governor = Governor(AdapterRef("local", 5, AdapterMode.SERVE))
        governor._validation_traces.append(
            ValidationTrace(
                active=governor.active_adapter,
                candidate=None,
                status="boundary-test",
                passed=True,
            )
        )

        gate = create_test_gate()
        triage_result = create_test_triage_result()

        assert governor.incorporate_exchange_gate(gate) is True
        assert governor._record_triage_result(triage_result) is True

        last_trace = governor.get_validation_traces()[-1]
        assert last_trace.exchange_gate_summary == build_compatibility_hint(gate)
        assert last_trace.triage_result_summary == build_readiness_hint(triage_result)
