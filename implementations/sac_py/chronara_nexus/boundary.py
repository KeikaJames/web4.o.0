"""Chronara boundary helpers for control-plane and optional mesh surfaces.

This module does not introduce new protocol behavior. It only makes existing
object boundaries explicit so later control-plane / mesh work can depend on a
small, stable interface.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List

from .types import FederationExchangeGate, TriageResult


class BoundarySurface(Enum):
    """Where an object is expected to live or be exported."""

    LOCAL_INTERNAL = "local_internal"
    CONTROL_PLANE = "control_plane"
    P2P_MESH = "p2p_mesh"


@dataclass(frozen=True)
class BoundaryDescriptor:
    """Explicit descriptor for a Chronara object boundary."""

    object_kind: str
    surfaces: tuple[BoundarySurface, ...]
    boundary_role: str
    notes: str


BOUNDARY_REGISTRY: Dict[str, BoundaryDescriptor] = {
    "validation_trace": BoundaryDescriptor(
        object_kind="validation_trace",
        surfaces=(BoundarySurface.LOCAL_INTERNAL,),
        boundary_role="internal_audit",
        notes="Governor-local audit chain; not intended for control-plane truth or mesh propagation.",
    ),
    "staged_remote_candidate": BoundaryDescriptor(
        object_kind="staged_remote_candidate",
        surfaces=(BoundarySurface.LOCAL_INTERNAL,),
        boundary_role="internal_staging_state",
        notes="Local staging state that should not be propagated directly.",
    ),
    "lifecycle_meta": BoundaryDescriptor(
        object_kind="lifecycle_meta",
        surfaces=(BoundarySurface.LOCAL_INTERNAL,),
        boundary_role="internal_lifecycle_state",
        notes="Local lifecycle state; control-plane should prefer lifecycle results instead.",
    ),
    "federation_summary": BoundaryDescriptor(
        object_kind="federation_summary",
        surfaces=(BoundarySurface.CONTROL_PLANE, BoundarySurface.P2P_MESH),
        boundary_role="summary",
        notes="Portable summary suitable for truth-source ingestion and mesh sharing.",
    ),
    "federation_event": BoundaryDescriptor(
        object_kind="federation_event",
        surfaces=(BoundarySurface.CONTROL_PLANE, BoundarySurface.P2P_MESH),
        boundary_role="event",
        notes="Bounded event payload suitable for control-plane audit or optional propagation.",
    ),
    "remote_execution_admission_bridge": BoundaryDescriptor(
        object_kind="remote_execution_admission_bridge",
        surfaces=(BoundarySurface.CONTROL_PLANE, BoundarySurface.P2P_MESH),
        boundary_role="receipt",
        notes="Receipt-style remote execution bridge; safe boundary between Atom output and Chronara admission.",
    ),
    "federation_exchange_gate": BoundaryDescriptor(
        object_kind="federation_exchange_gate",
        surfaces=(BoundarySurface.CONTROL_PLANE, BoundarySurface.P2P_MESH),
        boundary_role="compatibility_hint",
        notes="Gate object is useful to the control plane directly and as a mesh compatibility hint when compacted.",
    ),
    "triage_result": BoundaryDescriptor(
        object_kind="triage_result",
        surfaces=(BoundarySurface.CONTROL_PLANE, BoundarySurface.P2P_MESH),
        boundary_role="readiness_hint",
        notes="Full triage result is control-plane material; readiness projection is mesh-sized.",
    ),
    "lifecycle_result": BoundaryDescriptor(
        object_kind="lifecycle_result",
        surfaces=(BoundarySurface.CONTROL_PLANE,),
        boundary_role="lifecycle_record",
        notes="Control-plane candidate for policy and retention decisions; not useful as a mesh payload.",
    ),
    "conflict_resolution_result": BoundaryDescriptor(
        object_kind="conflict_resolution_result",
        surfaces=(BoundarySurface.CONTROL_PLANE,),
        boundary_role="conflict_record",
        notes="Conflict resolution belongs to centralized policy / admission truth.",
    ),
    "promotion_execution_result": BoundaryDescriptor(
        object_kind="promotion_execution_result",
        surfaces=(BoundarySurface.CONTROL_PLANE,),
        boundary_role="execution_record",
        notes="Execution outcomes are control-plane records, not mesh gossip.",
    ),
    "coordination_result": BoundaryDescriptor(
        object_kind="coordination_result",
        surfaces=(BoundarySurface.CONTROL_PLANE,),
        boundary_role="admission_record",
        notes="Final orchestration record for control-plane truth and audit.",
    ),
}


def get_boundary_descriptor(object_kind: str) -> BoundaryDescriptor:
    """Return descriptor for an object kind."""
    return BOUNDARY_REGISTRY[object_kind]


def list_boundary_object_kinds(surface: BoundarySurface) -> List[str]:
    """List object kinds that belong to a given surface."""
    return [
        kind
        for kind, descriptor in BOUNDARY_REGISTRY.items()
        if surface in descriptor.surfaces
    ]


def build_compatibility_hint(gate: FederationExchangeGate) -> Dict[str, object]:
    """Project a full exchange gate into a compact external hint."""
    return {
        "remote_adapter_id": gate.remote_adapter_id,
        "remote_generation": gate.remote_generation,
        "status": gate.status.value,
        "recommendation": gate.recommendation,
        "reason": gate.reason,
        "lineage_compatible": gate.lineage.compatible,
        "specialization_compatible": gate.specialization.compatible,
        "validation_acceptable": gate.validation.acceptable,
        "comparison_acceptable": gate.comparison.acceptable,
        "fallback_used": gate.fallback_used,
        "version": gate.version,
        "timestamp": gate.timestamp,
    }


def build_readiness_hint(result: TriageResult) -> Dict[str, object]:
    """Project a full triage result into a compact external hint."""
    return {
        "adapter_id": result.assessment.adapter_id,
        "generation": result.assessment.generation,
        "source_node": result.assessment.source_node,
        "status": result.assessment.triage_status.value,
        "readiness_score": result.assessment.readiness.readiness_score,
        "target_pool": result.target_pool,
        "priority": result.priority,
        "can_promote_later": result.assessment.can_promote_later,
        "needs_review": result.assessment.needs_review,
        "fallback_used": result.fallback_used,
        "trace_id": result.trace_id,
    }
