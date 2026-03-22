use base64::Engine;
use sac_rs::{PermissionCage, RootKeyMaterial, SACContainer};
use std::collections::HashMap;
use std::path::PathBuf;

const TEST_PASSPHRASE: &str = "correct horse battery staple";

fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../fixtures/sac_v1")
}

fn schemas_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../schemas")
}

fn load_schema(name: &str) -> serde_json::Value {
    let path = schemas_dir().join(name);
    serde_json::from_str(&std::fs::read_to_string(path).unwrap()).unwrap()
}

fn validate_against(schema: &serde_json::Value, instance: &serde_json::Value) {
    let validator = jsonschema::validator_for(schema).expect("invalid schema");
    let errors: Vec<_> = validator.iter_errors(instance).collect();
    if !errors.is_empty() {
        let msgs: Vec<_> = errors.iter().map(|e| format!("  {}", e)).collect();
        panic!("schema validation failed:\n{}", msgs.join("\n"));
    }
}

#[test]
fn test_create_sac() {
    let sac = SACContainer::create("./memory");
    assert!(!sac.sac_id.is_empty());
    assert_eq!(sac.root_key.key_bytes.len(), 32);
    assert_eq!(sac.memory_root.reference, "./memory");
    assert_eq!(
        sac.permissions.allowed_operations,
        vec![
            "file.write".to_string(),
            "financial.transaction".to_string()
        ]
    );
}

#[test]
fn test_save_and_load_encrypts_at_rest() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("test-sac.json");

    let sac = SACContainer::create("./memory");
    let original_key_bytes = sac.root_key.key_bytes.clone();

    sac.save(&path, TEST_PASSPHRASE).unwrap();
    let loaded = SACContainer::load(&path, TEST_PASSPHRASE).unwrap();

    let raw: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    assert_ne!(
        raw["root_key"]["key_bytes"].as_str().unwrap(),
        base64::engine::general_purpose::STANDARD.encode(&original_key_bytes)
    );
    assert_ne!(
        raw["memory_root"]["reference"].as_str().unwrap(),
        "./memory"
    );
    assert_eq!(loaded.root_key.key_bytes, original_key_bytes);
}

#[test]
fn test_load_rejects_tampered_container() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("tampered.json");

    let sac = SACContainer::create("./memory");
    sac.save(&path, TEST_PASSPHRASE).unwrap();

    let mut raw: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    raw["permissions"]["allowed_operations"]
        .as_array_mut()
        .unwrap()
        .push(serde_json::json!("financial.transaction"));
    std::fs::write(&path, serde_json::to_string_pretty(&raw).unwrap()).unwrap();

    assert!(SACContainer::load(&path, TEST_PASSPHRASE).is_err());
}

#[test]
fn test_derive_agent_and_revoke() {
    let mut sac = SACContainer::create("./memory");
    let child_permissions = PermissionCage {
        allowed_operations: vec!["file.write".to_string()],
        financial_daily_limit: None,
        financial_single_tx_limit: None,
        actions_require_confirmation: vec!["file.write".to_string()],
    };
    let agent = sac
        .derive_agent_with_permissions("email-handler", child_permissions)
        .unwrap();

    assert_eq!(
        agent.permissions.allowed_operations,
        vec!["file.write".to_string()]
    );
    sac.revoke_agent(&agent.agent_id).unwrap();

    let mut ctx = HashMap::new();
    ctx.insert("agent_id".to_string(), serde_json::json!(agent.agent_id));
    assert!(sac.check_permission("file.write", &ctx).is_err());
}

#[test]
fn test_derive_agent_rejects_permission_escalation() {
    let mut sac = SACContainer::create("./memory");
    sac.permissions.allowed_operations = vec!["file.write".to_string()];

    let child = PermissionCage {
        allowed_operations: vec![
            "file.write".to_string(),
            "financial.transaction".to_string(),
        ],
        financial_daily_limit: None,
        financial_single_tx_limit: None,
        actions_require_confirmation: Vec::new(),
    };

    assert!(sac
        .derive_agent_with_permissions("too-wide", child)
        .is_err());
}

#[test]
fn test_derive_agent_can_disable_parent_limited_operation() {
    let mut sac = SACContainer::create("./memory");
    sac.permissions.financial_single_tx_limit = Some(10.0);
    sac.permissions.actions_require_confirmation = vec!["file.write".to_string()];

    let child = PermissionCage {
        allowed_operations: vec!["file.write".to_string()],
        financial_daily_limit: None,
        financial_single_tx_limit: None,
        actions_require_confirmation: vec!["file.write".to_string()],
    };

    let agent = sac
        .derive_agent_with_permissions("write-only", child)
        .expect("child that disables financial access should still be valid");
    assert_eq!(
        agent.permissions.allowed_operations,
        vec!["file.write".to_string()]
    );
}

#[test]
fn test_rotate_key() {
    let mut sac = SACContainer::create("./memory");
    let old_key_id = sac.root_key.key_id.clone();
    let old_key_bytes = sac.root_key.key_bytes.clone();
    sac.rotate_key();
    assert_ne!(sac.root_key.key_id, old_key_id);
    assert_ne!(sac.root_key.key_bytes, old_key_bytes);
}

#[test]
fn test_export_metadata_redacts_reference() {
    let mut sac = SACContainer::create("./memory");
    sac.derive_agent("test-agent");
    let meta = sac.export_metadata();
    let reference = meta["memory_root"]["reference"].as_str().unwrap();

    assert!(reference.starts_with("sha256:"));
    assert_ne!(reference, "./memory");
    assert!(meta["root_key"].get("key_bytes").is_none());
}

#[test]
fn test_permission_limits_and_confirmation() {
    let mut sac = SACContainer::create("./memory");
    sac.permissions.financial_single_tx_limit = Some(1000.0);
    sac.permissions.financial_daily_limit = Some(5000.0);
    sac.permissions.actions_require_confirmation = vec!["file.write".to_string()];

    let mut tx_ctx = HashMap::new();
    tx_ctx.insert("amount".to_string(), serde_json::json!(500.0));
    tx_ctx.insert("daily_total".to_string(), serde_json::json!(3000.0));
    assert!(sac
        .check_permission("financial.transaction", &tx_ctx)
        .is_ok());

    tx_ctx.insert("amount".to_string(), serde_json::json!(2500.0));
    assert!(sac
        .check_permission("financial.transaction", &tx_ctx)
        .is_err());

    let write_ctx = HashMap::new();
    assert!(sac.check_permission("file.write", &write_ctx).is_err());
}

#[test]
fn test_user_confirmed_context_allows_confirmed_action() {
    let mut sac = SACContainer::create("./memory");
    sac.permissions.actions_require_confirmation = vec!["file.write".to_string()];

    let mut ctx = HashMap::new();
    ctx.insert("user_confirmed".to_string(), serde_json::json!(true));

    assert!(sac.check_permission("file.write", &ctx).is_ok());
}

#[test]
fn test_unknown_operation_denied() {
    let sac = SACContainer::create("./memory");
    let ctx = HashMap::new();
    assert!(sac.check_permission("data.read", &ctx).is_err());
}

#[test]
fn test_key_derivation_deterministic() {
    let key = RootKeyMaterial::generate();
    let k1 = key.derive_child_key("test-purpose");
    let k2 = key.derive_child_key("test-purpose");
    let k3 = key.derive_child_key("different-purpose");
    assert_eq!(k1, k2);
    assert_ne!(k1, k3);
}

#[test]
fn test_save_load_preserves_derived_agents() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("test-sac.json");

    let mut sac = SACContainer::create("./memory");
    sac.derive_agent("agent-1");
    sac.derive_agent_with_permissions(
        "agent-2",
        PermissionCage {
            allowed_operations: vec!["file.write".to_string()],
            financial_daily_limit: None,
            financial_single_tx_limit: None,
            actions_require_confirmation: vec!["file.write".to_string()],
        },
    )
    .unwrap();

    sac.save(&path, TEST_PASSPHRASE).unwrap();
    let loaded = SACContainer::load(&path, TEST_PASSPHRASE).unwrap();

    assert_eq!(loaded.derived_agents.len(), 2);
    assert_eq!(
        loaded.derived_agents[1]
            .permissions
            .actions_require_confirmation,
        vec!["file.write".to_string()]
    );
}

#[test]
fn test_fixture_loads() {
    let sac = SACContainer::load(
        fixtures_dir().join("python_generated.json"),
        TEST_PASSPHRASE,
    )
    .expect("Rust must load Python-generated SAC");
    assert_eq!(sac.memory_root.reference, "./memory");
    assert_eq!(sac.derived_agents.len(), 1);

    let sac = SACContainer::load(fixtures_dir().join("rust_generated.json"), TEST_PASSPHRASE)
        .expect("Rust must load Rust-generated SAC");
    assert_eq!(sac.permissions.financial_single_tx_limit, Some(500.0));
}

#[test]
fn test_export_metadata_schema() {
    let schema = load_schema("sac.v1.metadata.schema.json");
    let mut sac = SACContainer::create("./memory");
    sac.derive_agent("meta-test");
    let meta = sac.export_metadata();
    validate_against(&schema, &meta);
}

#[test]
fn test_container_schema_for_save_output() {
    let schema = load_schema("sac.v1.container.schema.json");
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("sac.json");
    let mut sac = SACContainer::create("./memory");
    sac.derive_agent("schema-test");
    sac.save(&path, TEST_PASSPHRASE).unwrap();
    let data: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    validate_against(&schema, &data);
}

#[test]
fn test_fixture_schemas() {
    let schema = load_schema("sac.v1.container.schema.json");
    for name in ["python_generated.json", "rust_generated.json"] {
        let data: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(fixtures_dir().join(name)).unwrap())
                .unwrap();
        validate_against(&schema, &data);
    }
}

#[test]
fn test_container_schema_rejects_missing_crypto() {
    let schema = load_schema("sac.v1.container.schema.json");
    let mut sac = SACContainer::create("./memory");
    sac.derive_agent("test");
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("sac.json");
    sac.save(&path, TEST_PASSPHRASE).unwrap();
    let mut data: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    data.as_object_mut().unwrap().remove("crypto");
    let validator = jsonschema::validator_for(&schema).unwrap();
    assert!(validator.iter_errors(&data).next().is_some());
}

#[test]
fn test_load_rejects_extra_top_level_field() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("extra-field.json");

    let sac = SACContainer::create("./memory");
    sac.save(&path, TEST_PASSPHRASE).unwrap();

    let mut data: serde_json::Value =
        serde_json::from_str(&std::fs::read_to_string(&path).unwrap()).unwrap();
    data["persona"] = serde_json::json!("bad");
    std::fs::write(&path, serde_json::to_string_pretty(&data).unwrap()).unwrap();

    let err = SACContainer::load(&path, TEST_PASSPHRASE).unwrap_err();
    let rendered = format!("{:?}", err);
    assert!(
        rendered.contains("unknown field") || rendered.contains("persona"),
        "unexpected error: {rendered}"
    );
}

#[test]
fn test_metadata_schema_rejects_key_bytes() {
    let schema = load_schema("sac.v1.metadata.schema.json");
    let mut meta = SACContainer::create("./memory").export_metadata();
    meta["root_key"]
        .as_object_mut()
        .unwrap()
        .insert("key_bytes".into(), "leaked".into());
    let validator = jsonschema::validator_for(&schema).unwrap();
    assert!(validator.iter_errors(&meta).next().is_some());
}

#[test]
fn test_metadata_schema_rejects_recovery_params() {
    let schema = load_schema("sac.v1.metadata.schema.json");
    let mut meta = SACContainer::create("./memory").export_metadata();
    meta.as_object_mut()
        .unwrap()
        .insert("recovery_params".into(), serde_json::json!({}));
    let validator = jsonschema::validator_for(&schema).unwrap();
    assert!(validator.iter_errors(&meta).next().is_some());
}
