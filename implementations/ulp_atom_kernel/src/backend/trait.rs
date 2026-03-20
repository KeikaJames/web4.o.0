use serde::{Deserialize, Serialize};

use crate::atom::Region;
use crate::kv::{KVChunk, MigrationReceipt};
use crate::shard::{ShardRef, LoadedShard};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum BackendKind {
    Mock,
    Http,
    Vulkan,
    Cuda,
}

impl std::fmt::Display for BackendKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            BackendKind::Mock => write!(f, "mock"),
            BackendKind::Http => write!(f, "http"),
            BackendKind::Vulkan => write!(f, "vulkan"),
            BackendKind::Cuda => write!(f, "cuda"),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendRequest {
    pub atom_id: String,
    pub input: Vec<u8>,
    pub kv_state: Vec<KVChunk>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BackendResponse {
    pub atom_id: String,
    pub output: Vec<u8>,
    pub tokens_produced: u32,
    pub kv_state: Vec<KVChunk>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeviceCapabilities {
    pub backend_kind: BackendKind,
    pub device_name: String,
    pub available: bool,
    pub compute_units: u32,
    pub memory_mb: u64,
    pub supports_prefill: bool,
    pub supports_decode: bool,
}

/// Unified compute backend trait
pub trait Backend: Send + Sync {
    fn execute_prefill(&self, request: BackendRequest) -> Result<BackendResponse, String>;
    fn execute_decode(&self, request: BackendRequest) -> Result<BackendResponse, String>;
    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String>;
    fn device_capabilities(&self) -> DeviceCapabilities;

    /// Load a shard from its source into memory.
    fn load_shard(&self, shard: &ShardRef) -> Result<LoadedShard, String> {
        crate::shard::load_shard(shard)
    }
}
