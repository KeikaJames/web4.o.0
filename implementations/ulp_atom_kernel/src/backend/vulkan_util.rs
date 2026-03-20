use ash::vk;
use std::ffi::CStr;

/// Encode one SPIR-V instruction word: (word_count << 16) | opcode
fn op(opcode: u32, word_count: u32) -> u32 {
    (word_count << 16) | opcode
}

/// Build SPIR-V for a compute shader that does: data[i] = (data[i] + 3) & 0xFF
/// In-place, one storage buffer, workgroup size 64.
pub fn build_add3_spirv() -> Vec<u32> {
    // ID assignments
    const VOID: u32 = 1;
    const FUNC_T: u32 = 2;
    const U32_T: u32 = 3;
    const C3: u32 = 4;
    const C0: u32 = 5;
    const UVEC3_T: u32 = 6;
    const PTR_IN_V3: u32 = 7;
    const GID_VAR: u32 = 8;
    const RT_ARR: u32 = 9;
    const BUF_ST: u32 = 10;
    const PTR_SB_ST: u32 = 11;
    const BUF_VAR: u32 = 12;
    const PTR_SB_U: u32 = 13;
    const PTR_IN_U: u32 = 14;
    const MAIN: u32 = 15;
    const LABEL: u32 = 16;
    const T17: u32 = 17;
    const T18: u32 = 18;
    const T19: u32 = 19;
    const T20: u32 = 20;
    const T21: u32 = 21;
    const C255: u32 = 22;
    const T23: u32 = 23;
    const BOUND: u32 = 24;

    let mut w: Vec<u32> = Vec::with_capacity(128);

    // --- Header ---
    w.push(0x07230203);
    w.push(0x00010500); // SPIR-V 1.5
    w.push(0);
    w.push(BOUND);
    w.push(0);

    // OpCapability Shader
    w.extend_from_slice(&[op(17, 2), 1]);

    // OpMemoryModel Logical GLSL450
    w.extend_from_slice(&[op(14, 3), 0, 1]);

    // OpEntryPoint GLCompute %MAIN "main" %GID_VAR
    let name = u32::from_le_bytes([b'm', b'a', b'i', b'n']);
    w.extend_from_slice(&[op(15, 6), 5, MAIN, name, 0, GID_VAR]);

    // OpExecutionMode %MAIN LocalSize 64 1 1
    w.extend_from_slice(&[op(16, 6), MAIN, 17, 64, 1, 1]);

    // --- Decorations ---
    w.extend_from_slice(&[op(71, 4), GID_VAR, 11, 28]); // BuiltIn GlobalInvocationId
    w.extend_from_slice(&[op(71, 4), BUF_VAR, 34, 0]);  // DescriptorSet 0
    w.extend_from_slice(&[op(71, 4), BUF_VAR, 33, 0]);  // Binding 0
    w.extend_from_slice(&[op(71, 4), RT_ARR, 6, 4]);     // ArrayStride 4
    w.extend_from_slice(&[op(71, 3), BUF_ST, 2]);        // Block
    w.extend_from_slice(&[op(72, 5), BUF_ST, 0, 35, 0]); // MemberDecorate Offset 0

    // --- Types ---
    w.extend_from_slice(&[op(19, 2), VOID]);
    w.extend_from_slice(&[op(33, 3), FUNC_T, VOID]);
    w.extend_from_slice(&[op(21, 4), U32_T, 32, 0]);
    w.extend_from_slice(&[op(43, 4), U32_T, C3, 3]);
    w.extend_from_slice(&[op(43, 4), U32_T, C0, 0]);
    w.extend_from_slice(&[op(43, 4), U32_T, C255, 255]);
    w.extend_from_slice(&[op(23, 4), UVEC3_T, U32_T, 3]);
    w.extend_from_slice(&[op(32, 4), PTR_IN_V3, 1, UVEC3_T]);
    w.extend_from_slice(&[op(59, 4), PTR_IN_V3, GID_VAR, 1]);
    w.extend_from_slice(&[op(29, 3), RT_ARR, U32_T]);
    w.extend_from_slice(&[op(30, 3), BUF_ST, RT_ARR]);
    w.extend_from_slice(&[op(32, 4), PTR_SB_ST, 12, BUF_ST]);
    w.extend_from_slice(&[op(59, 4), PTR_SB_ST, BUF_VAR, 12]);
    w.extend_from_slice(&[op(32, 4), PTR_SB_U, 12, U32_T]);
    w.extend_from_slice(&[op(32, 4), PTR_IN_U, 1, U32_T]);

    // --- Function ---
    w.extend_from_slice(&[op(54, 5), VOID, MAIN, 0, FUNC_T]);
    w.extend_from_slice(&[op(248, 2), LABEL]);
    // idx = GlobalInvocationID.x
    w.extend_from_slice(&[op(65, 5), PTR_IN_U, T17, GID_VAR, C0]);
    w.extend_from_slice(&[op(61, 4), U32_T, T18, T17]);
    // ptr = &buf.data[idx]
    w.extend_from_slice(&[op(65, 6), PTR_SB_U, T19, BUF_VAR, C0, T18]);
    // val = *ptr
    w.extend_from_slice(&[op(61, 4), U32_T, T20, T19]);
    // result = (val + 3) & 0xFF
    w.extend_from_slice(&[op(128, 5), U32_T, T21, T20, C3]);
    w.extend_from_slice(&[op(199, 5), U32_T, T23, T21, C255]); // OpBitwiseAnd
    // *ptr = result
    w.extend_from_slice(&[op(62, 3), T19, T23]);
    w.push(op(253, 1)); // OpReturn
    w.push(op(56, 1));  // OpFunctionEnd

    w
}

// --- Vulkan context ---

pub struct VulkanContext {
    _entry: ash::Entry,
    instance: ash::Instance,
    device: ash::Device,
    physical_device: vk::PhysicalDevice,
    queue: vk::Queue,
    queue_family: u32,
    device_index: u32,
    device_count: u32,
    device_name: String,
    compute_units: u32,
    memory_gb: f64,
}

impl VulkanContext {
    pub fn new(device_index: u32) -> Result<Self, String> {
        unsafe { Self::init(device_index) }
    }

    unsafe fn init(device_index: u32) -> Result<Self, String> {
        let entry = ash::Entry::load().map_err(|e| format!("vulkan loader: {e}"))?;

        let app_info = vk::ApplicationInfo::default()
            .api_version(vk::make_api_version(0, 1, 2, 0));
        let create_info = vk::InstanceCreateInfo::default()
            .application_info(&app_info);
        let instance = entry
            .create_instance(&create_info, None)
            .map_err(|e| format!("vkCreateInstance: {e}"))?;

        let phys_devices = instance
            .enumerate_physical_devices()
            .map_err(|e| format!("enumerate devices: {e}"))?;
        if phys_devices.is_empty() {
            instance.destroy_instance(None);
            return Err("no Vulkan physical devices".into());
        }
        let device_count = phys_devices.len() as u32;
        if (device_index as usize) >= phys_devices.len() {
            instance.destroy_instance(None);
            return Err(format!(
                "device_index {} out of range (found {} device{})",
                device_index, device_count, if device_count == 1 { "" } else { "s" }
            ));
        }
        let physical_device = phys_devices[device_index as usize];

        let props = instance.get_physical_device_properties(physical_device);
        let device_name = CStr::from_ptr(props.device_name.as_ptr())
            .to_string_lossy()
            .into_owned();

        let mem_props = instance.get_physical_device_memory_properties(physical_device);
        let memory_gb: f64 = mem_props.memory_heaps[..mem_props.memory_heap_count as usize]
            .iter()
            .filter(|h| h.flags.contains(vk::MemoryHeapFlags::DEVICE_LOCAL))
            .map(|h| h.size as f64 / (1024.0 * 1024.0 * 1024.0))
            .sum::<f64>()
            .max(0.1);

        // Find compute queue family
        let queue_families = instance
            .get_physical_device_queue_family_properties(physical_device);
        let queue_family = queue_families
            .iter()
            .enumerate()
            .find(|(_, qf)| qf.queue_flags.contains(vk::QueueFlags::COMPUTE))
            .map(|(i, _)| i as u32)
            .ok_or_else(|| {
                instance.destroy_instance(None);
                "no compute queue family".to_string()
            })?;

        let queue_priority = [1.0f32];
        let queue_ci = vk::DeviceQueueCreateInfo::default()
            .queue_family_index(queue_family)
            .queue_priorities(&queue_priority);
        let device_ci = vk::DeviceCreateInfo::default()
            .queue_create_infos(std::slice::from_ref(&queue_ci));
        let device = instance
            .create_device(physical_device, &device_ci, None)
            .map_err(|e| {
                instance.destroy_instance(None);
                format!("vkCreateDevice: {e}")
            })?;

        let queue = device.get_device_queue(queue_family, 0);

        Ok(VulkanContext {
            _entry: entry,
            instance,
            device,
            physical_device,
            queue,
            queue_family,
            device_index,
            device_count,
            device_name,
            compute_units: props.limits.max_compute_work_group_invocations,
            memory_gb,
        })
    }

    pub fn device_name(&self) -> &str { &self.device_name }
    pub fn compute_units(&self) -> u32 { self.compute_units }
    pub fn memory_gb(&self) -> f64 { self.memory_gb }
    pub fn device_index(&self) -> u32 { self.device_index }
    pub fn device_count(&self) -> u32 { self.device_count }
    /// Run the add-3 compute shader on `data` via real Vulkan dispatch.
    /// Each byte is processed as a u32, result masked to u8.
    pub fn execute_compute(&self, data: &[u8]) -> Result<Vec<u8>, String> {
        if data.is_empty() {
            return Ok(vec![]);
        }
        unsafe { self.run_shader(data) }
    }

    unsafe fn run_shader(&self, data: &[u8]) -> Result<Vec<u8>, String> {
        let d = &self.device;
        let n = data.len();
        let buf_size = (n * 4) as vk::DeviceSize; // u32 per element

        // --- Create buffer ---
        let buf_ci = vk::BufferCreateInfo::default()
            .size(buf_size)
            .usage(vk::BufferUsageFlags::STORAGE_BUFFER)
            .sharing_mode(vk::SharingMode::EXCLUSIVE);
        let buffer = d.create_buffer(&buf_ci, None)
            .map_err(|e| format!("create buffer: {e}"))?;

        let mem_reqs = d.get_buffer_memory_requirements(buffer);
        let mem_props = self.instance
            .get_physical_device_memory_properties(self.physical_device);
        let mem_type = find_memory_type(
            &mem_props, mem_reqs.memory_type_bits,
            vk::MemoryPropertyFlags::HOST_VISIBLE | vk::MemoryPropertyFlags::HOST_COHERENT,
        ).ok_or("no suitable memory type")?;

        let alloc_info = vk::MemoryAllocateInfo::default()
            .allocation_size(mem_reqs.size)
            .memory_type_index(mem_type);
        let memory = d.allocate_memory(&alloc_info, None)
            .map_err(|e| format!("alloc: {e}"))?;
        d.bind_buffer_memory(buffer, memory, 0)
            .map_err(|e| format!("bind: {e}"))?;

        // Upload: each byte → u32
        let ptr = d.map_memory(memory, 0, buf_size, vk::MemoryMapFlags::empty())
            .map_err(|e| format!("map: {e}"))?;
        let slice = std::slice::from_raw_parts_mut(ptr as *mut u32, n);
        for (i, &b) in data.iter().enumerate() {
            slice[i] = b as u32;
        }
        d.unmap_memory(memory);

        // --- Shader module ---
        let spirv = build_add3_spirv();
        let shader_ci = vk::ShaderModuleCreateInfo::default().code(&spirv);
        let shader = d.create_shader_module(&shader_ci, None)
            .map_err(|e| format!("shader: {e}"))?;

        // --- Descriptor set layout ---
        let binding = vk::DescriptorSetLayoutBinding::default()
            .binding(0)
            .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
            .descriptor_count(1)
            .stage_flags(vk::ShaderStageFlags::COMPUTE);
        let dsl_ci = vk::DescriptorSetLayoutCreateInfo::default()
            .bindings(std::slice::from_ref(&binding));
        let ds_layout = d.create_descriptor_set_layout(&dsl_ci, None)
            .map_err(|e| format!("ds layout: {e}"))?;

        // --- Pipeline layout ---
        let pl_ci = vk::PipelineLayoutCreateInfo::default()
            .set_layouts(std::slice::from_ref(&ds_layout));
        let pipeline_layout = d.create_pipeline_layout(&pl_ci, None)
            .map_err(|e| format!("pipeline layout: {e}"))?;

        // --- Compute pipeline ---
        let entry_name = c"main";
        let stage = vk::PipelineShaderStageCreateInfo::default()
            .stage(vk::ShaderStageFlags::COMPUTE)
            .module(shader)
            .name(entry_name);
        let pipe_ci = vk::ComputePipelineCreateInfo::default()
            .stage(stage)
            .layout(pipeline_layout);
        let pipeline = d.create_compute_pipelines(
            vk::PipelineCache::null(), std::slice::from_ref(&pipe_ci), None,
        ).map_err(|e| format!("pipeline: {e:?}"))?.into_iter().next().unwrap();

        // --- Descriptor pool + set ---
        let pool_size = vk::DescriptorPoolSize::default()
            .ty(vk::DescriptorType::STORAGE_BUFFER)
            .descriptor_count(1);
        let pool_ci = vk::DescriptorPoolCreateInfo::default()
            .max_sets(1)
            .pool_sizes(std::slice::from_ref(&pool_size));
        let pool = d.create_descriptor_pool(&pool_ci, None)
            .map_err(|e| format!("desc pool: {e}"))?;

        let alloc_ds = vk::DescriptorSetAllocateInfo::default()
            .descriptor_pool(pool)
            .set_layouts(std::slice::from_ref(&ds_layout));
        let desc_set = d.allocate_descriptor_sets(&alloc_ds)
            .map_err(|e| format!("alloc ds: {e}"))?[0];

        let buf_info = vk::DescriptorBufferInfo::default()
            .buffer(buffer)
            .offset(0)
            .range(buf_size);
        let write = vk::WriteDescriptorSet::default()
            .dst_set(desc_set)
            .dst_binding(0)
            .descriptor_type(vk::DescriptorType::STORAGE_BUFFER)
            .buffer_info(std::slice::from_ref(&buf_info));
        d.update_descriptor_sets(std::slice::from_ref(&write), &[]);

        // --- Command buffer ---
        let cmd_pool_ci = vk::CommandPoolCreateInfo::default()
            .queue_family_index(self.queue_family);
        let cmd_pool = d.create_command_pool(&cmd_pool_ci, None)
            .map_err(|e| format!("cmd pool: {e}"))?;

        let cmd_alloc = vk::CommandBufferAllocateInfo::default()
            .command_pool(cmd_pool)
            .level(vk::CommandBufferLevel::PRIMARY)
            .command_buffer_count(1);
        let cmd = d.allocate_command_buffers(&cmd_alloc)
            .map_err(|e| format!("cmd buf: {e}"))?[0];

        let begin = vk::CommandBufferBeginInfo::default()
            .flags(vk::CommandBufferUsageFlags::ONE_TIME_SUBMIT);
        d.begin_command_buffer(cmd, &begin)
            .map_err(|e| format!("begin cmd: {e}"))?;
        d.cmd_bind_pipeline(cmd, vk::PipelineBindPoint::COMPUTE, pipeline);
        d.cmd_bind_descriptor_sets(
            cmd, vk::PipelineBindPoint::COMPUTE, pipeline_layout,
            0, std::slice::from_ref(&desc_set), &[],
        );
        let groups = ((n as u32) + 63) / 64;
        d.cmd_dispatch(cmd, groups, 1, 1);
        d.end_command_buffer(cmd)
            .map_err(|e| format!("end cmd: {e}"))?;

        // --- Submit + wait ---
        let submit = vk::SubmitInfo::default()
            .command_buffers(std::slice::from_ref(&cmd));
        let fence_ci = vk::FenceCreateInfo::default();
        let fence = d.create_fence(&fence_ci, None)
            .map_err(|e| format!("fence: {e}"))?;
        d.queue_submit(self.queue, std::slice::from_ref(&submit), fence)
            .map_err(|e| format!("submit: {e}"))?;
        d.wait_for_fences(std::slice::from_ref(&fence), true, u64::MAX)
            .map_err(|e| format!("wait: {e}"))?;

        // --- Read back ---
        let ptr = d.map_memory(memory, 0, buf_size, vk::MemoryMapFlags::empty())
            .map_err(|e| format!("map read: {e}"))?;
        let out_slice = std::slice::from_raw_parts(ptr as *const u32, n);
        let result: Vec<u8> = out_slice.iter().map(|&v| (v & 0xFF) as u8).collect();
        d.unmap_memory(memory);

        // --- Cleanup ---
        d.destroy_fence(fence, None);
        d.destroy_command_pool(cmd_pool, None);
        d.destroy_descriptor_pool(pool, None);
        d.destroy_pipeline(pipeline, None);
        d.destroy_pipeline_layout(pipeline_layout, None);
        d.destroy_descriptor_set_layout(ds_layout, None);
        d.destroy_shader_module(shader, None);
        d.destroy_buffer(buffer, None);
        d.free_memory(memory, None);

        Ok(result)
    }
}

impl Drop for VulkanContext {
    fn drop(&mut self) {
        unsafe {
            self.device.device_wait_idle().ok();
            self.device.destroy_device(None);
            self.instance.destroy_instance(None);
        }
    }
}

fn find_memory_type(
    props: &vk::PhysicalDeviceMemoryProperties,
    type_bits: u32,
    flags: vk::MemoryPropertyFlags,
) -> Option<u32> {
    for i in 0..props.memory_type_count {
        if (type_bits & (1 << i)) != 0
            && props.memory_types[i as usize].property_flags.contains(flags)
        {
            return Some(i);
        }
    }
    None
}
