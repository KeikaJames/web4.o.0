use crate::atom::Region;
use crate::backend::{resolve_backend, BackendPreference};
use crate::client::RemoteClient;
use crate::exec::*;
use crate::kernel::*;
use crate::kv::*;
use crate::pipeline::execute_two_stage;
use crate::remote::{dispatch_federation, RemoteNode};
use crate::router::*;
use crate::sac_bridge::*;

/// Local stub kernel: uppercase ASCII, pass-through everything else.
pub struct LocalKernel;

impl ComputeKernel for LocalKernel {
    fn execute(&self, request: ExecRequest, _placement: &PlacementDecision) -> Result<ExecResponse, String> {
        let output = request.input.iter().map(|b| {
            if b.is_ascii_lowercase() { b - 32 } else { *b }
        }).collect();
        Ok(ExecResponse {
            atom_id: request.atom_id,
            output,
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }

    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String> {
        Ok(migrate(chunk, target))
    }
}

/// Build a single local fallback node from a SACRequest.
fn local_candidates(sac_req: &SACRequest) -> Vec<NodeProfile> {
    vec![NodeProfile {
        node_id: "local-0".into(),
        region: Region(sac_req.sovereignty_zone.clone()),
        latency_ms: 1.0,
        hotness: 1.0,
        supported_kinds: vec![sac_req.atom_kind.clone()],
        sovereignty_zone: sac_req.sovereignty_zone.clone(),
        prefill_affinity: 0.5,
        decode_affinity: 0.5,
        capacity: Default::default(),
    }]
}

/// Run with explicit node set and optional KV state.
pub fn run_request(
    request_json: &str,
    nodes_json: Option<&str>,
    kv_json: Option<&str>,
) -> Result<String, String> {
    let sac_req: SACRequest = serde_json::from_str(request_json)
        .map_err(|e| format!("parse request: {e}"))?;

    let candidates = match nodes_json {
        Some(nj) => serde_json::from_str::<Vec<NodeProfile>>(nj)
            .map_err(|e| format!("parse nodes: {e}"))?,
        None => local_candidates(&sac_req),
    };

    let kv_state = match kv_json {
        Some(kj) => serde_json::from_str::<Vec<KVChunk>>(kj)
            .map_err(|e| format!("parse kv: {e}"))?,
        None => vec![],
    };

    let atom_req = into_atom_request(&sac_req, kv_state, candidates);

    // Auto-resolve backend: try Vulkan, fallback to Mock
    let resolved = resolve_backend(BackendPreference::Auto, 0, None)
        .map_err(|e| format!("backend resolution: {}", e))?;

    let resp = dispatch(resolved.backend.as_ref(), atom_req)?;
    serde_json::to_string_pretty(&resp).map_err(|e| format!("json: {e}"))
}

/// Backward-compatible: single JSON, local-only.
pub fn run_from_json(json_input: &str) -> Result<String, String> {
    run_request(json_input, None, None)
}

/// Run with remote node federation
pub async fn run_request_remote(
    request_json: &str,
    remote_nodes_json: &str,
    kv_json: Option<&str>,
) -> Result<String, String> {
    let sac_req: SACRequest = serde_json::from_str(request_json)
        .map_err(|e| format!("parse request: {e}"))?;

    let remote_nodes: Vec<RemoteNode> = serde_json::from_str(remote_nodes_json)
        .map_err(|e| format!("parse remote nodes: {e}"))?;

    let kv_state = match kv_json {
        Some(kj) => serde_json::from_str::<Vec<KVChunk>>(kj)
            .map_err(|e| format!("parse kv: {e}"))?,
        None => vec![],
    };

    let region = Region(sac_req.sovereignty_zone.clone());
    let client = RemoteClient::new();

    // Two-stage mode
    if sac_req.two_stage {
        let prefill_atom = crate::atom::ComputeAtom {
            id: format!("atom-{}-prefill", sac_req.agent_id),
            kind: crate::atom::AtomKind::Prefill,
            region: region.clone(),
            model_id: sac_req.model_id.clone(),
            shard_count: 0,
        };

        let decode_atom = crate::atom::ComputeAtom {
            id: format!("atom-{}-decode", sac_req.agent_id),
            kind: crate::atom::AtomKind::Decode,
            region,
            model_id: sac_req.model_id.clone(),
            shard_count: 0,
        };

        let resp = execute_two_stage(&client, prefill_atom, decode_atom, sac_req.input, kv_state, &remote_nodes).await?;
        return serde_json::to_string_pretty(&resp).map_err(|e| format!("json: {e}"));
    }

    // Single-stage mode
    let atom = crate::atom::ComputeAtom {
        id: format!("atom-{}", sac_req.agent_id),
        kind: sac_req.atom_kind.clone(),
        region,
        model_id: sac_req.model_id.clone(),
        shard_count: 0,
    };

    let resp = dispatch_federation(&client, atom, sac_req.input, kv_state, &remote_nodes).await?;
    serde_json::to_string_pretty(&resp).map_err(|e| format!("json: {e}"))
}
