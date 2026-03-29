"""Chronara common utilities and shared patterns.

Provides unified helpers for:
- Timestamp generation
- Common metadata fields
- Decision threshold constants
- Safe fallback construction
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, Optional, Type, TypeVar


EnumT = TypeVar("EnumT", bound=Enum)


# =============================================================================
# Timestamp Utilities
# =============================================================================

def utc_now() -> str:
    """Generate UTC timestamp in ISO format with Z suffix.

    Unified helper to replace scattered _utc_now() definitions across modules.
    Format: 2024-01-01T00:00:00Z (compatible with JSON and ISO 8601)
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# =============================================================================
# Common Metadata Fields
# =============================================================================

class CommonMetadata:
    """Shared metadata field constants and helpers.

    Provides unified field names and default values for common fields
    that appear across Result, Trace, and Summary objects.
    """

    # Field names (centralized to avoid typos)
    PROCESSED_AT = "processed_at"
    PROCESSOR_VERSION = "processor_version"
    FALLBACK_USED = "fallback_used"
    VERSION = "version"
    REASON = "reason"
    RECOMMENDATION = "recommendation"
    TIMESTAMP = "timestamp"
    TRACE_ID = "trace_id"

    # Default values
    DEFAULT_VERSION = "1.0"
    DEFAULT_PROCESSOR_VERSION = "1.0"

    @classmethod
    def make_metadata(
        cls,
        processed_at: Optional[str] = None,
        version: str = DEFAULT_VERSION,
        fallback_used: bool = False,
        **extra
    ) -> Dict[str, Any]:
        """Create standardized metadata dictionary.

        Args:
            processed_at: ISO timestamp (defaults to now)
            version: Version string
            fallback_used: Whether fallback was used
            **extra: Additional fields to include

        Returns:
            Standardized metadata dict
        """
        return {
            cls.PROCESSED_AT: processed_at or utc_now(),
            cls.VERSION: version,
            cls.FALLBACK_USED: fallback_used,
            **extra
        }

    @classmethod
    def extract_metadata(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract common metadata fields from dictionary.

        Args:
            data: Source dictionary (may be nested under 'meta')

        Returns:
            Extracted metadata with defaults applied
        """
        # Handle both flat and nested structures
        if "meta" in data:
            source = data["meta"]
        else:
            source = data

        return {
            cls.PROCESSED_AT: source.get(cls.PROCESSED_AT, source.get(cls.TIMESTAMP, utc_now())),
            cls.VERSION: source.get(cls.VERSION, cls.DEFAULT_VERSION),
            cls.FALLBACK_USED: source.get(cls.FALLBACK_USED, False),
        }


# =============================================================================
# Decision Thresholds
# =============================================================================

class DecisionThresholds:
    """Unified decision thresholds for Chronara pipeline stages.

    Centralizes threshold values that were previously scattered across
    TriageEngine, PromotionExecutor, and ExchangeSkeleton.
    """

    # Readiness / compatibility
    MIN_READINESS_SCORE = 0.7
    MIN_VALIDATION_SCORE = 0.6
    MIN_COMPATIBILITY_SCORE = 0.5

    # TTL (hours)
    MIN_TTL_REMAINING_HOURS = 1.0

    # Gate pass thresholds
    MIN_PASSED_GATES_FOR_READY = 6  # Out of 7
    MIN_PASSED_GATES_FOR_HOLD = 4

    @classmethod
    def is_ready(cls, readiness_score: float, passed_gates: int) -> bool:
        """Check if readiness meets 'ready' threshold."""
        return (
            readiness_score >= cls.MIN_READINESS_SCORE
            and passed_gates >= cls.MIN_PASSED_GATES_FOR_READY
        )

    @classmethod
    def is_hold(cls, readiness_score: float, passed_gates: int) -> bool:
        """Check if readiness meets 'hold' threshold."""
        return (
            cls.MIN_VALIDATION_SCORE <= readiness_score < cls.MIN_READINESS_SCORE
            and passed_gates >= cls.MIN_PASSED_GATES_FOR_HOLD
        )

    @classmethod
    def is_compatible(cls, compatibility_score: float) -> bool:
        """Check if compatibility meets threshold."""
        return compatibility_score >= cls.MIN_COMPATIBILITY_SCORE


# =============================================================================
# Safe Fallback Helpers
# =============================================================================

class FallbackBuilder:
    """Builder for safe fallback result dictionaries.

    Provides consistent fallback construction across Result classes.
    """

    @classmethod
    def make_error_metadata(
        cls,
        error_message: str,
        version: str = CommonMetadata.DEFAULT_VERSION,
    ) -> Dict[str, Any]:
        """Create standardized error metadata."""
        return CommonMetadata.make_metadata(
            fallback_used=True,
            version=version,
            error=error_message,
        )

    @classmethod
    def make_rejection_reasoning(
        cls,
        reason: str,
        recommendation: str = "reject_due_to_error",
    ) -> Dict[str, Any]:
        """Create standardized rejection reasoning."""
        return {
            CommonMetadata.REASON: reason,
            CommonMetadata.RECOMMENDATION: recommendation,
        }


# =============================================================================
# Shared Section Builders / Parsers
# =============================================================================

def parse_enum(enum_cls: Type[EnumT], value: Any, default: EnumT) -> EnumT:
    """Parse enum value safely with explicit default."""
    try:
        return enum_cls(value)
    except (ValueError, TypeError):
        return default


def build_reasoning(
    reason: str = "",
    recommendation: str = "",
    **extra: Any,
) -> Dict[str, Any]:
    """Build a standardized reasoning section."""
    return {
        CommonMetadata.REASON: reason,
        CommonMetadata.RECOMMENDATION: recommendation,
        **extra,
    }


def extract_reasoning(
    data: Dict[str, Any],
    nested_key: Optional[str] = "reasoning",
    default_reason: str = "",
    default_recommendation: str = "",
) -> Dict[str, Any]:
    """Extract standardized reason/recommendation fields."""
    source = data.get(nested_key, {}) if nested_key else data
    if not isinstance(source, dict):
        source = {}
    return {
        CommonMetadata.REASON: source.get(CommonMetadata.REASON, default_reason),
        CommonMetadata.RECOMMENDATION: source.get(
            CommonMetadata.RECOMMENDATION,
            default_recommendation,
        ),
    }


def build_meta_section(
    *,
    fallback_used: bool = False,
    version: str = CommonMetadata.DEFAULT_VERSION,
    **extra: Any,
) -> Dict[str, Any]:
    """Build a standardized nested meta section."""
    return {
        CommonMetadata.FALLBACK_USED: fallback_used,
        CommonMetadata.VERSION: version,
        **extra,
    }


def extract_meta_section(
    data: Dict[str, Any],
    *,
    nested_key: Optional[str] = "meta",
    default_version: str = CommonMetadata.DEFAULT_VERSION,
    extra_keys: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """Extract a standardized nested meta section with optional extra fields."""
    source = data.get(nested_key, {}) if nested_key else data
    if not isinstance(source, dict):
        source = {}

    meta = {
        CommonMetadata.FALLBACK_USED: source.get(CommonMetadata.FALLBACK_USED, False),
        CommonMetadata.VERSION: source.get(CommonMetadata.VERSION, default_version),
    }
    for key in extra_keys or []:
        meta[key] = source.get(key)
    return meta


def build_processing_result(
    *,
    processed_at: str,
    processor_version: str,
    fallback_used: bool,
    trace_id: Optional[str] = None,
    **sections: Any,
) -> Dict[str, Any]:
    """Build the common top-level envelope used by Chronara Result objects."""
    result = {
        CommonMetadata.PROCESSED_AT: processed_at,
        CommonMetadata.PROCESSOR_VERSION: processor_version,
        CommonMetadata.FALLBACK_USED: fallback_used,
    }
    result.update(sections)
    if trace_id is not None:
        result[CommonMetadata.TRACE_ID] = trace_id
    return result


def extract_processing_result(
    data: Dict[str, Any],
    *,
    default_version: str = CommonMetadata.DEFAULT_PROCESSOR_VERSION,
) -> Dict[str, Any]:
    """Extract the common top-level Result envelope fields."""
    return {
        CommonMetadata.PROCESSED_AT: data.get(CommonMetadata.PROCESSED_AT, ""),
        CommonMetadata.PROCESSOR_VERSION: data.get(
            CommonMetadata.PROCESSOR_VERSION,
            default_version,
        ),
        CommonMetadata.FALLBACK_USED: data.get(CommonMetadata.FALLBACK_USED, False),
        CommonMetadata.TRACE_ID: data.get(CommonMetadata.TRACE_ID, ""),
    }


# =============================================================================
# Export/Import Helpers
# =============================================================================

def safe_get(data: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Safely get nested value from dictionary.

    Args:
        data: Source dictionary
        *keys: Keys to traverse (handles nested dicts)
        default: Default value if key not found

    Returns:
        Value or default
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key, {})
    return current if current != {} else default


def flatten_nested(
    data: Dict[str, Any],
    *nested_keys: str,
    flat_keys: Optional[list] = None
) -> Dict[str, Any]:
    """Flatten nested structure for easier access.

    Args:
        data: Source dictionary
        *nested_keys: Keys to check for nested structures
        flat_keys: Keys to extract from nested structures

    Returns:
        Flattened dictionary
    """
    result = dict(data)
    flat_keys = flat_keys or ["status", "reason", "recommendation"]

    for nested_key in nested_keys:
        if nested_key in result and isinstance(result[nested_key], dict):
            nested = result.pop(nested_key)
            for key in flat_keys:
                if key in nested:
                    result[f"{nested_key}_{key}"] = nested[key]

    return result
