"""Core types for Chronara adapter evolution."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class AdapterMode(Enum):
    """Adapter execution mode."""
    SERVE = "serve"
    VALIDATION = "validation"
    SHADOW_EVAL = "shadow_eval"


@dataclass
class AdapterRef:
    """Reference to a specific adapter generation."""
    adapter_id: str
    generation: int
    mode: AdapterMode = AdapterMode.SERVE


@dataclass
class AdapterManifest:
    """Adapter metadata and lineage."""
    adapter_id: str
    generation: int
    parent_generation: Optional[int]
    snapshot_ref: Optional[str]
    created_at: float


@dataclass
class SnapshotRef:
    """Reference to adapter parameter snapshot."""
    snapshot_id: str
    adapter_id: str
    generation: int
    byte_size: int


@dataclass
class ValidationReport:
    """Validation result for candidate adapter."""
    adapter_id: str
    generation: int
    passed: bool
    metric_summary: dict
    reason: Optional[str] = None
