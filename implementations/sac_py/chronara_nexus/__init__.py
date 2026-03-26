"""Chronara Nexus: Minimal adapter evolution and memory consolidation."""

from .types import (
    AdapterRef,
    AdapterManifest,
    AdapterSelection,
    SnapshotRef,
    ValidationReport,
    AdapterMode,
    AdapterSpecialization,
    ObservationType,
)
from .collector import Collector
from .consolidator import Consolidator
from .governor import Governor
from .snapshot_manager import SnapshotManager
from .deliberation import (
    BoundedDeliberation,
    DeliberationRequest,
    DeliberationResult,
    DeliberationOutcome,
    MultiRoleReviewResult,
    ReviewConsensusStatus,
    RoleDecision,
    MultiRoleReviewCoordinator,
    Planner,
    Critic,
    Verifier,
    Synthesizer,
)
from .coordinator import (
    FederationCoordinator,
    CoordinationResult,
    CoordinationDecision,
    CoordinationTrace,
    StageResult,
    StageStatus,
)

__all__ = [
    "AdapterRef",
    "AdapterManifest",
    "AdapterSelection",
    "SnapshotRef",
    "ValidationReport",
    "AdapterMode",
    "AdapterSpecialization",
    "Collector",
    "Consolidator",
    "Governor",
    "ObservationType",
    "SnapshotManager",
    "BoundedDeliberation",
    "DeliberationRequest",
    "DeliberationResult",
    "DeliberationOutcome",
    "MultiRoleReviewResult",
    "ReviewConsensusStatus",
    "RoleDecision",
    "MultiRoleReviewCoordinator",
    "Planner",
    "Critic",
    "Verifier",
    "Synthesizer",
    # Phase 20: Federation Coordinator
    "FederationCoordinator",
    "CoordinationResult",
    "CoordinationDecision",
    "CoordinationTrace",
    "StageResult",
    "StageStatus",
]
