//! Link cost model for unified transport decisions.

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum Direction {
    Upload,
    Download,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Link {
    pub bandwidth_mbps: f64,
    pub rtt_ms: f64,
    pub upload_multiplier: f64,
    pub download_multiplier: f64,
}

impl Link {
    pub fn datacenter() -> Self {
        Self {
            bandwidth_mbps: 10000.0,
            rtt_ms: 0.5,
            upload_multiplier: 1.0,
            download_multiplier: 1.0,
        }
    }

    pub fn p2p() -> Self {
        Self {
            bandwidth_mbps: 100.0,
            rtt_ms: 50.0,
            upload_multiplier: 0.3,
            download_multiplier: 1.0,
        }
    }

    pub fn transfer_cost(&self, bytes: usize, direction: Direction) -> f64 {
        let multiplier = match direction {
            Direction::Upload => self.upload_multiplier,
            Direction::Download => self.download_multiplier,
        };
        let effective_bw = self.bandwidth_mbps * multiplier;
        let transfer_time_ms = (bytes as f64 * 8.0) / (effective_bw * 1000.0);
        self.rtt_ms + transfer_time_ms
    }

    pub fn max_concurrent_streams(&self) -> usize {
        if self.bandwidth_mbps > 1000.0 { 8 } else { 2 }
    }
}

pub fn recompute_cost_kv(kv_bytes: usize, compute_flops: f64) -> f64 {
    let tokens = kv_bytes / 128;
    (tokens as f64 * 1e9) / compute_flops
}

pub fn recompute_cost_ffn(kv_bytes: usize, compute_flops: f64) -> f64 {
    recompute_cost_kv(kv_bytes, compute_flops) * 4.0
}

pub fn should_transfer(
    kv_bytes: usize,
    link: &Link,
    direction: Direction,
    compute_flops: f64,
    use_ffn_cost: bool,
) -> bool {
    let transfer = link.transfer_cost(kv_bytes, direction);
    let recompute = if use_ffn_cost {
        recompute_cost_ffn(kv_bytes, compute_flops)
    } else {
        recompute_cost_kv(kv_bytes, compute_flops)
    };
    transfer < recompute
}
