"""Phase 17: Federation event streaming layer.

Structured event streaming for federation pipeline:
- intake → staging → triage → lifecycle → conflict → execution

Provides deterministic, bounded event emission and history.
Safe to call during serve path - never blocks or raises.
"""

import uuid
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from enum import Enum
from dataclasses import dataclass, field


class EventType(Enum):
    """Phase 17: Federation event types.

    Events track progression through federation pipeline:
    - SUMMARY_INTAKEN: Remote summary received and validated
    - CANDIDATE_STAGED: Remote candidate staged for evaluation
    - TRIAGE_DECIDED: Triage decision made (ready/hold/downgrade/reject)
    - LIFECYCLE_UPDATED: Lifecycle state updated
    - CONFLICT_RESOLVED: Conflict resolution completed
    - PROMOTION_EXECUTED: Promotion executed successfully
    - PROMOTION_DEFERRED: Promotion deferred for later
    - PROMOTION_REJECTED: Promotion rejected
    - PROMOTION_ROLLED_BACK: Promotion rolled back
    """
    SUMMARY_INTAKEN = "summary_intaken"
    CANDIDATE_STAGED = "candidate_staged"
    TRIAGE_DECIDED = "triage_decided"
    LIFECYCLE_UPDATED = "lifecycle_updated"
    CONFLICT_RESOLVED = "conflict_resolved"
    PROMOTION_EXECUTED = "promotion_executed"
    PROMOTION_DEFERRED = "promotion_deferred"
    PROMOTION_REJECTED = "promotion_rejected"
    PROMOTION_ROLLED_BACK = "promotion_rolled_back"


@dataclass
class EventContext:
    """Phase 17: Context for federation events."""
    adapter_id: str
    generation: int
    source_node: Optional[str]
    trace_id: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "generation": self.generation,
            "source_node": self.source_node,
            "trace_id": self.trace_id,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventContext":
        return cls(
            adapter_id=data.get("adapter_id", ""),
            generation=data.get("generation", 0),
            source_node=data.get("source_node"),
            trace_id=data.get("trace_id", ""),
        )


@dataclass
class EventPayload:
    """Phase 17: Payload for federation events.

    Structured payload with type-specific data.
    """
    # Type-specific summary
    event_type: EventType
    summary: Dict[str, Any]

    # References to related objects
    intake_ref: Optional[str]
    staging_ref: Optional[str]
    triage_ref: Optional[str]
    lifecycle_ref: Optional[str]
    conflict_ref: Optional[str]
    execution_ref: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_type": self.event_type.value,
            "summary": self.summary,
            "refs": {
                "intake": self.intake_ref,
                "staging": self.staging_ref,
                "triage": self.triage_ref,
                "lifecycle": self.lifecycle_ref,
                "conflict": self.conflict_ref,
                "execution": self.execution_ref,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventPayload":
        refs = data.get("refs", {})
        type_str = data.get("event_type", "")
        event_type = EventType(type_str) if type_str in [t.value for t in EventType] else EventType.SUMMARY_INTAKEN

        return cls(
            event_type=event_type,
            summary=data.get("summary", {}),
            intake_ref=refs.get("intake"),
            staging_ref=refs.get("staging"),
            triage_ref=refs.get("triage"),
            lifecycle_ref=refs.get("lifecycle"),
            conflict_ref=refs.get("conflict"),
            execution_ref=refs.get("execution"),
        )


@dataclass
class FederationEvent:
    """Phase 17: Federation event.

    Structured event for federation pipeline tracking.
    """
    # Identity
    event_id: str
    event_type: EventType

    # Context
    context: EventContext

    # Payload
    payload: EventPayload

    # Metadata
    timestamp: str
    version: str
    fallback_used: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "identity": {
                "event_id": self.event_id,
                "event_type": self.event_type.value,
            },
            "context": self.context.to_dict(),
            "payload": self.payload.to_dict(),
            "meta": {
                "timestamp": self.timestamp,
                "version": self.version,
                "fallback_used": self.fallback_used,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FederationEvent":
        identity = data.get("identity", {})
        meta = data.get("meta", {})

        type_str = identity.get("event_type", "")
        event_type = EventType(type_str) if type_str in [t.value for t in EventType] else EventType.SUMMARY_INTAKEN

        return cls(
            event_id=identity.get("event_id", ""),
            event_type=event_type,
            context=EventContext.from_dict(data.get("context", {})),
            payload=EventPayload.from_dict(data.get("payload", {})),
            timestamp=meta.get("timestamp", ""),
            version=meta.get("version", "1.0"),
            fallback_used=meta.get("fallback_used", False),
        )


@dataclass
class EventStream:
    """Phase 17: Federation event stream.

    Bounded event history for federation pipeline.
    """
    stream_id: str
    events: List[FederationEvent]
    created_at: str
    updated_at: str
    version: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "stream_id": self.stream_id,
            "events": [e.to_dict() for e in self.events],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "version": self.version,
            "event_count": len(self.events),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventStream":
        events_data = data.get("events", [])
        events = [FederationEvent.from_dict(e) for e in events_data]

        return cls(
            stream_id=data.get("stream_id", ""),
            events=events,
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            version=data.get("version", "1.0"),
        )

    def append(self, event: FederationEvent) -> None:
        """Append event to stream."""
        self.events.append(event)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        self.updated_at = now

    def get_events_by_type(self, event_type: EventType) -> List[FederationEvent]:
        """Get all events of specific type."""
        return [e for e in self.events if e.event_type == event_type]

    def get_events_for_candidate(self, adapter_id: str, generation: int) -> List[FederationEvent]:
        """Get all events for specific candidate."""
        return [
            e for e in self.events
            if e.context.adapter_id == adapter_id and e.context.generation == generation
        ]

    def get_latest_event(self) -> Optional[FederationEvent]:
        """Get latest event in stream."""
        if not self.events:
            return None
        return self.events[-1]


class FederationEventEmitter:
    """Phase 17: Federation event emitter.

    Emits structured events for federation pipeline stages.
    Safe to call during serve path - never blocks or raises.
    """

    VERSION = "1.0"
    MAX_STREAM_SIZE = 1000  # Bounded

    def __init__(self):
        self._streams: Dict[str, EventStream] = {}

    def emit_summary_intaken(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        intake_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit summary intaken event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        payload = EventPayload(
            event_type=EventType.SUMMARY_INTAKEN,
            summary={
                "decision": intake_result.get("decision"),
                "is_staged": intake_result.get("is_staged"),
            },
            intake_ref=intake_result.get("processed_at"),
            staging_ref=None,
            triage_ref=None,
            lifecycle_ref=None,
            conflict_ref=None,
            execution_ref=None,
        )

        return self._emit(context, payload)

    def emit_candidate_staged(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        staged_candidate: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit candidate staged event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        staging = staged_candidate.get("staging", {})
        payload = EventPayload(
            event_type=EventType.CANDIDATE_STAGED,
            summary={
                "decision": staging.get("decision"),
                "staged_at": staging.get("staged_at"),
                "is_active": staging.get("is_active"),
            },
            intake_ref=None,
            staging_ref=staged_candidate.get("intake_ref"),
            triage_ref=None,
            lifecycle_ref=None,
            conflict_ref=None,
            execution_ref=None,
        )

        return self._emit(context, payload)

    def emit_triage_decided(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        triage_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit triage decided event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        triage = triage_result.get("assessment", {}).get("triage", {})
        readiness = triage_result.get("assessment", {}).get("readiness", {})
        payload = EventPayload(
            event_type=EventType.TRIAGE_DECIDED,
            summary={
                "status": triage.get("status"),
                "readiness_score": readiness.get("score"),
                "target_pool": triage_result.get("routing", {}).get("target_pool"),
            },
            intake_ref=None,
            staging_ref=None,
            triage_ref=triage_result.get("trace_id"),
            lifecycle_ref=None,
            conflict_ref=None,
            execution_ref=None,
        )

        return self._emit(context, payload)

    def emit_lifecycle_updated(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        lifecycle_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit lifecycle updated event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        lifecycle = lifecycle_result.get("lifecycle", {})
        state = lifecycle.get("state", {})
        decision = lifecycle.get("decision", {})
        payload = EventPayload(
            event_type=EventType.LIFECYCLE_UPDATED,
            summary={
                "state": state.get("current"),
                "decision": decision.get("action"),
                "ttl_remaining": lifecycle.get("ttl", {}).get("remaining"),
            },
            intake_ref=None,
            staging_ref=None,
            triage_ref=None,
            lifecycle_ref=lifecycle_result.get("trace_id"),
            conflict_ref=None,
            execution_ref=None,
        )

        return self._emit(context, payload)

    def emit_conflict_resolved(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        conflict_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit conflict resolved event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        conflict_set = conflict_result.get("conflict_set", {})
        resolution = conflict_set.get("resolution", {})
        payload = EventPayload(
            event_type=EventType.CONFLICT_RESOLVED,
            summary={
                "has_conflicts": conflict_set.get("has_conflicts"),
                "resolution_decision": resolution.get("decision"),
                "selected_candidate": resolution.get("selected_candidate"),
            },
            intake_ref=None,
            staging_ref=None,
            triage_ref=None,
            lifecycle_ref=None,
            conflict_ref=conflict_set.get("set_id"),
            execution_ref=None,
        )

        return self._emit(context, payload)

    def emit_promotion_executed(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        execution_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit promotion executed event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        execution = execution_result.get("execution", {})
        payload = EventPayload(
            event_type=EventType.PROMOTION_EXECUTED,
            summary={
                "execution_id": execution.get("identity", {}).get("execution_id"),
                "decision": execution.get("execution", {}).get("decision"),
                "status": execution.get("execution", {}).get("status"),
                "success": execution_result.get("success"),
            },
            intake_ref=None,
            staging_ref=None,
            triage_ref=None,
            lifecycle_ref=None,
            conflict_ref=None,
            execution_ref=execution.get("identity", {}).get("execution_id"),
        )

        return self._emit(context, payload)

    def emit_promotion_deferred(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        execution_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit promotion deferred event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        execution = execution_result.get("execution", {})
        payload = EventPayload(
            event_type=EventType.PROMOTION_DEFERRED,
            summary={
                "execution_id": execution.get("identity", {}).get("execution_id"),
                "reason": execution.get("reason"),
            },
            intake_ref=None,
            staging_ref=None,
            triage_ref=None,
            lifecycle_ref=None,
            conflict_ref=None,
            execution_ref=execution.get("identity", {}).get("execution_id"),
        )

        return self._emit(context, payload)

    def emit_promotion_rejected(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        execution_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit promotion rejected event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        execution = execution_result.get("execution", {})
        payload = EventPayload(
            event_type=EventType.PROMOTION_REJECTED,
            summary={
                "execution_id": execution.get("identity", {}).get("execution_id"),
                "reason": execution.get("reason"),
            },
            intake_ref=None,
            staging_ref=None,
            triage_ref=None,
            lifecycle_ref=None,
            conflict_ref=None,
            execution_ref=execution.get("identity", {}).get("execution_id"),
        )

        return self._emit(context, payload)

    def emit_promotion_rolled_back(
        self,
        adapter_id: str,
        generation: int,
        source_node: Optional[str],
        execution_result: Dict[str, Any],
        trace_id: Optional[str] = None,
    ) -> FederationEvent:
        """Emit promotion rolled back event."""
        context = EventContext(
            adapter_id=adapter_id,
            generation=generation,
            source_node=source_node,
            trace_id=trace_id or str(uuid.uuid4())[:8],
        )

        execution = execution_result.get("execution", {})
        payload = EventPayload(
            event_type=EventType.PROMOTION_ROLLED_BACK,
            summary={
                "execution_id": execution.get("identity", {}).get("execution_id"),
                "reason": execution.get("reason"),
                "previous_status": execution_result.get("outcome", {}).get("previous_status"),
            },
            intake_ref=None,
            staging_ref=None,
            triage_ref=None,
            lifecycle_ref=None,
            conflict_ref=None,
            execution_ref=execution.get("identity", {}).get("execution_id"),
        )

        return self._emit(context, payload)

    def _emit(self, context: EventContext, payload: EventPayload) -> FederationEvent:
        """Emit event to stream."""
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

        event = FederationEvent(
            event_id=f"evt-{str(uuid.uuid4())[:8]}",
            event_type=payload.event_type,
            context=context,
            payload=payload,
            timestamp=now,
            version=self.VERSION,
            fallback_used=False,
        )

        # Get or create stream for this candidate
        stream_key = f"{context.adapter_id}:{context.generation}"
        if stream_key not in self._streams:
            self._streams[stream_key] = EventStream(
                stream_id=f"stream-{stream_key}",
                events=[],
                created_at=now,
                updated_at=now,
                version=self.VERSION,
            )

        stream = self._streams[stream_key]

        # Bounded: trim if exceeds max size
        if len(stream.events) >= self.MAX_STREAM_SIZE:
            stream.events = stream.events[-(self.MAX_STREAM_SIZE - 1):]

        stream.append(event)
        return event

    def get_stream(self, adapter_id: str, generation: int) -> Optional[EventStream]:
        """Get event stream for specific candidate."""
        stream_key = f"{adapter_id}:{generation}"
        return self._streams.get(stream_key)

    def get_all_streams(self) -> Dict[str, EventStream]:
        """Get all event streams."""
        return self._streams.copy()

    def get_events_by_type(self, event_type: EventType) -> List[FederationEvent]:
        """Get all events of specific type across all streams."""
        events = []
        for stream in self._streams.values():
            events.extend(stream.get_events_by_type(event_type))
        return events

    def clear_stream(self, adapter_id: str, generation: int) -> bool:
        """Clear event stream for specific candidate."""
        stream_key = f"{adapter_id}:{generation}"
        if stream_key in self._streams:
            del self._streams[stream_key]
            return True
        return False

    def export_stream(self, adapter_id: str, generation: int) -> Optional[Dict[str, Any]]:
        """Export event stream as dictionary."""
        stream = self.get_stream(adapter_id, generation)
        if stream:
            return stream.to_dict()
        return None

    def import_stream(self, data: Dict[str, Any]) -> EventStream:
        """Import event stream from dictionary."""
        stream = EventStream.from_dict(data)
        stream_key = stream.stream_id.replace("stream-", "")
        self._streams[stream_key] = stream
        return stream
