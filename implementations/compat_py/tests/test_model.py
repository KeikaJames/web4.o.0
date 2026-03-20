"""Tests for compat_py model selection and response parsing."""

import pytest

from implementations.compat_py.model import _parse_model_response, get_model


def test_parse_model_response_accepts_plain_json():
    data = _parse_model_response(
        '{"transformed_text":"HELLO","proposed_action":"file.write","proposed_path":"out.txt"}'
    )
    assert data["proposed_action"] == "file.write"


def test_parse_model_response_accepts_fenced_json():
    data = _parse_model_response(
        "```json\n"
        '{"transformed_text":"HELLO","proposed_action":"file.write","proposed_path":"out.txt"}\n'
        "```"
    )
    assert data["proposed_path"] == "out.txt"


def test_get_model_requires_api_key_for_real_provider(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValueError, match="MODEL_API_KEY required"):
        get_model(provider="anthropic")
