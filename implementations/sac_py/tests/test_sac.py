"""Tests for SAC reference implementation."""

import base64
import json
from pathlib import Path

import jsonschema
import pytest

from sac_py.sac import (
    DEFAULT_ALLOWED_OPERATIONS,
    DerivedAgent,
    MemoryRoot,
    PermissionCage,
    RootKeyMaterial,
    SACContainer,
)


TEST_PASSPHRASE = "correct horse battery staple"
FIXTURES_DIR = Path(__file__).resolve().parent.parent.parent.parent / "fixtures" / "sac_v1"
SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "schemas"


def _load_container_schema():
    with open(SCHEMAS_DIR / "sac.v1.container.schema.json", "r", encoding="utf-8") as f:
        return json.load(f)


def _load_metadata_schema():
    with open(SCHEMAS_DIR / "sac.v1.metadata.schema.json", "r", encoding="utf-8") as f:
        return json.load(f)


def test_create_sac():
    sac = SACContainer.create()

    assert sac.sac_id is not None
    assert sac.root_key.key_bytes is not None
    assert len(sac.root_key.key_bytes) == 32
    assert sac.memory_root.reference == "./memory"
    assert sac.permissions.allowed_operations == DEFAULT_ALLOWED_OPERATIONS
    assert len(sac.derived_agents) == 0


def test_save_and_load_encrypts_at_rest(tmp_path):
    sac = SACContainer.create()
    original_key_id = sac.root_key.key_id
    original_key_bytes = sac.root_key.key_bytes
    path = tmp_path / "test-sac.json"

    sac.save(path, TEST_PASSPHRASE)
    loaded = SACContainer.load(path, TEST_PASSPHRASE)

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["root_key"]["key_bytes"] != base64.b64encode(original_key_bytes).decode("utf-8")
    assert raw["memory_root"]["reference"] != "./memory"
    assert loaded.sac_id == sac.sac_id
    assert loaded.root_key.key_id == original_key_id
    assert loaded.root_key.key_bytes == original_key_bytes


def test_load_rejects_tampered_container(tmp_path):
    sac = SACContainer.create()
    path = tmp_path / "tampered.json"
    sac.save(path, TEST_PASSPHRASE)

    data = json.loads(path.read_text(encoding="utf-8"))
    data["permissions"]["allowed_operations"].append("financial.transaction")
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="MAC verification failed"):
        SACContainer.load(path, TEST_PASSPHRASE)


def test_load_rejects_wrong_passphrase(tmp_path):
    sac = SACContainer.create()
    path = tmp_path / "test-sac.json"
    sac.save(path, TEST_PASSPHRASE)

    with pytest.raises(ValueError, match="MAC verification failed"):
        SACContainer.load(path, "wrong passphrase")


def test_derive_agent():
    sac = SACContainer.create()
    child_permissions = PermissionCage(
        allowed_operations=["file.write"],
        actions_require_confirmation=["file.write"],
    )

    agent = sac.derive_agent("email-handler", child_permissions)

    assert agent.agent_id is not None
    assert agent.purpose == "email-handler"
    assert agent.parent_sac_id == sac.sac_id
    assert agent.permissions.allowed_operations == ["file.write"]
    assert len(sac.derived_agents) == 1


def test_derive_agent_rejects_permission_escalation():
    sac = SACContainer.create()
    sac.permissions.allowed_operations = ["file.write"]

    with pytest.raises(ValueError, match="cannot exceed parent permissions"):
        sac.derive_agent(
            "too-wide",
            PermissionCage(allowed_operations=["file.write", "financial.transaction"]),
        )


def test_derive_agent_can_disable_parent_limited_operation():
    sac = SACContainer.create()
    sac.permissions.financial_single_tx_limit = 10.0
    sac.permissions.actions_require_confirmation = ["file.write"]

    agent = sac.derive_agent(
        "write-only",
        PermissionCage(
            allowed_operations=["file.write"],
            actions_require_confirmation=["file.write"],
        ),
    )

    assert agent.permissions.allowed_operations == ["file.write"]


def test_revoke_agent_blocks_execution():
    sac = SACContainer.create()
    agent = sac.derive_agent("test-agent")
    assert sac.revoke_agent(agent.agent_id) is True

    allowed, reason = sac.check_permission("file.write", {"agent_id": agent.agent_id})
    assert allowed is False
    assert "revoked" in reason


def test_rotate_key():
    sac = SACContainer.create()
    original_key_id = sac.root_key.key_id
    original_key_bytes = sac.root_key.key_bytes

    sac.rotate_key()

    assert sac.root_key.key_id != original_key_id
    assert sac.root_key.key_bytes != original_key_bytes
    assert sac.root_key.rotated_at is not None


def test_export_metadata_redacts_reference():
    sac = SACContainer.create()
    sac.derive_agent("test-agent")

    metadata = sac.export_metadata()

    assert metadata["sac_id"] == sac.sac_id
    assert metadata["root_key"]["key_id"] == sac.root_key.key_id
    assert metadata["memory_root"]["reference"].startswith("sha256:")
    assert metadata["memory_root"]["reference"] != sac.memory_root.reference
    assert "key_bytes" not in json.dumps(metadata)


def test_permission_check_financial_limit():
    sac = SACContainer.create()
    sac.permissions.financial_single_tx_limit = 1000.0

    allowed, _ = sac.check_permission("financial.transaction", {"amount": 500.0})
    assert allowed is True

    allowed, reason = sac.check_permission("financial.transaction", {"amount": 1500.0})
    assert allowed is False
    assert "Exceeds single transaction limit" in reason


def test_permission_check_daily_limit():
    sac = SACContainer.create()
    sac.permissions.financial_daily_limit = 5000.0

    allowed, _ = sac.check_permission(
        "financial.transaction",
        {"amount": 1000.0, "daily_total": 3000.0},
    )
    assert allowed is True

    allowed, reason = sac.check_permission(
        "financial.transaction",
        {"amount": 2000.0, "daily_total": 4000.0},
    )
    assert allowed is False
    assert "Exceeds daily limit" in reason


def test_permission_check_confirmation():
    sac = SACContainer.create()
    sac.permissions.actions_require_confirmation = ["file.write"]

    allowed, reason = sac.check_permission("file.write", {})
    assert allowed is False
    assert "requires user confirmation" in reason

    allowed, _ = sac.check_permission("file.write", {"user_confirmed": True})
    assert allowed is True


def test_permission_check_unknown_operation_denied():
    sac = SACContainer.create()
    allowed, reason = sac.check_permission("data.read", {})
    assert allowed is False
    assert "Operation not allowed" in reason


def test_save_load_preserves_derived_agents(tmp_path):
    sac = SACContainer.create()
    sac.derive_agent("agent-1")
    sac.derive_agent(
        "agent-2",
        PermissionCage(
            allowed_operations=["file.write"],
            actions_require_confirmation=["file.write"],
        ),
    )

    path = tmp_path / "test-sac.json"
    sac.save(path, TEST_PASSPHRASE)
    loaded = SACContainer.load(path, TEST_PASSPHRASE)

    assert len(loaded.derived_agents) == 2
    assert loaded.derived_agents[1].permissions.actions_require_confirmation == ["file.write"]


def test_key_derivation_deterministic():
    root_key = RootKeyMaterial.generate()
    assert root_key.derive_child_key("test-purpose") == root_key.derive_child_key("test-purpose")
    assert root_key.derive_child_key("test-purpose") != root_key.derive_child_key("different-purpose")


def test_minimal_sac_structure():
    sac = SACContainer.create()

    assert hasattr(sac, "root_key")
    assert hasattr(sac, "memory_root")
    assert hasattr(sac, "permissions")
    assert hasattr(sac, "derived_agents")
    assert not hasattr(sac, "persona")
    assert not hasattr(sac, "behavioral_constraints")
    assert not hasattr(sac, "interaction_preferences")


def test_load_rust_generated_container():
    sac = SACContainer.load(FIXTURES_DIR / "rust_generated.json", TEST_PASSPHRASE)

    assert sac.version == "1"
    assert len(sac.root_key.key_bytes) == 32
    assert sac.memory_root.reference == "./memory"
    assert len(sac.derived_agents) == 1
    assert "file.write" in sac.derived_agents[0].permissions.allowed_operations
    assert sac.permissions.financial_single_tx_limit == 500.0


def test_load_python_generated_container():
    sac = SACContainer.load(FIXTURES_DIR / "python_generated.json", TEST_PASSPHRASE)

    assert sac.version == "1"
    assert len(sac.derived_agents) == 1
    assert sac.derived_agents[0].purpose == "fixture-agent"
    assert sac.permissions.financial_single_tx_limit == 500.0


def test_timestamps_have_z_suffix():
    sac = SACContainer.create()
    assert sac.created_at.endswith("Z")
    assert sac.root_key.created_at.endswith("Z")
    assert sac.memory_root.created_at.endswith("Z")
    assert sac.derive_agent("test").created_at.endswith("Z")


def test_export_metadata_no_secrets_cross_check():
    sac = SACContainer.create()
    sac.derive_agent("agent")
    metadata = sac.export_metadata()
    raw = json.dumps(metadata)

    assert "key_bytes" not in raw
    assert metadata["memory_root"]["reference"].startswith("sha256:")
    assert metadata["root_key"]["key_id"] == sac.root_key.key_id


def test_fixture_python_validates_against_container_schema():
    schema = _load_container_schema()
    data = json.loads((FIXTURES_DIR / "python_generated.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_fixture_rust_validates_against_container_schema():
    schema = _load_container_schema()
    data = json.loads((FIXTURES_DIR / "rust_generated.json").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_save_output_validates_against_container_schema(tmp_path):
    schema = _load_container_schema()
    sac = SACContainer.create()
    sac.derive_agent("schema-test")
    path = tmp_path / "sac.json"
    sac.save(path, TEST_PASSPHRASE)
    data = json.loads(path.read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


def test_export_metadata_validates_against_metadata_schema():
    schema = _load_metadata_schema()
    sac = SACContainer.create()
    sac.derive_agent("meta-test")
    jsonschema.validate(sac.export_metadata(), schema)


def test_container_schema_rejects_missing_crypto(tmp_path):
    schema = _load_container_schema()
    sac = SACContainer.create()
    path = tmp_path / "sac.json"
    sac.save(path, TEST_PASSPHRASE)
    data = json.loads(path.read_text(encoding="utf-8"))
    del data["crypto"]
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)


def test_metadata_schema_rejects_key_bytes():
    schema = _load_metadata_schema()
    sac = SACContainer.create()
    metadata = sac.export_metadata()
    metadata["root_key"]["key_bytes"] = "leaked"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(metadata, schema)


def test_metadata_schema_rejects_recovery_params():
    schema = _load_metadata_schema()
    sac = SACContainer.create()
    metadata = sac.export_metadata()
    metadata["recovery_params"] = {}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(metadata, schema)


def test_container_schema_rejects_extra_field(tmp_path):
    schema = _load_container_schema()
    sac = SACContainer.create()
    path = tmp_path / "sac.json"
    sac.save(path, TEST_PASSPHRASE)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["persona"] = "bad"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(data, schema)
