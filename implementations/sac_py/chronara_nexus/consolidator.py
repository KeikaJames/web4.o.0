"""Consolidator: Candidate adapter lifecycle and micro-batch evolution."""

import numpy as np
from typing import Optional
from .types import AdapterRef, SnapshotRef


class Consolidator:
    """Manages candidate adapter evolution and snapshot generation."""

    def __init__(self, lr: float = 0.01, gamma: float = 0.001):
        self.candidate_adapter: Optional[AdapterRef] = None
        self.micro_batch_buffer = []
        self.lr = lr
        self.gamma = gamma
        self.phi = {}

    def create_candidate(self, base_adapter: AdapterRef) -> AdapterRef:
        """Create new candidate adapter from base."""
        candidate = AdapterRef(
            adapter_id=base_adapter.adapter_id,
            generation=base_adapter.generation + 1,
            mode=base_adapter.mode
        )
        self.candidate_adapter = candidate
        return candidate

    def accumulate_observation(self, observation: dict):
        """Add observation to micro-batch buffer."""
        self.micro_batch_buffer.append(observation)

    def evolve_micro_batch(self) -> bool:
        """Micro-batch parameter update with shrink formula."""
        if len(self.micro_batch_buffer) < 10:
            return False

        # Placeholder gradient computation
        g = np.random.randn(10)
        g_clip = np.clip(g, -1.0, 1.0)

        # Shrink formula: phi <- phi - lr * g_clip - gamma * phi
        for key in self.phi:
            self.phi[key] = self.phi[key] - self.lr * g_clip[0] - self.gamma * self.phi[key]

        self.micro_batch_buffer.clear()
        return True

    def prune_parameters(self, phi: dict) -> dict:
        """Prune parameters using quantile 0.1."""
        values = np.array(list(phi.values()))
        threshold = np.quantile(np.abs(values), 0.1)
        return {k: v for k, v in phi.items() if np.abs(v) > threshold}

    def generate_snapshot(self) -> Optional[SnapshotRef]:
        """Generate snapshot of candidate adapter."""
        if not self.candidate_adapter:
            return None
        return SnapshotRef(
            snapshot_id=f"{self.candidate_adapter.adapter_id}-gen{self.candidate_adapter.generation}",
            adapter_id=self.candidate_adapter.adapter_id,
            generation=self.candidate_adapter.generation,
            byte_size=0
        )
