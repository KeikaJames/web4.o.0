"""Collector: Admission gate and memory routing."""

from typing import Optional
from .types import AdapterRef
from .admission_gate import AdmissionGate, ObservationType
from .memory_sink import InMemorySink


class Collector:
    """Admission gate and memory routing for observations."""

    def __init__(self, active_adapter: AdapterRef):
        self.active_adapter = active_adapter
        self.admission_gate = AdmissionGate()
        self.explicit_trace = InMemorySink()
        self.strategy_trace = InMemorySink()
        self.parameter_queue = InMemorySink()

    def admit_observation(self, observation: dict) -> ObservationType:
        """Classify observation and route to appropriate memory layer."""
        obs_type = self.admission_gate.classify(observation)

        if obs_type == ObservationType.EXPLICIT_ONLY:
            self.explicit_trace.append(observation)
        elif obs_type == ObservationType.STRATEGY_ONLY:
            self.strategy_trace.append(observation)
        else:
            self.parameter_queue.append(observation)

        return obs_type

    def get_active_adapter(self) -> AdapterRef:
        """Return current active adapter reference."""
        return self.active_adapter

    def set_active_adapter(self, adapter_ref: AdapterRef):
        """Update active adapter."""
        self.active_adapter = adapter_ref
