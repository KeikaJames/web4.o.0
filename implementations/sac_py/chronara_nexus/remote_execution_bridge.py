"""Phase 21: Remote execution admission bridge.

Converts remote Atom execution receipts into Chronara-compatible admission input
without mutating stable/shared/candidate state directly.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from .types import (
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


BRIDGE_KIND = "remote_execution_admission_bridge"
BRIDGE_VERSION = "1.0"


class BridgeDecision(Enum):
    """Phase 21: Remote execution bridge routing decision."""

    BRIDGE_ACCEPT = "bridge_accept"
    BRIDGE_HOLD = "bridge_hold"
    BRIDGE_REJECT = "bridge_reject"


@dataclass(frozen=True)
class RemoteExecutionIdentity:
    execution_id: str
    execution_kind: str
    source_node_id: str
    source_tag: str
    home_node_id: str


@dataclass(frozen=True)
class RemoteExecutionStageSummary:
    stage: str
    tokens_produced: int
    kv_absorbed: int
    kv_migrated: bool
    receipt: Optional[Dict[str, Any]]
    prefill_receipt: Optional[Dict[str, Any]]
    decode_receipt: Optional[Dict[str, Any]]


@dataclass(frozen=True)
class BridgeValidationSummary:
    receipt_verified: bool
    handoff_verified: bool
    output_match: bool
    lineage_complete: bool
    lineage_consistent: bool
    specialization_attached: bool
    remote_execution_acceptable: bool


@dataclass(frozen=True)
class AdapterLineageSummary:
    adapter_id: Optional[str]
    adapter_generation: Optional[int]
    specialization: Optional[str]


@dataclass(frozen=True)
class RemoteExecutionAdmissionBridge:
    bridge_kind: str
    identity: RemoteExecutionIdentity
    stage_summary: RemoteExecutionStageSummary
    validation_summary: BridgeValidationSummary
    adapter_lineage: AdapterLineageSummary
    remote_execution_acceptable: bool
    bridge_decision: BridgeDecision
    recommendation: str
    reason: str
    fallback_used: bool
    version: str
    timestamp: str

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RemoteExecutionAdmissionBridge":
        identity_data = data.get("identity", {})
        stage_data = data.get("stage_summary", {})
        validation_data = data.get("validation_summary", {})
        lineage_data = data.get("adapter_lineage", {})
        decision_raw = data.get("bridge_decision", BridgeDecision.BRIDGE_REJECT.value)
        decision = (
            BridgeDecision(decision_raw)
            if decision_raw in {item.value for item in BridgeDecision}
            else BridgeDecision.BRIDGE_REJECT
        )
        return cls(
            bridge_kind=data.get("bridge_kind", ""),
            identity=RemoteExecutionIdentity(
                execution_id=identity_data.get("execution_id", ""),
                execution_kind=identity_data.get("execution_kind", ""),
                source_node_id=identity_data.get("source_node_id", ""),
                source_tag=identity_data.get("source_tag", ""),
                home_node_id=identity_data.get("home_node_id", ""),
            ),
            stage_summary=RemoteExecutionStageSummary(
                stage=stage_data.get("stage", ""),
                tokens_produced=stage_data.get("tokens_produced", 0),
                kv_absorbed=stage_data.get("kv_absorbed", 0),
                kv_migrated=stage_data.get("kv_migrated", False),
                receipt=stage_data.get("receipt"),
                prefill_receipt=stage_data.get("prefill_receipt"),
                decode_receipt=stage_data.get("decode_receipt"),
            ),
            validation_summary=BridgeValidationSummary(
                receipt_verified=validation_data.get("receipt_verified", False),
                handoff_verified=validation_data.get("handoff_verified", False),
                output_match=validation_data.get("output_match", False),
                lineage_complete=validation_data.get("lineage_complete", False),
                lineage_consistent=validation_data.get("lineage_consistent", False),
                specialization_attached=validation_data.get("specialization_attached", False),
                remote_execution_acceptable=validation_data.get("remote_execution_acceptable", False),
            ),
            adapter_lineage=AdapterLineageSummary(
                adapter_id=lineage_data.get("adapter_id"),
                adapter_generation=lineage_data.get("adapter_generation"),
                specialization=lineage_data.get("specialization"),
            ),
            remote_execution_acceptable=data.get("remote_execution_acceptable", False),
            bridge_decision=decision,
            recommendation=data.get("recommendation", ""),
            reason=data.get("reason", ""),
            fallback_used=data.get("fallback_used", False),
            version=data.get("version", BRIDGE_VERSION),
            timestamp=data.get("timestamp", "1970-01-01T00:00:00Z"),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "bridge_kind": self.bridge_kind,
            "identity": {
                "execution_id": self.identity.execution_id,
                "execution_kind": self.identity.execution_kind,
                "source_node_id": self.identity.source_node_id,
                "source_tag": self.identity.source_tag,
                "home_node_id": self.identity.home_node_id,
            },
            "stage_summary": {
                "stage": self.stage_summary.stage,
                "tokens_produced": self.stage_summary.tokens_produced,
                "kv_absorbed": self.stage_summary.kv_absorbed,
                "kv_migrated": self.stage_summary.kv_migrated,
                "receipt": self.stage_summary.receipt,
                "prefill_receipt": self.stage_summary.prefill_receipt,
                "decode_receipt": self.stage_summary.decode_receipt,
            },
            "validation_summary": {
                "receipt_verified": self.validation_summary.receipt_verified,
                "handoff_verified": self.validation_summary.handoff_verified,
                "output_match": self.validation_summary.output_match,
                "lineage_complete": self.validation_summary.lineage_complete,
                "lineage_consistent": self.validation_summary.lineage_consistent,
                "specialization_attached": self.validation_summary.specialization_attached,
                "remote_execution_acceptable": self.validation_summary.remote_execution_acceptable,
            },
            "adapter_lineage": {
                "adapter_id": self.adapter_lineage.adapter_id,
                "adapter_generation": self.adapter_lineage.adapter_generation,
                "specialization": self.adapter_lineage.specialization,
            },
            "remote_execution_acceptable": self.remote_execution_acceptable,
            "bridge_decision": self.bridge_decision.value,
            "recommendation": self.recommendation,
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "version": self.version,
            "timestamp": self.timestamp,
        }

    def to_trace_summary(self) -> Dict[str, Any]:
        return {
            "execution_id": self.identity.execution_id,
            "execution_kind": self.identity.execution_kind,
            "source_node_id": self.identity.source_node_id,
            "source_tag": self.identity.source_tag,
            "bridge_decision": self.bridge_decision.value,
            "remote_execution_acceptable": self.remote_execution_acceptable,
            "adapter_id": self.adapter_lineage.adapter_id,
            "adapter_generation": self.adapter_lineage.adapter_generation,
            "specialization": self.adapter_lineage.specialization,
            "recommendation": self.recommendation,
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "version": self.version,
            "timestamp": self.timestamp,
        }

    def to_federation_summary(
        self,
        local_summary: FederationSummary,
        source_node: Optional[str] = None,
    ) -> FederationSummary:
        if not self.adapter_lineage.adapter_id or self.adapter_lineage.adapter_generation is None:
            raise ValueError("bridge_missing_adapter_lineage")
        if not self.adapter_lineage.specialization:
            raise ValueError("bridge_missing_specialization")
        if not self.remote_execution_acceptable:
            raise ValueError("bridge_not_acceptable")

        local_generation = local_summary.identity.generation
        if self.bridge_decision == BridgeDecision.BRIDGE_ACCEPT:
            generation = max(self.adapter_lineage.adapter_generation, local_generation + 1)
            validation_score = 0.95
            quality_score = 0.9
            confidence = 0.85
            recommendation = "approve"
        elif self.bridge_decision == BridgeDecision.BRIDGE_HOLD:
            generation = max(self.adapter_lineage.adapter_generation, local_generation + 2)
            validation_score = 0.55
            quality_score = 0.6
            confidence = 0.6
            recommendation = "hold"
        else:
            raise ValueError("bridge_reject_cannot_enter_summary_path")

        adapter_id = self.adapter_lineage.adapter_id
        specialization = self.adapter_lineage.specialization
        parent_generation = generation - 1 if generation > 0 else None
        snapshot_id = f"{adapter_id}-gen{generation}"
        lineage_hash = f"{adapter_id}:{generation}:{specialization}:{self.identity.execution_id}"

        return FederationSummary(
            identity=AdapterIdentitySummary(
                adapter_id=adapter_id,
                generation=generation,
                parent_generation=parent_generation,
                specialization=specialization,
                mode="serve",
            ),
            specialization=SpecializationSummary(
                stable_generation=generation,
                shared_generation=None,
                candidate_generation=None,
                active_specialization=specialization,
            ),
            importance_mask=ImportanceMaskSummary(
                top_keys=["remote_execution", "lineage"],
                scores={"remote_execution": 0.9, "lineage": 0.7},
                threshold=0.7,
                compression_ratio=0.2,
            ),
            delta_norm=DeltaNormSummary(
                l1_norm=float(self.stage_summary.tokens_produced),
                l2_norm=float(self.stage_summary.kv_absorbed),
                max_abs=1.0 if self.stage_summary.kv_absorbed else 0.5,
                param_count=max(1, self.stage_summary.tokens_produced),
                relative_to_parent=0.1 if self.bridge_decision == BridgeDecision.BRIDGE_ACCEPT else 0.05,
            ),
            validation_score=ValidationScoreSummary(
                passed=True,
                lineage_valid=self.validation_summary.lineage_complete and self.validation_summary.lineage_consistent,
                specialization_valid=self.validation_summary.specialization_attached,
                output_match=self.validation_summary.output_match,
                kv_count_match=self.validation_summary.handoff_verified or not self.stage_summary.kv_migrated,
                generation_advanced=generation > local_generation,
                score=validation_score,
            ),
            comparison_outcome=ComparisonOutcomeSummary(
                status="candidate_observed",
                promote_recommendation=recommendation,
                lineage_valid=self.validation_summary.lineage_complete,
                specialization_valid=self.validation_summary.specialization_attached,
                is_acceptable=True,
            ),
            deliberation=DeliberationSummary(
                outcome="candidate_ready" if self.bridge_decision == BridgeDecision.BRIDGE_ACCEPT else "candidate_observed",
                quality_score=quality_score,
                confidence=confidence,
                consensus_status=None,
                has_disagreement=self.bridge_decision == BridgeDecision.BRIDGE_HOLD,
                escalation_used=self.bridge_decision == BridgeDecision.BRIDGE_HOLD,
            ),
            snapshot_lineage=SnapshotLineageSummary(
                snapshot_id=snapshot_id,
                adapter_id=adapter_id,
                generation=generation,
                specialization=specialization,
                parent_snapshot_id=f"{adapter_id}-gen{parent_generation}" if parent_generation else None,
                lineage_hash=lineage_hash,
            ),
            compatibility=CompatibilityHints(
                min_compatible_generation=max(0, generation - 2),
                max_compatible_generation=generation + 1,
                required_specialization=None,
                min_validation_score=0.5,
                requires_consensus_accept=False,
                format_version=BRIDGE_VERSION,
            ),
            export_timestamp=self.timestamp,
            export_version=self.version,
            source_node=source_node or self.identity.source_node_id,
        )


@dataclass(frozen=True)
class PreparedRemoteInput:
    normalized_summary_dict: Optional[Dict[str, Any]]
    bridge: Optional[RemoteExecutionAdmissionBridge]
    bridge_summary: Optional[Dict[str, Any]]
    bridge_decision: Optional[BridgeDecision]
    source_node: Optional[str]
    adapter_id: str
    generation: int
    reject_reason: Optional[str] = None


def is_remote_execution_bridge_payload(data: Dict[str, Any]) -> bool:
    return isinstance(data, dict) and data.get("bridge_kind") == BRIDGE_KIND


def prepare_remote_execution_input(
    remote_payload: Dict[str, Any],
    local_summary: FederationSummary,
    source_node: Optional[str] = None,
) -> PreparedRemoteInput:
    if not is_remote_execution_bridge_payload(remote_payload):
        identity = remote_payload.get("identity", {}) if isinstance(remote_payload, dict) else {}
        return PreparedRemoteInput(
            normalized_summary_dict=remote_payload,
            bridge=None,
            bridge_summary=None,
            bridge_decision=None,
            source_node=source_node,
            adapter_id=identity.get("adapter_id", "unknown"),
            generation=identity.get("generation", 0),
        )

    bridge = RemoteExecutionAdmissionBridge.from_dict(remote_payload)
    bridge_summary = bridge.to_trace_summary()
    effective_source = source_node or bridge.identity.source_node_id
    adapter_id = bridge.adapter_lineage.adapter_id or "unknown"
    generation = bridge.adapter_lineage.adapter_generation or 0

    if bridge.bridge_decision == BridgeDecision.BRIDGE_REJECT:
        return PreparedRemoteInput(
            normalized_summary_dict=None,
            bridge=bridge,
            bridge_summary=bridge_summary,
            bridge_decision=bridge.bridge_decision,
            source_node=effective_source,
            adapter_id=adapter_id,
            generation=generation,
            reject_reason=f"bridge_rejected:{bridge.reason}",
        )

    summary = bridge.to_federation_summary(local_summary, effective_source)
    return PreparedRemoteInput(
        normalized_summary_dict=summary.to_dict(),
        bridge=bridge,
        bridge_summary=bridge_summary,
        bridge_decision=bridge.bridge_decision,
        source_node=effective_source,
        adapter_id=summary.identity.adapter_id,
        generation=summary.identity.generation,
    )
