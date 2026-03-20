use crate::atom::Region;
use crate::backend::r#trait::{Backend, BackendRequest, BackendResponse, DeviceCapabilities};
use crate::backend::cuda_util::CudaContext;
use crate::kv::{migrate, KVChunk, MigrationReceipt};

/// CUDA compute backend — real GPU execution when available.
pub struct CudaBackend {
    ctx: Option<CudaContext>,
    init_error: Option<String>,
    device_index: u32,
}

impl CudaBackend {
    pub fn new(device_index: u32) -> Self {
        match CudaContext::new(device_index) {
            Ok(ctx) => Self { ctx: Some(ctx), init_error: None, device_index },
            Err(e) => Self { ctx: None, init_error: Some(e), device_index },
        }
    }

    /// Whether a real CUDA device was successfully initialized.
    pub fn is_available(&self) -> bool {
        self.ctx.is_some()
    }

    /// The initialization error, if CUDA is unavailable.
    pub fn init_error(&self) -> Option<&str> {
        self.init_error.as_deref()
    }

    /// The requested device index.
    pub fn device_index(&self) -> u32 {
        self.device_index
    }

    /// Number of CUDA devices found (0 if driver failed).
    pub fn device_count(&self) -> u32 {
        self.ctx.as_ref().map_or(0, |c| c.device_count())
    }

    /// The selected device name, or None if unavailable.
    pub fn selected_device_name(&self) -> Option<&str> {
        self.ctx.as_ref().map(|c| c.device_name())
    }

    fn require_ctx(&self) -> Result<&CudaContext, String> {
        self.ctx.as_ref().ok_or_else(|| {
            format!("CUDA unavailable: {}", self.init_error.as_deref().unwrap_or("unknown"))
        })
    }

    fn execute(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        let ctx = self.require_ctx()?;
        let output = ctx.execute_compute(&request.input)?;
        Ok(BackendResponse {
            atom_id: format!("{}-cuda", request.atom_id),
            output,
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }
}

impl Backend for CudaBackend {
    fn execute_prefill(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        self.execute(request)
    }

    fn execute_decode(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        self.execute(request)
    }

    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String> {
        Ok(migrate(chunk, target))
    }

    fn device_capabilities(&self) -> DeviceCapabilities {
        match &self.ctx {
            Some(ctx) => DeviceCapabilities {
                backend_kind: crate::backend::BackendKind::Cuda,
                device_name: ctx.device_name().to_string(),
                available: true,
                compute_units: ctx.compute_units(),
                memory_mb: ctx.memory_mb(),
                supports_prefill: true,
                supports_decode: true,
            },
            None => DeviceCapabilities {
                backend_kind: crate::backend::BackendKind::Cuda,
                device_name: format!("CudaDevice{} (unavailable)", self.device_index),
                available: false,
                compute_units: 0,
                memory_mb: 0,
                supports_prefill: false,
                supports_decode: false,
            },
        }
    }
}
