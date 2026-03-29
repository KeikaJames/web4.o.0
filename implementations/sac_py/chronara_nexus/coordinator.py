"""Phase 20: Federation / Exchange Execution Coordinator.

Unified execution coordinator that orchestrates the pre-federation pipeline:
intake → staging → triage/readiness → lifecycle → conflict resolution →
promotion execution → event emission → exchange skeleton

Provides structured coordination with per-stage status, failure-safe
short-circuit, and deterministic execution trace.

Safe to call during serve path - never blocks or raises.
"""

import uuid
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass
from .common import utc_now


class CoordinationDecision(Enum):
    """Phase 20: Final coordination decision.

    - COORDINATED_READY: All stages passed, candidate ready for federation
    - COORDINATED_HOLD: Hold for further observation
    - COORDINATED_REJECT: Reject candidate
    - COORDINATED_ROLLBACK: Rollback previously coordinated candidate
    """
    COORDINATED_READY = "coordinated_ready"
    COORDINATED_HOLD = "coordinated_hold"
    COORDINATED_REJECT = "coordinated_reject"
    COORDINATED_ROLLBACK = "coordinated_rollback"


class StageStatus(Enum):
    """Phase 20: Status of a coordination stage."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    REJECTED = "rejected"
    HELD = "held"
    ROLLBACK = "rollback"


@dataclass
class StageResult:
    """Phase 20: Result of a single coordination stage."""
    stage_name: str
    status: StageStatus
    success: bool
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    fallback_used: bool = False
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage_name,
            "status": self.status.value,
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "fallback_used": self.fallback_used,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "StageResult":
        status_str = data.get("status", "pending")
        status = StageStatus(status_str) if status_str in [s.value for s in StageStatus] else StageStatus.PENDING
        return cls(
            stage_name=data.get("stage", ""),
            status=status,
            success=data.get("success", False),
            output=data.get("output"),
            error=data.get("error"),
            fallback_used=data.get("fallback_used", False),
            timestamp=data.get("timestamp", ""),
        )


@dataclass
class CoordinationTrace:
    """Phase 20: Execution trace for coordination."""
    trace_id: str
    stages: List[StageResult]
    started_at: str
    completed_at: Optional[str] = None
    short_circuit_at: Optional[str] = None
    short_circuit_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "stages": [s.to_dict() for s in self.stages],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "short_circuit_at": self.short_circuit_at,
            "short_circuit_reason": self.short_circuit_reason,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoordinationTrace":
        stages_data = data.get("stages", [])
        stages = [StageResult.from_dict(s) for s in stages_data]
        return cls(
            trace_id=data.get("trace_id", ""),
            stages=stages,
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at"),
            short_circuit_at=data.get("short_circuit_at"),
            short_circuit_reason=data.get("short_circuit_reason"),
        )


@dataclass
class CoordinationResult:
    """Phase 20: Result of federation coordination.

    Structured result containing:
    - Source candidate identity
    - Per-stage status
    - Final coordination decision
    - Stage results summary
    - Reason / recommendation
    - Fallback tracking
    - Timestamp / version
    """
    # Identity
    coordination_id: str
    adapter_id: str
    generation: int
    source_node: Optional[str]

    # Final decision
    decision: CoordinationDecision
    is_ready: bool

    # Per-stage status
    intake_status: StageStatus
    triage_status: StageStatus
    lifecycle_status: StageStatus
    conflict_status: StageStatus
    execution_status: StageStatus
    event_status: StageStatus
    exchange_status: StageStatus

    # Stage results (structured summaries, not full objects)
    intake_summary: Optional[Dict[str, Any]] = None
    triage_summary: Optional[Dict[str, Any]] = None
    lifecycle_summary: Optional[Dict[str, Any]] = None
    conflict_summary: Optional[Dict[str, Any]] = None
    execution_summary: Optional[Dict[str, Any]] = None
    event_summary: Optional[Dict[str, Any]] = None
    exchange_summary: Optional[Dict[str, Any]] = None

    # Reasoning
    reason: str = ""
    recommendation: str = ""

    # Execution trace
    trace: Optional[CoordinationTrace] = None

    # Fallback tracking
    fallback_used: bool = False
    any_stage_fallback: bool = False

    # Metadata
    version: str = "1.0"
    coordinated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {
                "coordination_id": self.coordination_id,
                "adapter_id": self.adapter_id,
                "generation": self.generation,
                "source_node": self.source_node,
            },
            "decision": {
                "decision": self.decision.value,
                "is_ready": self.is_ready,
            },
            "stage_status": {
                "intake": self.intake_status.value,
                "triage": self.triage_status.value,
                "lifecycle": self.lifecycle_status.value,
                "conflict": self.conflict_status.value,
                "execution": self.execution_status.value,
                "event": self.event_status.value,
                "exchange": self.exchange_status.value,
            },
            "summaries": {
                "intake": self.intake_summary,
                "triage": self.triage_summary,
                "lifecycle": self.lifecycle_summary,
                "conflict": self.conflict_summary,
                "execution": self.execution_summary,
                "event": self.event_summary,
                "exchange": self.exchange_summary,
            },
            "reasoning": {
                "reason": self.reason,
                "recommendation": self.recommendation,
            },
            "trace": self.trace.to_dict() if self.trace else None,
            "fallback": {
                "coordination_fallback_used": self.fallback_used,
                "any_stage_fallback": self.any_stage_fallback,
            },
            "meta": {
                "version": self.version,
                "coordinated_at": self.coordinated_at,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoordinationResult":
        identity = data.get("identity", {})
        decision = data.get("decision", {})
        stage_status = data.get("stage_status", {})
        summaries = data.get("summaries", {})
        reasoning = data.get("reasoning", {})
        fallback = data.get("fallback", {})
        meta = data.get("meta", {})

        def parse_status(s: str) -> StageStatus:
            return StageStatus(s) if s in [st.value for st in StageStatus] else StageStatus.PENDING

        decision_str = decision.get("decision", "coordinated_reject")
        dec = CoordinationDecision(decision_str) if decision_str in [d.value for d in CoordinationDecision] else CoordinationDecision.COORDINATED_REJECT

        trace_data = data.get("trace")
        trace = CoordinationTrace.from_dict(trace_data) if trace_data else None

        return cls(
            coordination_id=identity.get("coordination_id", ""),
            adapter_id=identity.get("adapter_id", ""),
            generation=identity.get("generation", 0),
            source_node=identity.get("source_node"),
            decision=dec,
            is_ready=decision.get("is_ready", False),
            intake_status=parse_status(stage_status.get("intake", "pending")),
            triage_status=parse_status(stage_status.get("triage", "pending")),
            lifecycle_status=parse_status(stage_status.get("lifecycle", "pending")),
            conflict_status=parse_status(stage_status.get("conflict", "pending")),
            execution_status=parse_status(stage_status.get("execution", "pending")),
            event_status=parse_status(stage_status.get("event", "pending")),
            exchange_status=parse_status(stage_status.get("exchange", "pending")),
            intake_summary=summaries.get("intake"),
            triage_summary=summaries.get("triage"),
            lifecycle_summary=summaries.get("lifecycle"),
            conflict_summary=summaries.get("conflict"),
            execution_summary=summaries.get("execution"),
            event_summary=summaries.get("event"),
            exchange_summary=summaries.get("exchange"),
            reason=reasoning.get("reason", ""),
            recommendation=reasoning.get("recommendation", ""),
            trace=trace,
            fallback_used=fallback.get("coordination_fallback_used", False),
            any_stage_fallback=fallback.get("any_stage_fallback", False),
            version=meta.get("version", "1.0"),
            coordinated_at=meta.get("coordinated_at", ""),
        )

    def is_successful(self) -> bool:
        """Check if coordination was successful (ready)."""
        return self.decision == CoordinationDecision.COORDINATED_READY and self.is_ready

    def should_short_circuit(self) -> bool:
        """Check if coordination should short-circuit (reject/hold/rollback)."""
        return self.decision in (
            CoordinationDecision.COORDINATED_REJECT,
            CoordinationDecision.COORDINATED_ROLLBACK,
        )

    def get_final_stage(self) -> str:
        """Get the last completed stage name."""
        if self.trace and self.trace.stages:
            for stage in reversed(self.trace.stages):
                if stage.status in (StageStatus.COMPLETED, StageStatus.FAILED, StageStatus.REJECTED, StageStatus.HELD):
                    return stage.stage_name
        return "none"


class FederationCoordinator:
    """Phase 20: Federation / Exchange Execution Coordinator.

    Orchestrates the pre-federation pipeline with structured coordination:
    - intake → staging → triage → lifecycle → conflict → execution → event → exchange
    - Per-stage status tracking
    - Failure-safe short-circuit
    - Deterministic execution trace
    - Governor integration

    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"

    def __init__(
        self,
        intake_processor=None,
        triage_engine=None,
        lifecycle_engine=None,
        conflict_resolver=None,
        promotion_executor=None,
        event_emitter=None,
        exchange_skeleton=None,
    ):
        self.intake_processor = intake_processor
        self.triage_engine = triage_engine
        self.lifecycle_engine = lifecycle_engine
        self.conflict_resolver = conflict_resolver
        self.promotion_executor = promotion_executor
        self.event_emitter = event_emitter
        self.exchange_skeleton = exchange_skeleton

    def coordinate(
        self,
        remote_summary_dict: Dict[str, Any],
        local_summary: Any,
        source_node: Optional[str] = None,
        existing_candidates: Optional[List[Dict[str, Any]]] = None,
        fallback_on_error: bool = True,
    ) -> CoordinationResult:
        """Execute full coordination pipeline for a remote summary.

        Phase 20: Main entry point for federation coordination.

        Args:
            remote_summary_dict: Remote summary as dictionary
            local_summary: Local federation summary for comparison
            source_node: Optional source node identifier
            existing_candidates: Optional list of existing candidates for conflict check
            fallback_on_error: Whether to return safe fallback on error

        Returns:
            CoordinationResult with full coordination information
        """
        try:
            return self._do_coordinate(
                remote_summary_dict,
                local_summary,
                source_node,
                existing_candidates or [],
            )
        except Exception as e:
            if fallback_on_error:
                return self._fallback_result(remote_summary_dict, source_node, str(e))
            raise

    def _do_coordinate(
        self,
        remote_summary_dict: Dict[str, Any],
        local_summary: Any,
        source_node: Optional[str],
        existing_candidates: List[Dict[str, Any]],
    ) -> CoordinationResult:
        """Internal coordination logic."""
        now = utc_now()
        coordination_id = f"coord-{str(uuid.uuid4())[:8]}"
        trace_id = str(uuid.uuid4())[:8]

        # Extract identity
        identity = remote_summary_dict.get("identity", {})
        adapter_id = identity.get("adapter_id", "unknown")
        generation = identity.get("generation", 0)

        # Initialize trace
        trace = CoordinationTrace(
            trace_id=trace_id,
            stages=[],
            started_at=now,
        )

        # Initialize result with defaults
        result = CoordinationResult(
            coordination_id=coordination_id,
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            decision=CoordinationDecision.COORDINATED_REJECT,
            is_ready=False,
            intake_status=StageStatus.PENDING,
            triage_status=StageStatus.PENDING,
            lifecycle_status=StageStatus.PENDING,
            conflict_status=StageStatus.PENDING,
            execution_status=StageStatus.PENDING,
            event_status=StageStatus.PENDING,
            exchange_status=StageStatus.PENDING,
            trace=trace,
            version=self.VERSION,
            coordinated_at=now,
        )

        any_fallback = False

        # Stage 1: Intake
        intake_result = self._run_intake(
            remote_summary_dict, local_summary, source_node, trace
        )
        any_fallback = any_fallback or intake_result.fallback_used
        result.intake_status = intake_result.status
        result.intake_summary = intake_result.output

        if intake_result.status == StageStatus.REJECTED:
            result.decision = CoordinationDecision.COORDINATED_REJECT
            result.reason = f"Intake rejected: {intake_result.error}"
            result.recommendation = "reject_at_intake"
            result.any_stage_fallback = any_fallback
            trace.completed_at = utc_now()
            trace.short_circuit_at = "intake"
            trace.short_circuit_reason = result.reason
            return result

        if intake_result.status == StageStatus.HELD:
            result.decision = CoordinationDecision.COORDINATED_HOLD
            result.reason = f"Intake held: {intake_result.error}"
            result.recommendation = "hold_at_intake"
            result.any_stage_fallback = any_fallback
            trace.completed_at = utc_now()
            trace.short_circuit_at = "intake"
            trace.short_circuit_reason = result.reason
            return result

        if intake_result.status == StageStatus.SKIPPED:
            result.decision = CoordinationDecision.COORDINATED_REJECT
            result.reason = "Intake skipped: no processor available"
            result.recommendation = "reject_no_intake_processor"
            result.any_stage_fallback = any_fallback
            result.intake_status = StageStatus.SKIPPED
            trace.completed_at = utc_now()
            trace.short_circuit_at = "intake"
            trace.short_circuit_reason = result.reason
            return result

        # Stage 2: Triage (if staged candidate exists)
        staged_candidate = intake_result.output.get("staged_candidate") if intake_result.output else None
        if staged_candidate:
            triage_result = self._run_triage(staged_candidate, local_summary, trace)
            any_fallback = any_fallback or triage_result.fallback_used
            result.triage_status = triage_result.status
            result.triage_summary = triage_result.output

            if triage_result.status == StageStatus.REJECTED:
                result.decision = CoordinationDecision.COORDINATED_REJECT
                result.reason = f"Triage rejected: {triage_result.error}"
                result.recommendation = "reject_at_triage"
                result.any_stage_fallback = any_fallback
                trace.completed_at = utc_now()
                trace.short_circuit_at = "triage"
                trace.short_circuit_reason = result.reason
                return result

            if triage_result.status == StageStatus.HELD:
                result.decision = CoordinationDecision.COORDINATED_HOLD
                result.reason = f"Triage held: {triage_result.error}"
                result.recommendation = "hold_at_triage"
                result.any_stage_fallback = any_fallback
                trace.completed_at = utc_now()
                trace.short_circuit_at = "triage"
                trace.short_circuit_reason = result.reason
                return result

            # Stage 3: Lifecycle
            lifecycle_result = self._run_lifecycle(
                triage_result.output, trace,
                adapter_id=adapter_id, generation=generation, source_node=source_node,
            )
            any_fallback = any_fallback or lifecycle_result.fallback_used
            result.lifecycle_status = lifecycle_result.status
            result.lifecycle_summary = lifecycle_result.output

            if lifecycle_result.status == StageStatus.REJECTED:
                result.decision = CoordinationDecision.COORDINATED_REJECT
                result.reason = f"Lifecycle rejected: {lifecycle_result.error}"
                result.recommendation = "reject_at_lifecycle"
                result.any_stage_fallback = any_fallback
                trace.completed_at = utc_now()
                trace.short_circuit_at = "lifecycle"
                trace.short_circuit_reason = result.reason
                return result

            # Stage 4: Conflict Resolution
            conflict_result = self._run_conflict(
                adapter_id, generation, source_node,
                existing_candidates, triage_result.output, lifecycle_result.output, trace
            )
            any_fallback = any_fallback or conflict_result.fallback_used
            result.conflict_status = conflict_result.status
            result.conflict_summary = conflict_result.output

            if conflict_result.status == StageStatus.REJECTED:
                result.decision = CoordinationDecision.COORDINATED_REJECT
                result.reason = f"Conflict resolution rejected: {conflict_result.error}"
                result.recommendation = "reject_at_conflict"
                result.any_stage_fallback = any_fallback
                trace.completed_at = utc_now()
                trace.short_circuit_at = "conflict"
                trace.short_circuit_reason = result.reason
                return result

            # Stage 5: Promotion Execution
            candidate_dict = {"adapter_id": adapter_id, "generation": generation, "source_node": source_node}
            execution_result = self._run_execution(
                candidate_dict,
                triage_result.output,
                lifecycle_result.output,
                conflict_result.output,
                trace
            )
            any_fallback = any_fallback or execution_result.fallback_used
            result.execution_status = execution_result.status
            result.execution_summary = execution_result.output

            if execution_result.status == StageStatus.REJECTED:
                result.decision = CoordinationDecision.COORDINATED_REJECT
                result.reason = f"Execution rejected: {execution_result.error}"
                result.recommendation = "reject_at_execution"
                result.any_stage_fallback = any_fallback
                trace.completed_at = utc_now()
                trace.short_circuit_at = "execution"
                trace.short_circuit_reason = result.reason
                return result

            if execution_result.status == StageStatus.HELD:
                hold_reason = (execution_result.output or {}).get("reason", execution_result.error or "deferred")
                result.decision = CoordinationDecision.COORDINATED_HOLD
                result.reason = f"Execution deferred: {hold_reason}"
                result.recommendation = "hold_at_execution"
                result.any_stage_fallback = any_fallback
                trace.completed_at = utc_now()
                trace.short_circuit_at = "execution"
                trace.short_circuit_reason = result.reason
                return result

            # Stage 6: Event Emission
            event_result = self._run_event_emission(
                adapter_id, generation, source_node,
                intake_result.output,
                triage_result.output,
                lifecycle_result.output,
                conflict_result.output,
                execution_result.output,
                trace
            )
            any_fallback = any_fallback or event_result.fallback_used
            result.event_status = event_result.status
            result.event_summary = event_result.output

            # Stage 7: Exchange Skeleton
            exchange_result = self._run_exchange_skeleton(
                candidate_dict,
                triage_result.output,
                lifecycle_result.output,
                conflict_result.output,
                execution_result.output,
                trace
            )
            any_fallback = any_fallback or exchange_result.fallback_used
            result.exchange_status = exchange_result.status
            result.exchange_summary = exchange_result.output

        # Final decision based on all stages
        result.any_stage_fallback = any_fallback
        trace.completed_at = utc_now()

        # Determine final decision
        if result.execution_status == StageStatus.COMPLETED:
            exec_success = result.execution_summary.get("success", False) if result.execution_summary else False
            if exec_success:
                result.decision = CoordinationDecision.COORDINATED_READY
                result.is_ready = True
                result.reason = "All coordination stages completed successfully"
                result.recommendation = "proceed_with_federation"
            else:
                result.decision = CoordinationDecision.COORDINATED_REJECT
                result.reason = "Execution did not succeed"
                result.recommendation = "reject_due_to_execution_failure"
        elif result.triage_status == StageStatus.COMPLETED:
            # Check if triage was ready
            triage_status_val = result.triage_summary.get("status") if result.triage_summary else None
            if triage_status_val == "ready":
                result.decision = CoordinationDecision.COORDINATED_HOLD
                result.reason = "Triage ready but execution incomplete"
                result.recommendation = "hold_for_execution"
            else:
                result.decision = CoordinationDecision.COORDINATED_REJECT
                result.reason = "Triage did not reach ready state"
                result.recommendation = "reject_due_to_triage"
        else:
            result.decision = CoordinationDecision.COORDINATED_REJECT
            result.reason = "Coordination incomplete"
            result.recommendation = "reject_incomplete"

        return result

    def _run_intake(
        self,
        remote_summary_dict: Dict[str, Any],
        local_summary: Any,
        source_node: Optional[str],
        trace: CoordinationTrace,
    ) -> StageResult:
        """Run intake stage."""
        now = utc_now()

        if self.intake_processor is None:
            # No processor available - skip with warning
            result = StageResult(
                stage_name="intake",
                status=StageStatus.SKIPPED,
                success=True,
                output={"skipped": True, "reason": "no_processor"},
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        try:
            from .intake_processor import RemoteIntakeProcessor
            intake_result = RemoteIntakeProcessor.process_intake(
                remote_summary_dict=remote_summary_dict,
                local_summary=local_summary,
                source_node=source_node,
            )

            # Determine status based on decision
            decision = intake_result.decision.value if intake_result.decision else "stage_reject"
            if decision == "stage_accept":
                status = StageStatus.COMPLETED
            elif decision == "stage_downgrade":
                status = StageStatus.COMPLETED  # Downgrade is still completed
            elif decision == "stage_reject":
                status = StageStatus.REJECTED
            else:
                status = StageStatus.FAILED

            output = {
                "decision": decision,
                "staged_candidate": intake_result.staged_candidate.to_dict() if intake_result.staged_candidate else None,
                "recommendation": intake_result.recommendation,
            }

            result = StageResult(
                stage_name="intake",
                status=status,
                success=status == StageStatus.COMPLETED,
                output=output,
                fallback_used=intake_result.fallback_used,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        except Exception as e:
            result = StageResult(
                stage_name="intake",
                status=StageStatus.FAILED,
                success=False,
                error=str(e),
                fallback_used=True,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

    def _run_triage(
        self,
        staged_candidate: Dict[str, Any],
        local_summary: Any,
        trace: CoordinationTrace,
    ) -> StageResult:
        """Run triage stage."""
        now = utc_now()

        if self.triage_engine is None:
            from .triage_engine import RemoteTriageEngine
            triage_engine = RemoteTriageEngine
        else:
            triage_engine = self.triage_engine

        try:
            from .types import StagedRemoteCandidate
            # Parse staged candidate
            if isinstance(staged_candidate, dict):
                # Convert dict to StagedRemoteCandidate
                from .types import FederationSummary, FederationExchangeGate, StagingDecision
                summary_dict = staged_candidate.get("summary", {})
                summary = FederationSummary.from_dict(summary_dict) if summary_dict else None

                gate_dict = staged_candidate.get("gate_result", {})
                gate = FederationExchangeGate.from_dict(gate_dict) if gate_dict else None

                decision_str = staged_candidate.get("staging_decision", "stage_reject")
                decision = StagingDecision(decision_str) if decision_str in [d.value for d in StagingDecision] else StagingDecision.STAGE_REJECT

                candidate = StagedRemoteCandidate(
                    adapter_id=staged_candidate.get("adapter_id", ""),
                    generation=staged_candidate.get("generation", 0),
                    source_node=staged_candidate.get("source_node"),
                    staged_at=staged_candidate.get("staged_at", now),
                    staging_decision=decision,
                    staging_version=staged_candidate.get("staging_version", "1.0"),
                    summary=summary,
                    gate_result=gate,
                    is_active=staged_candidate.get("is_active", False),
                    is_downgraded=staged_candidate.get("is_downgraded", False),
                    intake_record_ref=staged_candidate.get("intake_record_ref", ""),
                )
            else:
                candidate = staged_candidate

            triage_result = triage_engine.triage(
                staged_candidate=candidate,
                local_summary=local_summary,
                fallback_on_error=True,
            )

            # Determine status based on triage status
            status_val = triage_result.assessment.triage_status.value if triage_result.assessment else "reject"
            if status_val == "ready":
                status = StageStatus.COMPLETED
            elif status_val == "hold":
                status = StageStatus.HELD
            elif status_val == "downgrade":
                status = StageStatus.COMPLETED
            else:  # reject
                status = StageStatus.REJECTED

            output = {
                "status": status_val,
                "readiness_score": triage_result.assessment.readiness.readiness_score if triage_result.assessment else 0.0,
                "target_pool": triage_result.target_pool,
                "priority": triage_result.priority,
                "can_promote_later": triage_result.assessment.can_promote_later if triage_result.assessment else False,
            }

            result = StageResult(
                stage_name="triage",
                status=status,
                success=status in (StageStatus.COMPLETED, StageStatus.HELD),
                output=output,
                fallback_used=triage_result.fallback_used,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        except Exception as e:
            result = StageResult(
                stage_name="triage",
                status=StageStatus.FAILED,
                success=False,
                error=str(e),
                fallback_used=True,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

    def _run_lifecycle(
        self,
        triage_output: Optional[Dict[str, Any]],
        trace: CoordinationTrace,
        adapter_id: str = "unknown",
        generation: int = 0,
        source_node: Optional[str] = None,
    ) -> StageResult:
        """Run lifecycle stage."""
        now = utc_now()

        if self.lifecycle_engine is None:
            from .lifecycle_engine import TriagePoolLifecycle
            lifecycle_engine = TriagePoolLifecycle
        else:
            lifecycle_engine = self.lifecycle_engine

        try:
            from .types import TriageResult, TriageAssessment, ReadinessSummary, TriageStatus

            # Reconstruct minimal triage result from output
            status_str = triage_output.get("status", "reject") if triage_output else "reject"
            triage_status = TriageStatus(status_str) if status_str in [s.value for s in TriageStatus] else TriageStatus.REJECT

            readiness_score = triage_output.get("readiness_score", 0.0) if triage_output else 0.0

            # Create assessment with real identity from coordinator context
            assessment = TriageAssessment(
                adapter_id=adapter_id,
                generation=generation,
                source_node=source_node,
                triage_status=triage_status,
                triage_version="1.0",
                triaged_at=now,
                readiness=ReadinessSummary(
                    readiness_score=readiness_score,
                    lineage_score=0.0,
                    specialization_score=0.0,
                    validation_score=0.0,
                    comparison_score=0.0,
                    recency_score=0.0,
                    is_fresh=False,
                    is_compatible=False,
                    is_priority=False,
                    score_reason="coordinator_reconstruction",
                ),
                lineage_compatible=False,
                specialization_compatible=False,
                validation_acceptable=False,
                comparison_acceptable=False,
                recommendation="coordinator_reconstruction",
                reason="coordinator_reconstruction",
                can_promote_later=triage_status in (TriageStatus.READY, TriageStatus.HOLD),
                needs_review=triage_status == TriageStatus.HOLD,
                expiration_hint=None,
                original_staging_ref="",
            )

            triage_result = TriageResult(
                processed_at=now,
                processor_version="1.0",
                fallback_used=False,
                assessment=assessment,
                target_pool=triage_output.get("target_pool", "rejected") if triage_output else "rejected",
                priority=triage_output.get("priority", 0) if triage_output else 0,
                trace_id="coord-recon",
            )

            lifecycle_result = lifecycle_engine.evaluate(
                triage_result=triage_result,
                previous_meta=None,
                fallback_on_error=True,
            )

            # Determine status based on lifecycle state
            state = lifecycle_result.meta.state.value if lifecycle_result.meta else "expired"
            if state == "ready":
                status = StageStatus.COMPLETED
            elif state in ("staged", "hold"):
                status = StageStatus.COMPLETED
            elif state == "downgraded":
                status = StageStatus.COMPLETED
            elif state == "expired":
                status = StageStatus.REJECTED
            elif state == "evicted":
                status = StageStatus.REJECTED
            else:
                status = StageStatus.FAILED

            output = {
                "state": state,
                "ttl_remaining": lifecycle_result.meta.ttl_remaining if lifecycle_result.meta else 0.0,
                "freshness_score": lifecycle_result.meta.freshness_score if lifecycle_result.meta else 0.0,
                "priority_score": lifecycle_result.meta.priority_score if lifecycle_result.meta else 0,
                "can_promote": lifecycle_result.meta.can_promote() if lifecycle_result.meta else False,
            }

            result = StageResult(
                stage_name="lifecycle",
                status=status,
                success=status == StageStatus.COMPLETED or state in ("ready", "hold", "staged", "downgraded"),
                output=output,
                fallback_used=lifecycle_result.fallback_used,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        except Exception as e:
            result = StageResult(
                stage_name="lifecycle",
                status=StageStatus.FAILED,
                success=False,
                error=str(e),
                fallback_used=True,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

    def _run_conflict(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        existing_candidates: List[Dict[str, Any]],
        triage_output: Optional[Dict[str, Any]],
        lifecycle_output: Optional[Dict[str, Any]],
        trace: CoordinationTrace,
    ) -> StageResult:
        """Run conflict resolution stage."""
        now = utc_now()

        if self.conflict_resolver is None:
            from .conflict_resolution import RemoteCandidateConflictResolver
            conflict_resolver = RemoteCandidateConflictResolver
        else:
            conflict_resolver = self.conflict_resolver

        try:
            # Build candidate list as dicts (resolve() expects List[Dict[str, Any]])
            candidates = [
                {
                    "adapter_id": adapter_id,
                    "generation": generation,
                    "source_node": source_node,
                }
            ]

            for cand in existing_candidates:
                candidates.append({
                    "adapter_id": cand.get("adapter_id", ""),
                    "generation": cand.get("generation", 0),
                    "source_node": cand.get("source_node"),
                })

            conflict_result = conflict_resolver.resolve(
                candidates=candidates,
                fallback_on_error=True,
            )

            # Determine status based on resolution
            has_conflicts = conflict_result.conflict_set.has_conflicts if conflict_result.conflict_set else False
            can_proceed = conflict_result.conflict_set.can_proceed() if conflict_result.conflict_set else False

            if not has_conflicts:
                status = StageStatus.COMPLETED
            elif can_proceed:
                status = StageStatus.COMPLETED
            else:
                status = StageStatus.REJECTED

            output = {
                "has_conflicts": has_conflicts,
                "can_proceed": can_proceed,
                "resolution_decision": conflict_result.conflict_set.resolution_decision.value if conflict_result.conflict_set else "reject_all",
                "selected_candidate": conflict_result.conflict_set.selected_candidate.to_dict() if conflict_result.conflict_set and conflict_result.conflict_set.selected_candidate else None,
            }

            result = StageResult(
                stage_name="conflict",
                status=status,
                success=status == StageStatus.COMPLETED,
                output=output,
                fallback_used=conflict_result.fallback_used,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        except Exception as e:
            result = StageResult(
                stage_name="conflict",
                status=StageStatus.FAILED,
                success=False,
                error=str(e),
                fallback_used=True,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

    def _run_execution(
        self,
        candidate_dict: Dict[str, Any],
        triage_output: Optional[Dict[str, Any]],
        lifecycle_output: Optional[Dict[str, Any]],
        conflict_output: Optional[Dict[str, Any]],
        trace: CoordinationTrace,
    ) -> StageResult:
        """Run promotion execution stage."""
        now = utc_now()

        if self.promotion_executor is None:
            from .promotion_execution import FederationPromotionExecutor
            promotion_executor = FederationPromotionExecutor
        else:
            promotion_executor = self.promotion_executor

        try:
            # Build summaries for execution
            triage_summary = {
                "status": triage_output.get("status") if triage_output else "reject",
                "readiness_score": triage_output.get("readiness_score", 0.0) if triage_output else 0.0,
            } if triage_output else None

            lifecycle_summary = {
                "state": lifecycle_output.get("state") if lifecycle_output else "expired",
                "ttl_remaining": lifecycle_output.get("ttl_remaining", 0.0) if lifecycle_output else 0.0,
            } if lifecycle_output else None

            conflict_summary = {
                "has_conflicts": conflict_output.get("has_conflicts", False) if conflict_output else False,
                "can_proceed": conflict_output.get("can_proceed", False) if conflict_output else False,
            } if conflict_output else None

            execution_result = promotion_executor.execute(
                candidate_dict=candidate_dict,
                triage_summary=triage_summary,
                lifecycle_summary=lifecycle_summary,
                conflict_summary=conflict_summary,
                fallback_on_error=True,
            )

            # Determine status based on execution
            decision = execution_result.execution.decision.value if execution_result.execution else "reject"
            status_val = execution_result.execution.status.value if execution_result.execution else "rejected"

            if decision == "execute" and status_val == "completed":
                status = StageStatus.COMPLETED
            elif decision == "defer":
                status = StageStatus.HELD
            elif decision == "rollback":
                status = StageStatus.ROLLBACK
            elif decision == "reject":
                status = StageStatus.REJECTED
            else:
                status = StageStatus.FAILED

            output = {
                "success": execution_result.success,
                "decision": decision,
                "status": status_val,
                "execution_id": execution_result.execution.execution_id if execution_result.execution else None,
            }

            result = StageResult(
                stage_name="execution",
                status=status,
                success=status in (StageStatus.COMPLETED, StageStatus.HELD),
                output=output,
                fallback_used=execution_result.fallback_used,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        except Exception as e:
            result = StageResult(
                stage_name="execution",
                status=StageStatus.FAILED,
                success=False,
                error=str(e),
                fallback_used=True,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

    def _run_event_emission(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        intake_output: Optional[Dict[str, Any]],
        triage_output: Optional[Dict[str, Any]],
        lifecycle_output: Optional[Dict[str, Any]],
        conflict_output: Optional[Dict[str, Any]],
        execution_output: Optional[Dict[str, Any]],
        trace: CoordinationTrace,
    ) -> StageResult:
        """Run event emission stage."""
        now = utc_now()

        if self.event_emitter is None:
            # No emitter - skip
            result = StageResult(
                stage_name="event",
                status=StageStatus.SKIPPED,
                success=True,
                output={"skipped": True, "reason": "no_emitter"},
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        try:
            # Emit promotion event based on execution result
            exec_success = execution_output.get("success", False) if execution_output else False
            exec_decision = execution_output.get("decision", "reject") if execution_output else "reject"

            if exec_success:
                event = self.event_emitter.emit_promotion_executed(
                    adapter_id=adapter_id,
                    generation=generation,
                    source_node=source_node,
                    execution_result={"execution": execution_output, "success": True},
                )
            elif exec_decision == "defer":
                event = self.event_emitter.emit_promotion_deferred(
                    adapter_id=adapter_id,
                    generation=generation,
                    source_node=source_node,
                    execution_result={"execution": execution_output, "success": False},
                )
            else:
                event = self.event_emitter.emit_promotion_rejected(
                    adapter_id=adapter_id,
                    generation=generation,
                    source_node=source_node,
                    execution_result={"execution": execution_output, "success": False},
                )

            output = {
                "event_id": event.event_id if event else None,
                "event_type": event.event_type.value if event else None,
                "emitted": True,
            }

            result = StageResult(
                stage_name="event",
                status=StageStatus.COMPLETED,
                success=True,
                output=output,
                fallback_used=False,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        except Exception as e:
            result = StageResult(
                stage_name="event",
                status=StageStatus.FAILED,
                success=False,
                error=str(e),
                fallback_used=True,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

    def _run_exchange_skeleton(
        self,
        candidate_dict: Dict[str, Any],
        triage_output: Optional[Dict[str, Any]],
        lifecycle_output: Optional[Dict[str, Any]],
        conflict_output: Optional[Dict[str, Any]],
        execution_output: Optional[Dict[str, Any]],
        trace: CoordinationTrace,
    ) -> StageResult:
        """Run exchange skeleton stage."""
        now = utc_now()

        if self.exchange_skeleton is None:
            from .exchange_skeleton import ParameterMemoryExchangeSkeleton
            exchange_skeleton = ParameterMemoryExchangeSkeleton
        else:
            exchange_skeleton = self.exchange_skeleton

        try:
            # Create proposal
            proposal = exchange_skeleton.create_proposal(
                candidate_dict=candidate_dict,
                intent="share_delta",
                priority=triage_output.get("priority", 50) if triage_output else 50,
                fallback_on_error=True,
            )

            # Build summaries for readiness assessment
            triage_summary = {
                "status": triage_output.get("status") if triage_output else "reject",
                "readiness_score": triage_output.get("readiness_score", 0.0) if triage_output else 0.0,
            } if triage_output else None

            lifecycle_summary = {
                "state": lifecycle_output.get("state") if lifecycle_output else "expired",
                "ttl_remaining": lifecycle_output.get("ttl_remaining", 0.0) if lifecycle_output else 0.0,
            } if lifecycle_output else None

            conflict_summary = {
                "can_proceed": conflict_output.get("can_proceed", False) if conflict_output else False,
            } if conflict_output else None

            execution_summary = {
                "success": execution_output.get("success", False) if execution_output else False,
            } if execution_output else None

            readiness = exchange_skeleton.assess_readiness(
                proposal=proposal,
                triage_summary=triage_summary,
                lifecycle_summary=lifecycle_summary,
                conflict_summary=conflict_summary,
                execution_summary=execution_summary,
                fallback_on_error=True,
            )

            # Determine status
            decision = readiness.decision.value if readiness.decision else "exchange_reject"
            if decision == "exchange_ready":
                status = StageStatus.COMPLETED
            elif decision == "exchange_hold":
                status = StageStatus.HELD
            else:
                status = StageStatus.REJECTED

            output = {
                "is_ready": readiness.is_ready,
                "decision": decision,
                "readiness_score": readiness.readiness_score,
                "readiness_id": readiness.readiness_id,
            }

            result = StageResult(
                stage_name="exchange",
                status=status,
                success=status in (StageStatus.COMPLETED, StageStatus.HELD),
                output=output,
                fallback_used=readiness.fallback_used,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

        except Exception as e:
            result = StageResult(
                stage_name="exchange",
                status=StageStatus.FAILED,
                success=False,
                error=str(e),
                fallback_used=True,
                timestamp=now,
            )
            trace.stages.append(result)
            return result

    def _fallback_result(
        self,
        remote_summary_dict: Dict[str, Any],
        source_node: Optional[str],
        error_message: str,
    ) -> CoordinationResult:
        """Create fallback coordination result on error."""
        now = utc_now()
        coordination_id = f"coord-fallback-{str(uuid.uuid4())[:8]}"
        trace_id = str(uuid.uuid4())[:8]

        identity = remote_summary_dict.get("identity", {}) if isinstance(remote_summary_dict, dict) else {}
        adapter_id = identity.get("adapter_id", "unknown")
        generation = identity.get("generation", 0)

        return CoordinationResult(
            coordination_id=coordination_id,
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            decision=CoordinationDecision.COORDINATED_REJECT,
            is_ready=False,
            intake_status=StageStatus.FAILED,
            triage_status=StageStatus.PENDING,
            lifecycle_status=StageStatus.PENDING,
            conflict_status=StageStatus.PENDING,
            execution_status=StageStatus.PENDING,
            event_status=StageStatus.PENDING,
            exchange_status=StageStatus.PENDING,
            reason=f"Coordination error: {error_message}",
            recommendation="reject_due_to_error",
            trace=CoordinationTrace(
                trace_id=trace_id,
                stages=[],
                started_at=now,
                completed_at=now,
                short_circuit_at="coordination",
                short_circuit_reason=error_message,
            ),
            fallback_used=True,
            any_stage_fallback=True,
            version=self.VERSION,
            coordinated_at=now,
        )

    def export_result(self, result: CoordinationResult) -> Dict[str, Any]:
        """Export coordination result to dictionary."""
        return result.to_dict()

    def import_result(self, data: Dict[str, Any]) -> CoordinationResult:
        """Import coordination result from dictionary."""
        return CoordinationResult.from_dict(data)

    def quick_coordination_check(
        self,
        remote_summary_dict: Dict[str, Any],
    ) -> bool:
        """Quick check if summary can be coordinated.

        Phase 20: Fast path for simple coordination decisions.
        """
        try:
            # Check structure
            identity = remote_summary_dict.get("identity", {})
            if not identity.get("adapter_id"):
                return False
            if not isinstance(identity.get("generation"), int):
                return False

            # Check required fields
            required = ["identity", "specialization", "validation_score", "snapshot_lineage"]
            for field in required:
                if field not in remote_summary_dict:
                    return False

            return True
        except Exception:
            return False
