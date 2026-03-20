use serde::{Deserialize, Serialize};

use crate::atom::{AtomKind, ComputeAtom, Region};
use crate::kernel::AtomRequest;
use crate::kv::KVChunk;
use crate::router::NodeProfile;

/// Minimal SAC-backed request context.
/// Carries the agent identity and sovereignty constraints
/// that a SAC container would provide.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SACRequest {
    pub agent_id: String,
    pub sovereignty_zone: String,
    pub model_id: String,
    pub atom_kind: AtomKind,
    pub input: Vec<u8>,
    #[serde(default)]
    pub two_stage: bool,
}

/// Convert a SAC-backed request into a kernel AtomRequest,
/// given the current KV state and candidate nodes.
pub fn into_atom_request(
    sac_req: &SACRequest,
    kv_state: Vec<KVChunk>,
    candidates: Vec<NodeProfile>,
) -> AtomRequest {
    let region = Region(sac_req.sovereignty_zone.clone());
    AtomRequest {
        atom: ComputeAtom {
            id: format!("atom-{}", sac_req.agent_id),
            kind: sac_req.atom_kind.clone(),
            region,
            model_id: sac_req.model_id.clone(),
            shard_count: 0,
        },
        input: sac_req.input.clone(),
        kv_state,
        candidates,
    }
}
