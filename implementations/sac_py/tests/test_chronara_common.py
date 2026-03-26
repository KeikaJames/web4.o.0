"""Tests for Chronara common utilities.

Tests for shared helpers: utc_now, CommonMetadata, DecisionThresholds, FallbackBuilder, safe_get.
"""

import pytest
from datetime import datetime, timezone

from implementations.sac_py.chronara_nexus.common import (
    utc_now,
    CommonMetadata,
    DecisionThresholds,
    FallbackBuilder,
    safe_get,
    flatten_nested,
)


class TestUtcNow:
    """Test utc_now utility."""

    def test_returns_string(self):
        """utc_now returns a string."""
        result = utc_now()
        assert isinstance(result, str)

    def test_returns_valid_iso_format(self):
        """utc_now returns valid ISO format with Z suffix."""
        result = utc_now()
        # Should end with Z
        assert result.endswith("Z")
        # Should be parseable
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        assert dt.tzinfo is not None

    def test_returns_utc_time(self):
        """utc_now returns UTC time."""
        result = utc_now()
        dt = datetime.fromisoformat(result.replace("Z", "+00:00"))
        # Should be close to current UTC time
        now = datetime.now(timezone.utc)
        diff = abs((now - dt).total_seconds())
        assert diff < 1.0  # Within 1 second

    def test_consistent_format(self):
        """utc_now format is consistent across calls."""
        result1 = utc_now()
        result2 = utc_now()
        # Both should have same format (length)
        assert len(result1) == len(result2)


class TestCommonMetadata:
    """Test CommonMetadata helper."""

    def test_make_metadata_defaults(self):
        """make_metadata provides sensible defaults."""
        meta = CommonMetadata.make_metadata()
        assert CommonMetadata.PROCESSED_AT in meta
        assert CommonMetadata.VERSION in meta
        assert CommonMetadata.FALLBACK_USED in meta
        assert meta[CommonMetadata.VERSION] == CommonMetadata.DEFAULT_VERSION
        assert meta[CommonMetadata.FALLBACK_USED] is False

    def test_make_metadata_custom_values(self):
        """make_metadata accepts custom values."""
        meta = CommonMetadata.make_metadata(
            processed_at="2024-01-01T00:00:00Z",
            version="2.0",
            fallback_used=True,
            custom_field="custom_value",
        )
        assert meta[CommonMetadata.PROCESSED_AT] == "2024-01-01T00:00:00Z"
        assert meta[CommonMetadata.VERSION] == "2.0"
        assert meta[CommonMetadata.FALLBACK_USED] is True
        assert meta["custom_field"] == "custom_value"

    def test_extract_metadata_flat(self):
        """extract_metadata handles flat structure."""
        data = {
            "processed_at": "2024-01-01T00:00:00Z",
            "version": "2.0",
            "fallback_used": True,
        }
        meta = CommonMetadata.extract_metadata(data)
        assert meta["processed_at"] == "2024-01-01T00:00:00Z"
        assert meta["version"] == "2.0"
        assert meta["fallback_used"] is True

    def test_extract_metadata_nested(self):
        """extract_metadata handles nested structure."""
        data = {
            "meta": {
                "processed_at": "2024-01-01T00:00:00Z",
                "version": "2.0",
                "fallback_used": True,
            }
        }
        meta = CommonMetadata.extract_metadata(data)
        assert meta["processed_at"] == "2024-01-01T00:00:00Z"
        assert meta["version"] == "2.0"
        assert meta["fallback_used"] is True

    def test_extract_metadata_defaults(self):
        """extract_metadata provides defaults for missing fields."""
        data = {}
        meta = CommonMetadata.extract_metadata(data)
        assert CommonMetadata.PROCESSED_AT in meta
        assert meta[CommonMetadata.VERSION] == CommonMetadata.DEFAULT_VERSION
        assert meta[CommonMetadata.FALLBACK_USED] is False

    def test_extract_metadata_uses_timestamp_fallback(self):
        """extract_metadata falls back to 'timestamp' field."""
        data = {"timestamp": "2024-06-01T12:00:00Z"}
        meta = CommonMetadata.extract_metadata(data)
        assert meta[CommonMetadata.PROCESSED_AT] == "2024-06-01T12:00:00Z"


class TestDecisionThresholds:
    """Test DecisionThresholds helper."""

    def test_is_ready_true(self):
        """is_ready returns True when thresholds met."""
        assert DecisionThresholds.is_ready(
            readiness_score=0.8,
            passed_gates=6,
        ) is True

    def test_is_ready_false_low_score(self):
        """is_ready returns False when score too low."""
        assert DecisionThresholds.is_ready(
            readiness_score=0.6,
            passed_gates=6,
        ) is False

    def test_is_ready_false_low_gates(self):
        """is_ready returns False when gates too low."""
        assert DecisionThresholds.is_ready(
            readiness_score=0.8,
            passed_gates=5,
        ) is False

    def test_is_hold_true(self):
        """is_hold returns True when in hold range."""
        assert DecisionThresholds.is_hold(
            readiness_score=0.65,
            passed_gates=4,
        ) is True

    def test_is_hold_false_too_high(self):
        """is_hold returns False when score too high."""
        assert DecisionThresholds.is_hold(
            readiness_score=0.8,
            passed_gates=4,
        ) is False

    def test_is_hold_false_too_low(self):
        """is_hold returns False when score too low."""
        assert DecisionThresholds.is_hold(
            readiness_score=0.5,
            passed_gates=4,
        ) is False

    def test_is_compatible_true(self):
        """is_compatible returns True when score meets threshold."""
        assert DecisionThresholds.is_compatible(0.6) is True

    def test_is_compatible_false(self):
        """is_compatible returns False when score below threshold."""
        assert DecisionThresholds.is_compatible(0.4) is False

    def test_threshold_constants(self):
        """Threshold constants are reasonable values."""
        assert 0 < DecisionThresholds.MIN_READINESS_SCORE < 1
        assert 0 < DecisionThresholds.MIN_VALIDATION_SCORE < 1
        assert DecisionThresholds.MIN_PASSED_GATES_FOR_READY > DecisionThresholds.MIN_PASSED_GATES_FOR_HOLD


class TestFallbackBuilder:
    """Test FallbackBuilder helper."""

    def test_make_error_metadata(self):
        """make_error_metadata creates proper error metadata."""
        meta = FallbackBuilder.make_error_metadata("test error")
        assert meta[CommonMetadata.FALLBACK_USED] is True
        assert meta["error"] == "test error"
        assert CommonMetadata.PROCESSED_AT in meta

    def test_make_rejection_reasoning(self):
        """make_rejection_reasoning creates proper reasoning."""
        reasoning = FallbackBuilder.make_rejection_reasoning("bad data")
        assert reasoning[CommonMetadata.REASON] == "bad data"
        assert reasoning[CommonMetadata.RECOMMENDATION] == "reject_due_to_error"

    def test_make_rejection_reasoning_custom(self):
        """make_rejection_reasoning accepts custom recommendation."""
        reasoning = FallbackBuilder.make_rejection_reasoning(
            "bad data",
            recommendation="custom_reject",
        )
        assert reasoning[CommonMetadata.RECOMMENDATION] == "custom_reject"


class TestSafeGet:
    """Test safe_get utility."""

    def test_safe_get_top_level(self):
        """safe_get retrieves top-level key."""
        data = {"key": "value"}
        assert safe_get(data, "key") == "value"

    def test_safe_get_nested(self):
        """safe_get retrieves nested key."""
        data = {"outer": {"inner": "value"}}
        assert safe_get(data, "outer", "inner") == "value"

    def test_safe_get_deeply_nested(self):
        """safe_get retrieves deeply nested key."""
        data = {"a": {"b": {"c": "value"}}}
        assert safe_get(data, "a", "b", "c") == "value"

    def test_safe_get_missing_key(self):
        """safe_get returns default for missing key."""
        data = {"key": "value"}
        assert safe_get(data, "missing") is None
        assert safe_get(data, "missing", default="default") == "default"

    def test_safe_get_missing_nested(self):
        """safe_get returns default for missing nested key."""
        data = {"outer": {"inner": "value"}}
        assert safe_get(data, "outer", "missing") is None

    def test_safe_get_not_dict(self):
        """safe_get handles non-dict in path."""
        data = {"outer": "not_a_dict"}
        assert safe_get(data, "outer", "inner") is None


class TestFlattenNested:
    """Test flatten_nested utility."""

    def test_flatten_nested_basic(self):
        """flatten_nested flattens specified nested keys."""
        data = {
            "name": "test",
            "status_info": {"status": "ready", "reason": "good"},
        }
        result = flatten_nested(data, "status_info")
        assert result["name"] == "test"
        assert result["status_info_status"] == "ready"
        assert result["status_info_reason"] == "good"
        assert "status_info" not in result

    def test_flatten_nested_multiple(self):
        """flatten_nested handles multiple nested keys."""
        data = {
            "a": {"status": "s1"},
            "b": {"status": "s2"},
        }
        result = flatten_nested(data, "a", "b")
        assert result["a_status"] == "s1"
        assert result["b_status"] == "s2"

    def test_flatten_nested_missing_key(self):
        """flatten_nested ignores missing nested keys."""
        data = {"name": "test"}
        result = flatten_nested(data, "missing")
        assert result["name"] == "test"

    def test_flatten_nested_not_dict(self):
        """flatten_nested ignores non-dict nested values."""
        data = {"name": "test", "status_info": "not_a_dict"}
        result = flatten_nested(data, "status_info")
        # Should keep original since it's not a dict
        assert result["status_info"] == "not_a_dict"


class TestCommonIntegration:
    """Integration tests for common utilities."""

    def test_metadata_round_trip(self):
        """Metadata can be created and extracted consistently."""
        original = CommonMetadata.make_metadata(
            version="1.5",
            fallback_used=True,
        )
        # Simulate serialization
        serialized = {"meta": original}
        # Extract
        extracted = CommonMetadata.extract_metadata(serialized)
        assert extracted[CommonMetadata.VERSION] == "1.5"
        assert extracted[CommonMetadata.FALLBACK_USED] is True

    def test_thresholds_with_realistic_values(self):
        """Thresholds work with realistic readiness values."""
        # High readiness -> ready
        assert DecisionThresholds.is_ready(0.85, 7) is True
        # Medium readiness -> hold
        assert DecisionThresholds.is_hold(0.65, 5) is True
        # Low readiness -> neither
        assert DecisionThresholds.is_ready(0.5, 3) is False
        assert DecisionThresholds.is_hold(0.5, 3) is False

    def test_fallback_builder_integration(self):
        """FallbackBuilder integrates with CommonMetadata."""
        error_meta = FallbackBuilder.make_error_metadata("error")
        reasoning = FallbackBuilder.make_rejection_reasoning("reason")

        # Both use CommonMetadata fields
        assert CommonMetadata.FALLBACK_USED in error_meta
        assert CommonMetadata.REASON in reasoning
        assert CommonMetadata.RECOMMENDATION in reasoning
