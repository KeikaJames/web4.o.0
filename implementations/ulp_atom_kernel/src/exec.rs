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
    #[serde(default)]
    pub adapter_id: Option<String>,
    #[serde(default)]
    pub adapter_generation: Option<u64>,
    /// Adapter specialization for lineage tracking.
    #[serde(default)]
    pub adapter_specialization: Option<crate::adapter::AdapterSpecialization>,
    /// Specialization-aware summary if available.
    #[serde(default)]
    pub specialization_summary: Option<SpecializationSummary>,
}

/// Minimal specialization-aware summary for exec response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SpecializationSummary {
    pub stable_generation: u64,
    #[serde(default)]
    pub shared_generation: Option<u64>,
    #[serde(default)]
    pub candidate_generation: Option<u64>,
    #[serde(default)]
    pub stable_adapter_id: String,
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
