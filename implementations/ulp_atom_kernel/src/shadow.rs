//! Shadow evaluation: dual-path execution for adapter validation.

use serde::{Deserialize, Serialize};
use crate::exec::ExecResponse;
use crate::adapter::AdapterSpecialization;

/// Comparison status for shadow evaluation.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ComparisonStatus {
    /// Active-only execution (no candidate to compare).
    ActiveOnly,
    /// Candidate shadow observed and compared.
    CandidateObserved,
    /// Lineage mismatch between active and candidate.
    LineageMismatch,
    /// Specialization mismatch in adapter chain.
    SpecializationMismatch,
    /// Comparison could not be performed.
    Unavailable,
}

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
    pub specialization_valid: bool,
    pub is_acceptable: bool,
    pub status: ComparisonStatus,
    /// Active adapter identity summary.
    pub active_summary: AdapterComparisonSummary,
    /// Candidate adapter identity summary (if present).
    pub candidate_summary: Option<AdapterComparisonSummary>,
    /// Promote recommendation based on comparison.
    pub promote_recommendation: PromoteRecommendation,
}

/// Adapter identity summary for comparison.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterComparisonSummary {
    pub adapter_id: String,
    pub generation: u64,
    pub specialization: AdapterSpecialization,
}

/// Promote recommendation from shadow comparison.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PromoteRecommendation {
    /// Candidate can be promoted.
    Approve,
    /// Candidate should not be promoted.
    Reject,
    /// Not enough information to decide.
    Undecided,
    /// Comparison failed, cannot recommend.
    Failed,
}

impl ComparisonResult {
    pub fn compare(
        active: ExecResponse,
        shadow: ExecResponse,
        active_spec: Option<AdapterSpecialization>,
        candidate_spec: Option<AdapterSpecialization>,
    ) -> Self {
        let output_match = active.output == shadow.output;
        let output_diff_bytes = if output_match {
            0
        } else {
            active.output.len().max(shadow.output.len())
        };
        let tokens_match = active.tokens_produced == shadow.tokens_produced;
        let kv_count_match = active.kv_state.len() == shadow.kv_state.len();

        // Build adapter summaries
        let active_summary = AdapterComparisonSummary {
            adapter_id: active.adapter_id.clone().unwrap_or_default(),
            generation: active.adapter_generation.unwrap_or(0),
            specialization: active_spec.clone().unwrap_or(AdapterSpecialization::Stable),
        };

        let candidate_summary = shadow.adapter_id.as_ref().map(|id| {
            AdapterComparisonSummary {
                adapter_id: id.clone(),
                generation: shadow.adapter_generation.unwrap_or(0),
                specialization: candidate_spec.clone().unwrap_or(AdapterSpecialization::Candidate),
            }
        });

        // Lineage valid if shadow has higher generation
        let lineage_valid = match (active.adapter_generation, shadow.adapter_generation) {
            (Some(a), Some(s)) => s > a,
            _ => false,
        };

        // Specialization valid if active is stable/shared and candidate is candidate
        let specialization_valid = match (&active_spec, &candidate_spec) {
            (Some(a), Some(c)) => {
                (*a == AdapterSpecialization::Stable || *a == AdapterSpecialization::Shared)
                && *c == AdapterSpecialization::Candidate
            }
            (Some(a), None) => *a == AdapterSpecialization::Stable || *a == AdapterSpecialization::Shared,
            _ => false,
        };

        // Determine status
        let status = if !lineage_valid {
            ComparisonStatus::LineageMismatch
        } else if !specialization_valid {
            ComparisonStatus::SpecializationMismatch
        } else if candidate_summary.is_some() {
            ComparisonStatus::CandidateObserved
        } else {
            ComparisonStatus::ActiveOnly
        };

        // Determine recommendation
        let promote_recommendation = if !lineage_valid || !specialization_valid {
            PromoteRecommendation::Reject
        } else if lineage_valid && output_match && kv_count_match {
            PromoteRecommendation::Approve
        } else if lineage_valid {
            PromoteRecommendation::Undecided
        } else {
            PromoteRecommendation::Failed
        };

        let is_acceptable = lineage_valid && specialization_valid && kv_count_match;

        ComparisonResult {
            active_response: active,
            shadow_response: shadow,
            output_match,
            output_diff_bytes,
            tokens_match,
            kv_count_match,
            lineage_valid,
            specialization_valid,
            is_acceptable,
            status,
            active_summary,
            candidate_summary,
            promote_recommendation,
        }
    }

    pub fn is_acceptable(&self) -> bool {
        self.is_acceptable
    }

    /// Check if this comparison can be used for promote decision.
    pub fn can_promote(&self) -> bool {
        self.promote_recommendation == PromoteRecommendation::Approve
            && self.lineage_valid
            && self.specialization_valid
    }
}
