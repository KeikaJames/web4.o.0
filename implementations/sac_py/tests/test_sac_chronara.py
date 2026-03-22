"""Test SAC Chronara integration."""

import pytest
from implementations.sac_py.sac import SACContainer
from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode


def test_sac_chronara_integration():
    sac = SACContainer.create()
    sac.init_chronara()

    adapter_ref = sac.current_adapter_ref()
    assert adapter_ref.adapter_id == "default"
    assert adapter_ref.generation == 1


def test_sac_record_observation():
    sac = SACContainer.create()

    obs = {"explicit_feedback": True}
    obs_type = sac.record_observation(obs)
    assert obs_type is not None


def test_sac_promote_candidate():
    sac = SACContainer.create()
    sac.init_chronara()

    candidate = AdapterRef("default", 2, AdapterMode.SERVE)
    promoted = sac.promote_candidate_if_valid(candidate)
    assert promoted
