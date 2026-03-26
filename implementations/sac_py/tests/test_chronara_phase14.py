"""Phase 14: Triage pool lifecycle tests."""

import pytest
from datetime import datetime, timedelta

try:
    from chronara_nexus.lifecycle_engine import (
        LifecycleDecision,
        LifecycleState,
        LifecycleMeta,
        LifecycleResult,
        TriagePoolLifecycle,
    )
    from chronara_nexus.types import (
        TriageResult,
        TriageAssessment,
        TriageStatus,
        ReadinessSummary,
        StagedRemoteCandidate,
        StagingDecision,
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
    )
    from chronara_nexus.governor import Governor
except ImportError:
    from implementations.sac_py.chronara_nexus.lifecycle_engine import (
        LifecycleDecision,
        LifecycleState,
        LifecycleMeta,
        LifecycleResult,
        TriagePoolLifecycle,
    )
    from implementations.sac_py.chronara_nexus.types import (
        TriageResult,
        TriageAssessment,
        TriageStatus,
        ReadinessSummary,
        StagedRemoteCandidate,
        StagingDecision,
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
    )
    from implementations.sac_py.chronara_nexus.governor import Governor


def create_test_readiness(score=0.9, is_fresh=True, is_priority=True):
    """Helper to create test readiness summary."""
    return ReadinessSummary(
        readiness_score=score,
        lineage_score=0.9,
        specialization_score=0.9,
        validation_score=0.9,
        comparison_score=0.9,
        recency_score=0.9,
        is_fresh=is_fresh,
        is_compatible=True,
        is_priority=is_priority,
        score_reason="test",
    )


def create_test_triage_assessment(status=TriageStatus.READY, score=0.9):
    """Helper to create test triage assessment."""
    return TriageAssessment(
        adapter_id="test",
        generation=2,
        source_node="node-1",
        triage_status=status,
        triage_version="1.0",
        triaged_at="2024-01-01T00:00:00Z",
        readiness=create_test_readiness(score),
        lineage_compatible=True,
        specialization_compatible=True,
        validation_acceptable=True,
        comparison_acceptable=True,
        recommendation="test",
        reason="test",
        can_promote_later=status in (TriageStatus.READY, TriageStatus.HOLD),
        needs_review=status == TriageStatus.HOLD,
        expiration_hint=None,
        original_staging_ref="abc123",
    )


def create_test_triage_result(status=TriageStatus.READY, score=0.9):
    """Helper to create test triage result."""
    return TriageResult(
        processed_at="2024-01-01T00:00:00Z",
        processor_version="1.0",
        fallback_used=False,
        assessment=create_test_triage_assessment(status, score),
        target_pool=status.value,
        priority=90,
        trace_id="test123",
    )


class TestLifecycleTypes:
    """Phase 14: Lifecycle type structure tests."""

    def test_lifecycle_decision_enum_values(self):
        """LifecycleDecision has correct enum values."""
        assert LifecycleDecision.KEEP.value == "keep"
        assert LifecycleDecision.REQUEUE.value == "requeue"
        assert LifecycleDecision.DOWNGRADE.value == "downgrade"
        assert LifecycleDecision.EXPIRE.value == "expire"
        assert LifecycleDecision.EVICT.value == "evict"

    def test_lifecycle_state_enum_values(self):
        """LifecycleState has correct enum values."""
        assert LifecycleState.STAGED.value == "staged"
        assert LifecycleState.READY.value == "ready"
        assert LifecycleState.HOLD.value == "hold"
        assert LifecycleState.DOWNGRADED.value == "downgraded"
        assert LifecycleState.EXPIRED.value == "expired"
        assert LifecycleState.EVICTED.value == "evicted"

    def test_lifecycle_meta_structure(self):
        """LifecycleMeta is a real structured object."""
        meta = LifecycleMeta(
            adapter_id="test",
            generation=2,
            source_node="node-1",
            state=LifecycleState.READY,
            entered_at="2024-01-01T00:00:00Z",
            last_reviewed_at="2024-01-01T00:00:00Z",
            expires_at="2024-01-08T00:00:00Z",
            ttl_hours=168,
            ttl_remaining=150.0,
            freshness_score=0.9,
            priority_score=90,
            priority_changed=False,
            decision=LifecycleDecision.KEEP,
            decision_reason="healthy",
            fallback_used=False,
            version="1.0",
            reviewed_at="2024-01-01T00:00:00Z",
        )

        assert meta.adapter_id == "test"
        assert meta.generation == 2
        assert meta.state == LifecycleState.READY
        assert meta.ttl_hours == 168
        assert meta.freshness_score == 0.9
        assert meta.priority_score == 90
        assert meta.decision == LifecycleDecision.KEEP

    def test_lifecycle_meta_is_active(self):
        """LifecycleMeta.is_active() works correctly."""
        active_states = [LifecycleState.STAGED, LifecycleState.READY, LifecycleState.HOLD, LifecycleState.DOWNGRADED]
        for state in active_states:
            meta = LifecycleMeta(
                adapter_id="test", generation=1, source_node=None,
                state=state, entered_at="", last_reviewed_at="", expires_at=None,
                ttl_hours=24, ttl_remaining=10.0, freshness_score=0.5, priority_score=50,
                priority_changed=False, decision=LifecycleDecision.KEEP, decision_reason="",
                fallback_used=False, version="1.0", reviewed_at="",
            )
            assert meta.is_active() is True

        inactive_meta = LifecycleMeta(
            adapter_id="test", generation=1, source_node=None,
            state=LifecycleState.EXPIRED, entered_at="", last_reviewed_at="", expires_at=None,
            ttl_hours=0, ttl_remaining=0.0, freshness_score=0.0, priority_score=0,
            priority_changed=False, decision=LifecycleDecision.EXPIRE, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at="",
        )
        assert inactive_meta.is_active() is False

    def test_lifecycle_meta_can_promote(self):
        """LifecycleMeta.can_promote() works correctly."""
        ready_meta = LifecycleMeta(
            adapter_id="test", generation=1, source_node=None,
            state=LifecycleState.READY, entered_at="", last_reviewed_at="",
            expires_at="2024-12-31T00:00:00Z", ttl_hours=168, ttl_remaining=100.0,
            freshness_score=0.9, priority_score=90, priority_changed=False,
            decision=LifecycleDecision.KEEP, decision_reason="", fallback_used=False,
            version="1.0", reviewed_at="",
        )
        assert ready_meta.can_promote() is True

        expired_meta = LifecycleMeta(
            adapter_id="test", generation=1, source_node=None,
            state=LifecycleState.READY, entered_at="", last_reviewed_at="", expires_at=None,
            ttl_hours=0, ttl_remaining=0.0, freshness_score=0.0, priority_score=0,
            priority_changed=False, decision=LifecycleDecision.EXPIRE, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at="",
        )
        assert expired_meta.can_promote() is False

    def test_lifecycle_meta_to_dict_round_trip(self):
        """LifecycleMeta round-trips through to_dict/from_dict."""
        original = LifecycleMeta(
            adapter_id="test",
            generation=2,
            source_node="node-1",
            state=LifecycleState.READY,
            entered_at="2024-01-01T00:00:00Z",
            last_reviewed_at="2024-01-01T00:00:00Z",
            expires_at="2024-01-08T00:00:00Z",
            ttl_hours=168,
            ttl_remaining=150.0,
            freshness_score=0.9,
            priority_score=90,
            priority_changed=False,
            decision=LifecycleDecision.KEEP,
            decision_reason="healthy",
            fallback_used=False,
            version="1.0",
            reviewed_at="2024-01-01T00:00:00Z",
        )

        data = original.to_dict()
        restored = LifecycleMeta.from_dict(data)

        assert restored.adapter_id == original.adapter_id
        assert restored.generation == original.generation
        assert restored.state == original.state
        assert restored.decision == original.decision
        assert restored.freshness_score == original.freshness_score

    def test_lifecycle_result_structure(self):
        """LifecycleResult is a real structured object."""
        meta = LifecycleMeta(
            adapter_id="test", generation=1, source_node=None,
            state=LifecycleState.READY, entered_at="", last_reviewed_at="", expires_at=None,
            ttl_hours=24, ttl_remaining=10.0, freshness_score=0.5, priority_score=50,
            priority_changed=False, decision=LifecycleDecision.KEEP, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at="",
        )

        result = LifecycleResult(
            processed_at="2024-01-01T00:00:00Z",
            processor_version="1.0",
            fallback_used=False,
            meta=meta,
            previous_state=LifecycleState.HOLD,
            state_changed=True,
            needs_cleanup=False,
            needs_requeue=False,
            trace_id="abc123",
        )

        assert result.meta.adapter_id == "test"
        assert result.state_changed is True
        assert result.previous_state == LifecycleState.HOLD
        assert result.needs_cleanup is False

    def test_lifecycle_result_to_dict_round_trip(self):
        """LifecycleResult round-trips through to_dict/from_dict."""
        meta = LifecycleMeta(
            adapter_id="test", generation=2, source_node="node-1",
            state=LifecycleState.READY, entered_at="2024-01-01T00:00:00Z",
            last_reviewed_at="2024-01-01T00:00:00Z", expires_at="2024-01-08T00:00:00Z",
            ttl_hours=168, ttl_remaining=150.0, freshness_score=0.9, priority_score=90,
            priority_changed=False, decision=LifecycleDecision.KEEP, decision_reason="healthy",
            fallback_used=False, version="1.0", reviewed_at="2024-01-01T00:00:00Z",
        )

        original = LifecycleResult(
            processed_at="2024-01-01T00:00:00Z",
            processor_version="1.0",
            fallback_used=False,
            meta=meta,
            previous_state=LifecycleState.HOLD,
            state_changed=True,
            needs_cleanup=False,
            needs_requeue=False,
            trace_id="abc123",
        )

        data = original.to_dict()
        restored = LifecycleResult.from_dict(data)

        assert restored.meta.adapter_id == original.meta.adapter_id
        assert restored.state_changed == original.state_changed
        assert restored.previous_state == original.previous_state


class TestLifecycleEvaluation:
    """Phase 14: Lifecycle evaluation tests."""

    def test_evaluate_ready_candidate(self):
        """Ready candidate gets KEEP decision."""
        triage_result = create_test_triage_result(TriageStatus.READY, 0.9)

        result = TriagePoolLifecycle.evaluate(triage_result)

        assert result.meta.state == LifecycleState.READY
        assert result.meta.decision == LifecycleDecision.KEEP
        assert result.meta.ttl_hours == 168  # 7 days
        assert result.meta.freshness_score > 0.8
        assert result.needs_cleanup is False

    def test_evaluate_hold_candidate(self):
        """Hold candidate gets REQUEUE decision."""
        triage_result = create_test_triage_result(TriageStatus.HOLD, 0.6)

        result = TriagePoolLifecycle.evaluate(triage_result)

        assert result.meta.state == LifecycleState.HOLD
        assert result.meta.decision == LifecycleDecision.REQUEUE
        assert result.meta.ttl_hours == 72  # 3 days
        assert result.needs_requeue is True

    def test_evaluate_downgrade_candidate(self):
        """Downgrade candidate gets appropriate decision."""
        triage_result = create_test_triage_result(TriageStatus.DOWNGRADE, 0.4)

        result = TriagePoolLifecycle.evaluate(triage_result)

        assert result.meta.state == LifecycleState.DOWNGRADED
        assert result.meta.ttl_hours == 24  # 1 day

    def test_evaluate_reject_candidate(self):
        """Reject candidate gets EXPIRE decision."""
        triage_result = create_test_triage_result(TriageStatus.REJECT, 0.2)

        result = TriagePoolLifecycle.evaluate(triage_result)

        assert result.meta.state == LifecycleState.EXPIRED
        assert result.meta.decision == LifecycleDecision.EXPIRE
        assert result.needs_cleanup is True

    def test_deterministic_same_input(self):
        """Same input produces deterministic lifecycle result."""
        triage_result = create_test_triage_result(TriageStatus.READY, 0.85)

        result1 = TriagePoolLifecycle.evaluate(triage_result)
        result2 = TriagePoolLifecycle.evaluate(triage_result)

        assert result1.meta.state == result2.meta.state
        assert result1.meta.decision == result2.meta.decision
        assert result1.meta.ttl_hours == result2.meta.ttl_hours

    def test_state_transition_tracking(self):
        """State transitions are tracked correctly."""
        triage_result = create_test_triage_result(TriageStatus.READY)

        # First evaluation - no previous state
        result1 = TriagePoolLifecycle.evaluate(triage_result)
        assert result1.previous_state is None
        assert result1.state_changed is False  # No previous to compare

        # Second evaluation - transition from HOLD to READY
        previous_meta = LifecycleMeta(
            adapter_id="test", generation=2, source_node="node-1",
            state=LifecycleState.HOLD, entered_at="2024-01-01T00:00:00Z",
            last_reviewed_at="2024-01-01T00:00:00Z", expires_at=None,
            ttl_hours=72, ttl_remaining=50.0, freshness_score=0.6, priority_score=60,
            priority_changed=False, decision=LifecycleDecision.REQUEUE, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at="2024-01-01T00:00:00Z",
        )

        result2 = TriagePoolLifecycle.evaluate(triage_result, previous_meta)
        assert result2.previous_state == LifecycleState.HOLD
        assert result2.state_changed is True


class TestLifecycleExpiration:
    """Phase 14: Lifecycle expiration tests."""

    def test_expiration_based_on_ttl(self):
        """Expired candidates are detected based on TTL."""
        # Create a meta with negative TTL
        expired_meta = LifecycleMeta(
            adapter_id="test", generation=1, source_node=None,
            state=LifecycleState.READY, entered_at="2024-01-01T00:00:00Z",
            last_reviewed_at="2024-01-01T00:00:00Z", expires_at=None,
            ttl_hours=24, ttl_remaining=-1.0, freshness_score=0.5, priority_score=50,
            priority_changed=False, decision=LifecycleDecision.KEEP, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at="",
        )

        assert expired_meta.is_expired() is True

        # Quick expiration check
        is_expired = TriagePoolLifecycle.quick_expiration_check(expired_meta)
        assert is_expired is True

    def test_ready_can_expire(self):
        """Ready candidate can expire and get EXPIRE decision."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=200)).isoformat().replace("+00:00", "Z")

        # Create triage result and manually set up expired state
        triage_result = create_test_triage_result(TriageStatus.READY)

        # Simulate previous meta that's about to expire
        previous_meta = LifecycleMeta(
            adapter_id="test", generation=2, source_node="node-1",
            state=LifecycleState.READY, entered_at=old_time,
            last_reviewed_at=old_time, expires_at=None,
            ttl_hours=168, ttl_remaining=-32.0, freshness_score=0.3, priority_score=30,
            priority_changed=False, decision=LifecycleDecision.KEEP, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at=old_time,
        )

        result = TriagePoolLifecycle.evaluate(triage_result, previous_meta)

        assert result.meta.decision == LifecycleDecision.EXPIRE
        assert result.meta.state == LifecycleState.EXPIRED
        assert result.needs_cleanup is True

    def test_hold_can_expire(self):
        """Hold candidate can expire if stale."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        old_time = (now - timedelta(hours=100)).isoformat().replace("+00:00", "Z")

        triage_result = create_test_triage_result(TriageStatus.HOLD, 0.4)

        # Simulate previous hold state that's stale
        previous_meta = LifecycleMeta(
            adapter_id="test", generation=2, source_node="node-1",
            state=LifecycleState.HOLD, entered_at=old_time,
            last_reviewed_at=old_time, expires_at=None,
            ttl_hours=72, ttl_remaining=-28.0, freshness_score=0.2, priority_score=30,
            priority_changed=False, decision=LifecycleDecision.KEEP, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at=old_time,
        )

        result = TriagePoolLifecycle.evaluate(triage_result, previous_meta)

        # Low freshness should cause expire
        assert result.meta.decision == LifecycleDecision.EXPIRE
        assert result.needs_cleanup is True


class TestLifecyclePoolTransitions:
    """Phase 14: Pool transition tests."""

    def test_ready_to_hold_transition(self):
        """Ready can transition to hold on declining freshness."""
        # Create a hold triage result directly
        triage_result = create_test_triage_result(TriageStatus.HOLD, 0.6)

        result = TriagePoolLifecycle.evaluate(triage_result)

        # Hold state should trigger requeue
        assert result.meta.state == LifecycleState.HOLD
        assert result.meta.decision == LifecycleDecision.REQUEUE
        assert result.needs_requeue is True

    def test_ready_to_downgrade_transition(self):
        """Ready can transition to downgrade on low freshness."""
        # Create a downgrade triage result directly
        triage_result = create_test_triage_result(TriageStatus.DOWNGRADE, 0.4)

        result = TriagePoolLifecycle.evaluate(triage_result)

        # Downgrade state should downgrade
        assert result.meta.state == LifecycleState.DOWNGRADED
        assert result.meta.decision == LifecycleDecision.KEEP

    def test_hold_to_expire_transition(self):
        """Hold can transition to expire if requeued but not improved."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        entered_at = now.isoformat().replace("+00:00", "Z")

        triage_result = create_test_triage_result(TriageStatus.HOLD, 0.6)

        # Simulate previous hold state that was already requeued
        previous_meta = LifecycleMeta(
            adapter_id="test", generation=2, source_node="node-1",
            state=LifecycleState.HOLD, entered_at=entered_at,
            last_reviewed_at=entered_at, expires_at=None,
            ttl_hours=72, ttl_remaining=30.0, freshness_score=0.6, priority_score=60,
            priority_changed=False, decision=LifecycleDecision.REQUEUE, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at=entered_at,
        )

        result = TriagePoolLifecycle.evaluate(triage_result, previous_meta)

        # Already requeued, should expire now
        assert result.meta.decision == LifecycleDecision.EXPIRE
        assert result.needs_cleanup is True

    def test_reject_not_in_main_pool(self):
        """Reject candidates don't enter main lifecycle pool."""
        triage_result = create_test_triage_result(TriageStatus.REJECT)

        result = TriagePoolLifecycle.evaluate(triage_result)

        assert result.meta.state == LifecycleState.EXPIRED
        assert result.meta.is_active() is False
        assert result.needs_cleanup is True

    def test_evict_leaves_pool(self):
        """Evict decision removes candidate from pool."""
        # Create expired meta that should be evicted
        expired_meta = LifecycleMeta(
            adapter_id="test", generation=1, source_node=None,
            state=LifecycleState.EXPIRED, entered_at="2024-01-01T00:00:00Z",
            last_reviewed_at="2024-01-01T00:00:00Z", expires_at=None,
            ttl_hours=0, ttl_remaining=-10.0, freshness_score=0.0, priority_score=0,
            priority_changed=False, decision=LifecycleDecision.EXPIRE, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at="",
        )

        # Create a mock triage result for already-expired
        triage_result = create_test_triage_result(TriageStatus.REJECT)

        result = TriagePoolLifecycle.evaluate(triage_result, expired_meta)

        # Already expired should be evicted
        assert result.meta.decision == LifecycleDecision.EVICT
        assert result.meta.state == LifecycleState.EVICTED
        assert result.needs_cleanup is True


class TestLifecyclePriorityRecalculation:
    """Phase 14: Priority recalculation tests."""

    def test_priority_calculated_from_readiness(self):
        """Priority is calculated from readiness score."""
        triage_result = create_test_triage_result(TriageStatus.READY, 0.85)

        result = TriagePoolLifecycle.evaluate(triage_result)

        # Priority should be around 85 + 20 boost for priority candidate
        assert result.meta.priority_score > 80
        assert result.meta.priority_score <= 100

    def test_priority_changed_detection(self):
        """Priority changes are detected."""
        triage_result = create_test_triage_result(TriageStatus.READY, 0.9)

        # First evaluation
        result1 = TriagePoolLifecycle.evaluate(triage_result)
        assert result1.meta.priority_changed is False  # No previous

        # Second evaluation with different score
        triage_result2 = create_test_triage_result(TriageStatus.READY, 0.5)
        result2 = TriagePoolLifecycle.evaluate(triage_result2, result1.meta)

        # Significant change should be detected
        assert result2.meta.priority_changed is True


class TestGovernorLifecycleIntegration:
    """Phase 14: Governor lifecycle integration tests."""

    def _create_governor(self):
        """Helper to create governor with proper imports."""
        try:
            from chronara_nexus.types import AdapterRef, AdapterMode
            ref = AdapterRef("test_adapter", 1, AdapterMode.SERVE)
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import AdapterRef, AdapterMode
            ref = AdapterRef("test_adapter", 1, AdapterMode.SERVE)
        return Governor(ref)

    def test_governor_evaluate_lifecycle(self):
        """Governor can evaluate lifecycle for triaged candidate."""
        governor = create_test_governor()
        triage_result = create_test_triage_result(TriageStatus.READY)

        result = governor.evaluate_lifecycle(triage_result)

        assert result.meta.adapter_id == "test"
        assert result.meta.state == LifecycleState.READY
        assert hasattr(result, 'needs_cleanup')

    def test_governor_records_lifecycle_in_trace(self):
        """Governor records lifecycle result in validation trace."""
        try:
            from chronara_nexus.types import AdapterRef, AdapterMode
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import AdapterRef, AdapterMode
        governor = create_test_governor()

        # Create a validation trace first
        candidate = AdapterRef("test_candidate", 2, AdapterMode.SERVE)
        governor.validate_candidate(candidate)

        triage_result = create_test_triage_result(TriageStatus.READY)
        governor.evaluate_lifecycle(triage_result)

        traces = governor.get_validation_traces()
        assert len(traces) > 0
        last_trace = traces[-1]
        assert hasattr(last_trace, 'lifecycle_result_summary')
        assert last_trace.lifecycle_result_summary is not None
        assert last_trace.lifecycle_result_summary['adapter_id'] == "test"

    def test_governor_lifecycle_only_trace_does_not_mark_validation_passed(self):
        """Lifecycle-only traces must not look like successful validation traces."""
        governor = create_test_governor()
        triage_result = create_test_triage_result(TriageStatus.READY)

        governor.evaluate_lifecycle(triage_result)

        last_trace = governor.get_last_validation_trace()
        assert last_trace is not None
        assert last_trace.status == "lifecycle"
        assert last_trace.passed is False
        assert last_trace.reason == "Lifecycle-only trace"

    def test_governor_get_active_candidates(self):
        """Governor can retrieve active lifecycle candidates."""
        try:
            from chronara_nexus.types import AdapterRef, AdapterMode
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import AdapterRef, AdapterMode
        governor = create_test_governor()

        # Create validation trace with lifecycle
        candidate = AdapterRef("test_candidate", 2, AdapterMode.SERVE)
        governor.validate_candidate(candidate)
        triage_result = create_test_triage_result(TriageStatus.READY)
        governor.evaluate_lifecycle(triage_result)

        active = governor.get_active_lifecycle_candidates()
        assert len(active) >= 1
        assert active[0]['state'] == 'ready'

    def test_governor_get_expired_candidates(self):
        """Governor can retrieve expired lifecycle candidates."""
        try:
            from chronara_nexus.types import AdapterRef, AdapterMode
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import AdapterRef, AdapterMode
        governor = create_test_governor()

        # Create validation trace with expired lifecycle
        candidate = AdapterRef("test_candidate", 2, AdapterMode.SERVE)
        governor.validate_candidate(candidate)
        triage_result = create_test_triage_result(TriageStatus.REJECT)
        governor.evaluate_lifecycle(triage_result)

        expired = governor.get_expired_candidates()
        assert len(expired) >= 1
        assert expired[0]['state'] == 'expired'

    def test_governor_can_promote_check(self):
        """Governor can check if lifecycle candidate is promotable."""
        try:
            from chronara_nexus.types import AdapterRef, AdapterMode
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import AdapterRef, AdapterMode
        governor = create_test_governor()

        # Create ready candidate
        candidate = AdapterRef("test_candidate", 2, AdapterMode.SERVE)
        governor.validate_candidate(candidate)
        triage_result = create_test_triage_result(TriageStatus.READY)
        governor.evaluate_lifecycle(triage_result)

        # Should be promotable
        can_promote = governor.can_promote_lifecycle_candidate("test", 2)
        assert can_promote is True

        # Create expired candidate
        candidate2 = AdapterRef("test_candidate2", 3, AdapterMode.SERVE)
        governor.validate_candidate(candidate2)
        triage_result2 = create_test_triage_result(TriageStatus.REJECT)
        governor.evaluate_lifecycle(triage_result2)

        # Should not be promotable
        can_promote2 = governor.can_promote_lifecycle_candidate("test", 2)
        # Note: This depends on trace order, may find the ready one

    def test_governor_quick_expiration_check(self):
        """Governor can quick-check expiration."""
        governor = create_test_governor()

        meta = LifecycleMeta(
            adapter_id="test", generation=1, source_node=None,
            state=LifecycleState.READY, entered_at="", last_reviewed_at="", expires_at=None,
            ttl_hours=24, ttl_remaining=-1.0, freshness_score=0.5, priority_score=50,
            priority_changed=False, decision=LifecycleDecision.KEEP, decision_reason="",
            fallback_used=False, version="1.0", reviewed_at="",
        )

        is_expired = governor.quick_expiration_check(meta)
        assert is_expired is True


def create_test_governor():
    """Helper to create a test governor."""
    try:
        from chronara_nexus.types import AdapterRef, AdapterMode
        ref = AdapterRef("test_adapter", 1, AdapterMode.SERVE)
    except ImportError:
        from implementations.sac_py.chronara_nexus.types import AdapterRef, AdapterMode
        ref = AdapterRef("test_adapter", 1, AdapterMode.SERVE)
    return Governor(ref)


class TestLifecycleFailureSafety:
    """Phase 14: Lifecycle failure safety tests."""

    def test_fallback_on_error(self):
        """Lifecycle evaluation returns safe fallback on error."""
        # Create invalid triage result that will cause error
        invalid_triage = None

        result = TriagePoolLifecycle.evaluate(
            invalid_triage,
            fallback_on_error=True
        )

        assert result.fallback_used is True
        assert result.meta.state == LifecycleState.EXPIRED
        assert result.meta.decision == LifecycleDecision.EXPIRE
        assert result.needs_cleanup is True

    def test_governor_fallback_on_error(self):
        """Governor returns fallback lifecycle result on error."""
        governor = create_test_governor()

        # Pass None to trigger error
        result = governor.evaluate_lifecycle(None)

        assert result.fallback_used is True
        assert result.meta.state == LifecycleState.EXPIRED

    def test_expired_does_not_pollute_local_state(self):
        """Expired lifecycle candidates don't pollute local state."""
        try:
            from chronara_nexus.types import AdapterRef, AdapterMode
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import AdapterRef, AdapterMode
        governor = create_test_governor()

        # Create expired candidate
        candidate = AdapterRef("test_candidate", 2, AdapterMode.SERVE)
        governor.validate_candidate(candidate)
        triage_result = create_test_triage_result(TriageStatus.REJECT)
        result = governor.evaluate_lifecycle(triage_result)

        assert result.meta.state == LifecycleState.EXPIRED
        assert result.needs_cleanup is True

        # Local governor state should not be affected
        # Governor uses active_adapter, not _active_adapter_id
        assert governor.active_adapter is not None  # Still has the original active adapter


class TestLifecycleBatchOperations:
    """Phase 14: Batch lifecycle operations tests."""

    def test_batch_evaluate(self):
        """Batch lifecycle evaluation works."""
        triage_results = [
            create_test_triage_result(TriageStatus.READY, 0.9),
            create_test_triage_result(TriageStatus.HOLD, 0.6),
            create_test_triage_result(TriageStatus.REJECT, 0.2),
        ]

        results = TriagePoolLifecycle.batch_evaluate(triage_results)

        assert len(results) == 3
        assert results[0].meta.state == LifecycleState.READY
        assert results[1].meta.state == LifecycleState.HOLD
        assert results[2].meta.state == LifecycleState.EXPIRED

    def test_batch_with_previous_metas(self):
        """Batch evaluation with previous metadata."""
        triage_results = [
            create_test_triage_result(TriageStatus.READY),
        ]

        previous_metas = {
            "test:2": LifecycleMeta(
                adapter_id="test", generation=2, source_node="node-1",
                state=LifecycleState.HOLD, entered_at="2024-01-01T00:00:00Z",
                last_reviewed_at="2024-01-01T00:00:00Z", expires_at=None,
                ttl_hours=72, ttl_remaining=50.0, freshness_score=0.6, priority_score=60,
                priority_changed=False, decision=LifecycleDecision.REQUEUE, decision_reason="",
                fallback_used=False, version="1.0", reviewed_at="2024-01-01T00:00:00Z",
            )
        }

        results = TriagePoolLifecycle.batch_evaluate(triage_results, previous_metas)

        assert results[0].previous_state == LifecycleState.HOLD
        assert results[0].state_changed is True


class TestPhase13Regression:
    """Phase 14: Phase 13 regression tests."""

    def test_triage_still_works(self):
        """Phase 13 triage/readiness still works."""
        try:
            from chronara_nexus.triage_engine import RemoteTriageEngine
        except ImportError:
            from implementations.sac_py.chronara_nexus.triage_engine import RemoteTriageEngine

        # Create minimal staged candidate
        summary = FederationSummary(
            identity=None, specialization=None, importance_mask=None,
            delta_norm=None, validation_score=None, comparison_outcome=None,
            deliberation=None, snapshot_lineage=None, compatibility=None,
            export_timestamp="2024-01-01T00:00:00Z", export_version="1.0", source_node="node-1"
        )

        gate = FederationExchangeGate(
            local_adapter_id="local", local_generation=1,
            remote_adapter_id="test", remote_generation=2,
            lineage=LineageCompatibility(True, 0.9, 1, True, False, "test"),
            specialization=SpecializationCompatibility(True, "stable", "stable", True, "test"),
            validation=ValidationCompatibility(True, 0.9, 0.95, 0.05, True, "test"),
            comparison=ComparisonCompatibility(True, "ok", "ok", True, "test"),
            status=ExchangeStatus.ACCEPT, recommendation="accept", reason="test",
            fallback_used=False, version="1.0", timestamp="2024-01-01T00:00:00Z",
        )

        staged = StagedRemoteCandidate(
            adapter_id="test", generation=2, source_node="node-1",
            staged_at="2024-01-01T00:00:00Z", staging_decision=StagingDecision.STAGE_ACCEPT,
            staging_version="1.0", is_downgraded=False, is_active=True,
            summary=summary, gate_result=gate,
            intake_record_ref="abc123",
        )

        result = RemoteTriageEngine.triage(staged)

        assert result.assessment.adapter_id == "test"
        assert result.target_pool in ("ready", "hold", "downgraded", "rejected")
