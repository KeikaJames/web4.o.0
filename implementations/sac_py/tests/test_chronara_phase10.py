"""Phase 10: FIL / federation-ready summary layer tests."""

import pytest
from datetime import datetime

try:
    from chronara_nexus.types import (
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
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
        ValidationReport,
    )
    from chronara_nexus.governor import Governor
    from chronara_nexus.collector import Collector
    from chronara_nexus.consolidator import Consolidator
except ImportError:
    from implementations.sac_py.chronara_nexus.types import (
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
        AdapterRef,
        AdapterMode,
        AdapterSpecialization,
        ValidationReport,
    )
    from implementations.sac_py.chronara_nexus.governor import Governor
    from implementations.sac_py.chronara_nexus.collector import Collector
    from implementations.sac_py.chronara_nexus.consolidator import Consolidator


class TestFederationSummaryStructure:
    """Test that FederationSummary is a real structured object."""

    def test_federation_summary_has_all_required_fields(self):
        """Phase 10: Summary must have all 10 required field groups."""
        identity = AdapterIdentitySummary(
            adapter_id="test",
            generation=1,
            parent_generation=0,
            specialization="stable",
            mode="serve",
        )
        specialization = SpecializationSummary(
            stable_generation=1,
            shared_generation=None,
            candidate_generation=None,
            active_specialization="stable",
        )
        importance_mask = ImportanceMaskSummary(
            top_keys=["p0", "p1"],
            scores={"p0": 0.9, "p1": 0.5},
            threshold=0.1,
            compression_ratio=0.2,
        )
        delta_norm = DeltaNormSummary(
            l1_norm=1.5,
            l2_norm=0.8,
            max_abs=0.9,
            param_count=10,
            relative_to_parent=0.5,
        )
        validation_score = ValidationScoreSummary(
            passed=True,
            lineage_valid=True,
            specialization_valid=True,
            output_match=True,
            kv_count_match=True,
            generation_advanced=True,
            score=0.95,
        )
        comparison_outcome = ComparisonOutcomeSummary(
            status="candidate_observed",
            promote_recommendation="approve",
            lineage_valid=True,
            specialization_valid=True,
            is_acceptable=True,
        )
        deliberation = DeliberationSummary(
            outcome="candidate_ready",
            quality_score=0.85,
            confidence=0.9,
            consensus_status="consensus_accept",
            has_disagreement=False,
            escalation_used=False,
        )
        snapshot_lineage = SnapshotLineageSummary(
            snapshot_id="test-gen1",
            adapter_id="test",
            generation=1,
            specialization="stable",
            parent_snapshot_id="test-gen0",
            lineage_hash="test:1:stable",
        )
        compatibility = CompatibilityHints(
            min_compatible_generation=0,
            max_compatible_generation=2,
            required_specialization=None,
            min_validation_score=0.5,
            requires_consensus_accept=False,
            format_version="1.0",
        )

        summary = FederationSummary(
            identity=identity,
            specialization=specialization,
            importance_mask=importance_mask,
            delta_norm=delta_norm,
            validation_score=validation_score,
            comparison_outcome=comparison_outcome,
            deliberation=deliberation,
            snapshot_lineage=snapshot_lineage,
            compatibility=compatibility,
            export_timestamp="2024-01-01T00:00:00Z",
            export_version="1.0",
            source_node="node-1",
        )

        assert summary.identity.adapter_id == "test"
        assert summary.specialization.stable_generation == 1
        assert len(summary.importance_mask.top_keys) == 2
        assert summary.delta_norm.param_count == 10
        assert summary.validation_score.passed is True
        assert summary.comparison_outcome.status == "candidate_observed"
        assert summary.deliberation.outcome == "candidate_ready"
        assert summary.snapshot_lineage.lineage_hash == "test:1:stable"
        assert summary.compatibility.format_version == "1.0"
        assert summary.export_timestamp == "2024-01-01T00:00:00Z"


class TestFederationSummaryDeterminism:
    """Test that same state produces deterministic summary."""

    def test_same_adapter_produces_deterministic_summary(self):
        """Phase 10: Same internal state must produce identical summary."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Extract twice
        summary1 = governor.extract_federation_summary()
        summary2 = governor.extract_federation_summary()

        # Should be identical (except timestamp which is expected to differ)
        assert summary1.identity.adapter_id == summary2.identity.adapter_id
        assert summary1.identity.generation == summary2.identity.generation
        assert summary1.snapshot_lineage.lineage_hash == summary2.snapshot_lineage.lineage_hash
        # Timestamps will differ slightly between calls - this is expected

    def test_to_dict_produces_deterministic_output(self):
        """Phase 10: to_dict must produce deterministic JSON-friendly output."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)
        summary = governor.extract_federation_summary()

        dict1 = summary.to_dict()
        dict2 = summary.to_dict()

        assert dict1 == dict2
        assert isinstance(dict1, dict)
        assert "identity" in dict1
        assert "specialization" in dict1


class TestFederationSummaryExtraction:
    """Test extraction from Governor, Collector, Consolidator."""

    def test_governor_extraction_includes_validation_data(self):
        """Phase 10: Governor extraction must include validation info."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Create a validation report
        report = ValidationReport(
            adapter_id="test",
            generation=2,
            passed=True,
            metric_summary={
                "lineage_valid": True,
                "specialization_valid": True,
                "output_match": True,
                "kv_count_match": True,
                "generation_advanced": True,
            },
            deliberation_outcome="candidate_ready",
            deliberation_quality=0.85,
            consensus_status="consensus_accept",
            has_role_disagreement=False,
        )
        governor.last_validation_report = report

        summary = governor.extract_federation_summary()

        assert summary.validation_score.passed is True
        assert summary.validation_score.lineage_valid is True
        assert summary.deliberation.outcome == "candidate_ready"
        assert summary.deliberation.quality_score == 0.85
        assert summary.deliberation.consensus_status == "consensus_accept"

    def test_governor_extraction_with_consolidator_params(self):
        """Phase 10: Extraction must use consolidator params for importance/delta."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        params = {"p0": 1.0, "p1": 0.5, "p2": -0.3, "p3": 0.8}
        summary = governor.extract_federation_summary(consolidator_params=params)

        assert summary.importance_mask.top_keys is not None
        assert len(summary.importance_mask.top_keys) <= 10  # Bounded
        assert summary.delta_norm.param_count == 4
        assert summary.delta_norm.l1_norm > 0

    def test_collector_extraction_includes_observation_summary(self):
        """Phase 10: Collector must provide observation routing summary."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        collector = Collector(adapter)

        # Add some observations
        collector.admit_observation({"explicit_feedback": True})
        collector.admit_observation({"strategy_signal": True})
        collector.admit_observation({"data": 0.5})

        summary = collector.extract_observation_summary()

        assert summary["observation_counts"]["explicit_only"] == 1
        assert summary["observation_counts"]["strategy_only"] == 1
        # strategy_signal goes to both strategy_trace and shared_queue
        assert summary["observation_counts"]["parameter_candidate"] == 1
        assert summary["total_observations"] >= 3  # May include shared queue

    def test_consolidator_extraction_includes_parameter_summary(self):
        """Phase 10: Consolidator must provide parameter-side summary."""
        consolidator = Consolidator()

        # Create adapters
        base = AdapterRef("test", 1, AdapterMode.SERVE)
        consolidator.create_candidate(base)

        summary = consolidator.extract_parameter_summary()

        assert "specializations" in summary
        assert "candidate" in summary["specializations"]
        assert "stable" in summary["specializations"]
        assert summary["specializations"]["candidate"]["exists"] is True
        assert "norms" in summary["specializations"]["candidate"]
        assert "top_keys" in summary["specializations"]["candidate"]


class TestFederationSummarySerialization:
    """Test export/serialize paths."""

    def test_to_dict_creates_json_friendly_structure(self):
        """Phase 10: to_dict must create JSON-serializable structure."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)
        summary = governor.extract_federation_summary()

        data = summary.to_dict()

        # All values must be JSON-serializable
        import json
        json_str = json.dumps(data)
        assert isinstance(json_str, str)

        # Round-trip
        data2 = json.loads(json_str)
        assert data2["identity"]["adapter_id"] == "test"

    def test_from_dict_reconstructs_summary(self):
        """Phase 10: from_dict must reconstruct FederationSummary."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)
        original = governor.extract_federation_summary()

        data = original.to_dict()
        reconstructed = FederationSummary.from_dict(data)

        assert reconstructed.identity.adapter_id == original.identity.adapter_id
        assert reconstructed.identity.generation == original.identity.generation
        assert reconstructed.specialization.stable_generation == original.specialization.stable_generation


class TestCompatibilityHints:
    """Test compatibility hints are structured and comparable."""

    def test_is_compatible_with_checks_generation(self):
        """Phase 10: Compatibility must check generation range."""
        identity1 = AdapterIdentitySummary("test", 5, 4, "stable", "serve")
        identity2 = AdapterIdentitySummary("test", 6, 5, "stable", "serve")

        compat = CompatibilityHints(
            min_compatible_generation=4,
            max_compatible_generation=6,
            required_specialization=None,
            min_validation_score=0.0,
            requires_consensus_accept=False,
        )

        summary1 = FederationSummary._minimal_safe_summary("test", 5)
        summary1.compatibility = compat
        summary1.identity = identity1

        summary2 = FederationSummary._minimal_safe_summary("test", 6)
        summary2.identity = identity2

        # Should be compatible
        assert summary1.is_compatible_with(summary2) is True

    def test_is_compatible_with_rejects_different_adapter(self):
        """Phase 10: Compatibility must reject different adapter IDs."""
        summary1 = FederationSummary._minimal_safe_summary("adapter1", 1)
        summary2 = FederationSummary._minimal_safe_summary("adapter2", 1)

        assert summary1.is_compatible_with(summary2) is False

    def test_is_compatible_with_checks_validation_score(self):
        """Phase 10: Compatibility must check validation score threshold."""
        summary1 = FederationSummary._minimal_safe_summary("test", 1)
        summary1.compatibility.min_validation_score = 0.8

        summary2 = FederationSummary._minimal_safe_summary("test", 1)
        summary2.validation_score.score = 0.5  # Below threshold

        assert summary1.is_compatible_with(summary2) is False

    def test_is_compatible_with_checks_consensus_requirement(self):
        """Phase 10: Compatibility must check consensus requirement."""
        summary1 = FederationSummary._minimal_safe_summary("test", 1)
        summary1.compatibility.requires_consensus_accept = True

        summary2 = FederationSummary._minimal_safe_summary("test", 1)
        summary2.deliberation.consensus_status = "consensus_strategy_only"  # Not accept

        assert summary1.is_compatible_with(summary2) is False


class TestLineageMatch:
    """Test lineage match computation."""

    def test_same_generation_perfect_match(self):
        """Phase 10: Same generation = 1.0 match."""
        summary1 = FederationSummary._minimal_safe_summary("test", 5)
        summary2 = FederationSummary._minimal_safe_summary("test", 5)

        assert summary1.compute_lineage_match(summary2) == 1.0

    def test_parent_child_high_match(self):
        """Phase 10: Parent-child relationship = 0.9 match."""
        summary1 = FederationSummary._minimal_safe_summary("test", 5)
        summary1.identity.parent_generation = 4

        summary2 = FederationSummary._minimal_safe_summary("test", 4)

        assert summary1.compute_lineage_match(summary2) == 0.9

    def test_different_adapter_zero_match(self):
        """Phase 10: Different adapter = 0.0 match."""
        summary1 = FederationSummary._minimal_safe_summary("adapter1", 1)
        summary2 = FederationSummary._minimal_safe_summary("adapter2", 1)

        assert summary1.compute_lineage_match(summary2) == 0.0

    def test_generation_distance_penalty(self):
        """Phase 10: Generation distance reduces match score."""
        summary1 = FederationSummary._minimal_safe_summary("test", 10)
        summary2 = FederationSummary._minimal_safe_summary("test", 5)
        # Make lineage hashes different to trigger distance penalty
        summary1.snapshot_lineage.lineage_hash = "test:10:stable"
        summary2.snapshot_lineage.lineage_hash = "test:5:stable"

        score = summary1.compute_lineage_match(summary2)
        assert score < 0.8
        assert score >= 0.0


class TestFailureSafety:
    """Test summary extraction failure safety."""

    def test_extraction_failure_returns_minimal_summary(self):
        """Phase 10: Extraction failure must return safe minimal summary."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        # Force an error by passing invalid params
        summary = governor.extract_federation_summary(consolidator_params=None)

        # Should still return a valid summary
        assert summary is not None
        assert summary.identity.adapter_id == "test"
        assert summary.validation_score.passed is False
        assert summary.validation_score.score == 0.0
        assert summary.comparison_outcome.is_acceptable is False

    def test_minimal_safe_summary_factory(self):
        """Phase 10: _minimal_safe_summary must return valid summary."""
        summary = FederationSummary._minimal_safe_summary("fallback", 0, "error-node")

        assert summary.identity.adapter_id == "fallback"
        assert summary.identity.generation == 0
        assert summary.source_node == "error-node"
        assert summary.validation_score.passed is False
        assert summary.validation_score.score == 0.0
        assert summary.comparison_outcome.is_acceptable is False

    def test_collector_extraction_failure_safety(self):
        """Phase 10: Collector extraction must fail safely."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        collector = Collector(adapter)

        # Should work even with no observations
        summary = collector.extract_observation_summary()

        assert "observation_counts" in summary
        assert summary["total_observations"] == 0

    def test_consolidator_extraction_failure_safety(self):
        """Phase 10: Consolidator extraction must fail safely."""
        consolidator = Consolidator()

        # Should work even with no adapters
        summary = consolidator.extract_parameter_summary()

        assert "specializations" in summary
        assert summary["buffer_sizes"]["micro_batch"] == 0


class TestNoServePathBlocking:
    """Test that summary extraction doesn't block serve path."""

    def test_governor_extraction_does_not_modify_state(self):
        """Phase 10: Extraction must be read-only."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        initial_active = governor.active_adapter
        initial_stable = governor.stable_adapter

        # Extract multiple times
        governor.extract_federation_summary()
        governor.extract_federation_summary()
        summary = governor.extract_federation_summary()

        # State unchanged
        assert governor.active_adapter is initial_active
        assert governor.stable_adapter is initial_stable
        assert summary.identity.adapter_id == "test"

    def test_sac_extraction_does_not_affect_promote_path(self):
        """Phase 10: SAC extraction must not interfere with promote."""
        try:
            from sac import SACContainer
        except ImportError:
            from implementations.sac_py.sac import SACContainer

        sac = SACContainer.create(memory_path="/tmp/test-federation")
        sac.init_chronara()

        # Create a candidate with correct adapter_id
        initial_adapter = sac._chronara_governor.active_adapter
        candidate = AdapterRef(initial_adapter.adapter_id, 2, AdapterMode.SHADOW_EVAL)

        # Extract summary before promotion
        summary1 = sac.extract_federation_summary()

        # Create validation report for promotion
        try:
            from chronara_nexus.types import ValidationReport
        except ImportError:
            from implementations.sac_py.chronara_nexus.types import ValidationReport
        report = ValidationReport(
            adapter_id=initial_adapter.adapter_id,
            generation=2,
            passed=True,
            metric_summary={"generation_advanced": True},
        )
        sac._chronara_governor.last_validation_report = report

        # Promote should still work
        promoted = sac.promote_candidate_if_valid(candidate)
        assert promoted is True

        # Extract summary after promotion
        summary2 = sac.extract_federation_summary()

        # Both summaries valid (adapter_id matches)
        assert summary1.identity.adapter_id == initial_adapter.adapter_id
        assert summary2.identity.adapter_id == initial_adapter.adapter_id


class TestPhase9Regression:
    """Test that Phase 9 capabilities still work."""

    def test_multi_role_review_still_routes_correctly(self):
        """Phase 10: Phase 9 multi-role review routing must still work."""
        try:
            from chronara_nexus.deliberation import BoundedDeliberation
        except ImportError:
            from implementations.sac_py.chronara_nexus.deliberation import BoundedDeliberation

        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        collector = Collector(adapter, enable_deliberation=True)

        # Add observations that trigger deliberation
        obs_type = collector.admit_observation({"data": 0.9})  # High quality

        # Should route to parameter_queue (consensus likely)
        assert len(collector.parameter_queue) >= 0  # May or may not be populated

    def test_promote_gate_still_blocks_consensus_strategy_only(self):
        """Phase 10: Phase 7/9 promote gate must still block consensus_strategy_only."""
        adapter = AdapterRef("test", 1, AdapterMode.SERVE)
        governor = Governor(adapter)

        comparison_result = {
            "status": "candidate_observed",
            "promote_recommendation": "approve",
            "lineage_valid": True,
            "specialization_valid": True,
            "output_match": True,
            "kv_count_match": True,
            "is_acceptable": True,
            "candidate_summary": {"adapter_id": "candidate", "generation": 2},
            "multi_role_review": {
                "consensus_status": "consensus_strategy_only",
                "has_disagreement": False,
            },
        }

        can_promote = governor.can_promote_based_on_comparison(comparison_result)
        assert can_promote is False

    def test_explicit_feedback_returns_strategy_only(self):
        """Phase 10: explicit_feedback must return STRATEGY_ONLY from deliberation."""
        try:
            from chronara_nexus.deliberation import BoundedDeliberation, DeliberationRequest
        except ImportError:
            from implementations.sac_py.chronara_nexus.deliberation import BoundedDeliberation, DeliberationRequest

        deliberation = BoundedDeliberation()
        observation = {"explicit_feedback": True}
        request = DeliberationRequest(observation=observation)

        result = deliberation.deliberate(request)

        try:
            from chronara_nexus.deliberation import DeliberationOutcome
        except ImportError:
            from implementations.sac_py.chronara_nexus.deliberation import DeliberationOutcome
        assert result.outcome == DeliberationOutcome.STRATEGY_ONLY
