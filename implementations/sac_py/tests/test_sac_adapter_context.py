"""Test SAC adapter context for atom integration."""

import pytest
from implementations.sac_py.sac import SACContainer
from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode


def test_sac_current_adapter_ref_structure():
    """SAC current_adapter_ref returns valid AdapterRef."""
    sac = SACContainer.create("/tmp/mem")
    sac.init_chronara()

    adapter = sac.current_adapter_ref()

    assert isinstance(adapter, AdapterRef)
    assert adapter.adapter_id == "default"
    assert adapter.generation == 1
    assert adapter.mode == AdapterMode.SERVE


def test_sac_adapter_ref_to_dict():
    """AdapterRef can be serialized for atom request."""
    sac = SACContainer.create("/tmp/mem")
    sac.init_chronara()

    adapter = sac.current_adapter_ref()

    # Verify it has the fields atom expects
    assert hasattr(adapter, 'adapter_id')
    assert hasattr(adapter, 'generation')
    assert hasattr(adapter, 'mode')
    assert isinstance(adapter.generation, int)


def test_sac_adapter_context_after_promotion():
    """Adapter context reflects promoted generation."""
    sac = SACContainer.create("/tmp/mem")
    sac.init_chronara()

    # Initial state
    adapter = sac.current_adapter_ref()
    assert adapter.generation == 1

    # Create and promote candidate
    candidate = AdapterRef("default", 2, AdapterMode.SERVE)
    report = sac.validate_from_atom_result(candidate, {
        "exec_response": {
            "adapter_id": "default",
            "adapter_generation": 2,
        }
    })
    assert report.passed

    promoted = sac.promote_candidate_if_valid(candidate)
    assert promoted

    # Verify updated context
    current = sac.current_adapter_ref()
    assert current.generation == 2
    assert current.adapter_id == "default"
