"""Phase 14: Triage pool lifecycle engine.

Manages lifecycle of staged/triaged/ready remote summaries:
- Expiration judgment
- Lifecycle transitions (ready -> hold -> downgrade -> evict)
- Priority/freshness recalculation
- Cleanup/eviction paths

Safe to call during serve path - never blocks or raises.
"""

import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field

from .types import (
    TriageResult,
    TriageStatus,
    StagedRemoteCandidate,
)


class LifecycleDecision(Enum):
    """Phase 14: Lifecycle decision for remote candidate.

    - KEEP: Keep in current pool, no change
    - REQUEUE: Re-evaluate, may change pool
    - DOWNGRADE: Move to downgrade pool
    - EXPIRE: Mark as expired, ready for cleanup
    - EVICT: Remove from pool entirely
    """
    KEEP = "keep"
    REQUEUE = "requeue"
    DOWNGRADE = "downgrade"
    EXPIRE = "expire"
    EVICT = "evict"


class LifecycleState(Enum):
    """Phase 14: Current lifecycle state of remote candidate.

    States map to pools but track temporal progression:
    - STAGED: Just staged, not yet triaged
    - READY: Ready for federation promotion
    - HOLD: Under observation
    - DOWNGRADED: Downgraded, limited use
    - EXPIRED: Expired, pending eviction
    - EVICTED: Removed from pool
    """
    STAGED = "staged"
    READY = "ready"
    HOLD = "hold"
    DOWNGRADED = "downgraded"
    EXPIRED = "expired"
    EVICTED = "evicted"


@dataclass
class LifecycleMeta:
    """Phase 14: Lifecycle metadata for remote candidate.

    Bounded-size metadata for lifecycle tracking.
    """
    # Identity
    adapter_id: str
    generation: int
    source_node: Optional[str]

    # Current state
    state: LifecycleState

    # Timing
    entered_at: str  # ISO timestamp when entered current state
    last_reviewed_at: str  # ISO timestamp of last lifecycle review
    expires_at: Optional[str]  # ISO timestamp when expires (if applicable)

    # TTL configuration (hours)
    ttl_hours: int
    ttl_remaining: float  # Hours remaining

    # Freshness/priority summary
    freshness_score: float  # 0.0-1.0
    priority_score: int  # 0-100
    priority_changed: bool  # Whether priority changed since last review

    # Lifecycle decision
    decision: LifecycleDecision
    decision_reason: str

    # Fallback tracking
    fallback_used: bool

    # Version/timestamp
    version: str
    reviewed_at: str  # ISO timestamp of this review

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "identity": {
                "adapter_id": self.adapter_id,
                "generation": self.generation,
                "source_node": self.source_node,
            },
            "state": {
                "current": self.state.value,
                "entered_at": self.entered_at,
                "last_reviewed_at": self.last_reviewed_at,
                "expires_at": self.expires_at,
            },
            "ttl": {
                "hours": self.ttl_hours,
                "remaining": round(self.ttl_remaining, 2),
            },
            "scores": {
                "freshness": round(self.freshness_score, 2),
                "priority": self.priority_score,
                "priority_changed": self.priority_changed,
            },
            "decision": {
                "action": self.decision.value,
                "reason": self.decision_reason,
            },
            "meta": {
                "fallback_used": self.fallback_used,
                "version": self.version,
                "reviewed_at": self.reviewed_at,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LifecycleMeta":
        """Create from dictionary."""
        identity = data.get("identity", {})
        state_info = data.get("state", {})
        ttl = data.get("ttl", {})
        scores = data.get("scores", {})
        decision = data.get("decision", {})
        meta = data.get("meta", {})

        state_str = state_info.get("current", "staged")
        state = LifecycleState(state_str) if state_str in [s.value for s in LifecycleState] else LifecycleState.STAGED

        decision_str = decision.get("action", "keep")
        dec = LifecycleDecision(decision_str) if decision_str in [d.value for d in LifecycleDecision] else LifecycleDecision.KEEP

        return cls(
            adapter_id=identity.get("adapter_id", ""),
            generation=identity.get("generation", 0),
            source_node=identity.get("source_node"),
            state=state,
            entered_at=state_info.get("entered_at", ""),
            last_reviewed_at=state_info.get("last_reviewed_at", ""),
            expires_at=state_info.get("expires_at"),
            ttl_hours=ttl.get("hours", 24),
            ttl_remaining=ttl.get("remaining", 0.0),
            freshness_score=scores.get("freshness", 0.0),
            priority_score=scores.get("priority", 0),
            priority_changed=scores.get("priority_changed", False),
            decision=dec,
            decision_reason=decision.get("reason", ""),
            fallback_used=meta.get("fallback_used", False),
            version=meta.get("version", "1.0"),
            reviewed_at=meta.get("reviewed_at", ""),
        )

    def is_active(self) -> bool:
        """Check if candidate is still in active pool."""
        return self.state in (LifecycleState.STAGED, LifecycleState.READY, LifecycleState.HOLD, LifecycleState.DOWNGRADED)

    def is_expired(self) -> bool:
        """Check if candidate has expired."""
        return self.state == LifecycleState.EXPIRED or self.ttl_remaining <= 0

    def can_promote(self) -> bool:
        """Check if candidate can be promoted."""
        return self.state == LifecycleState.READY and not self.is_expired()


@dataclass
class LifecycleResult:
    """Phase 14: Complete lifecycle evaluation result.

    Includes lifecycle metadata and transition information.
    """
    # Processing metadata
    processed_at: str
    processor_version: str
    fallback_used: bool

    # Lifecycle metadata
    meta: LifecycleMeta

    # Transition information
    previous_state: Optional[LifecycleState]
    state_changed: bool

    # Action hints
    needs_cleanup: bool
    needs_requeue: bool

    # Audit
    trace_id: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-friendly dictionary."""
        return {
            "processed_at": self.processed_at,
            "processor_version": self.processor_version,
            "fallback_used": self.fallback_used,
            "lifecycle": self.meta.to_dict(),
            "transition": {
                "previous_state": self.previous_state.value if self.previous_state else None,
                "state_changed": self.state_changed,
            },
            "action_hints": {
                "needs_cleanup": self.needs_cleanup,
                "needs_requeue": self.needs_requeue,
            },
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LifecycleResult":
        """Create from dictionary."""
        transition = data.get("transition", {})
        action_hints = data.get("action_hints", {})

        prev_state_str = transition.get("previous_state")
        prev_state = LifecycleState(prev_state_str) if prev_state_str else None

        return cls(
            processed_at=data.get("processed_at", ""),
            processor_version=data.get("processor_version", "1.0"),
            fallback_used=data.get("fallback_used", False),
            meta=LifecycleMeta.from_dict(data.get("lifecycle", {})),
            previous_state=prev_state,
            state_changed=transition.get("state_changed", False),
            needs_cleanup=action_hints.get("needs_cleanup", False),
            needs_requeue=action_hints.get("needs_requeue", False),
            trace_id=data.get("trace_id", ""),
        )


class TriagePoolLifecycle:
    """Phase 14: Lifecycle engine for triage pool.

    Manages lifecycle of staged/triaged/ready remote candidates:
    - Expiration judgment based on TTL
    - State transitions (ready -> hold -> downgrade -> expire -> evict)
    - Priority/freshness recalculation
    - Cleanup/eviction paths

    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"

    # TTL configuration (hours)
    DEFAULT_TTL_READY = 168  # 7 days for ready candidates
    DEFAULT_TTL_HOLD = 72   # 3 days for hold candidates
    DEFAULT_TTL_DOWNGRADED = 24  # 1 day for downgraded candidates
    DEFAULT_TTL_STAGED = 48  # 2 days for staged (pre-triage)

    # Freshness thresholds
    FRESHNESS_THRESHOLD_HIGH = 0.8
    FRESHNESS_THRESHOLD_MEDIUM = 0.5
    FRESHNESS_THRESHOLD_LOW = 0.3

    # Priority recalculation interval (hours)
    PRIORITY_RECALC_INTERVAL = 6

    @classmethod
    def evaluate(
        cls,
        triage_result: TriageResult,
        previous_meta: Optional[LifecycleMeta] = None,
        current_time: Optional[datetime] = None,
        fallback_on_error: bool = True,
    ) -> LifecycleResult:
        """Evaluate lifecycle for a triaged remote candidate.

        Phase 14: Main entry point for lifecycle evaluation.

        Args:
            triage_result: The triage result to evaluate
            previous_meta: Optional previous lifecycle metadata
            current_time: Optional current time (defaults to now)
            fallback_on_error: Whether to return safe fallback on error

        Returns:
            LifecycleResult with lifecycle metadata and transition info
        """
        try:
            return cls._do_evaluate(triage_result, previous_meta, current_time)
        except Exception as e:
            if fallback_on_error:
                return cls._fallback_result(triage_result, previous_meta, str(e))
            raise

    @classmethod
    def _do_evaluate(
        cls,
        triage_result: TriageResult,
        previous_meta: Optional[LifecycleMeta],
        current_time: Optional[datetime],
    ) -> LifecycleResult:
        """Internal lifecycle evaluation logic."""
        from datetime import timezone
        now = current_time or datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        processed_at = now.isoformat().replace("+00:00", "Z")
        trace_id = str(uuid.uuid4())[:8]

        assessment = triage_result.assessment

        # Determine current state from triage status
        current_state = cls._triage_status_to_lifecycle_state(assessment.triage_status)

        # Get previous state if available
        previous_state = previous_meta.state if previous_meta else None
        state_changed = previous_state is not None and previous_state != current_state

        # Calculate TTL based on state
        ttl_hours = cls._get_ttl_for_state(current_state)

        # Calculate entered_at
        if previous_meta and not state_changed:
            entered_at = previous_meta.entered_at
        else:
            entered_at = processed_at

        # Calculate last_reviewed_at
        last_reviewed_at = previous_meta.reviewed_at if previous_meta else processed_at

        # Calculate expiration
        entered_dt_str = entered_at.replace("Z", "+00:00")
        entered_dt = datetime.fromisoformat(entered_dt_str)
        if entered_dt.tzinfo is None:
            entered_dt = entered_dt.replace(tzinfo=timezone.utc)

        expires_dt = entered_dt + timedelta(hours=ttl_hours)
        expires_at = expires_dt.isoformat().replace("+00:00", "Z")

        # Calculate TTL remaining
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        ttl_remaining = (expires_dt - now).total_seconds() / 3600

        # Calculate freshness score
        freshness = cls._calculate_freshness(ttl_remaining, ttl_hours, assessment)

        # Calculate priority score
        priority, priority_changed = cls._calculate_priority(
            assessment, previous_meta, now
        )

        # Determine lifecycle decision
        decision, reason = cls._determine_decision(
            current_state, ttl_remaining, freshness, assessment, previous_meta
        )

        # Update state based on decision
        if decision == LifecycleDecision.EXPIRE:
            current_state = LifecycleState.EXPIRED
            state_changed = previous_state != current_state if previous_state else True
        elif decision == LifecycleDecision.EVICT:
            current_state = LifecycleState.EVICTED
            state_changed = previous_state != current_state if previous_state else True
        elif decision == LifecycleDecision.DOWNGRADE:
            current_state = LifecycleState.DOWNGRADED
            state_changed = previous_state != current_state if previous_state else True

        # Determine action hints
        needs_cleanup = decision in (LifecycleDecision.EXPIRE, LifecycleDecision.EVICT)
        needs_requeue = decision == LifecycleDecision.REQUEUE

        # Build lifecycle metadata
        meta = LifecycleMeta(
            adapter_id=assessment.adapter_id,
            generation=assessment.generation,
            source_node=assessment.source_node,
            state=current_state,
            entered_at=entered_at,
            last_reviewed_at=last_reviewed_at,
            expires_at=expires_at if ttl_remaining > 0 else None,
            ttl_hours=ttl_hours,
            ttl_remaining=max(0, ttl_remaining),
            freshness_score=freshness,
            priority_score=priority,
            priority_changed=priority_changed,
            decision=decision,
            decision_reason=reason,
            fallback_used=False,
            version=cls.VERSION,
            reviewed_at=processed_at,
        )

        return LifecycleResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=False,
            meta=meta,
            previous_state=previous_state,
            state_changed=state_changed,
            needs_cleanup=needs_cleanup,
            needs_requeue=needs_requeue,
            trace_id=trace_id,
        )

    @classmethod
    def _triage_status_to_lifecycle_state(cls, status: TriageStatus) -> LifecycleState:
        """Map triage status to lifecycle state."""
        mapping = {
            TriageStatus.READY: LifecycleState.READY,
            TriageStatus.HOLD: LifecycleState.HOLD,
            TriageStatus.DOWNGRADE: LifecycleState.DOWNGRADED,
            TriageStatus.REJECT: LifecycleState.EXPIRED,
        }
        return mapping.get(status, LifecycleState.HOLD)

    @classmethod
    def _get_ttl_for_state(cls, state: LifecycleState) -> int:
        """Get TTL hours for a lifecycle state."""
        ttl_map = {
            LifecycleState.READY: cls.DEFAULT_TTL_READY,
            LifecycleState.HOLD: cls.DEFAULT_TTL_HOLD,
            LifecycleState.DOWNGRADED: cls.DEFAULT_TTL_DOWNGRADED,
            LifecycleState.STAGED: cls.DEFAULT_TTL_STAGED,
        }
        return ttl_map.get(state, cls.DEFAULT_TTL_HOLD)

    @classmethod
    def _calculate_freshness(
        cls,
        ttl_remaining: float,
        ttl_hours: int,
        assessment: Any,
    ) -> float:
        """Calculate freshness score (0.0-1.0)."""
        # Base freshness from TTL ratio
        ttl_ratio = max(0, min(1, ttl_remaining / ttl_hours)) if ttl_hours > 0 else 0

        # Boost from assessment freshness
        assessment_fresh = 1.0 if assessment.readiness.is_fresh else 0.7

        # Combined score
        freshness = (ttl_ratio * 0.6) + (assessment_fresh * 0.4)

        return round(min(1.0, freshness), 2)

    @classmethod
    def _calculate_priority(
        cls,
        assessment: Any,
        previous_meta: Optional[LifecycleMeta],
        now: datetime,
    ) -> tuple[int, bool]:
        """Calculate priority score and whether it changed."""
        # Base priority from triage result
        base_priority = assessment.readiness.readiness_score * 100

        # Boost for priority candidates
        if assessment.readiness.is_priority:
            base_priority += 20

        # Penalty for needing review
        if assessment.needs_review:
            base_priority -= 10

        # Ensure bounds
        priority = int(max(0, min(100, base_priority)))

        # Check if changed from previous
        changed = False
        if previous_meta:
            # Only flag as changed if significant difference (>5)
            changed = abs(priority - previous_meta.priority_score) > 5

        return priority, changed

    @classmethod
    def _determine_decision(
        cls,
        state: LifecycleState,
        ttl_remaining: float,
        freshness: float,
        assessment: Any,
        previous_meta: Optional[LifecycleMeta],
    ) -> tuple[LifecycleDecision, str]:
        """Determine lifecycle decision."""
        # Expired: must expire or evict
        if ttl_remaining <= 0:
            if state == LifecycleState.EXPIRED:
                return (LifecycleDecision.EVICT, "TTL expired, evict from pool")
            return (LifecycleDecision.EXPIRE, f"TTL expired ({ttl_remaining:.1f}h remaining)")

        # Reject status: expire immediately
        if assessment.triage_status == TriageStatus.REJECT:
            return (LifecycleDecision.EXPIRE, "Triage status is reject")

        # Ready state: can downgrade if freshness drops
        if state == LifecycleState.READY:
            if freshness < cls.FRESHNESS_THRESHOLD_LOW:
                return (LifecycleDecision.DOWNGRADE, f"Freshness too low ({freshness:.2f})")
            if freshness < cls.FRESHNESS_THRESHOLD_MEDIUM:
                return (LifecycleDecision.REQUEUE, f"Freshness declining ({freshness:.2f})")
            return (LifecycleDecision.KEEP, "Ready candidate healthy")

        # Hold state: can requeue or expire
        if state == LifecycleState.HOLD:
            if freshness < cls.FRESHNESS_THRESHOLD_LOW:
                return (LifecycleDecision.EXPIRE, f"Hold candidate stale ({freshness:.2f})")
            if previous_meta and previous_meta.decision == LifecycleDecision.REQUEUE:
                # Already requeued, time to expire
                return (LifecycleDecision.EXPIRE, "Hold candidate requeued but not improved")
            return (LifecycleDecision.REQUEUE, "Hold candidate needs re-evaluation")

        # Downgraded state: expire soon
        if state == LifecycleState.DOWNGRADED:
            if ttl_remaining < cls.DEFAULT_TTL_DOWNGRADED / 2:
                return (LifecycleDecision.EXPIRE, "Downgraded candidate nearing expiration")
            return (LifecycleDecision.KEEP, "Downgraded candidate retained")

        # Default: keep
        return (LifecycleDecision.KEEP, "No lifecycle action needed")

    @classmethod
    def _fallback_result(
        cls,
        triage_result: TriageResult,
        previous_meta: Optional[LifecycleMeta],
        error_message: str,
    ) -> LifecycleResult:
        """Create fallback lifecycle result on error."""
        from datetime import timezone
        processed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        trace_id = str(uuid.uuid4())[:8]
        trace_id = str(uuid.uuid4())[:8]

        assessment = triage_result.assessment if triage_result else None

        # Safe fallback: expire the candidate
        meta = LifecycleMeta(
            adapter_id=assessment.adapter_id if assessment else "unknown",
            generation=assessment.generation if assessment else 0,
            source_node=assessment.source_node if assessment else None,
            state=LifecycleState.EXPIRED,
            entered_at=processed_at,
            last_reviewed_at=processed_at,
            expires_at=None,
            ttl_hours=0,
            ttl_remaining=0.0,
            freshness_score=0.0,
            priority_score=0,
            priority_changed=False,
            decision=LifecycleDecision.EXPIRE,
            decision_reason=f"Lifecycle evaluation error: {error_message}",
            fallback_used=True,
            version=cls.VERSION,
            reviewed_at=processed_at,
        )

        return LifecycleResult(
            processed_at=processed_at,
            processor_version=cls.VERSION,
            fallback_used=True,
            meta=meta,
            previous_state=previous_meta.state if previous_meta else None,
            state_changed=True,
            needs_cleanup=True,
            needs_requeue=False,
            trace_id=trace_id,
        )

    @classmethod
    def quick_expiration_check(
        cls,
        lifecycle_meta: LifecycleMeta,
        current_time: Optional[datetime] = None,
    ) -> bool:
        """Quick check if candidate has expired.

        Phase 14: Fast path for expiration checks.
        """
        try:
            if lifecycle_meta.ttl_remaining <= 0:
                return True

            if lifecycle_meta.expires_at:
                now = current_time or datetime.utcnow()
                expires_dt = datetime.fromisoformat(lifecycle_meta.expires_at.replace("Z", "+00:00"))
                return now >= expires_dt

            return False
        except Exception:
            return True  # Conservative: treat errors as expired

    @classmethod
    def batch_evaluate(
        cls,
        triage_results: List[TriageResult],
        previous_metas: Optional[Dict[str, LifecycleMeta]] = None,
        current_time: Optional[datetime] = None,
    ) -> List[LifecycleResult]:
        """Evaluate lifecycle for multiple triage results.

        Phase 14: Batch processing for efficiency.
        """
        previous_metas = previous_metas or {}
        results = []

        for triage_result in triage_results:
            key = f"{triage_result.assessment.adapter_id}:{triage_result.assessment.generation}"
            previous_meta = previous_metas.get(key)

            result = cls.evaluate(
                triage_result=triage_result,
                previous_meta=previous_meta,
                current_time=current_time,
                fallback_on_error=True,
            )
            results.append(result)

        return results
