"""Phase 16: Federation promotion execution layer.

Manages the execution of promotion for resolved remote candidates.
Provides structured execution gate, precondition checks, and execution results
without actual adapter merging or federation training.

Safe to call during serve path - never blocks or raises.
"""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass


class ExecutionDecision(Enum):
    """Phase 16: Execution decision for promotion.

    - EXECUTE: Execute the promotion
    - DEFER: Defer execution for later
    - REJECT: Reject the promotion
    - ROLLBACK: Rollback a previously executed promotion
    """
    EXECUTE = "execute"
    DEFER = "defer"
    REJECT = "reject"
    ROLLBACK = "rollback"


class ExecutionStatus(Enum):
    """Phase 16: Execution status.

    - PENDING: Execution pending
    - EXECUTING: Currently executing
    - COMPLETED: Execution completed successfully
    - FAILED: Execution failed
    - ROLLED_BACK: Execution was rolled back
    - DEFERRED: Execution deferred
    - REJECTED: Execution rejected
    """
    PENDING = "pending"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"
    DEFERRED = "deferred"
    REJECTED = "rejected"


@dataclass
class PromotionCandidate:
    """Phase 16: Candidate for promotion execution."""
    adapter_id: str
    generation: int
    source_node: Optional[str]

    def to_key(self) -> str:
        """Generate unique key for this candidate."""
        return f"{self.adapter_id}:{self.generation}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "generation": self.generation,
            "source_node": self.source_node,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "PromotionCandidate":
        if not isinstance(data, dict):
            return cls(adapter_id="", generation=0, source_node=None)
        return cls(
            adapter_id=data.get("adapter_id", ""),
            generation=data.get("generation", 0),
            source_node=data.get("source_node"),
        )


@dataclass
class PreconditionSummary:
    """Phase 16: Summary of preconditions for promotion execution."""
    # Triage/readiness checks
    triage_ready: bool
    readiness_score: float

    # Lifecycle checks
    lifecycle_valid: bool
    ttl_remaining: float
    state: str

    # Conflict resolution checks
    conflict_resolved: bool
    resolution_decision: str
    can_proceed: bool

    # Validation/comparison checks
    validation_passed: bool
    comparison_acceptable: bool
    lineage_valid: bool
    specialization_valid: bool

    # Overall
    all_preconditions_met: bool
    failed_checks: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "triage": {
                "ready": self.triage_ready,
                "readiness_score": round(self.readiness_score, 2),
            },
            "lifecycle": {
                "valid": self.lifecycle_valid,
                "ttl_remaining": round(self.ttl_remaining, 2),
                "state": self.state,
            },
            "conflict": {
                "resolved": self.conflict_resolved,
                "decision": self.resolution_decision,
                "can_proceed": self.can_proceed,
            },
            "validation": {
                "passed": self.validation_passed,
                "comparison_acceptable": self.comparison_acceptable,
                "lineage_valid": self.lineage_valid,
                "specialization_valid": self.specialization_valid,
            },
            "overall": {
                "all_met": self.all_preconditions_met,
                "failed_checks": self.failed_checks,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PreconditionSummary":
        triage = data.get("triage", {})
        lifecycle = data.get("lifecycle", {})
        conflict = data.get("conflict", {})
        validation = data.get("validation", {})
        overall = data.get("overall", {})

        return cls(
            triage_ready=triage.get("ready", False),
            readiness_score=triage.get("readiness_score", 0.0),
            lifecycle_valid=lifecycle.get("valid", False),
            ttl_remaining=lifecycle.get("ttl_remaining", 0.0),
            state=lifecycle.get("state", ""),
            conflict_resolved=conflict.get("resolved", False),
            resolution_decision=conflict.get("decision", ""),
            can_proceed=conflict.get("can_proceed", False),
            validation_passed=validation.get("passed", False),
            comparison_acceptable=validation.get("comparison_acceptable", False),
            lineage_valid=validation.get("lineage_valid", False),
            specialization_valid=validation.get("specialization_valid", False),
            all_preconditions_met=overall.get("all_met", False),
            failed_checks=overall.get("failed_checks", []),
        )


@dataclass
class ExecutionTrace:
    """Phase 16: Trace of promotion execution."""
    timestamp: str
    action: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "action": self.action,
            "details": self.details,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionTrace":
        return cls(
            timestamp=data.get("timestamp", ""),
            action=data.get("action", ""),
            details=data.get("details", {}),
        )


@dataclass
class PromotionExecution:
    """Phase 16: Federation promotion execution.

    Structured representation of a promotion execution.
    """
    # Identity
    execution_id: str
    candidate: PromotionCandidate

    # Preconditions
    preconditions: PreconditionSummary

    # Execution decision
    decision: ExecutionDecision
    status: ExecutionStatus

    # Execution metadata
    executed_at: Optional[str]
    completed_at: Optional[str]

    # Trace
    execution_trace: List[ExecutionTrace]

    # Reasoning
    reason: str
    recommendation: str

    # Fallback
    fallback_used: bool
    version: str
    created_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {
                "execution_id": self.execution_id,
                "candidate": self.candidate.to_dict(),
            },
            "preconditions": self.preconditions.to_dict(),
            "execution": {
                "decision": self.decision.value,
                "status": self.status.value,
                "executed_at": self.executed_at,
                "completed_at": self.completed_at,
            },
            "trace": [t.to_dict() for t in self.execution_trace],
            "reasoning": {
                "reason": self.reason,
                "recommendation": self.recommendation,
            },
            "meta": {
                "fallback_used": self.fallback_used,
                "version": self.version,
                "created_at": self.created_at,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromotionExecution":
        identity = data.get("identity", {})
        execution = data.get("execution", {})
        reasoning = data.get("reasoning", {})
        meta = data.get("meta", {})

        decision_str = execution.get("decision", "reject")
        decision = ExecutionDecision(decision_str) if decision_str in [d.value for d in ExecutionDecision] else ExecutionDecision.REJECT

        status_str = execution.get("status", "rejected")
        status = ExecutionStatus(status_str) if status_str in [s.value for s in ExecutionStatus] else ExecutionStatus.REJECTED

        trace_data = data.get("trace", [])
        execution_trace = [ExecutionTrace.from_dict(t) for t in trace_data]

        return cls(
            execution_id=identity.get("execution_id", ""),
            candidate=PromotionCandidate.from_dict(identity.get("candidate", {})),
            preconditions=PreconditionSummary.from_dict(data.get("preconditions", {})),
            decision=decision,
            status=status,
            executed_at=execution.get("executed_at"),
            completed_at=execution.get("completed_at"),
            execution_trace=execution_trace,
            reason=reasoning.get("reason", ""),
            recommendation=reasoning.get("recommendation", ""),
            fallback_used=meta.get("fallback_used", False),
            version=meta.get("version", "1.0"),
            created_at=meta.get("created_at", ""),
        )

    def is_executable(self) -> bool:
        """Check if this execution can be executed."""
        return (
            self.decision == ExecutionDecision.EXECUTE
            and self.preconditions.all_preconditions_met
            and self.status in (ExecutionStatus.PENDING, ExecutionStatus.DEFERRED)
        )

    def is_completed(self) -> bool:
        """Check if execution is completed."""
        return self.status == ExecutionStatus.COMPLETED

    def is_rollbackable(self) -> bool:
        """Check if execution can be rolled back."""
        return self.status in (ExecutionStatus.COMPLETED, ExecutionStatus.EXECUTING)


@dataclass
class PromotionExecutionResult:
    """Phase 16: Result of promotion execution.

    Complete result including execution and outcome.
    """
    # Processing metadata
    processed_at: str
    processor_version: str
    fallback_used: bool

    # Execution
    execution: PromotionExecution

    # Outcome
    success: bool
    outcome_status: str
    outcome_details: Dict[str, Any]

    # Audit
    trace_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "processed_at": self.processed_at,
            "processor_version": self.processor_version,
            "fallback_used": self.fallback_used,
            "execution": self.execution.to_dict(),
            "outcome": {
                "success": self.success,
                "status": self.outcome_status,
                "details": self.outcome_details,
            },
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromotionExecutionResult":
        outcome = data.get("outcome", {})
        return cls(
            processed_at=data.get("processed_at", ""),
            processor_version=data.get("processor_version", "1.0"),
            fallback_used=data.get("fallback_used", False),
            execution=PromotionExecution.from_dict(data.get("execution", {})),
            success=outcome.get("success", False),
            outcome_status=outcome.get("status", ""),
            outcome_details=outcome.get("details", {}),
            trace_id=data.get("trace_id", ""),
        )


class FederationPromotionExecutor:
    """Phase 16: Federation promotion executor.

    Manages the execution of promotion for resolved remote candidates.
    Provides precondition checking and structured execution results.

    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"

    # Precondition thresholds
    MIN_READINESS_SCORE = 0.7
    MIN_TTL_REMAINING = 1.0  # hours
    MIN_VALIDATION_SCORE = 0.6

    @classmethod
    def execute(
        cls,
        candidate_dict: Dict[str, Any],
        triage_summary: Optional[Dict[str, Any]] = None,
        lifecycle_summary: Optional[Dict[str, Any]] = None,
        conflict_summary: Optional[Dict[str, Any]] = None,
        fallback_on_error: bool = True,
    ) -> PromotionExecutionResult:
        """Execute promotion for a resolved remote candidate.

        Phase 16: Main entry point for promotion execution.

        Args:
            candidate_dict: Candidate identity dictionary
            triage_summary: Optional triage/readiness summary
            lifecycle_summary: Optional lifecycle summary
            conflict_summary: Optional conflict resolution summary
            fallback_on_error: Whether to return safe fallback on error

        Returns:
            PromotionExecutionResult with full execution result
        """
        try:
            return cls._do_execute(
                candidate_dict,
                triage_summary,
                lifecycle_summary,
                conflict_summary,
            )
        except Exception as e:
            if fallback_on_error:
                return cls._fallback_result(candidate_dict, str(e))
            raise

    @classmethod
    def _do_execute(
        cls,
        candidate_dict: Dict[str, Any],
        triage_summary: Optional[Dict[str, Any]],
        lifecycle_summary: Optional[Dict[str, Any]],
        conflict_summary: Optional[Dict[str, Any]],
    ) -> PromotionExecutionResult:
        """Internal promotion execution logic."""
        now = datetime.now(timezone.utc)
        processed_at = now.isoformat().replace("+00:00", "Z")
        trace_id = str(uuid.uuid4())[:8]
        execution_id = f"exec-{trace_id}"

        # Build candidate
        candidate = PromotionCandidate.from_dict(candidate_dict)

        # Check preconditions
        preconditions = cls._check_preconditions(
            candidate,
            triage_summary,
            lifecycle_summary,
            conflict_summary,
        )

        # Determine execution decision
        decision, status, reason, recommendation = cls._determine_execution(
            preconditions, candidate
        )

        # Build execution trace
        execution_trace = [
            ExecutionTrace(
                timestamp=processed_at,
                action="precondition_check",
                details={"all_met": preconditions.all_preconditions_met},
            ),
        ]

        if decision == ExecutionDecision.EXECUTE:
            execution_trace.append(ExecutionTrace(
                timestamp=processed_at,
                action="execution_started",
                details={"candidate_key": candidate.to_key()},
            ))

        # Build execution
        execution = PromotionExecution(
            execution_id=execution_id,
            candidate=candidate,
            preconditions=preconditions,
            decision=decision,
            status=status,
            executed_at=processed_at if decision == ExecutionDecision.EXECUTE else None,
            completed_at=processed_at if decision == ExecutionDecision.EXECUTE else None,
            execution_trace=execution_trace,
            reason=reason,
            recommendation=recommendation,
            fallback_used=False,
            version=cls.VERSION,
            created_at=processed_at,
        )

        # Determine outcome
        success = decision == ExecutionDecision.EXECUTE and status == ExecutionStatus.COMPLETED
        outcome_status = "completed" if success else status.value

        return PromotionExecutionResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=False,
            execution=execution,
            success=success,
            outcome_status=outcome_status,
            outcome_details={
                "preconditions_met": preconditions.all_preconditions_met,
                "decision": decision.value,
                "candidate_key": candidate.to_key(),
            },
            trace_id=trace_id,
        )

    @classmethod
    def _check_preconditions(
        cls,
        candidate: PromotionCandidate,
        triage_summary: Optional[Dict[str, Any]],
        lifecycle_summary: Optional[Dict[str, Any]],
        conflict_summary: Optional[Dict[str, Any]],
    ) -> PreconditionSummary:
        """Check all preconditions for promotion execution."""
        failed_checks = []

        # Triage/readiness checks
        triage_ready = False
        readiness_score = 0.0
        if triage_summary:
            triage_status = triage_summary.get("status", "")
            triage_ready = triage_status == "ready"
            readiness_score = triage_summary.get("readiness_score", 0.0)
            if not triage_ready:
                failed_checks.append("triage_not_ready")
            if readiness_score < cls.MIN_READINESS_SCORE:
                failed_checks.append(f"readiness_score_low:{readiness_score}")

        # Lifecycle checks
        lifecycle_valid = False
        ttl_remaining = 0.0
        state = ""
        if lifecycle_summary:
            state = lifecycle_summary.get("state", "")
            lifecycle_valid = state in ("ready", "hold")
            ttl_remaining = lifecycle_summary.get("ttl_remaining", 0.0)
            if not lifecycle_valid:
                failed_checks.append(f"invalid_lifecycle_state:{state}")
            if ttl_remaining < cls.MIN_TTL_REMAINING:
                failed_checks.append(f"ttl_expired:{ttl_remaining}")

        # Conflict resolution checks
        conflict_resolved = False
        resolution_decision = ""
        can_proceed = False
        if conflict_summary:
            conflict_resolved = not conflict_summary.get("has_conflicts", True)
            resolution_decision = conflict_summary.get("resolution_decision", "")
            can_proceed = conflict_summary.get("can_proceed", False)
            if not can_proceed:
                failed_checks.append("conflict_cannot_proceed")

        # Validation/comparison checks (from triage or other sources)
        validation_passed = triage_ready
        comparison_acceptable = triage_ready
        lineage_valid = triage_ready
        specialization_valid = triage_ready

        # Overall - require "ready" state specifically for execution
        all_preconditions_met = (
            triage_ready
            and state == "ready"  # Must be "ready" not just "hold"
            and ttl_remaining >= cls.MIN_TTL_REMAINING
            and can_proceed
            and readiness_score >= cls.MIN_READINESS_SCORE
        )

        return PreconditionSummary(
            triage_ready=triage_ready,
            readiness_score=readiness_score,
            lifecycle_valid=lifecycle_valid,
            ttl_remaining=ttl_remaining,
            state=state,
            conflict_resolved=conflict_resolved,
            resolution_decision=resolution_decision,
            can_proceed=can_proceed,
            validation_passed=validation_passed,
            comparison_acceptable=comparison_acceptable,
            lineage_valid=lineage_valid,
            specialization_valid=specialization_valid,
            all_preconditions_met=all_preconditions_met,
            failed_checks=failed_checks,
        )

    @classmethod
    def _determine_execution(
        cls,
        preconditions: PreconditionSummary,
        candidate: PromotionCandidate,
    ) -> tuple:
        """Determine execution decision based on preconditions."""
        if preconditions.all_preconditions_met:
            return (
                ExecutionDecision.EXECUTE,
                ExecutionStatus.COMPLETED,
                "All preconditions met - promotion executed",
                "execute_promotion",
            )

        # Check for critical failures
        if not preconditions.conflict_resolved or not preconditions.can_proceed:
            return (
                ExecutionDecision.REJECT,
                ExecutionStatus.REJECTED,
                "Conflict resolution blocks execution",
                "reject_due_to_conflict",
            )

        if preconditions.ttl_remaining < 0:
            return (
                ExecutionDecision.REJECT,
                ExecutionStatus.REJECTED,
                "Candidate expired",
                "reject_due_to_expiration",
            )

        # Check for deferrable conditions
        if not preconditions.triage_ready or preconditions.readiness_score < cls.MIN_READINESS_SCORE:
            return (
                ExecutionDecision.DEFER,
                ExecutionStatus.DEFERRED,
                "Readiness not sufficient - defer for observation",
                "defer_for_readiness",
            )

        # Default to reject
        return (
            ExecutionDecision.REJECT,
            ExecutionStatus.REJECTED,
            f"Preconditions not met: {', '.join(preconditions.failed_checks)}",
            "reject_due_to_preconditions",
        )

    @classmethod
    def _fallback_result(
        cls,
        candidate_dict: Dict[str, Any],
        error_message: str,
    ) -> PromotionExecutionResult:
        """Create fallback execution result on error."""
        now = datetime.now(timezone.utc)
        processed_at = now.isoformat().replace("+00:00", "Z")
        trace_id = str(uuid.uuid4())[:8]
        execution_id = f"exec-fallback-{trace_id}"

        candidate = PromotionCandidate.from_dict(candidate_dict)

        preconditions = PreconditionSummary(
            triage_ready=False,
            readiness_score=0.0,
            lifecycle_valid=False,
            ttl_remaining=0.0,
            state="",
            conflict_resolved=False,
            resolution_decision="",
            can_proceed=False,
            validation_passed=False,
            comparison_acceptable=False,
            lineage_valid=False,
            specialization_valid=False,
            all_preconditions_met=False,
            failed_checks=[f"execution_error:{error_message}"],
        )

        execution = PromotionExecution(
            execution_id=execution_id,
            candidate=candidate,
            preconditions=preconditions,
            decision=ExecutionDecision.REJECT,
            status=ExecutionStatus.REJECTED,
            executed_at=None,
            completed_at=None,
            execution_trace=[
                ExecutionTrace(
                    timestamp=processed_at,
                    action="fallback",
                    details={"error": error_message},
                ),
            ],
            reason=f"Execution error: {error_message}",
            recommendation="reject_fallback",
            fallback_used=True,
            version=cls.VERSION,
            created_at=processed_at,
        )

        return PromotionExecutionResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=True,
            execution=execution,
            success=False,
            outcome_status="rejected",
            outcome_details={
                "error": error_message,
                "fallback": True,
            },
            trace_id=trace_id,
        )

    @classmethod
    def rollback_execution(
        cls,
        execution_result: PromotionExecutionResult,
        reason: str = "rollback_requested",
    ) -> PromotionExecutionResult:
        """Rollback a previously executed promotion.

        Phase 16: Rollback an execution that was previously completed.
        """
        if not execution_result.execution.is_rollbackable():
            # Cannot rollback - return unchanged with failure
            return PromotionExecutionResult(
                processed_at=execution_result.processed_at,
                processor_version=cls.VERSION,
                fallback_used=False,
                execution=execution_result.execution,
                success=False,
                outcome_status="rollback_failed",
                outcome_details={
                    "reason": "Execution not rollbackable",
                    "current_status": execution_result.execution.status.value,
                },
                trace_id=execution_result.trace_id,
            )

        now = datetime.now(timezone.utc)
        processed_at = now.isoformat().replace("+00:00", "Z")

        # Deep copy to avoid mutating the caller's object
        import copy
        execution = copy.deepcopy(execution_result.execution)
        execution.decision = ExecutionDecision.ROLLBACK
        execution.status = ExecutionStatus.ROLLED_BACK
        execution.execution_trace.append(ExecutionTrace(
            timestamp=processed_at,
            action="rollback",
            details={"reason": reason},
        ))
        execution.reason = f"Rolled back: {reason}"

        return PromotionExecutionResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=False,
            execution=execution,
            success=True,
            outcome_status="rolled_back",
            outcome_details={
                "rollback_reason": reason,
                "previous_status": execution_result.outcome_status,
            },
            trace_id=execution_result.trace_id,
        )

    @classmethod
    def quick_execute_check(
        cls,
        candidate_dict: Dict[str, Any],
        lifecycle_summary: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Quick check if candidate can be executed.

        Phase 16: Fast path for execute eligibility.
        """
        try:
            # Check lifecycle state
            if lifecycle_summary:
                state = lifecycle_summary.get("state", "")
                if state != "ready":
                    return False
                ttl = lifecycle_summary.get("ttl_remaining", 0)
                if ttl < cls.MIN_TTL_REMAINING:
                    return False

            # Check candidate validity
            candidate = PromotionCandidate.from_dict(candidate_dict)
            if not candidate.adapter_id or candidate.generation <= 0:
                return False

            return True
        except Exception:
            return False

    @classmethod
    def batch_execute(
        cls,
        candidates: List[Dict[str, Any]],
        triage_summaries: Optional[Dict[str, Dict[str, Any]]] = None,
        lifecycle_summaries: Optional[Dict[str, Dict[str, Any]]] = None,
        conflict_summaries: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[PromotionExecutionResult]:
        """Execute promotion for multiple candidates.

        Phase 16: Batch processing for efficiency.
        """
        triage_summaries = triage_summaries or {}
        lifecycle_summaries = lifecycle_summaries or {}
        conflict_summaries = conflict_summaries or {}

        results = []
        for candidate in candidates:
            key = f"{candidate.get('adapter_id', '')}:{candidate.get('generation', 0)}"
            result = cls.execute(
                candidate_dict=candidate,
                triage_summary=triage_summaries.get(key),
                lifecycle_summary=lifecycle_summaries.get(key),
                conflict_summary=conflict_summaries.get(key),
                fallback_on_error=True,
            )
            results.append(result)

        return results
