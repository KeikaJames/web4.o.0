"""Collector: observation classification and in-memory routing."""

from .types import AdapterRef, ObservationType


class Collector:
    """Classify observations and route them into in-memory traces."""

    def __init__(self, active_adapter: AdapterRef):
        self.active_adapter = active_adapter
        self.explicit_trace = []
        self.strategy_trace = []
        self.parameter_queue = []

    @staticmethod
    def classify(observation: dict) -> ObservationType:
        """Classify one observation without an extra wrapper object."""
        if observation.get("explicit_feedback"):
            return ObservationType.EXPLICIT_ONLY
        if observation.get("strategy_signal"):
            return ObservationType.STRATEGY_ONLY
        return ObservationType.PARAMETER_CANDIDATE

    def admit_observation(self, observation: dict) -> ObservationType:
        """Classify observation and route to appropriate memory layer."""
        obs_type = self.classify(observation)

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
