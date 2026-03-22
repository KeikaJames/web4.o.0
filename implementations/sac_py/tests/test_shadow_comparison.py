"""Test shadow evaluation with comparison results."""

import pytest
from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode
from implementations.sac_py.chronara_nexus.governor import Governor


def test_governor_validate_from_comparison_success():
    """Governor validates candidate using comparison result."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    governor = Governor(active)

    comparison_result = {
        "lineage_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "is_acceptable": True,
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert report.passed
    assert report.adapter_id == "base"
    assert report.generation == 2
    assert report.metric_summary["lineage_valid"]
    assert report.metric_summary["is_acceptable"]


def test_governor_validate_from_comparison_lineage_invalid():
    """Governor rejects candidate with invalid lineage."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    governor = Governor(active)

    comparison_result = {
        "lineage_valid": False,
        "output_match": True,
        "kv_count_match": True,
        "is_acceptable": False,
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert not report.passed
    assert "lineage invalid" in report.reason


def test_governor_validate_from_comparison_not_acceptable():
    """Governor rejects candidate with unacceptable behavior."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    governor = Governor(active)

    comparison_result = {
        "lineage_valid": True,
        "output_match": False,
        "kv_count_match": False,
        "is_acceptable": False,
    }

    report = governor.validate_from_comparison(candidate, comparison_result)

    assert not report.passed
    assert "not acceptable" in report.reason


def test_sac_validate_from_comparison():
    """SAC can validate using comparison result."""
    from implementations.sac_py.sac import SACContainer

    sac = SACContainer.create("/tmp/mem")
    sac.init_chronara()

    candidate = AdapterRef("base", 2, AdapterMode.SHADOW_EVAL)

    comparison_result = {
        "lineage_valid": True,
        "output_match": True,
        "kv_count_match": True,
        "is_acceptable": True,
    }

    report = sac.validate_from_comparison(candidate, comparison_result)
    assert report.passed
