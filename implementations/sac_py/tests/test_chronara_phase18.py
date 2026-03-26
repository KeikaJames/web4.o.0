"""Phase 18: Parameter memory exchange skeleton tests."""

from implementations.sac_py.chronara_nexus.exchange_skeleton import (
    ExchangeDecision,
    ParameterMemoryExchangeSkeleton,
)


def test_exchange_proposal_tracks_blocking_factors():
    candidate = {
        "adapter_id": "base",
        "generation": 7,
        "source_node": "node-a",
        "lineage_compatible": True,
        "specialization_compatible": True,
        "validation_passed": True,
        "comparison_acceptable": False,
        "lifecycle_valid": True,
        "conflict_resolved": True,
        "execution_ready": False,
    }

    proposal = ParameterMemoryExchangeSkeleton.create_proposal(candidate)

    assert proposal.candidate.adapter_id == "base"
    assert proposal.eligibility.is_eligible is False
    assert proposal.eligibility.blocking_factors == [
        "skeleton_mode: no actual validation performed"
    ]


def test_exchange_readiness_requires_enough_gates():
    candidate = {
        "adapter_id": "base",
        "generation": 8,
        "source_node": "node-b",
        "lineage_compatible": True,
        "specialization_compatible": True,
        "validation_passed": True,
        "comparison_acceptable": True,
        "lifecycle_valid": True,
        "conflict_resolved": True,
        "execution_ready": True,
        "param_count": 1024,
        "memory_size_bytes": 4096,
        "compression_ratio": 0.25,
        "has_delta": True,
        "delta_magnitude": 0.12,
        "relative_change": 0.03,
        "importance_threshold": 0.7,
        "top_k_ratio": 0.1,
    }

    proposal = ParameterMemoryExchangeSkeleton.create_proposal(candidate)
    readiness = ParameterMemoryExchangeSkeleton.assess_readiness(
        proposal,
        triage_summary={
            "lineage_compatible": True,
            "specialization_compatible": True,
            "readiness_score": 0.95,
            "status": "ready",
        },
        lifecycle_summary={
            "state": "ready",
            "ttl_remaining": 24.0,
        },
        conflict_summary={
            "can_proceed": True,
        },
        execution_summary={
            "success": True,
        },
    )

    assert readiness.decision == ExchangeDecision.EXCHANGE_READY
    assert readiness.is_ready is True
    assert readiness.readiness_score >= 0.7
