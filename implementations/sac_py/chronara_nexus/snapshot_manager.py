"""Snapshot manager: candidate, window, and stable snapshots."""

from typing import Optional, List
from collections import deque
from .types import SnapshotRef, AdapterRef


class SnapshotManager:
    """Manages adapter snapshots for candidate, window, and stable states."""

    def __init__(self):
        self.candidate_snapshot: Optional[SnapshotRef] = None
        self.window_snapshots: deque = deque(maxlen=3)
        self.stable_snapshots: deque = deque(maxlen=5)

    @staticmethod
    def _snapshot_for(adapter: AdapterRef, tier: str) -> SnapshotRef:
        return SnapshotRef(
            snapshot_id=f"{adapter.adapter_id}-gen{adapter.generation}-{tier}",
            adapter_id=adapter.adapter_id,
            generation=adapter.generation,
            byte_size=0,
        )

    def save_candidate_snapshot(self, adapter: AdapterRef) -> SnapshotRef:
        """Save candidate adapter snapshot."""
        snapshot = self._snapshot_for(adapter, "candidate")
        self.candidate_snapshot = snapshot
        return snapshot

    def save_window_snapshot(self, adapter: AdapterRef) -> SnapshotRef:
        """Save window snapshot (keep recent 3)."""
        snapshot = self._snapshot_for(adapter, "window")
        self.window_snapshots.append(snapshot)
        return snapshot

    def save_stable_snapshot(self, adapter: AdapterRef) -> SnapshotRef:
        """Save stable snapshot (keep recent 5)."""
        snapshot = self._snapshot_for(adapter, "stable")
        self.stable_snapshots.append(snapshot)
        return snapshot

    def get_rollback_target(self) -> Optional[SnapshotRef]:
        """Get rollback target (most recent stable snapshot)."""
        if self.stable_snapshots:
            return self.stable_snapshots[-1]
        return None

    def get_window_snapshots(self) -> List[SnapshotRef]:
        """Get all window snapshots."""
        return list(self.window_snapshots)

    def get_stable_snapshots(self) -> List[SnapshotRef]:
        """Get all stable snapshots."""
        return list(self.stable_snapshots)
