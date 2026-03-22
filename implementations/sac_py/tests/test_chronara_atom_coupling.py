"""Test Chronara ↔ Atom second coupling: shadow eval and lineage validation."""

import pytest
from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode
from implementations.sac_py.chronara_nexus.governor import Governor


def test_governor_create_shadow_request():
    """Governor can create shadow eval request."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    governor = Governor(active)
    request = governor.create_shadow_request(candidate, b"test_input")

    assert request["active_adapter"]["adapter_id"] == "base"
    assert request["active_adapter"]["generation"] == 1
    assert request["candidate_adapter"]["adapter_id"] == "base"
    assert request["candidate_adapter"]["generation"] == 2
    assert request["candidate_adapter"]["mode"] == "shadow_eval"
    assert request["input"] == b"test_input"


def test_governor_validate_from_lineage_success():
    """Governor validates candidate using atom lineage."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    governor = Governor(active)

    atom_result = {
        "exec_response": {
            "adapter_id": "base",
            "adapter_generation": 2,
            "output": b"result",
        }
    }

    report = governor.validate_from_lineage(candidate, atom_result)

    assert report.passed
    assert report.adapter_id == "base"
    assert report.generation == 2
    assert report.metric_summary["lineage_match"]
    assert report.metric_summary["generation_advanced"]


def test_governor_validate_from_lineage_mismatch():
    """Governor rejects candidate with lineage mismatch."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    governor = Governor(active)

    atom_result = {
        "exec_response": {
            "adapter_id": "base",
            "adapter_generation": 1,  # Wrong generation
            "output": b"result",
        }
    }

    report = governor.validate_from_lineage(candidate, atom_result)

    assert not report.passed
    assert "mismatch" in report.reason


def test_sac_shadow_eval_integration():
    """SAC can create shadow eval request and validate result."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/mem")
    sac.init_chronara()

    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    # Create shadow request
    request = sac.create_shadow_eval_request(candidate, b"test")
    assert request["candidate_adapter"]["mode"] == "shadow_eval"

    # Validate from atom result
    atom_result = {
        "exec_response": {
            "adapter_id": "base",
            "adapter_generation": 2,
        }
    }
    report = sac.validate_from_atom_result(candidate, atom_result)
    assert report.passed
