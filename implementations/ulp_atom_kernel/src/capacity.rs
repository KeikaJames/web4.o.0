use serde::{Deserialize, Serialize};

/// Runtime capacity state of a remote node
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeCapacity {
    #[serde(default)]
    pub available_vram_gb: f64,
    #[serde(default)]
    pub current_load: f64,
    #[serde(default)]
    pub active_kv_chunks: usize,
}

impl Default for NodeCapacity {
    fn default() -> Self {
        Self {
            available_vram_gb: 16.0,
            current_load: 0.0,
            active_kv_chunks: 0,
        }
    }
}

/// Score capacity state for routing
pub fn score_capacity(capacity: &NodeCapacity, is_prefill: bool, is_decode: bool) -> (f64, f64, f64) {
    let vram_score = if capacity.available_vram_gb > 0.0 {
        (capacity.available_vram_gb / 32.0).min(1.0)
    } else {
        0.0
    };

    let load_score = (1.0 - capacity.current_load).max(0.0);

    let kv_capacity_score = if capacity.active_kv_chunks < 100 {
        1.0 - (capacity.active_kv_chunks as f64 / 100.0)
    } else {
        0.0
    };

    let capacity_score = if is_prefill {
        vram_score * 0.6 + load_score * 0.3 + kv_capacity_score * 0.1
    } else if is_decode {
        load_score * 0.5 + kv_capacity_score * 0.4 + vram_score * 0.1
    } else {
        vram_score * 0.4 + load_score * 0.4 + kv_capacity_score * 0.2
    };

    (capacity_score, vram_score, load_score)
}
