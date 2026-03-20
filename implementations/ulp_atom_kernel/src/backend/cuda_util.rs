use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int, c_uint, c_void};
use std::ptr;

// --- CUDA Driver API types (minimal) ---
type CUresult = c_int;
type CUdevice = c_int;
type CUcontext = *mut c_void;
type CUmodule = *mut c_void;
type CUfunction = *mut c_void;
type CUdeviceptr = u64;
type CUstream = *mut c_void;

const CUDA_SUCCESS: CUresult = 0;

/// PTX source for: data[i] = (data[i] + 3) & 0xFF
/// Each element is a u32 in the buffer.
pub fn build_add3_ptx() -> &'static str {
    r#"
.version 7.0
.target sm_30
.address_size 64

.visible .entry add3(
    .param .u64 param_data,
    .param .u32 param_n
)
{
    .reg .u64 %rd<4>;
    .reg .u32 %r<6>;
    .reg .pred %p0;

    ld.param.u64 %rd0, [param_data];
    ld.param.u32 %r0, [param_n];

    mov.u32 %r1, %ctaid.x;
    mov.u32 %r2, %ntid.x;
    mov.u32 %r3, %tid.x;
    mad.lo.u32 %r1, %r1, %r2, %r3;

    setp.ge.u32 %p0, %r1, %r0;
    @%p0 bra done;

    // addr = data + idx * 4
    cvt.u64.u32 %rd1, %r1;
    shl.b64 %rd1, %rd1, 2;
    add.u64 %rd2, %rd0, %rd1;

    ld.global.u32 %r4, [%rd2];
    add.u32 %r4, %r4, 3;
    and.b32 %r4, %r4, 255;
    st.global.u32 [%rd2], %r4;

done:
    ret;
}
"#
}

// --- Dynamic CUDA Driver API ---

struct CudaApi {
    _lib: libloading::Library,
    cu_init: unsafe extern "C" fn(c_uint) -> CUresult,
    cu_device_get_count: unsafe extern "C" fn(*mut c_int) -> CUresult,
    cu_device_get: unsafe extern "C" fn(*mut CUdevice, c_int) -> CUresult,
    cu_device_get_name: unsafe extern "C" fn(*mut c_char, c_int, CUdevice) -> CUresult,
    cu_device_total_mem: unsafe extern "C" fn(*mut usize, CUdevice) -> CUresult,
    cu_device_get_attribute: unsafe extern "C" fn(*mut c_int, c_int, CUdevice) -> CUresult,
    cu_ctx_create: unsafe extern "C" fn(*mut CUcontext, c_uint, CUdevice) -> CUresult,
    cu_ctx_destroy: unsafe extern "C" fn(CUcontext) -> CUresult,
    cu_module_load_data: unsafe extern "C" fn(*mut CUmodule, *const c_void) -> CUresult,
    cu_module_get_function: unsafe extern "C" fn(*mut CUfunction, CUmodule, *const c_char) -> CUresult,
    cu_module_unload: unsafe extern "C" fn(CUmodule) -> CUresult,
    cu_mem_alloc: unsafe extern "C" fn(*mut CUdeviceptr, usize) -> CUresult,
    cu_mem_free: unsafe extern "C" fn(CUdeviceptr) -> CUresult,
    cu_memcpy_htod: unsafe extern "C" fn(CUdeviceptr, *const c_void, usize) -> CUresult,
    cu_memcpy_dtoh: unsafe extern "C" fn(*mut c_void, CUdeviceptr, usize) -> CUresult,
    cu_launch_kernel: unsafe extern "C" fn(
        CUfunction, c_uint, c_uint, c_uint, c_uint, c_uint, c_uint,
        c_uint, CUstream, *mut *mut c_void, *mut *mut c_void,
    ) -> CUresult,
    cu_ctx_synchronize: unsafe extern "C" fn() -> CUresult,
}

impl CudaApi {
    unsafe fn load() -> Result<Self, String> {
        #[cfg(target_os = "linux")]
        let names = &["libcuda.so.1", "libcuda.so"];
        #[cfg(target_os = "macos")]
        let names: &[&str] = &["libcuda.dylib"];
        #[cfg(target_os = "windows")]
        let names = &["nvcuda.dll"];

        let lib = names
            .iter()
            .find_map(|n| unsafe { libloading::Library::new(n).ok() })
            .ok_or_else(|| {
                format!(
                    "cuda loader: could not load {}",
                    names.join(" or ")
                )
            })?;

        macro_rules! sym {
            ($lib:expr, $name:expr) => {
                *$lib
                    .get::<*const ()>($name)
                    .map_err(|e| format!("cuda symbol {}: {}", std::str::from_utf8($name).unwrap_or("?"), e))?
            };
        }

        let api = CudaApi {
            cu_init: std::mem::transmute(sym!(lib, b"cuInit\0")),
            cu_device_get_count: std::mem::transmute(sym!(lib, b"cuDeviceGetCount\0")),
            cu_device_get: std::mem::transmute(sym!(lib, b"cuDeviceGet\0")),
            cu_device_get_name: std::mem::transmute(sym!(lib, b"cuDeviceGetName\0")),
            cu_device_total_mem: std::mem::transmute(sym!(lib, b"cuDeviceTotalMem_v2\0")),
            cu_device_get_attribute: std::mem::transmute(sym!(lib, b"cuDeviceGetAttribute\0")),
            cu_ctx_create: std::mem::transmute(sym!(lib, b"cuCtxCreate_v2\0")),
            cu_ctx_destroy: std::mem::transmute(sym!(lib, b"cuCtxDestroy_v2\0")),
            cu_module_load_data: std::mem::transmute(sym!(lib, b"cuModuleLoadData\0")),
            cu_module_get_function: std::mem::transmute(sym!(lib, b"cuModuleGetFunction\0")),
            cu_module_unload: std::mem::transmute(sym!(lib, b"cuModuleUnload\0")),
            cu_mem_alloc: std::mem::transmute(sym!(lib, b"cuMemAlloc_v2\0")),
            cu_mem_free: std::mem::transmute(sym!(lib, b"cuMemFree_v2\0")),
            cu_memcpy_htod: std::mem::transmute(sym!(lib, b"cuMemcpyHtoD_v2\0")),
            cu_memcpy_dtoh: std::mem::transmute(sym!(lib, b"cuMemcpyDtoH_v2\0")),
            cu_launch_kernel: std::mem::transmute(sym!(lib, b"cuLaunchKernel\0")),
            cu_ctx_synchronize: std::mem::transmute(sym!(lib, b"cuCtxSynchronize\0")),
            _lib: lib,
        };

        Ok(api)
    }
}

// --- CUDA Context ---

pub struct CudaContext {
    api: CudaApi,
    ctx: CUcontext,
    _device: CUdevice,
    device_index: u32,
    device_count: u32,
    device_name: String,
    compute_units: u32, // SM count
    memory_mb: u64,
}

// SAFETY: CudaContext holds a CUDA driver context which is thread-safe
// once created (single-context-per-thread model; we only use it from &self).
unsafe impl Send for CudaContext {}
unsafe impl Sync for CudaContext {}

impl CudaContext {
    pub fn new(device_index: u32) -> Result<Self, String> {
        unsafe { Self::init(device_index) }
    }

    unsafe fn init(device_index: u32) -> Result<Self, String> {
        let api = CudaApi::load()?;

        let rc = (api.cu_init)(0);
        if rc != CUDA_SUCCESS {
            return Err(format!("cuInit failed: error {}", rc));
        }

        let mut count: c_int = 0;
        let rc = (api.cu_device_get_count)(&mut count);
        if rc != CUDA_SUCCESS {
            return Err(format!("cuDeviceGetCount: error {}", rc));
        }
        if count == 0 {
            return Err("no CUDA devices".into());
        }
        let device_count = count as u32;
        if device_index >= device_count {
            return Err(format!(
                "device_index {} out of range (found {} device{})",
                device_index,
                device_count,
                if device_count == 1 { "" } else { "s" }
            ));
        }

        let mut device: CUdevice = 0;
        let rc = (api.cu_device_get)(&mut device, device_index as c_int);
        if rc != CUDA_SUCCESS {
            return Err(format!("cuDeviceGet: error {}", rc));
        }

        // Device name
        let mut name_buf = [0u8; 256];
        let rc = (api.cu_device_get_name)(
            name_buf.as_mut_ptr() as *mut c_char,
            name_buf.len() as c_int,
            device,
        );
        let device_name = if rc == CUDA_SUCCESS {
            CStr::from_ptr(name_buf.as_ptr() as *const c_char)
                .to_string_lossy()
                .into_owned()
        } else {
            format!("CudaDevice{}", device_index)
        };

        // Total memory
        let mut total_mem: usize = 0;
        let _ = (api.cu_device_total_mem)(&mut total_mem, device);
        let memory_mb = (total_mem / (1024 * 1024)) as u64;

        // SM count (attribute 16 = CU_DEVICE_ATTRIBUTE_MULTIPROCESSOR_COUNT)
        let mut sm_count: c_int = 0;
        let _ = (api.cu_device_get_attribute)(&mut sm_count, 16, device);
        let compute_units = sm_count.max(0) as u32;

        // Create context
        let mut ctx: CUcontext = ptr::null_mut();
        let rc = (api.cu_ctx_create)(&mut ctx, 0, device);
        if rc != CUDA_SUCCESS {
            return Err(format!("cuCtxCreate: error {}", rc));
        }

        Ok(CudaContext {
            api,
            ctx,
            _device: device,
            device_index,
            device_count,
            device_name,
            compute_units,
            memory_mb,
        })
    }

    pub fn device_name(&self) -> &str {
        &self.device_name
    }
    pub fn compute_units(&self) -> u32 {
        self.compute_units
    }
    pub fn memory_mb(&self) -> u64 {
        self.memory_mb
    }
    pub fn device_index(&self) -> u32 {
        self.device_index
    }
    pub fn device_count(&self) -> u32 {
        self.device_count
    }

    /// Run the add-3 kernel on `data` via real CUDA dispatch.
    /// Each byte → u32, kernel does (val+3)&0xFF, result → u8.
    pub fn execute_compute(&self, data: &[u8]) -> Result<Vec<u8>, String> {
        if data.is_empty() {
            return Ok(vec![]);
        }
        unsafe { self.run_kernel(data) }
    }

    unsafe fn run_kernel(&self, data: &[u8]) -> Result<Vec<u8>, String> {
        let n = data.len();
        let buf_bytes = n * 4; // u32 per element

        // Upload: each byte → u32
        let host_buf: Vec<u32> = data.iter().map(|&b| b as u32).collect();

        // Load PTX module
        let ptx = CString::new(build_add3_ptx()).map_err(|e| format!("ptx cstring: {e}"))?;
        let mut module: CUmodule = ptr::null_mut();
        let rc = (self.api.cu_module_load_data)(&mut module, ptx.as_ptr() as *const c_void);
        if rc != CUDA_SUCCESS {
            return Err(format!("cuModuleLoadData: error {}", rc));
        }

        let func_name = CString::new("add3").unwrap();
        let mut func: CUfunction = ptr::null_mut();
        let rc = (self.api.cu_module_get_function)(&mut func, module, func_name.as_ptr());
        if rc != CUDA_SUCCESS {
            (self.api.cu_module_unload)(module);
            return Err(format!("cuModuleGetFunction: error {}", rc));
        }

        // Allocate device memory
        let mut d_buf: CUdeviceptr = 0;
        let rc = (self.api.cu_mem_alloc)(&mut d_buf, buf_bytes);
        if rc != CUDA_SUCCESS {
            (self.api.cu_module_unload)(module);
            return Err(format!("cuMemAlloc: error {}", rc));
        }

        // Copy host → device
        let rc = (self.api.cu_memcpy_htod)(d_buf, host_buf.as_ptr() as *const c_void, buf_bytes);
        if rc != CUDA_SUCCESS {
            (self.api.cu_mem_free)(d_buf);
            (self.api.cu_module_unload)(module);
            return Err(format!("cuMemcpyHtoD: error {}", rc));
        }

        // Launch kernel
        let n_u32 = n as u32;
        let mut arg_data = d_buf;
        let mut arg_n = n_u32;
        let mut args: [*mut c_void; 2] = [
            &mut arg_data as *mut CUdeviceptr as *mut c_void,
            &mut arg_n as *mut u32 as *mut c_void,
        ];
        let block_size = 256u32;
        let grid_size = (n as u32 + block_size - 1) / block_size;

        let rc = (self.api.cu_launch_kernel)(
            func,
            grid_size, 1, 1,
            block_size, 1, 1,
            0,
            ptr::null_mut(), // default stream
            args.as_mut_ptr(),
            ptr::null_mut(),
        );
        if rc != CUDA_SUCCESS {
            (self.api.cu_mem_free)(d_buf);
            (self.api.cu_module_unload)(module);
            return Err(format!("cuLaunchKernel: error {}", rc));
        }

        let rc = (self.api.cu_ctx_synchronize)();
        if rc != CUDA_SUCCESS {
            (self.api.cu_mem_free)(d_buf);
            (self.api.cu_module_unload)(module);
            return Err(format!("cuCtxSynchronize: error {}", rc));
        }

        // Copy device → host
        let mut result_buf = vec![0u32; n];
        let rc = (self.api.cu_memcpy_dtoh)(
            result_buf.as_mut_ptr() as *mut c_void,
            d_buf,
            buf_bytes,
        );
        if rc != CUDA_SUCCESS {
            (self.api.cu_mem_free)(d_buf);
            (self.api.cu_module_unload)(module);
            return Err(format!("cuMemcpyDtoH: error {}", rc));
        }

        // Cleanup
        (self.api.cu_mem_free)(d_buf);
        (self.api.cu_module_unload)(module);

        Ok(result_buf.iter().map(|&v| (v & 0xFF) as u8).collect())
    }
}

impl Drop for CudaContext {
    fn drop(&mut self) {
        unsafe {
            (self.api.cu_ctx_synchronize)();
            (self.api.cu_ctx_destroy)(self.ctx);
        }
    }
}
