use crate::atom::Region;
use crate::backend::r#trait::{Backend, BackendRequest, BackendResponse, DeviceCapabilities};
use crate::kv::{migrate, KVChunk, MigrationReceipt};
use crate::shard::{LoadedShard, ShardRef};

/// Mock backend: uppercase ASCII, pass-through KV
pub struct MockBackend;

impl Backend for MockBackend {
    fn execute_prefill(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        let output = request.input.iter().map(|b| {
            if b.is_ascii_lowercase() { b - 32 } else { *b }
        }).collect();
        Ok(BackendResponse {
            atom_id: request.atom_id,
            output,
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }

    fn execute_decode(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        let output = request.input.iter().map(|b| {
            if b.is_ascii_lowercase() { b - 32 } else { *b }
        }).collect();
        Ok(BackendResponse {
            atom_id: request.atom_id,
            output,
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }

    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String> {
        Ok(migrate(chunk, target))
    }

    fn device_capabilities(&self) -> DeviceCapabilities {
        DeviceCapabilities {
            backend_kind: crate::backend::BackendKind::Mock,
            device_name: "MockCPU".into(),
            available: true,
            compute_units: 1,
            memory_mb: 0,
            supports_prefill: true,
            supports_decode: true,
        }
    }

    fn load_shard(&self, shard: &ShardRef) -> Result<LoadedShard, String> {
        let size = shard.byte_size.unwrap_or(64) as usize;
        let data: Vec<u8> = shard.shard_id.bytes().cycle().take(size).collect();
        Ok(LoadedShard {
            shard_id: shard.shard_id.clone(),
            byte_size: data.len() as u64,
            data,
            checksum_verified: false,
        })
    }
}
