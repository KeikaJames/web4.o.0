use crate::backend::r#trait::{Backend, BackendKind, DeviceCapabilities};
use crate::backend::{CudaBackend, HttpBackend, MockBackend, VulkanBackend};

/// Preference for backend resolution.
#[derive(Debug, Clone)]
pub enum BackendPreference {
    /// Try Vulkan first, fall back to Mock if unavailable.
    Auto,
    /// Use a specific backend kind. Vulkan returns Err if unavailable.
    Require(BackendKind),
    /// Try the given kind, fall back to Mock if unavailable.
    Prefer(BackendKind),
}

/// Result of backend resolution — the backend plus why it was chosen.
pub struct ResolvedBackend {
    pub backend: Box<dyn Backend>,
    pub capabilities: DeviceCapabilities,
    pub fallback_used: bool,
    pub reason: String,
}

impl std::fmt::Debug for ResolvedBackend {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ResolvedBackend")
            .field("capabilities", &self.capabilities)
            .field("fallback_used", &self.fallback_used)
            .field("reason", &self.reason)
            .finish()
    }
}

/// Resolve a backend according to the given preference.
///
/// `device_index` is used for Vulkan/Cuda device selection.
/// `http_endpoint` is used when Http is requested.
pub fn resolve_backend(
    pref: BackendPreference,
    device_index: u32,
    http_endpoint: Option<&str>,
) -> Result<ResolvedBackend, String> {
    match pref {
        BackendPreference::Auto => try_auto(device_index),
        BackendPreference::Require(kind) => try_require(kind, device_index, http_endpoint),
        BackendPreference::Prefer(kind) => try_prefer(kind, device_index, http_endpoint),
    }
}

fn try_auto(device_index: u32) -> Result<ResolvedBackend, String> {
    // Try Vulkan first
    let vk = VulkanBackend::new(device_index);
    let vk_caps = vk.device_capabilities();
    if vk_caps.available {
        return Ok(ResolvedBackend {
            reason: format!("auto: vulkan available ({})", vk_caps.device_name),
            capabilities: vk_caps,
            backend: Box::new(vk),
            fallback_used: false,
        });
    }

    // Try CUDA second
    let cuda = CudaBackend::new(device_index);
    let cuda_caps = cuda.device_capabilities();
    if cuda_caps.available {
        return Ok(ResolvedBackend {
            reason: format!("auto: cuda available ({})", cuda_caps.device_name),
            capabilities: cuda_caps,
            backend: Box::new(cuda),
            fallback_used: false,
        });
    }

    // Fall back to Mock
    let mock = MockBackend;
    let caps = mock.device_capabilities();
    Ok(ResolvedBackend {
        reason: format!("auto: vulkan/cuda unavailable, fallback to mock"),
        capabilities: caps,
        backend: Box::new(mock),
        fallback_used: true,
    })
}

fn try_require(
    kind: BackendKind,
    device_index: u32,
    http_endpoint: Option<&str>,
) -> Result<ResolvedBackend, String> {
    let (backend, caps): (Box<dyn Backend>, DeviceCapabilities) = match kind {
        BackendKind::Mock => {
            let b = MockBackend;
            let c = b.device_capabilities();
            (Box::new(b), c)
        }
        BackendKind::Http => {
            let ep = http_endpoint.ok_or("http endpoint required")?;
            let b = HttpBackend::new(ep.to_string());
            let c = b.device_capabilities();
            (Box::new(b), c)
        }
        BackendKind::Vulkan => {
            let b = VulkanBackend::new(device_index);
            let c = b.device_capabilities();
            if !c.available {
                return Err(format!(
                    "vulkan required but unavailable: {}",
                    b.init_error().unwrap_or("unknown")
                ));
            }
            (Box::new(b), c)
        }
        BackendKind::Cuda => {
            let b = CudaBackend::new(device_index);
            let c = b.device_capabilities();
            if !c.available {
                return Err(format!(
                    "cuda required but unavailable: {}",
                    b.init_error().unwrap_or("unknown")
                ));
            }
            (Box::new(b), c)
        }
    };
    Ok(ResolvedBackend {
        reason: format!("require: {kind}"),
        capabilities: caps,
        backend,
        fallback_used: false,
    })
}

fn try_prefer(
    kind: BackendKind,
    device_index: u32,
    http_endpoint: Option<&str>,
) -> Result<ResolvedBackend, String> {
    match try_require(kind, device_index, http_endpoint) {
        Ok(r) => Ok(r),
        Err(_) => {
            let mock = MockBackend;
            let caps = mock.device_capabilities();
            Ok(ResolvedBackend {
                reason: format!("prefer {kind}: unavailable, fallback to mock"),
                capabilities: caps,
                backend: Box::new(mock),
                fallback_used: true,
            })
        }
    }
}
