"""Test Governor consumes atom validation_result."""

import pytest
from implementations.sac_py.chronara_nexus import AdapterRef, AdapterMode, Governor


def test_governor_consumes_atom_validation_result():
    """Governor uses atom validation_result when available."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    # Atom result with validation_result
    atom_result = {
        "validation_result": {
            "active_adapter_id": "base",
            "active_generation": 1,
            "candidate_adapter_id": "base",
            "candidate_generation": 2,
            "lineage_valid": True,
            "output_match": True,
            "kv_count_match": True,
            "is_acceptable": True,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert report.passed
    assert report.metric_summary["lineage_valid"] is True
    assert report.metric_summary["is_acceptable"] is True
    assert report.metric_summary["source"] == "atom_validation_result"


def test_governor_rejects_lineage_invalid():
    """Governor rejects when atom reports lineage_valid=False."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    atom_result = {
        "validation_result": {
            "active_adapter_id": "base",
            "active_generation": 1,
            "candidate_adapter_id": "wrong",
            "candidate_generation": 2,
            "lineage_valid": False,
            "output_match": False,
            "kv_count_match": False,
            "is_acceptable": False,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert not report.passed
    assert "lineage invalid" in report.reason


def test_governor_rejects_not_acceptable():
    """Governor rejects when atom reports is_acceptable=False."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    atom_result = {
        "validation_result": {
            "active_adapter_id": "base",
            "active_generation": 1,
            "candidate_adapter_id": "base",
            "candidate_generation": 2,
            "lineage_valid": True,
            "output_match": False,
            "kv_count_match": False,
            "is_acceptable": False,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert not report.passed
    assert "not acceptable" in report.reason


def test_governor_rejects_validation_result_lineage_mismatch():
    """Governor rejects validation_result that disagrees with expected adapter lineage."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    atom_result = {
        "validation_result": {
            "active_adapter_id": "wrong-active",
            "active_generation": 999,
            "candidate_adapter_id": "wrong-candidate",
            "candidate_generation": 999,
            "lineage_valid": True,
            "output_match": True,
            "kv_count_match": True,
            "is_acceptable": True,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert not report.passed
    assert report.metric_summary["active_match"] is False
    assert report.metric_summary["candidate_match"] is False
    assert "lineage invalid" in report.reason


def test_governor_rejects_output_mismatch_even_if_acceptable_true():
    """Governor does not accept contradictory validation results."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    atom_result = {
        "validation_result": {
            "active_adapter_id": "base",
            "active_generation": 1,
            "candidate_adapter_id": "base",
            "candidate_generation": 2,
            "lineage_valid": True,
            "output_match": False,
            "kv_count_match": True,
            "is_acceptable": True,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert not report.passed
    assert report.metric_summary["output_match"] is False
    assert "not acceptable" in report.reason


def test_governor_fallback_to_exec_response():
    """Governor falls back to exec_response when no validation_result."""
    active = AdapterRef("base", 1, AdapterMode.SERVE)
    candidate = AdapterRef("base", 2, AdapterMode.SERVE)
    governor = Governor(active)

    # Old-style atom result without validation_result
    atom_result = {
        "exec_response": {
            "adapter_id": "base",
            "adapter_generation": 2,
        }
    }

    report = governor.validate_from_atom_result(candidate, atom_result)

    assert report.passed
    assert report.metric_summary["source"] == "exec_response_lineage"
