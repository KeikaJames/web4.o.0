use serde::{Deserialize, Serialize};

use crate::atom::ComputeAtom;
use crate::client::RemoteClient;
use crate::kernel::AtomResponse;
use crate::remote::{dispatch_federation, RemoteNode};

/// Two-stage execution result
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TwoStageResponse {
    pub prefill_node: String,
    pub decode_node: String,
    pub prefill_response: AtomResponse,
    pub decode_response: AtomResponse,
    pub migration_occurred: bool,
}

/// Execute Prefill -> KV migration -> Decode pipeline
pub async fn execute_two_stage(
    client: &RemoteClient,
    prefill_atom: ComputeAtom,
    decode_atom: ComputeAtom,
    input: Vec<u8>,
    initial_kv_state: Vec<crate::kv::KVChunk>,
    remote_nodes: &[RemoteNode],
) -> Result<TwoStageResponse, String> {
    // Stage 1: Prefill
    let prefill_resp = dispatch_federation(
        client,
        prefill_atom.clone(),
        input.clone(),
        initial_kv_state,
        remote_nodes,
    ).await?;

    let prefill_node = prefill_resp.explain.node_id.clone();
    let kv_state = prefill_resp.exec_response.kv_state.clone();

    // Stage 2: Decode with KV from prefill
    let decode_resp = dispatch_federation(
        client,
        decode_atom.clone(),
        input,
        kv_state,
        remote_nodes,
    ).await?;

    let decode_node = decode_resp.explain.node_id.clone();
    let migration_occurred = prefill_node != decode_node;

    Ok(TwoStageResponse {
        prefill_node,
        decode_node,
        prefill_response: prefill_resp,
        decode_response: decode_resp,
        migration_occurred,
    })
}
