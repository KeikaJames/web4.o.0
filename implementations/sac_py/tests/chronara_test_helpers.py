"""Shared helpers for Chronara phase-level tests."""

from typing import Optional, Dict, List

from implementations.sac_py.chronara_nexus.common import utc_now
from implementations.sac_py.chronara_nexus.remote_execution_bridge import BRIDGE_KIND, BridgeDecision
from implementations.sac_py.chronara_nexus.types import (
    AdapterIdentitySummary,
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


def create_federation_summary(
    adapter_id: str = "test-adapter",
    generation: int = 5,
    *,
    source_node: str = "test-node",
    parent_generation: Optional[int] = None,
    specialization: str = "stable",
    mode: str = "serve",
    top_keys: Optional[List[str]] = None,
    scores: Optional[Dict[str, float]] = None,
    threshold: float = 0.5,
    compression_ratio: float = 0.2,
    l1_norm: float = 1.0,
    l2_norm: float = 0.5,
    max_abs: float = 0.3,
    param_count: int = 100,
    relative_to_parent: Optional[float] = 0.1,
    validation_passed: bool = True,
    validation_score: float = 0.95,
    lineage_valid: bool = True,
    specialization_valid: bool = True,
    output_match: bool = True,
    kv_count_match: bool = True,
    generation_advanced: bool = True,
    comparison_status: str = "candidate_observed",
    comparison_recommendation: str = "approve",
    comparison_acceptable: bool = True,
    deliberation_outcome: str = "candidate_ready",
    quality_score: float = 0.9,
    confidence: float = 0.85,
    consensus_status: Optional[str] = "consensus_accept",
    has_disagreement: Optional[bool] = False,
    escalation_used: bool = False,
    lineage_hash: Optional[str] = None,
    min_compatible_generation: Optional[int] = None,
    max_compatible_generation: Optional[int] = None,
    min_validation_score: float = 0.7,
) -> FederationSummary:
    now = utc_now()
    resolved_parent_generation = (
        parent_generation if parent_generation is not None else generation - 1 if generation > 1 else None
    )
    resolved_top_keys = top_keys if top_keys is not None else ["param1", "param2"]
    resolved_scores = scores if scores is not None else {"param1": 0.9, "param2": 0.8}
    resolved_lineage_hash = lineage_hash or f"{adapter_id}:{generation}"

    return FederationSummary(
        identity=AdapterIdentitySummary(
            adapter_id=adapter_id,
            generation=generation,
            parent_generation=resolved_parent_generation,
            specialization=specialization,
            mode=mode,
        ),
        specialization=SpecializationSummary(
            stable_generation=generation,
            shared_generation=None,
            candidate_generation=None,
            active_specialization=specialization,
        ),
        importance_mask=ImportanceMaskSummary(
            top_keys=resolved_top_keys,
            scores=resolved_scores,
            threshold=threshold,
            compression_ratio=compression_ratio,
        ),
        delta_norm=DeltaNormSummary(
            l1_norm=l1_norm,
            l2_norm=l2_norm,
            max_abs=max_abs,
            param_count=param_count,
            relative_to_parent=relative_to_parent,
        ),
        validation_score=ValidationScoreSummary(
            passed=validation_passed,
            lineage_valid=lineage_valid,
            specialization_valid=specialization_valid,
            output_match=output_match,
            kv_count_match=kv_count_match,
            generation_advanced=generation_advanced,
            score=validation_score,
        ),
        comparison_outcome=ComparisonOutcomeSummary(
            status=comparison_status,
            promote_recommendation=comparison_recommendation,
            lineage_valid=lineage_valid,
            specialization_valid=specialization_valid,
            is_acceptable=comparison_acceptable,
        ),
        deliberation=DeliberationSummary(
            outcome=deliberation_outcome,
            quality_score=quality_score,
            confidence=confidence,
            consensus_status=consensus_status,
            has_disagreement=has_disagreement,
            escalation_used=escalation_used,
        ),
        snapshot_lineage=SnapshotLineageSummary(
            snapshot_id=f"{adapter_id}-gen{generation}",
            adapter_id=adapter_id,
            generation=generation,
            specialization=specialization,
            parent_snapshot_id=(
                f"{adapter_id}-gen{resolved_parent_generation}"
                if resolved_parent_generation is not None
                else None
            ),
            lineage_hash=resolved_lineage_hash,
        ),
        compatibility=CompatibilityHints(
            min_compatible_generation=(
                min_compatible_generation
                if min_compatible_generation is not None
                else max(0, generation - 2)
            ),
            max_compatible_generation=(
                max_compatible_generation
                if max_compatible_generation is not None
                else generation + 1
            ),
            required_specialization=None,
            min_validation_score=min_validation_score,
            requires_consensus_accept=False,
            format_version="1.0",
        ),
        export_timestamp=now,
        export_version="1.0",
        source_node=source_node,
    )


def create_bridge_payload(
    *,
    decision: str = BridgeDecision.BRIDGE_ACCEPT.value,
    adapter_id: str = "bridge-adapter",
    generation: int = 2,
    specialization: str = "stable",
    source_node: str = "remote-node",
) -> dict:
    acceptable = decision != BridgeDecision.BRIDGE_REJECT.value
    kv_migrated = decision == BridgeDecision.BRIDGE_HOLD.value
    return {
        "bridge_kind": BRIDGE_KIND,
        "identity": {
            "execution_id": f"exec-{decision}",
            "execution_kind": "two_stage_remote_execution",
            "source_node_id": source_node,
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
