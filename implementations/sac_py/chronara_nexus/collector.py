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

        Phase 9: Uses multi-role review with consensus detection for routing:
        - CONSENSUS_ACCEPT / CANDIDATE_READY -> parameter_queue
        - CONSENSUS_STRATEGY_ONLY / STRATEGY_ONLY -> shared_queue
        - CONSENSUS_REJECT / REJECT -> explicit_trace
        - DISAGREEMENT_ESCALATE -> conservative handling (downgrade or reject)

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
            # PARAMETER_CANDIDATE: Phase 9 multi-role review screening
            if self.enable_deliberation:
                deliberation = self._get_deliberation()
                if deliberation:
                    try:
                        from .deliberation import (
                            DeliberationOutcome,
                            ReviewConsensusStatus,
                        )

                        # Phase 9: Use multi-role review instead of single deliberation
                        review_result = deliberation.multi_role_review(observation)

                        # Phase 9: Route based on consensus status and final outcome
                        if review_result.consensus_status == ReviewConsensusStatus.CONSENSUS_ACCEPT:
                            # All roles agree on candidate_ready - high confidence
                            self.parameter_queue.append({
                                **observation,
                                "_specialization_target": AdapterSpecialization.CANDIDATE.value,
                                "_deliberation_outcome": review_result.final_outcome.value,
                                "_consensus_status": review_result.consensus_status.value,
                                "_review_request_id": review_result.request_id,
                                "_has_disagreement": False,
                            })
                        elif review_result.consensus_status == ReviewConsensusStatus.CONSENSUS_STRATEGY_ONLY:
                            # All roles agree on strategy_only
                            self.strategy_trace.append(observation)
                            self.shared_queue.append({
                                **observation,
                                "_specialization_target": AdapterSpecialization.SHARED.value,
                                "_deliberation_outcome": review_result.final_outcome.value,
                                "_consensus_status": review_result.consensus_status.value,
                                "_review_request_id": review_result.request_id,
                            })
                        elif review_result.consensus_status == ReviewConsensusStatus.DISAGREEMENT_ESCALATE:
                            # Phase 9: Disagreement - check escalation result
                            if review_result.escalation_used:
                                # Escalation attempted - use escalated outcome
                                if review_result.final_outcome == DeliberationOutcome.CANDIDATE_READY:
                                    self.parameter_queue.append({
                                        **observation,
                                        "_specialization_target": AdapterSpecialization.CANDIDATE.value,
                                        "_deliberation_outcome": review_result.final_outcome.value,
                                        "_consensus_status": "escalated_accept",
                                        "_review_request_id": review_result.request_id,
                                        "_has_disagreement": True,
                                        "_escalation_used": True,
                                    })
                                elif review_result.final_outcome == DeliberationOutcome.STRATEGY_ONLY:
                                    self.strategy_trace.append(observation)
                                    self.shared_queue.append({
                                        **observation,
                                        "_specialization_target": AdapterSpecialization.SHARED.value,
                                        "_deliberation_outcome": review_result.final_outcome.value,
                                        "_consensus_status": "escalated_strategy",
                                        "_review_request_id": review_result.request_id,
                                        "_has_disagreement": True,
                                        "_escalation_used": True,
                                    })
                                else:
                                    # Escalated to reject
                                    self.explicit_trace.append({
                                        **observation,
                                        "_deliberation_rejected": True,
                                        "_deliberation_outcome": review_result.final_outcome.value,
                                        "_consensus_status": "escalated_reject",
                                        "_review_request_id": review_result.request_id,
                                        "_has_disagreement": True,
                                        "_escalation_used": True,
                                    })
                            else:
                                # Fallback due to budget - reject conservatively
                                self.explicit_trace.append({
                                    **observation,
                                    "_deliberation_rejected": True,
                                    "_deliberation_outcome": review_result.final_outcome.value,
                                    "_consensus_status": review_result.consensus_status.value,
                                    "_review_request_id": review_result.request_id,
                                    "_has_disagreement": True,
                                    "_fallback_used": True,
                                })
                        else:
                            # CONSENSUS_REJECT or other - reject
                            self.explicit_trace.append({
                                **observation,
                                "_deliberation_rejected": True,
                                "_deliberation_outcome": review_result.final_outcome.value,
                                "_consensus_status": review_result.consensus_status.value,
                                "_review_request_id": review_result.request_id,
                            })
                        return obs_type
                    except Exception:
                        # Fallback to original behavior on deliberation failure
                        pass

            # Default routing (no deliberation or fallback)
            self.parameter_queue.append({
                **observation,
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

    def extract_observation_summary(self) -> dict:
        """Extract observation routing summary for federation.

        Phase 10: Minimal summary of observation quality and routing.
        """
        try:
            # Count observations by type
            explicit_count = len(self.explicit_trace)
            strategy_count = len(self.strategy_trace)
            parameter_count = len(self.parameter_queue)
            shared_count = len(self.shared_queue)

            # Extract deliberation outcomes if available
            deliberation_outcomes = {}
            for obs in self.parameter_queue:
                outcome = obs.get("_deliberation_outcome")
                if outcome:
                    deliberation_outcomes[outcome] = deliberation_outcomes.get(outcome, 0) + 1

            for obs in self.shared_queue:
                outcome = obs.get("_deliberation_outcome")
                if outcome:
                    deliberation_outcomes[outcome] = deliberation_outcomes.get(outcome, 0) + 1

            # Count consensus statuses
            consensus_statuses = {}
            for obs in self.parameter_queue + self.shared_queue:
                status = obs.get("_consensus_status")
                if status:
                    consensus_statuses[status] = consensus_statuses.get(status, 0) + 1

            return {
                "observation_counts": {
                    "explicit_only": explicit_count,
                    "strategy_only": strategy_count,
                    "parameter_candidate": parameter_count,
                    "shared": shared_count,
                },
                "deliberation_outcomes": deliberation_outcomes,
                "consensus_statuses": consensus_statuses,
                "total_observations": explicit_count + strategy_count + parameter_count + shared_count,
                "has_deliberation": self.enable_deliberation,
            }
        except Exception:
            # Failure safety: return minimal summary
            return {
                "observation_counts": {},
                "deliberation_outcomes": {},
                "consensus_statuses": {},
                "total_observations": 0,
                "has_deliberation": self.enable_deliberation,
            }
