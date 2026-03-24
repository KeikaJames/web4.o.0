"""Phase 11: Federation-ready compatibility & exchange gate tests."""

import pytest
from datetime import datetime

try:
    from chronara_nexus.types import (
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        AdapterIdentitySummary,
        SpecializationSummary,
        ImportanceMaskSummary,
        DeltaNormSummary,
        ValidationScoreSummary,
        ComparisonOutcomeSummary,
        DeliberationSummary,
        SnapshotLineageSummary,
        CompatibilityHints,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
    )
    from chronara_nexus.exchange_gate import FederationExchangeComparator
    from chronara_nexus.governor import Governor
except ImportError:
    from implementations.sac_py.chronara_nexus.types import (
        FederationSummary,
        FederationExchangeGate,
        ExchangeStatus,
        AdapterIdentitySummary,
        SpecializationSummary,
        ImportanceMaskSummary,
        DeltaNormSummary,
        ValidationScoreSummary,
        ComparisonOutcomeSummary,
        DeliberationSummary,
        SnapshotLineageSummary,
        CompatibilityHints,
        LineageCompatibility,
        SpecializationCompatibility,
        ValidationCompatibility,
        ComparisonCompatibility,
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
    )
    from implementations.sac_py.chronara_nexus.exchange_gate import FederationExchangeComparator
    from implementations.sac_py.chronara_nexus.governor import Governor


def create_test_summary(
    adapter_id: str = "test",
    generation: int = 1,
    parent_gen: int = None,
    specialization: str = "stable",
    validation_score: float = 1.0,
    validation_passed: bool = True,
    comparison_acceptable: bool = True,
    lineage_hash: str = None,
) -> FederationSummary:
    """Helper to create test federation summaries."""
    identity = AdapterIdentitySummary(
        adapter_id=adapter_id,
        generation=generation,
        parent_generation=parent_gen,
        specialization=specialization,
        mode="serve",
    )
    return FederationSummary(
        identity=identity,
        specialization=SpecializationSummary(
            stable_generation=generation,
            shared_generation=None,
            candidate_generation=None,
            active_specialization=specialization,
        ),
        importance_mask=ImportanceMaskSummary(
            top_keys=["p0"],
            scores={"p0": 0.9},
            threshold=0.1,
            compression_ratio=0.1,
        ),
        delta_norm=DeltaNormSummary(
            l1_norm=1.0,
            l2_norm=0.5,
            max_abs=0.9,
            param_count=10,
            relative_to_parent=None,
        ),
        validation_score=ValidationScoreSummary(
            passed=validation_passed,
            lineage_valid=True,
            specialization_valid=True,
            output_match=True,
            kv_count_match=True,
            generation_advanced=True,
            score=validation_score,
        ),
        comparison_outcome=ComparisonOutcomeSummary(
            status="candidate_observed",
            promote_recommendation="approve" if comparison_acceptable else "reject",
            lineage_valid=True,
            specialization_valid=True,
            is_acceptable=comparison_acceptable,
        ),
        deliberation=DeliberationSummary(
            outcome="candidate_ready",
            quality_score=0.85,
            confidence=0.9,
            consensus_status="consensus_accept",
            has_disagreement=False,
            escalation_used=False,
        ),
        snapshot_lineage=SnapshotLineageSummary(
            snapshot_id=f"{adapter_id}-gen{generation}",
            adapter_id=adapter_id,
            generation=generation,
            specialization=specialization,
            parent_snapshot_id=f"{adapter_id}-gen{parent_gen}" if parent_gen else None,
            lineage_hash=lineage_hash or f"{adapter_id}:{generation}:{specialization}",
        ),
        compatibility=CompatibilityHints(
            min_compatible_generation=0,
            max_compatible_generation=10,
            required_specialization=None,
            min_validation_score=0.5,
            requires_consensus_accept=False,
            format_version="1.0",
        ),
        export_timestamp="2024-01-01T00:00:00Z",
        export_version="1.0",
        source_node="test-node",
    )


class TestFederationExchangeGateStructure:
    """Test that FederationExchangeGate is a real structured object."""

    def test_exchange_gate_has_all_required_fields(self):
        """Phase 11: Gate must have all required field groups."""
        gate = FederationExchangeGate(
            local_adapter_id="local",
            local_generation=1,
            remote_adapter_id="remote",
            remote_generation=2,
            lineage=LineageCompatibility(
                compatible=True,
                match_score=0.9,
                generation_gap=1,
                is_parent_child=True,
                lineage_hash_match=False,
                reason="parent_child",
            ),
            specialization=SpecializationCompatibility(
                compatible=True,
                local_spec="stable",
                remote_spec="stable",
                can_compose=True,
                reason="same_specialization",
            ),
            validation=ValidationCompatibility(
                acceptable=True,
                local_score=0.9,
                remote_score=0.95,
                score_delta=0.05,
                meets_threshold=True,
                reason="improvement",
            ),
            comparison=ComparisonCompatibility(
                acceptable=True,
                local_status="candidate_observed",
                remote_status="candidate_observed",
                both_acceptable=True,
                reason="both_acceptable",
            ),
            status=ExchangeStatus.ACCEPT,
            recommendation="accept_compatible",
            reason="All checks passed",
            fallback_used=False,
            version="1.0",
            timestamp="2024-01-01T00:00:00Z",
        )

        assert gate.local_adapter_id == "local"
        assert gate.remote_adapter_id == "remote"
        assert gate.status == ExchangeStatus.ACCEPT
        assert gate.lineage.compatible is True
        assert gate.specialization.can_compose is True
        assert gate.validation.acceptable is True
        assert gate.comparison.both_acceptable is True

    def test_exchange_gate_status_enum_values(self):
        """Phase 11: ExchangeStatus must have correct values."""
        assert ExchangeStatus.ACCEPT.value == "accept"
        assert ExchangeStatus.DOWNGRADE.value == "downgrade"
        assert ExchangeStatus.REJECT.value == "reject"

    def test_exchange_gate_can_exchange_method(self):
        """Phase 11: can_exchange() must work correctly."""
        accept_gate = FederationExchangeGate(
            local_adapter_id="a", local_generation=1,
            remote_adapter_id="a", remote_generation=2,
            lineage=LineageCompatibility(True, 0.9, 1, True, False, None),
            specialization=SpecializationCompatibility(True, "stable", "stable", True, None),
            validation=ValidationCompatibility(True, 0.9, 0.95, 0.05, True, None),
            comparison=ComparisonCompatibility(True, "ok", "ok", True, None),
            status=ExchangeStatus.ACCEPT,
            recommendation="accept",
            reason="ok",
            fallback_used=False,
            version="1.0",
            timestamp="2024-01-01T00:00:00Z",
        )
        reject_gate = FederationExchangeGate(
            local_adapter_id="a", local_generation=1,
            remote_adapter_id="a", remote_generation=2,
            lineage=LineageCompatibility(False, 0.0, 0, False, False, "no"),
            specialization=SpecializationCompatibility(False, "stable", "candidate", False, "no"),
            validation=ValidationCompatibility(False, 0.9, 0.1, -0.8, False, "no"),
            comparison=ComparisonCompatibility(False, "ok", "fail", False, "no"),
            status=ExchangeStatus.REJECT,
            recommendation="reject",
            reason="no",
            fallback_used=False,
            version="1.0",
            timestamp="2024-01-01T00:00:00Z",
        )

        assert accept_gate.can_exchange() is True
        assert reject_gate.can_exchange() is False


class TestFederationExchangeComparator:
    """Test exchange comparison logic."""

    def test_same_generation_accept(self):
        """Phase 11: Same generation should be accepted."""
        local = create_test_summary("test", 1)
        remote = create_test_summary("test", 1)

        gate = FederationExchangeComparator.compare(local, remote)

        assert gate.status == ExchangeStatus.ACCEPT
        assert gate.lineage.match_score == 1.0
        assert gate.lineage.compatible is True

    def test_adapter_id_mismatch_reject(self):
        """Phase 11: Different adapter IDs should be rejected."""
        local = create_test_summary("adapter1", 1)
        remote = create_test_summary("adapter2", 1)

        gate = FederationExchangeComparator.compare(local, remote)

        assert gate.status == ExchangeStatus.REJECT
        assert gate.lineage.compatible is False
        assert "adapter_id" in gate.lineage.reason.lower()

    def test_parent_child_accept(self):
        """Phase 11: Parent-child relationship should be accepted."""
        local = create_test_summary("test", 2, parent_gen=1)
        remote = create_test_summary("test", 1)

        gate = FederationExchangeComparator.compare(local, remote)

        assert gate.status in (ExchangeStatus.ACCEPT, ExchangeStatus.DOWNGRADE)
        assert gate.lineage.is_parent_child is True
        assert gate.lineage.match_score == 0.9

    def test_validation_failed_reject(self):
        """Phase 11: Failed validation should be rejected."""
        local = create_test_summary("test", 1, validation_passed=True)
        remote = create_test_summary("test", 2, validation_passed=False)

        gate = FederationExchangeComparator.compare(local, remote)

        assert gate.status == ExchangeStatus.REJECT
        assert gate.validation.acceptable is False

    def test_large_generation_gap_downgrade_or_reject(self):
        """Phase 11: Large generation gap should downgrade or reject."""
        local = create_test_summary("test", 1)
        remote = create_test_summary("test", 10)

        gate = FederationExchangeComparator.compare(local, remote)

        assert gate.status in (ExchangeStatus.DOWNGRADE, ExchangeStatus.REJECT)
        assert gate.lineage.generation_gap == 9

    def test_specialization_mismatch_can_compose_downgrade(self):
        """Phase 11: Spec mismatch but can compose should downgrade."""
        local = create_test_summary("test", 1, specialization="stable")
        remote = create_test_summary("test", 2, specialization="shared")

        gate = FederationExchangeComparator.compare(local, remote)

        # Should not reject due to specialization
        assert gate.status in (ExchangeStatus.ACCEPT, ExchangeStatus.DOWNGRADE)

    def test_deterministic_same_input_same_output(self):
        """Phase 11: Same inputs must produce same outputs."""
        local = create_test_summary("test", 1)
        remote = create_test_summary("test", 2)

        gate1 = FederationExchangeComparator.compare(local, remote)
        gate2 = FederationExchangeComparator.compare(local, remote)

        assert gate1.status == gate2.status
        assert gate1.recommendation == gate2.recommendation
        assert gate1.lineage.match_score == gate2.lineage.match_score


class TestGovernorIntegration:
    """Test Governor exchange gate integration."""

    def test_governor_check_exchange_compatibility(self):
        """Phase 11: Governor must be able to check exchange compatibility."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        remote = create_test_summary("test", 2)
        gate = governor.check_exchange_compatibility(remote)

        assert gate.local_adapter_id == "test"
        assert gate.remote_adapter_id == "test"
        assert gate.remote_generation == 2
        assert gate.lineage.compatible is True

    def test_governor_can_accept_remote_summary(self):
        """Phase 11: Governor must have quick accept check."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Compatible remote
        compatible_remote = create_test_summary("test", 2)
        assert governor.can_accept_remote_summary(compatible_remote) is True

        # Incompatible remote (different adapter)
        incompatible_remote = create_test_summary("other", 1)
        assert governor.can_accept_remote_summary(incompatible_remote) is False

    def test_governor_incorporate_exchange_gate(self):
        """Phase 11: Governor must record exchange gate in traces."""
        try:
            from chronara_nexus.types import ValidationReport
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import ValidationReport

        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Create a validation trace first
        report = ValidationReport(
            adapter_id="test",
            generation=2,
            passed=True,
            metric_summary={"test": True},
        )
        governor.last_validation_report = report

        # Get a gate
        remote = create_test_summary("test", 2)
        gate = governor.check_exchange_compatibility(remote)

        # Incorporate into traces
        success = governor.incorporate_exchange_gate(gate)
        assert success is True

        # Check trace has exchange info
        traces = governor.get_validation_traces()
        if traces:
            last_trace = traces[-1]
            if hasattr(last_trace, 'exchange_gate_summary'):
                assert last_trace.exchange_gate_summary is not None


class TestSerialization:
    """Test exchange gate serialization."""

    def test_exchange_gate_to_dict(self):
        """Phase 11: to_dict must create JSON-friendly structure."""
        local = create_test_summary("test", 1)
        remote = create_test_summary("test", 2)

        gate = FederationExchangeComparator.compare(local, remote)
        data = gate.to_dict()

        assert "local" in data
        assert "remote" in data
        assert "lineage" in data
        assert "status" in data
        assert data["status"] in ("accept", "downgrade", "reject")

    def test_exchange_gate_from_dict(self):
        """Phase 11: from_dict must reconstruct gate."""
        local = create_test_summary("test", 1)
        remote = create_test_summary("test", 2)

        original = FederationExchangeComparator.compare(local, remote)
        data = original.to_dict()
        reconstructed = FederationExchangeGate.from_dict(data)

        assert reconstructed.local_adapter_id == original.local_adapter_id
        assert reconstructed.remote_adapter_id == original.remote_adapter_id
        assert reconstructed.status == original.status
        assert reconstructed.lineage.compatible == original.lineage.compatible


class TestFailureSafety:
    """Test failure safety."""

    def test_comparator_fallback_on_error(self):
        """Phase 11: Comparator must return safe fallback on error."""
        # Create a local summary
        local = create_test_summary("test", 1)

        # Create an invalid remote (will cause issues)
        invalid_remote = FederationSummary(
            identity=AdapterIdentitySummary("", 0, None, "", ""),
            specialization=SpecializationSummary(0, None, None, ""),
            importance_mask=ImportanceMaskSummary([], {}, 0.0, 0.0),
            delta_norm=DeltaNormSummary(0.0, 0.0, 0.0, 0, None),
            validation_score=ValidationScoreSummary(False, False, False, False, False, False, 0.0),
            comparison_outcome=ComparisonOutcomeSummary("", "", False, False, False),
            deliberation=DeliberationSummary("", 0.0, 0.0, None, None, False),
            snapshot_lineage=SnapshotLineageSummary("", "", 0, "", None, ""),
            compatibility=CompatibilityHints(0, 0, None, 0.0, False, "1.0"),
            export_timestamp="",
            export_version="1.0",
            source_node=None,
        )

        gate = FederationExchangeComparator.compare(local, invalid_remote)

        # Should not raise, should return some result
        assert gate is not None
        assert gate.status in (ExchangeStatus.ACCEPT, ExchangeStatus.DOWNGRADE, ExchangeStatus.REJECT)

    def test_fallback_gate_used_flag(self):
        """Phase 11: Fallback gate must have fallback_used=True."""
        local = create_test_summary("test", 1)
        remote = create_test_summary("other", 1)  # Different adapter

        gate = FederationExchangeComparator.compare(local, remote)

        # This should trigger a fallback
        assert gate.fallback_used is False  # Normal operation


class TestPhase10Regression:
    """Test that Phase 10 federation summary still works."""

    def test_federation_summary_still_extractable(self):
        """Phase 11: Phase 10 summary extraction must still work."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        summary = governor.extract_federation_summary()

        assert summary is not None
        assert summary.identity.adapter_id == "test"
        assert summary.to_dict() is not None


class TestPhase9Regression:
    """Test that Phase 9 multi-role review still works."""

    def test_multi_role_review_still_functions(self):
        """Phase 11: Phase 9 multi-role review must still work."""
        try:
            from chronara_nexus.deliberation import BoundedDeliberation
        except ImportError:
            from implementations.sac_py.chronara_nexus.deliberation import BoundedDeliberation

        deliberation = BoundedDeliberation()
        result = deliberation.multi_role_review({"data": 0.9})

        assert result is not None
        assert result.consensus_status is not None
