"""Tests for the action governance boundary (adapter)."""

from implementations.sac_py.sac import SACContainer
from implementations.compat_py import adapter as adapter_module
from implementations.compat_py.adapter import file_write
from implementations.compat_py.path_security import resolve_within_memory_root as real_resolve_within_memory_root
from implementations.compat_py.types import AdapterRequest, AdapterResult, AuditEntry, ReasonCode


def test_allowed_write_returns_success(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    target = tmp_path / "out.txt"

    result, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(target),
        content="hello from agent",
    ))

    assert result.performed is True
    assert result.reason_code == ReasonCode.SUCCESS
    assert result.message == "OK"
    assert result.operation == "file.write"
    assert result.bytes_written == len("hello from agent".encode("utf-8"))
    assert target.read_text() == "hello from agent"

    assert audit.performed is True
    assert audit.reason_code == ReasonCode.SUCCESS
    assert audit.operation == "file.write"
    assert audit.timestamp  # non-empty


def test_denied_path_returns_target_not_allowed(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path / "safe"))
    outside = tmp_path / "outside.txt"

    result, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(outside),
        content="blocked",
    ))

    assert result.performed is False
    assert result.reason_code == ReasonCode.TARGET_NOT_ALLOWED
    assert not outside.exists()
    assert audit.reason_code == ReasonCode.TARGET_NOT_ALLOWED


def test_confirmation_required_returns_requires_confirmation(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    sac.permissions.actions_require_confirmation = ["file.write"]
    target = tmp_path / "denied.txt"

    result, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(target),
        content="should not land",
    ))

    assert result.performed is False
    assert result.reason_code == ReasonCode.REQUIRES_CONFIRMATION
    assert not target.exists()
    assert audit.reason_code == ReasonCode.REQUIRES_CONFIRMATION


def test_confirmation_provided_allows_write(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    sac.permissions.actions_require_confirmation = ["file.write"]
    target = tmp_path / "confirmed.txt"

    result, _ = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(target),
        content="confirmed write",
        requires_confirmation=True,
    ))

    assert result.performed is True
    assert result.reason_code == ReasonCode.SUCCESS
    assert target.read_text() == "confirmed write"


def test_revoked_agent_returns_agent_revoked(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    agent = sac.derive_agent("test-agent")
    sac.revoke_agent(agent.agent_id)

    result, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(tmp_path / "revoked.txt"),
        content="nope",
        agent_id=agent.agent_id,
    ))

    assert result.performed is False
    assert result.reason_code == ReasonCode.AGENT_REVOKED
    assert audit.reason_code == ReasonCode.AGENT_REVOKED
    assert audit.agent_id == agent.agent_id


def test_agent_scope_denied(tmp_path):
    from implementations.sac_py.sac import PermissionCage
    sac = SACContainer.create(memory_path=str(tmp_path))
    sac.permissions.allowed_operations = ["file.write"]
    agent = sac.derive_agent("narrow", permissions=PermissionCage(
        allowed_operations=["file.write"],
    ))
    # Remove file.write from agent after creation
    agent.permissions.allowed_operations = []

    result, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(tmp_path / "scope.txt"),
        content="nope",
        agent_id=agent.agent_id,
    ))

    assert result.performed is False
    assert result.reason_code == ReasonCode.AGENT_SCOPE_DENIED
    assert audit.reason_code == ReasonCode.AGENT_SCOPE_DENIED


def test_unsupported_action_returns_action_not_supported():
    sac = SACContainer.create()

    result, audit = file_write(sac, AdapterRequest(
        operation="file.delete",
        target="/tmp/nope",
        content="",
    ))

    assert result.performed is False
    assert result.reason_code == ReasonCode.ACTION_NOT_SUPPORTED
    assert audit.reason_code == ReasonCode.ACTION_NOT_SUPPORTED


def test_write_creates_parent_dirs(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    target = tmp_path / "sub" / "dir" / "file.txt"

    result, _ = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(target),
        content="nested",
    ))

    assert result.performed is True
    assert target.read_text() == "nested"


def test_write_rejects_symlinked_ancestor_planted_after_resolution(tmp_path, monkeypatch):
    memory_root = tmp_path / "memory"
    outside = tmp_path / "outside"
    memory_root.mkdir()
    outside.mkdir()
    sac = SACContainer.create(memory_path=str(memory_root))

    def plant_symlink_after_resolution(sac_obj, requested_path, *, must_exist):
        target = real_resolve_within_memory_root(sac_obj, requested_path, must_exist=must_exist)
        (memory_root / "subdir").symlink_to(outside, target_is_directory=True)
        return target

    monkeypatch.setattr(adapter_module, "resolve_within_memory_root", plant_symlink_after_resolution)

    result, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target="subdir/escape.txt",
        content="blocked",
    ))

    assert result.performed is False
    assert result.reason_code == ReasonCode.TARGET_NOT_ALLOWED
    assert not (outside / "escape.txt").exists()
    assert audit.reason_code == ReasonCode.TARGET_NOT_ALLOWED


def test_result_includes_resolved_target(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    target = tmp_path / "path_check.txt"

    result, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(target),
        content="x",
    ))

    assert result.target == str(target.resolve())
    assert audit.target == str(target.resolve())


def test_audit_entry_has_all_fields(tmp_path):
    sac = SACContainer.create(memory_path=str(tmp_path))
    agent = sac.derive_agent("audit-agent")
    target = tmp_path / "audit.txt"

    _, audit = file_write(sac, AdapterRequest(
        operation="file.write",
        target=str(target),
        content="audit me",
        agent_id=agent.agent_id,
    ))

    assert isinstance(audit, AuditEntry)
    assert audit.timestamp
    assert audit.operation == "file.write"
    assert audit.target == str(target.resolve())
    assert audit.agent_id == agent.agent_id
    assert audit.performed is True
    assert audit.reason_code == ReasonCode.SUCCESS
