"""Collector: Admission gate and memory routing."""

from enum import Enum
from typing import Optional
from .types import AdapterRef


class MemoryLayer(Enum):
    """Three-layer memory separation."""
    EXPLICIT = "explicit"
    STRATEGY = "strategy"
    PARAMETER = "parameter"


class ObservationType(Enum):
    """Observation classification."""
    TYPE_1_EXPLICIT = "type_1_explicit"
    TYPE_2_STRATEGY = "type_2_strategy"
    TYPE_3_PARAMETER = "type_3_parameter"


class Collector:
    """Admission gate and memory routing for observations."""

    def __init__(self, active_adapter: AdapterRef):
        self.active_adapter = active_adapter
        self.observation_queue = []

    def admit_observation(self, observation: dict) -> ObservationType:
        """Classify observation and route to appropriate memory layer."""
        obs_type = self._classify(observation)
        self.observation_queue.append((obs_type, observation))
        return obs_type

    def _classify(self, observation: dict) -> ObservationType:
        """Minimal classification logic."""
        if observation.get("explicit_feedback"):
            return ObservationType.TYPE_1_EXPLICIT
        elif observation.get("strategy_signal"):
            return ObservationType.TYPE_2_STRATEGY
        else:
            return ObservationType.TYPE_3_PARAMETER

    def get_active_adapter(self) -> AdapterRef:
        """Return current active adapter reference."""
        return self.active_adapter

    def set_active_adapter(self, adapter_ref: AdapterRef):
        """Update active adapter."""
        self.active_adapter = adapter_ref
