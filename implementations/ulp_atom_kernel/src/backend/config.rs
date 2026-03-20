use crate::backend::r#trait::Backend;
use crate::backend::{CudaBackend, HttpBackend, MockBackend, VulkanBackend};

/// Explicit backend selector (unchanged API, kept for backward compat).
#[derive(Debug, Clone)]
pub enum BackendType {
    Mock,
    Http(String),
    Vulkan(u32),
    Cuda(u32),
}

impl BackendType {
    pub fn create(&self) -> Box<dyn Backend> {
        match self {
            BackendType::Mock => Box::new(MockBackend),
            BackendType::Http(endpoint) => Box::new(HttpBackend::new(endpoint.clone())),
            BackendType::Vulkan(device_index) => Box::new(VulkanBackend::new(*device_index)),
            BackendType::Cuda(device_index) => Box::new(CudaBackend::new(*device_index)),
        }
    }
}
