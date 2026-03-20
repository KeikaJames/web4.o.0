use crate::atom::Region;
use crate::backend::r#trait::{Backend, BackendRequest, BackendResponse, DeviceCapabilities};
use crate::backend::vulkan_util::VulkanContext;
use crate::kv::{migrate, KVChunk, MigrationReceipt};

/// Vulkan compute backend — real GPU execution when available.
pub struct VulkanBackend {
    ctx: Option<VulkanContext>,
    init_error: Option<String>,
    device_index: u32,
}

impl VulkanBackend {
    pub fn new(device_index: u32) -> Self {
        match VulkanContext::new(device_index) {
            Ok(ctx) => Self { ctx: Some(ctx), init_error: None, device_index },
            Err(e) => Self { ctx: None, init_error: Some(e), device_index },
        }
    }

    /// Whether a real Vulkan device was successfully initialized.
    pub fn is_available(&self) -> bool {
        self.ctx.is_some()
    }

    /// The initialization error, if Vulkan is unavailable.
    pub fn init_error(&self) -> Option<&str> {
        self.init_error.as_deref()
    }

    /// The requested device index.
    pub fn device_index(&self) -> u32 {
        self.device_index
    }

    /// Number of physical devices found (0 if Vulkan loader failed).
    pub fn device_count(&self) -> u32 {
        self.ctx.as_ref().map_or(0, |c| c.device_count())
    }

    /// The selected device name, or None if unavailable.
    pub fn selected_device_name(&self) -> Option<&str> {
        self.ctx.as_ref().map(|c| c.device_name())
    }

    fn require_ctx(&self) -> Result<&VulkanContext, String> {
        self.ctx.as_ref().ok_or_else(|| {
            format!("Vulkan unavailable: {}", self.init_error.as_deref().unwrap_or("unknown"))
        })
    }

    fn execute(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        let ctx = self.require_ctx()?;
        let output = ctx.execute_compute(&request.input)?;
        Ok(BackendResponse {
            atom_id: format!("{}-vk", request.atom_id),
            output,
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }
}

impl Backend for VulkanBackend {
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
                backend_kind: crate::backend::BackendKind::Vulkan,
                device_name: ctx.device_name().to_string(),
                available: true,
                compute_units: ctx.compute_units(),
                memory_mb: (ctx.memory_gb() * 1024.0) as u64,
                supports_prefill: true,
                supports_decode: true,
            },
            None => DeviceCapabilities {
                backend_kind: crate::backend::BackendKind::Vulkan,
                device_name: format!("VulkanDevice{} (unavailable)", self.device_index),
                available: false,
                compute_units: 0,
                memory_mb: 0,
                supports_prefill: false,
                supports_decode: false,
            },
        }
    }
}
