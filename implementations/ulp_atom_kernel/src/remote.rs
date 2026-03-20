use serde::{Deserialize, Serialize};

use crate::atom::ComputeAtom;
use crate::client::RemoteClient;
use crate::kernel::{AtomRequest, AtomResponse};
use crate::kv::KVChunk;
use crate::router::{self, KVContext, NodeProfile};

/// Remote node with endpoint
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RemoteNode {
    #[serde(flatten)]
    pub profile: NodeProfile,
    pub endpoint: String,
}

/// Federation dispatch: route locally, then send to chosen remote node
pub async fn dispatch_federation(
    client: &RemoteClient,
    atom: ComputeAtom,
    input: Vec<u8>,
    kv_state: Vec<KVChunk>,
    remote_nodes: &[RemoteNode],
) -> Result<AtomResponse, String> {
    if remote_nodes.is_empty() {
        return Err("no remote nodes available".to_string());
    }

    // 1. Local placement decision
    let candidates: Vec<NodeProfile> = remote_nodes.iter().map(|rn| rn.profile.clone()).collect();
    let kv_ctx = KVContext { active_chunks: &kv_state };
    let placement = router::route_with_kv(&atom, &candidates, Some(&kv_ctx))
        .ok_or_else(|| "no candidate nodes".to_string())?;

    // 2. Find chosen remote node endpoint
    let chosen = remote_nodes
        .iter()
        .find(|rn| rn.profile.node_id == placement.breakdown.node_id)
        .ok_or_else(|| format!("chosen node {} not found in remote set", placement.breakdown.node_id))?;

    // 3. Dispatch to remote node
    let request = AtomRequest {
        atom,
        input,
        kv_state,
        candidates: vec![chosen.profile.clone()],
    };

    client.dispatch(&chosen.endpoint, request).await
}
