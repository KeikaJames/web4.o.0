"""Consolidator: Candidate adapter lifecycle and micro-batch evolution."""

from typing import Dict, Optional, List, Any
from .types import AdapterRef, SnapshotRef, AdapterSpecialization


class Consolidator:
    """Manages candidate adapter evolution and snapshot generation.

    Specialization-aware consolidation:
    - candidate: Current experimental parameters (direct updates)
    - shared: Cross-task shared tendencies (summary accumulation)
    - stable: Long-term validated parameters (reference baseline)
    """

    def __init__(self, lr: float = 0.01, gamma: float = 0.001):
        self.candidate_adapter: Optional[AdapterRef] = None
        self.stable_adapter: Optional[AdapterRef] = None
        self.shared_adapter: Optional[AdapterRef] = None

        self.micro_batch_buffer: List[dict] = []
        self.shared_accumulator: List[dict] = []

        self.lr = lr
        self.gamma = gamma

        # Parameters per specialization
        self.phi_candidate: Dict[str, float] = {"p0": 1.0, "p1": 0.5, "p2": -0.3}
        self.phi_shared: Dict[str, float] = {"s0": 0.0, "s1": 0.0}
        self.phi_stable: Dict[str, float] = {"p0": 1.0, "p1": 0.5, "p2": -0.3}

    def create_candidate(self, base_adapter: AdapterRef) -> AdapterRef:
        """Create new candidate adapter from base.

        Candidate inherits from base but with CANDIDATE specialization.
        Base becomes the stable reference.
        """
        candidate = AdapterRef(
            adapter_id=base_adapter.adapter_id,
            generation=base_adapter.generation + 1,
            mode=base_adapter.mode,
            specialization=AdapterSpecialization.CANDIDATE
        )
        self.candidate_adapter = candidate
        self.stable_adapter = AdapterRef(
            adapter_id=base_adapter.adapter_id,
            generation=base_adapter.generation,
            mode=base_adapter.mode,
            specialization=AdapterSpecialization.STABLE
        )
        return candidate

    def set_shared_adapter(self, adapter_ref: AdapterRef) -> AdapterRef:
        """Set shared adapter for cross-task preferences.

        Shared adapter uses SHARED specialization and serves as
        augmentation layer for cross-observation patterns.
        """
        self.shared_adapter = AdapterRef(
            adapter_id=adapter_ref.adapter_id,
            generation=adapter_ref.generation,
            mode=adapter_ref.mode,
            specialization=AdapterSpecialization.SHARED
        )
        return self.shared_adapter

    def get_specialization_params(self, specialization: AdapterSpecialization) -> Dict[str, float]:
        """Get parameters for specific specialization."""
        if specialization == AdapterSpecialization.CANDIDATE:
            return self.phi_candidate.copy()
        if specialization == AdapterSpecialization.SHARED:
            return self.phi_shared.copy()
        if specialization == AdapterSpecialization.STABLE:
            return self.phi_stable.copy()
        return {}

    @property
    def phi(self) -> Dict[str, float]:
        """Backward compatibility: returns candidate parameters."""
        return self.phi_candidate

    @phi.setter
    def phi(self, value: Dict[str, float]):
        """Backward compatibility: sets candidate parameters."""
        self.phi_candidate = value

    def accumulate_observation(self, observation: dict):
        """Add observation to micro-batch buffer.

        Phase 8: Considers deliberation quality scores for weighting.
        Routes to specialization-specific accumulator based on
        _specialization_target marker from Collector.
        """
        target_spec = observation.get("_specialization_target")

        # Phase 8: Extract deliberation quality for weighted accumulation
        quality_score = observation.get("_quality_score", 1.0)
        deliberation_outcome = observation.get("_deliberation_outcome", None)

        # Add quality-weighted observation
        weighted_obs = {
            **observation,
            "_accumulation_weight": quality_score,
            "_deliberation_outcome": deliberation_outcome,
        }

        if target_spec == AdapterSpecialization.SHARED.value:
            self.shared_accumulator.append(weighted_obs)
        else:
            # Default to candidate path
            self.micro_batch_buffer.append(weighted_obs)

    def accumulate_for_specialization(self, observation: dict, specialization: AdapterSpecialization):
        """Explicitly add observation for specific specialization."""
        if specialization == AdapterSpecialization.SHARED:
            self.shared_accumulator.append(observation)
        else:
            self.micro_batch_buffer.append(observation)

    @staticmethod
    def _clip(value: float, lower: float, upper: float) -> float:
        return max(lower, min(upper, value))

    @staticmethod
    def _quantile(sorted_values: list[float], q: float) -> float:
        if not sorted_values:
            raise ValueError("quantile requires at least one value")
        if len(sorted_values) == 1:
            return sorted_values[0]

        position = (len(sorted_values) - 1) * q
        lower = int(position)
        upper = min(lower + 1, len(sorted_values) - 1)
        weight = position - lower
        return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight

    def _extract_numeric_summary(self, observations: list) -> list[float]:
        """Extract deterministic numeric summary from observations.

        Phase 8: Uses deliberation quality scores as accumulation weights.
        Higher quality observations contribute more to the summary.
        """
        summary = []
        for obs in observations:
            # Phase 8: Apply deliberation quality weight if available
            weight = obs.get("_accumulation_weight", 1.0)

            value = 0.0
            if isinstance(obs.get("data"), (int, float)):
                value = float(obs["data"])
            elif "explicit_feedback" in obs:
                value = 1.0
            elif "strategy_signal" in obs:
                value = 0.5

            # Weight the value by quality score
            summary.append(value * weight)
        return summary[:10]

    def evolve_micro_batch(self) -> bool:
        """Micro-batch parameter update with shrink formula for candidate."""
        return self._evolve_for_specialization(AdapterSpecialization.CANDIDATE)

    def evolve_shared(self) -> bool:
        """Update shared parameters from shared accumulator."""
        return self._evolve_for_specialization(AdapterSpecialization.SHARED)

    def _evolve_for_specialization(self, specialization: AdapterSpecialization) -> bool:
        """Execute micro-batch update for specific specialization.

        Uses shrink formula: phi <- phi - lr * g_clip - gamma * phi
        """
        if specialization == AdapterSpecialization.SHARED:
            buffer = self.shared_accumulator
            phi = self.phi_shared
        else:
            buffer = self.micro_batch_buffer
            phi = self.phi_candidate

        if len(buffer) < 10:
            return False

        # Deterministic gradient from observations
        numeric_summary = self._extract_numeric_summary(buffer)
        if not numeric_summary:
            return False

        mean_value = sum(numeric_summary) / len(numeric_summary)
        g_clip = [self._clip(value - mean_value, -1.0, 1.0) for value in numeric_summary]

        # Shrink formula: phi <- phi - lr * g_clip - gamma * phi
        for i, key in enumerate(sorted(phi.keys())):
            grad_component = g_clip[i % len(g_clip)]
            phi[key] = phi[key] - self.lr * grad_component - self.gamma * phi[key]

        if specialization == AdapterSpecialization.SHARED:
            self.shared_accumulator.clear()
        else:
            self.micro_batch_buffer.clear()
        return True

    def prune_parameters(self, phi: Optional[dict] = None, specialization: Optional[AdapterSpecialization] = None) -> dict:
        """Prune parameters using quantile 0.1.

        If phi is not provided, uses parameters from specified specialization.
        """
        if phi is None:
            phi = self.get_specialization_params(specialization or AdapterSpecialization.CANDIDATE)

        if not phi:
            return {}
        magnitudes = sorted(abs(value) for value in phi.values())
        threshold = self._quantile(magnitudes, 0.1)
        return {k: v for k, v in phi.items() if abs(v) > threshold}

    def prune_candidate(self) -> dict:
        """Prune candidate parameters."""
        return self.prune_parameters(specialization=AdapterSpecialization.CANDIDATE)

    def prune_shared(self) -> dict:
        """Prune shared parameters."""
        return self.prune_parameters(specialization=AdapterSpecialization.SHARED)

    def generate_snapshot(self, specialization: Optional[AdapterSpecialization] = None) -> Optional[SnapshotRef]:
        """Generate snapshot of adapter for given specialization.

        If specialization not specified, uses candidate if available,
        otherwise stable.
        """
        if specialization is None:
            specialization = AdapterSpecialization.CANDIDATE if self.candidate_adapter else AdapterSpecialization.STABLE

        if specialization == AdapterSpecialization.CANDIDATE and self.candidate_adapter:
            adapter = self.candidate_adapter
        elif specialization == AdapterSpecialization.SHARED and self.shared_adapter:
            adapter = self.shared_adapter
        elif specialization == AdapterSpecialization.STABLE and self.stable_adapter:
            adapter = self.stable_adapter
        else:
            return None

        return SnapshotRef(
            snapshot_id=f"{adapter.adapter_id}-gen{adapter.generation}-{specialization.value}",
            adapter_id=adapter.adapter_id,
            generation=adapter.generation,
            byte_size=0,
            specialization=specialization
        )

    def extract_parameter_summary(self) -> dict:
        """Extract parameter-side summary for federation.

        Phase 10: Minimal delta-side summary for cross-node comparison.
        """
        try:
            # Get params for all specializations
            candidate_params = self.get_specialization_params(AdapterSpecialization.CANDIDATE)
            shared_params = self.get_specialization_params(AdapterSpecialization.SHARED)
            stable_params = self.get_specialization_params(AdapterSpecialization.STABLE)

            # Compute norms
            def compute_norms(params: dict) -> dict:
                if not params:
                    return {"l1": 0.0, "l2": 0.0, "max": 0.0, "count": 0}
                values = list(params.values())
                return {
                    "l1": sum(abs(v) for v in values),
                    "l2": (sum(v**2 for v in values)) ** 0.5,
                    "max": max(abs(v) for v in values),
                    "count": len(values),
                }

            # Get top-k important keys per specialization
            def get_top_keys(params: dict, top_n: int = 5) -> list:
                if not params:
                    return []
                sorted_items = sorted(params.items(), key=lambda x: abs(x[1]), reverse=True)
                return [key for key, v in sorted_items[:top_n]]

            return {
                "specializations": {
                    "candidate": {
                        "exists": self.candidate_adapter is not None,
                        "generation": self.candidate_adapter.generation if self.candidate_adapter else None,
                        "norms": compute_norms(candidate_params),
                        "top_keys": get_top_keys(candidate_params),
                    },
                    "shared": {
                        "exists": self.shared_adapter is not None,
                        "generation": self.shared_adapter.generation if self.shared_adapter else None,
                        "norms": compute_norms(shared_params),
                        "top_keys": get_top_keys(shared_params),
                    },
                    "stable": {
                        "exists": self.stable_adapter is not None,
                        "generation": self.stable_adapter.generation if self.stable_adapter else None,
                        "norms": compute_norms(stable_params),
                        "top_keys": get_top_keys(stable_params),
                    },
                },
                "buffer_sizes": {
                    "micro_batch": len(self.micro_batch_buffer),
                    "shared_accumulator": len(self.shared_accumulator),
                },
                "hyperparameters": {
                    "lr": self.lr,
                    "gamma": self.gamma,
                },
            }
        except Exception:
            # Failure safety: return minimal summary
            return {
                "specializations": {},
                "buffer_sizes": {
                    "micro_batch": 0,
                    "shared_accumulator": 0,
                },
                "hyperparameters": {
                    "lr": self.lr,
                    "gamma": self.gamma,
                },
            }
