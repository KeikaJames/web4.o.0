use serde::{Deserialize, Serialize};

use crate::atom::Region;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KVChunk {
    pub chunk_id: String,
    pub source_region: Region,
    pub seq_start: u64,
    pub seq_end: u64,
    pub byte_size: usize,
    pub payload: Vec<u8>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MigrationReceipt {
    pub chunk_id: String,
    pub from: Region,
    pub to: Region,
    pub byte_size: usize,
}

/// Estimated cost of moving KV state between two regions.
/// 0.0 = same region (no transfer), scales with byte_size for cross-region.
pub fn migration_cost(chunk: &KVChunk, target: &Region) -> f64 {
    if chunk.source_region == *target {
        0.0
    } else {
        // normalized: bytes / 1MB, so cost is proportional but bounded
        chunk.byte_size as f64 / (1024.0 * 1024.0)
    }
}

pub fn migrate(chunk: KVChunk, target: Region) -> (KVChunk, MigrationReceipt) {
    let receipt = MigrationReceipt {
        chunk_id: chunk.chunk_id.clone(),
        from: chunk.source_region.clone(),
        to: target.clone(),
        byte_size: chunk.byte_size,
    };
    let migrated = KVChunk {
        source_region: target,
        ..chunk
    };
    (migrated, receipt)
}
