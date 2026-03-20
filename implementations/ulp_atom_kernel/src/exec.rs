use serde::{Deserialize, Serialize};

use crate::atom::Region;
use crate::kv::{KVChunk, MigrationReceipt};
use crate::router::PlacementDecision;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecRequest {
    pub atom_id: String,
    pub input: Vec<u8>,
    pub kv_state: Vec<KVChunk>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExecResponse {
    pub atom_id: String,
    pub output: Vec<u8>,
    pub tokens_produced: u32,
    #[serde(default)]
    pub kv_state: Vec<KVChunk>,
}

/// The kernel's execution-facing boundary.
///
/// An implementor is one compute atom that can:
/// - execute a request (inference, embedding, etc.)
/// - migrate KV state to a target region
/// - accept a placement decision from the router
pub trait ComputeKernel {
    fn execute(&self, request: ExecRequest, placement: &PlacementDecision) -> Result<ExecResponse, String>;
    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String>;
}
