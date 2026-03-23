"""Collector: observation classification and in-memory routing."""

from typing import Optional
from .types import AdapterRef, ObservationType


class Collector:
    """Classify observations and route them into in-memory traces."""

    def __init__(self, active_adapter: AdapterRef, enable_deliberation: bool = False):
        self.active_adapter = active_adapter
        self.explicit_trace = []
        self.strategy_trace = []
        self.parameter_queue = []
        self.enable_deliberation = enable_deliberation
        self._deliberation = None

    def _get_deliberation(self):
        """Lazy load deliberation to avoid circular import."""
        if self._deliberation is None and self.enable_deliberation:
            from .deliberation import BoundedDeliberation
            self._deliberation = BoundedDeliberation()
        return self._deliberation

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
            # PARAMETER_CANDIDATE: optionally enhance via deliberation
            if self.enable_deliberation:
                deliberation = self._get_deliberation()
                if deliberation:
                    try:
                        from .deliberation import DeliberationRequest
                        request = DeliberationRequest(observation=observation)
                        result = deliberation.deliberate(request)
                        # Use synthesized output if accepted
                        enhanced_obs = result.synthesized_output if result.accepted else observation
                        self.parameter_queue.append(enhanced_obs)
                    except Exception:
                        # Fallback on deliberation failure
                        self.parameter_queue.append(observation)
                else:
                    self.parameter_queue.append(observation)
            else:
                self.parameter_queue.append(observation)

        return obs_type

    def get_active_adapter(self) -> AdapterRef:
        """Return current active adapter reference."""
        return self.active_adapter

    def set_active_adapter(self, adapter_ref: AdapterRef):
        """Update active adapter."""
        self.active_adapter = adapter_ref
