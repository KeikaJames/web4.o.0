use serde::{Deserialize, Serialize};

/// Minimal validation result from atom execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationResult {
    /// Active adapter lineage.
    pub active_adapter_id: String,
    pub active_generation: u64,

    /// Candidate adapter lineage (if shadow_eval).
    pub candidate_adapter_id: Option<String>,
    pub candidate_generation: Option<u64>,

    /// Lineage consistency check.
    pub lineage_valid: bool,

    /// Minimal comparison summary.
    pub output_match: bool,
    pub kv_count_match: bool,

    /// Overall acceptability.
    pub is_acceptable: bool,
}

impl ValidationResult {
    /// Create result for serve mode (no candidate).
    pub fn serve_only(adapter_id: String, generation: u64) -> Self {
        Self {
            active_adapter_id: adapter_id,
            active_generation: generation,
            candidate_adapter_id: None,
            candidate_generation: None,
            lineage_valid: true,
            output_match: true,
            kv_count_match: true,
            is_acceptable: true,
        }
    }

    /// Create result for shadow_eval mode.
    pub fn shadow_eval(
        active_id: String,
        active_gen: u64,
        candidate_id: String,
        candidate_gen: u64,
        lineage_valid: bool,
        output_match: bool,
        kv_count_match: bool,
    ) -> Self {
        let is_acceptable = lineage_valid && output_match && kv_count_match;
        Self {
            active_adapter_id: active_id,
            active_generation: active_gen,
            candidate_adapter_id: Some(candidate_id),
            candidate_generation: Some(candidate_gen),
            lineage_valid,
            output_match,
            kv_count_match,
            is_acceptable,
        }
    }
}
