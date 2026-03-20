use sac_rs::SACContainer;
use std::collections::HashMap;
use std::io::{self, IsTerminal, Write};
use std::process;

fn main() {
    let args: Vec<String> = std::env::args().collect();

    if args.len() < 2 {
        print_usage();
        process::exit(1);
    }

    let result = match args[1].as_str() {
        "create" => cmd_create(&args[2..]),
        "show" => cmd_show(&args[2..]),
        "derive-agent" => cmd_derive_agent(&args[2..]),
        "rotate-key" => cmd_rotate_key(&args[2..]),
        "export-metadata" => cmd_export_metadata(&args[2..]),
        "check-permission" => cmd_check_permission(&args[2..]),
        _ => {
            eprintln!("Unknown command: {}", args[1]);
            print_usage();
            process::exit(1);
        }
    };

    if let Err(e) = result {
        eprintln!("Error: {}", e);
        process::exit(1);
    }
}

fn print_usage() {
    eprintln!("Usage: sac <command> [args]");
    eprintln!();
    eprintln!("Commands:");
    eprintln!("  create          --output <path> [--memory-path <path>] [--financial-limit <n>] [--daily-limit <n>] [--passphrase <secret>]");
    eprintln!("  show            <container> [--passphrase <secret>]");
    eprintln!("  derive-agent    <container> --purpose <purpose> [--passphrase <secret>]");
    eprintln!("  rotate-key      <container> [--passphrase <secret>]");
    eprintln!("  export-metadata <container> [--output <path>] [--passphrase <secret>]");
    eprintln!("  check-permission <container> --operation <op> [--amount <n>] [--daily-total <n>] [--confirmed] [--passphrase <secret>]");
}

fn parse_flag(args: &[String], flag: &str) -> Option<String> {
    args.iter()
        .position(|a| a == flag)
        .and_then(|i| args.get(i + 1).cloned())
}

fn has_flag(args: &[String], flag: &str) -> bool {
    args.iter().any(|a| a == flag)
}

fn positional(args: &[String]) -> Option<&str> {
    args.first()
        .map(|s| s.as_str())
        .filter(|s| !s.starts_with('-'))
}

fn passphrase(args: &[String]) -> Result<String, String> {
    if let Some(passphrase) = parse_flag(args, "--passphrase") {
        return Ok(passphrase);
    }
    if let Ok(passphrase) = std::env::var("SAC_PASSPHRASE") {
        if !passphrase.is_empty() {
            return Ok(passphrase);
        }
    }
    if io::stdin().is_terminal() && io::stderr().is_terminal() {
        eprint!("SAC passphrase: ");
        io::stderr().flush().map_err(|e| e.to_string())?;
        return rpassword::read_password().map_err(|e| e.to_string());
    }
    Err("passphrase required: use --passphrase or SAC_PASSPHRASE".to_string())
}

fn cmd_create(args: &[String]) -> Result<(), String> {
    let output = parse_flag(args, "--output").ok_or("--output required")?;
    let memory_path = parse_flag(args, "--memory-path").unwrap_or_else(|| "./memory".to_string());
    let passphrase = passphrase(args)?;

    let mut sac = SACContainer::create(&memory_path);

    if let Some(v) = parse_flag(args, "--financial-limit") {
        sac.permissions.financial_single_tx_limit =
            Some(v.parse::<f64>().map_err(|_| "invalid --financial-limit")?);
    }
    if let Some(v) = parse_flag(args, "--daily-limit") {
        sac.permissions.financial_daily_limit =
            Some(v.parse::<f64>().map_err(|_| "invalid --daily-limit")?);
    }

    sac.save(&output, &passphrase).map_err(|e| format!("{:?}", e))?;

    println!("Created SAC: {}", sac.sac_id);
    println!("Saved to: {}", output);
    println!("Root key ID: {}", sac.root_key.key_id);
    Ok(())
}

fn cmd_show(args: &[String]) -> Result<(), String> {
    let path = positional(args).ok_or("container path required")?;
    let passphrase = passphrase(args)?;
    let sac = SACContainer::load(path, &passphrase).map_err(|e| format!("{:?}", e))?;

    println!("SAC ID: {}", sac.sac_id);
    println!("Created: {}", sac.created_at);
    println!("Root Key ID: {}", sac.root_key.key_id);
    println!("Memory Root: {}", sac.memory_root.reference);
    println!("Derived Agents: {}", sac.derived_agents.len());

    for agent in &sac.derived_agents {
        let status = if agent.revoked { "REVOKED" } else { "ACTIVE" };
        println!(
            "  - {}... | {} | {}",
            &agent.agent_id[..8],
            agent.purpose,
            status
        );
    }
    Ok(())
}

fn cmd_derive_agent(args: &[String]) -> Result<(), String> {
    let path = positional(args).ok_or("container path required")?;
    let purpose = parse_flag(args, "--purpose").ok_or("--purpose required")?;
    let passphrase = passphrase(args)?;

    let mut sac = SACContainer::load(path, &passphrase).map_err(|e| format!("{:?}", e))?;
    let agent = sac.derive_agent(&purpose);
    sac.save(path, &passphrase).map_err(|e| format!("{:?}", e))?;

    println!("Derived agent: {}", agent.agent_id);
    println!("Purpose: {}", agent.purpose);
    println!("Derived key ID: {}", agent.derived_key_id);
    Ok(())
}

fn cmd_rotate_key(args: &[String]) -> Result<(), String> {
    let path = positional(args).ok_or("container path required")?;
    let passphrase = passphrase(args)?;

    let mut sac = SACContainer::load(path, &passphrase).map_err(|e| format!("{:?}", e))?;
    let old_key_id = sac.root_key.key_id.clone();
    sac.rotate_key();
    sac.save(path, &passphrase).map_err(|e| format!("{:?}", e))?;

    println!("Rotated root key");
    println!("Old key ID: {}", old_key_id);
    println!("New key ID: {}", sac.root_key.key_id);
    Ok(())
}

fn cmd_export_metadata(args: &[String]) -> Result<(), String> {
    let path = positional(args).ok_or("container path required")?;
    let passphrase = passphrase(args)?;
    let sac = SACContainer::load(path, &passphrase).map_err(|e| format!("{:?}", e))?;

    let metadata = sac.export_metadata();
    let json = serde_json::to_string_pretty(&metadata).map_err(|e| format!("{:?}", e))?;

    if let Some(output) = parse_flag(args, "--output") {
        std::fs::write(&output, &json).map_err(|e| format!("{:?}", e))?;
        println!("Exported metadata to: {}", output);
    } else {
        println!("{}", json);
    }
    Ok(())
}

fn cmd_check_permission(args: &[String]) -> Result<(), String> {
    let path = positional(args).ok_or("container path required")?;
    let operation = parse_flag(args, "--operation").ok_or("--operation required")?;
    let passphrase = passphrase(args)?;

    let sac = SACContainer::load(path, &passphrase).map_err(|e| format!("{:?}", e))?;

    let mut context = HashMap::new();
    if let Some(v) = parse_flag(args, "--amount") {
        let amount: f64 = v.parse().map_err(|_| "invalid --amount")?;
        context.insert("amount".to_string(), serde_json::json!(amount));
    }
    if let Some(v) = parse_flag(args, "--daily-total") {
        let total: f64 = v.parse().map_err(|_| "invalid --daily-total")?;
        context.insert("daily_total".to_string(), serde_json::json!(total));
    }
    if has_flag(args, "--confirmed") {
        context.insert("user_confirmed".to_string(), serde_json::json!(true));
    }

    match sac.check_permission(&operation, &context) {
        Ok(()) => {
            println!("✓ ALLOWED: {}", operation);
            Ok(())
        }
        Err(reason) => {
            println!("✗ DENIED: {}", operation);
            println!("  Reason: {}", reason);
            std::process::exit(1);
        }
    }
}
