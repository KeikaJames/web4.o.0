"""Tests for the local agent loop with explicit governance types."""

import pytest

from implementations.sac_py.sac import SACContainer
from implementations.compat_py.agent_loop import run_once, LoopResult
from implementations.compat_py.model import MockModel, ModelOutput, get_model
from implementations.compat_py.types import AdapterResult, AuditEntry, ReasonCode


def test_allowed_loop_returns_success(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    input_file = tmp_path / "input.txt"
    input_file.write_text("hello world")
    output_file = tmp_path / "output.txt"

    result = run_once(sac, str(input_file), str(output_file))

    assert isinstance(result, LoopResult)
    assert isinstance(result.adapter_result, AdapterResult)
    assert isinstance(result.audit, AuditEntry)
    assert result.adapter_result.performed is True
    assert result.adapter_result.reason_code == ReasonCode.SUCCESS
    assert result.audit.reason_code == ReasonCode.SUCCESS
    assert output_file.read_text() == "HELLO WORLD"


def test_denied_without_confirmation(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    sac.permissions.actions_require_confirmation = ["file.write"]
    input_file = tmp_path / "input.txt"
    input_file.write_text("should not land")
    output_file = tmp_path / "denied.txt"

    result = run_once(sac, str(input_file), str(output_file))

    assert result.adapter_result.performed is False
    assert result.adapter_result.reason_code == ReasonCode.REQUIRES_CONFIRMATION
    assert result.audit.reason_code == ReasonCode.REQUIRES_CONFIRMATION
    assert not output_file.exists()


def test_allowed_with_confirmation(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    sac.permissions.actions_require_confirmation = ["file.write"]
    input_file = tmp_path / "input.txt"
    input_file.write_text("confirmed input")
    output_file = tmp_path / "confirmed.txt"

    result = run_once(sac, str(input_file), str(output_file),
                      context={"user_confirmed": True})

    assert result.adapter_result.performed is True
    assert result.adapter_result.reason_code == ReasonCode.SUCCESS
    assert output_file.read_text() == "CONFIRMED INPUT"


def test_loop_result_carries_full_trace(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    input_file = tmp_path / "trace.txt"
    input_file.write_text("trace me")
    output_file = tmp_path / "traced.txt"

    result = run_once(sac, str(input_file), str(output_file))

    assert result.input_path == str(input_file)
    assert result.input_text == "trace me"
    assert result.model_output.proposed_path == str(output_file)
    assert result.adapter_result.target == str(output_file.resolve())
    assert result.adapter_result.bytes_written == len("TRACE ME".encode("utf-8"))
    assert result.audit.operation == "file.write"
    assert result.audit.performed is True


def test_loop_rejects_input_outside_memory_root(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path / "safe"))
    outside = tmp_path / "outside.txt"
    outside.write_text("blocked")

    with pytest.raises(PermissionError):
        run_once(sac, str(outside), "ignored.txt")


def test_loop_with_agent_id(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    agent = sac.derive_agent("loop-agent")
    input_file = tmp_path / "input.txt"
    input_file.write_text("agent input")
    output_file = tmp_path / "agent_out.txt"

    result = run_once(sac, str(input_file), str(output_file),
                      agent_id=agent.agent_id)

    assert result.adapter_result.performed is True
    assert result.audit.agent_id == agent.agent_id


def test_loop_revoked_agent_denied(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    agent = sac.derive_agent("revoke-me")
    sac.revoke_agent(agent.agent_id)
    input_file = tmp_path / "input.txt"
    input_file.write_text("nope")
    output_file = tmp_path / "nope.txt"

    result = run_once(sac, str(input_file), str(output_file),
                      agent_id=agent.agent_id)

    assert result.adapter_result.performed is False
    assert result.adapter_result.reason_code == ReasonCode.AGENT_REVOKED
    assert result.audit.reason_code == ReasonCode.AGENT_REVOKED


def test_get_model_returns_mock_without_config(monkeypatch):
    """Without MODEL_API_KEY or ANTHROPIC_API_KEY, get_model() returns MockModel."""
    monkeypatch.delenv("MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    m = get_model()
    assert isinstance(m, MockModel)


def test_get_model_explicit_mock_provider(monkeypatch):
    """MODEL_PROVIDER=mock returns MockModel even if API key is set."""
    monkeypatch.setenv("MODEL_PROVIDER", "mock")
    monkeypatch.setenv("MODEL_API_KEY", "sk-fake")
    m = get_model()
    assert isinstance(m, MockModel)


def test_get_model_unknown_provider_raises(monkeypatch):
    """Unknown provider raises ValueError."""
    monkeypatch.setenv("MODEL_PROVIDER", "openai")
    monkeypatch.setenv("MODEL_API_KEY", "sk-fake")
    with pytest.raises(ValueError, match="Unknown model provider"):
        get_model()


def test_explicit_mock_model_injection(tmp_path):
    """Passing model= explicitly uses that model, not env."""
    sac = SACContainer.create(memory_path=str(tmp_path))
    input_file = tmp_path / "input.txt"
    input_file.write_text("inject me")
    output_file = tmp_path / "injected.txt"

    class ReverseModel:
        def run(self, input_text: str, output_path: str) -> ModelOutput:
            return ModelOutput(
                transformed_text=input_text[::-1],
                proposed_action="file.write",
                proposed_path=output_path,
            )

    result = run_once(sac, str(input_file), str(output_file),
                      model=ReverseModel())

    assert result.adapter_result.performed is True
    assert output_file.read_text() == "em tcejni"
