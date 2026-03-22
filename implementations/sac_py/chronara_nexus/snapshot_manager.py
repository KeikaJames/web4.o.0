"""Snapshot manager: candidate, window, and stable snapshots."""

from typing import Optional
from .types import SnapshotRef, AdapterRef


class SnapshotManager:
    """Manages adapter snapshots for candidate, window, and stable states."""

    def __init__(self):
        self.candidate_snapshot: Optional[SnapshotRef] = None
        self.window_snapshot: Optional[SnapshotRef] = None
        self.stable_snapshot: Optional[SnapshotRef] = None

    def save_candidate_snapshot(self, adapter: AdapterRef) -> SnapshotRef:
        """Save candidate adapter snapshot."""
        snapshot = SnapshotRef(
            snapshot_id=f"{adapter.adapter_id}-gen{adapter.generation}-candidate",
            adapter_id=adapter.adapter_id,
            generation=adapter.generation,
            byte_size=0
        )
        self.candidate_snapshot = snapshot
        return snapshot

    def save_window_snapshot(self, adapter: AdapterRef) -> SnapshotRef:
        """Save window snapshot."""
        snapshot = SnapshotRef(
            snapshot_id=f"{adapter.adapter_id}-gen{adapter.generation}-window",
            adapter_id=adapter.adapter_id,
            generation=adapter.generation,
            byte_size=0
        )
        self.window_snapshot = snapshot
        return snapshot

    def save_stable_snapshot(self, adapter: AdapterRef) -> SnapshotRef:
        """Save stable snapshot."""
        snapshot = SnapshotRef(
            snapshot_id=f"{adapter.adapter_id}-gen{adapter.generation}-stable",
            adapter_id=adapter.adapter_id,
            generation=adapter.generation,
            byte_size=0
        )
        self.stable_snapshot = snapshot
        return snapshot

    def get_rollback_target(self) -> Optional[SnapshotRef]:
        """Get rollback target (stable snapshot)."""
        return self.stable_snapshot
