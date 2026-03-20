use crate::atom::Region;
use crate::backend::r#trait::{Backend, BackendRequest, BackendResponse, DeviceCapabilities};
use crate::kv::{migrate, KVChunk, MigrationReceipt};

/// HTTP-based external backend stub
#[derive(Clone)]
pub struct HttpBackend {
    pub endpoint: String,
}

impl HttpBackend {
    pub fn new(endpoint: String) -> Self {
        Self { endpoint }
    }
}

impl Backend for HttpBackend {
    fn execute_prefill(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        let output = request.input.iter().map(|b| b.wrapping_add(2)).collect();
        Ok(BackendResponse {
            atom_id: format!("{}-http", request.atom_id),
            output,
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }

    fn execute_decode(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        let output = request.input.iter().map(|b| b.wrapping_add(2)).collect();
        Ok(BackendResponse {
            atom_id: format!("{}-http", request.atom_id),
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
            backend_kind: crate::backend::BackendKind::Http,
            device_name: format!("HttpRemote({})", self.endpoint),
            available: true,
            compute_units: 0,
            memory_mb: 0,
            supports_prefill: true,
            supports_decode: true,
        }
    }
}
