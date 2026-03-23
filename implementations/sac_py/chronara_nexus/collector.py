"""Collector: observation classification and in-memory routing."""

from typing import Optional, List
from .types import AdapterRef, ObservationType, AdapterSpecialization


class Collector:
    """Classify observations and route them into in-memory traces.

    Specialization-aware routing:
    - explicit_only: Does not enter parameter layer (isolated trace)
    - strategy_only: Maps to SHARED semantics (cross-task shared preferences)
    - parameter_candidate: Maps to CANDIDATE path (experimental parameters)
    """

    def __init__(self, active_adapter: AdapterRef, enable_deliberation: bool = False):
        self.active_adapter = active_adapter
        self.explicit_trace: List[dict] = []
        self.strategy_trace: List[dict] = []
        self.parameter_queue: List[dict] = []
        self.shared_queue: List[dict] = []
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
        """Classify observation and route to appropriate memory layer.

        Specialization routing:
        - EXPLICIT_ONLY -> explicit_trace (no parameter layer entry)
        - STRATEGY_ONLY -> strategy_trace + shared_queue (SHARED semantics)
        - PARAMETER_CANDIDATE -> parameter_queue (CANDIDATE path)
        """
        obs_type = self.classify(observation)

        if obs_type == ObservationType.EXPLICIT_ONLY:
            self.explicit_trace.append(observation)
        elif obs_type == ObservationType.STRATEGY_ONLY:
            # Strategy signals map to SHARED specialization semantics
            self.strategy_trace.append(observation)
            self.shared_queue.append({
                **observation,
                "_specialization_target": AdapterSpecialization.SHARED.value
            })
        else:
            # PARAMETER_CANDIDATE: optionally enhance via deliberation
            enhanced_obs = observation
            if self.enable_deliberation:
                deliberation = self._get_deliberation()
                if deliberation:
                    try:
                        from .deliberation import DeliberationRequest
                        request = DeliberationRequest(observation=observation)
                        result = deliberation.deliberate(request)
                        # Use synthesized output if accepted
                        enhanced_obs = result.synthesized_output if result.accepted else observation
                    except Exception:
                        pass  # Fallback to original observation

            # Route to candidate path with specialization marker
            self.parameter_queue.append({
                **enhanced_obs,
                "_specialization_target": AdapterSpecialization.CANDIDATE.value
            })

        return obs_type

    def get_active_adapter(self) -> AdapterRef:
        """Return current active adapter reference."""
        return self.active_adapter

    def set_active_adapter(self, adapter_ref: AdapterRef):
        """Update active adapter."""
        self.active_adapter = adapter_ref

    def get_specialization_queue(self, specialization: AdapterSpecialization) -> List[dict]:
        """Get observation queue for specific specialization.

        - STABLE: Not directly accumulated, derived from validated candidate
        - SHARED: Returns shared_queue (strategy_only observations)
        - CANDIDATE: Returns parameter_queue (parameter_candidate observations)
        """
        if specialization == AdapterSpecialization.SHARED:
            return self.shared_queue
        if specialization == AdapterSpecialization.CANDIDATE:
            return self.parameter_queue
        return []

    def clear_specialization_queue(self, specialization: AdapterSpecialization):
        """Clear observation queue for specific specialization."""
        if specialization == AdapterSpecialization.SHARED:
            self.shared_queue.clear()
        elif specialization == AdapterSpecialization.CANDIDATE:
            self.parameter_queue.clear()
