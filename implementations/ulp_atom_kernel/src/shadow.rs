//! Shadow evaluation: dual-path execution for adapter validation.

use serde::{Deserialize, Serialize};
use crate::exec::ExecResponse;

/// Result of comparing active vs shadow execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComparisonResult {
    pub active_response: ExecResponse,
    pub shadow_response: ExecResponse,
    pub output_match: bool,
    pub output_diff_bytes: usize,
    pub tokens_match: bool,
    pub kv_count_match: bool,
    pub lineage_valid: bool,
    pub is_acceptable: bool,
}

impl ComparisonResult {
    pub fn compare(active: ExecResponse, shadow: ExecResponse) -> Self {
        let output_match = active.output == shadow.output;
        let output_diff_bytes = if output_match {
            0
        } else {
            active.output.len().max(shadow.output.len())
        };
        let tokens_match = active.tokens_produced == shadow.tokens_produced;
        let kv_count_match = active.kv_state.len() == shadow.kv_state.len();

        // Lineage valid if shadow has higher generation
        let lineage_valid = match (active.adapter_generation, shadow.adapter_generation) {
            (Some(a), Some(s)) => s > a,
            _ => false,
        };
        let is_acceptable = lineage_valid && kv_count_match;

        ComparisonResult {
            active_response: active,
            shadow_response: shadow,
            output_match,
            output_diff_bytes,
            tokens_match,
            kv_count_match,
            lineage_valid,
            is_acceptable,
        }
    }

    pub fn is_acceptable(&self) -> bool {
        self.is_acceptable
    }
}
