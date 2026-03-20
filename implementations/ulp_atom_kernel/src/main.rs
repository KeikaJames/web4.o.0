use std::io::Read;
use std::process;

use ulp_atom_kernel::runner::{run_request, run_request_remote};
use ulp_atom_kernel::server::run_server;

const USAGE: &str = "\
ulp_atom_kernel_runner — local ULP atom kernel dispatch

Usage:
  ulp_atom_kernel_runner [OPTIONS] [REQUEST_FILE]
  ulp_atom_kernel_runner --server [ADDR]

Options:
  --nodes <FILE>         JSON file with candidate node profiles (local mode)
  --remote-nodes <FILE>  JSON file with remote node endpoints (federation mode)
  --kv <FILE>            JSON file with active KV chunks
  --server [ADDR]        Run as HTTP server (default: 127.0.0.1:3000)
  -h, --help             Show this help

Reads a JSON SACRequest from REQUEST_FILE (or stdin),
routes across candidate nodes, migrates KV if needed,
executes, and prints a JSON AtomResponse.

Server mode listens for POST /dispatch with AtomRequest JSON.";

#[derive(Debug, PartialEq, Eq)]
struct CliArgs {
    nodes_path: Option<String>,
    remote_nodes_path: Option<String>,
    kv_path: Option<String>,
    request_path: Option<String>,
    server_mode: bool,
    server_addr: String,
    show_help: bool,
}

fn parse_args(args: &[String]) -> Result<CliArgs, String> {
    let mut nodes_path: Option<String> = None;
    let mut remote_nodes_path: Option<String> = None;
    let mut kv_path: Option<String> = None;
    let mut request_path: Option<String> = None;
    let mut server_mode = false;
    let mut server_addr = "127.0.0.1:3000".to_string();
    let mut i = 1;

    while i < args.len() {
        match args[i].as_str() {
            "-h" | "--help" => {
                return Ok(CliArgs {
                    nodes_path,
                    remote_nodes_path,
                    kv_path,
                    request_path,
                    server_mode,
                    server_addr,
                    show_help: true,
                });
            }
            "--nodes" => {
                i += 1;
                nodes_path = Some(args.get(i).ok_or("--nodes requires a file")?.clone());
            }
            "--remote-nodes" => {
                i += 1;
                remote_nodes_path = Some(args.get(i).ok_or("--remote-nodes requires a file")?.clone());
            }
            "--kv" => {
                i += 1;
                kv_path = Some(args.get(i).ok_or("--kv requires a file")?.clone());
            }
            "--server" => {
                server_mode = true;
                if i + 1 < args.len() && !args[i + 1].starts_with('-') {
                    i += 1;
                    server_addr = args[i].clone();
                }
            }
            arg if arg.starts_with('-') => {
                return Err(format!("unknown option: {arg}"));
            }
            positional => {
                if request_path.is_some() {
                    return Err(format!("multiple request files provided: {}", positional));
                }
                request_path = Some(positional.to_string());
            }
        }
        i += 1;
    }

    Ok(CliArgs {
        nodes_path,
        remote_nodes_path,
        kv_path,
        request_path,
        server_mode,
        server_addr,
        show_help: false,
    })
}

async fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().collect();
    let parsed = parse_args(&args)?;

    if parsed.show_help {
        println!("{USAGE}");
        return Ok(());
    }

    if parsed.server_mode {
        println!("Starting server on {}", parsed.server_addr);
        run_server(&parsed.server_addr).await?;
        return Ok(());
    }

    let request_json = match parsed.request_path {
        Some(p) => std::fs::read_to_string(&p).map_err(|e| format!("read {p}: {e}"))?,
        None => {
            let mut buf = String::new();
            std::io::stdin().read_to_string(&mut buf).map_err(|e| format!("stdin: {e}"))?;
            buf
        }
    };

    let kv_json = match &parsed.kv_path {
        Some(p) => Some(std::fs::read_to_string(p).map_err(|e| format!("read {p}: {e}"))?),
        None => None,
    };

    // Federation mode: use remote nodes
    if let Some(remote_path) = &parsed.remote_nodes_path {
        let remote_json = std::fs::read_to_string(remote_path)
            .map_err(|e| format!("read {remote_path}: {e}"))?;
        let output = run_request_remote(&request_json, &remote_json, kv_json.as_deref()).await?;
        println!("{output}");
        return Ok(());
    }

    // Local mode: use local nodes
    let nodes_json = match &parsed.nodes_path {
        Some(p) => Some(std::fs::read_to_string(p).map_err(|e| format!("read {p}: {e}"))?),
        None => None,
    };

    let output = run_request(
        &request_json,
        nodes_json.as_deref(),
        kv_json.as_deref(),
    )?;
    println!("{output}");
    Ok(())
}

#[tokio::main]
async fn main() {
    if let Err(e) = run().await {
        eprintln!("error: {e}");
        process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::{parse_args, CliArgs};

    fn args(parts: &[&str]) -> Vec<String> {
        let mut all = vec!["ulp_atom_kernel_runner".to_string()];
        all.extend(parts.iter().map(|part| (*part).to_string()));
        all
    }

    #[test]
    fn parse_args_accepts_expected_flags() {
        let parsed = parse_args(&args(&["--nodes", "nodes.json", "--kv", "kv.json", "req.json"])).unwrap();
        assert_eq!(
            parsed,
            CliArgs {
                nodes_path: Some("nodes.json".into()),
                remote_nodes_path: None,
                kv_path: Some("kv.json".into()),
                request_path: Some("req.json".into()),
                server_mode: false,
                server_addr: "127.0.0.1:3000".into(),
                show_help: false,
            }
        );
    }

    #[test]
    fn parse_args_rejects_unknown_flag() {
        let err = parse_args(&args(&["--wat"])).unwrap_err();
        assert_eq!(err, "unknown option: --wat");
    }

    #[test]
    fn parse_args_rejects_multiple_request_files() {
        let err = parse_args(&args(&["a.json", "b.json"])).unwrap_err();
        assert_eq!(err, "multiple request files provided: b.json");
    }

    #[test]
    fn parse_args_accepts_server_mode() {
        let parsed = parse_args(&args(&["--server"])).unwrap();
        assert!(parsed.server_mode);
        assert_eq!(parsed.server_addr, "127.0.0.1:3000");
    }

    #[test]
    fn parse_args_accepts_server_with_addr() {
        let parsed = parse_args(&args(&["--server", "0.0.0.0:8080"])).unwrap();
        assert!(parsed.server_mode);
        assert_eq!(parsed.server_addr, "0.0.0.0:8080");
    }
}
