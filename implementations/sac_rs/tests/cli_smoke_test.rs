use std::process::Command;

const TEST_PASSPHRASE: &str = "correct horse battery staple";

fn cargo_bin() -> Command {
    let mut cmd = Command::new(env!("CARGO"));
    cmd.args(["run", "--quiet", "--"]);
    cmd.current_dir(env!("CARGO_MANIFEST_DIR"));
    cmd.env("SAC_PASSPHRASE", TEST_PASSPHRASE);
    cmd
}

#[test]
fn test_cli_create_show_roundtrip() {
    let dir = tempfile::tempdir().unwrap();
    let sac_path = dir.path().join("test.json");
    let sac_str = sac_path.to_str().unwrap();

    // create
    let out = cargo_bin()
        .args(["create", "--output", sac_str, "--memory-path", "./mem"])
        .output()
        .unwrap();
    assert!(
        out.status.success(),
        "create failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("Created SAC:"));

    // show
    let out = cargo_bin().args(["show", sac_str]).output().unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("Memory Root: ./mem"));
}

#[test]
fn test_cli_derive_agent_and_export() {
    let dir = tempfile::tempdir().unwrap();
    let sac_path = dir.path().join("test.json");
    let sac_str = sac_path.to_str().unwrap();

    // create
    cargo_bin()
        .args(["create", "--output", sac_str])
        .output()
        .unwrap();

    // derive-agent
    let out = cargo_bin()
        .args(["derive-agent", sac_str, "--purpose", "test-bot"])
        .output()
        .unwrap();
    assert!(out.status.success());
    assert!(String::from_utf8_lossy(&out.stdout).contains("Purpose: test-bot"));

    // export-metadata must not contain key_bytes
    let out = cargo_bin()
        .args(["export-metadata", sac_str])
        .output()
        .unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(!stdout.contains("key_bytes"));
    assert!(stdout.contains("test-bot"));
}

#[test]
fn test_cli_rotate_key() {
    let dir = tempfile::tempdir().unwrap();
    let sac_path = dir.path().join("test.json");
    let sac_str = sac_path.to_str().unwrap();

    cargo_bin()
        .args(["create", "--output", sac_str])
        .output()
        .unwrap();

    let out = cargo_bin().args(["rotate-key", sac_str]).output().unwrap();
    assert!(out.status.success());
    let stdout = String::from_utf8_lossy(&out.stdout);
    assert!(stdout.contains("Old key ID:"));
    assert!(stdout.contains("New key ID:"));
}

#[test]
fn test_cli_check_permission_allow_deny() {
    let dir = tempfile::tempdir().unwrap();
    let sac_path = dir.path().join("test.json");
    let sac_str = sac_path.to_str().unwrap();

    cargo_bin()
        .args(["create", "--output", sac_str, "--financial-limit", "1000"])
        .output()
        .unwrap();

    // under limit -> allowed
    let out = cargo_bin()
        .args([
            "check-permission",
            sac_str,
            "--operation",
            "financial.transaction",
            "--amount",
            "500",
        ])
        .output()
        .unwrap();
    assert!(out.status.success());
    assert!(String::from_utf8_lossy(&out.stdout).contains("ALLOWED"));

    // over limit -> denied (exit 1)
    let out = cargo_bin()
        .args([
            "check-permission",
            sac_str,
            "--operation",
            "financial.transaction",
            "--amount",
            "2000",
        ])
        .output()
        .unwrap();
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stdout).contains("DENIED"));
}

#[test]
fn test_cli_no_args_shows_usage() {
    let out = cargo_bin().output().unwrap();
    assert!(!out.status.success());
    assert!(String::from_utf8_lossy(&out.stderr).contains("Usage:"));
}
