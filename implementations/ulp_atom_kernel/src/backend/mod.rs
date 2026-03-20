pub mod r#trait;
pub mod mock;
pub mod http;
pub mod vulkan;
pub mod vulkan_util;
pub mod cuda;
pub mod cuda_util;
pub mod config;
pub mod selector;

pub use r#trait::{Backend, BackendKind, BackendRequest, BackendResponse, DeviceCapabilities};
pub use mock::MockBackend;
pub use http::HttpBackend;
pub use vulkan::VulkanBackend;
pub use cuda::CudaBackend;
pub use config::BackendType;
pub use selector::{resolve_backend, BackendPreference};
