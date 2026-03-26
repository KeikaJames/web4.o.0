use serde::{Deserialize, Serialize};
use crate::adapter::AdapterSpecialization;

/// Validation status for comprehensive tracking.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ValidationStatus {
    /// Serve path validation (no candidate).
    ServeValid,
    /// Shadow validation passed.
    ShadowValid,
    /// Lineage check failed.
    LineageInvalid,
    /// Specialization check failed.
    SpecializationInvalid,
    /// Output mismatch detected.
    OutputMismatch,
    /// KV state mismatch.
    KvMismatch,
    /// Validation undecided.
    Undecided,
}

/// Minimal validation result from atom execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationResult {
    /// Active adapter lineage.
    pub active_adapter_id: String,
    pub active_generation: u64,
    pub active_specialization: AdapterSpecialization,

    /// Candidate adapter lineage (if shadow_eval).
    pub candidate_adapter_id: Option<String>,
    pub candidate_generation: Option<u64>,
    pub candidate_specialization: Option<AdapterSpecialization>,

    /// Lineage consistency check.
    pub lineage_valid: bool,
    pub specialization_valid: bool,

    /// Minimal comparison summary.
    pub output_match: bool,
    pub kv_count_match: bool,

    /// Overall acceptability.
    pub is_acceptable: bool,

    /// Validation status.
    pub status: ValidationStatus,

    /// Promote recommendation.
    pub promote_recommendation: PromoteRecommendation,
}

/// Promote recommendation from validation.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum PromoteRecommendation {
    /// Candidate can be promoted.
    Approve,
    /// Candidate should not be promoted.
    Reject,
    /// Not enough information to decide.
    Undecided,
    /// Validation failed, cannot recommend.
    Failed,
}

impl ValidationResult {
    /// Create result for serve mode (no candidate).
    pub fn serve_only(adapter_id: String, generation: u64) -> Self {
        Self {
            active_adapter_id: adapter_id.clone(),
            active_generation: generation,
            active_specialization: AdapterSpecialization::Stable,
            candidate_adapter_id: None,
            candidate_generation: None,
            candidate_specialization: None,
            lineage_valid: true,
            specialization_valid: true,
            output_match: true,
            kv_count_match: true,
            is_acceptable: true,
            status: ValidationStatus::ServeValid,
            promote_recommendation: PromoteRecommendation::Undecided,
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
        let status = if !lineage_valid {
            ValidationStatus::LineageInvalid
        } else if !output_match {
            ValidationStatus::OutputMismatch
        } else if !kv_count_match {
            ValidationStatus::KvMismatch
        } else {
            ValidationStatus::ShadowValid
        };
        let promote_recommendation = if is_acceptable {
            PromoteRecommendation::Approve
        } else if !lineage_valid {
            PromoteRecommendation::Reject
        } else {
            PromoteRecommendation::Undecided
        };

        Self {
            active_adapter_id: active_id,
            active_generation: active_gen,
            active_specialization: AdapterSpecialization::Stable,
            candidate_adapter_id: Some(candidate_id),
            candidate_generation: Some(candidate_gen),
            candidate_specialization: Some(AdapterSpecialization::Candidate),
            lineage_valid,
            specialization_valid: true,
            output_match,
            kv_count_match,
            is_acceptable,
            status,
            promote_recommendation,
        }
    }

    /// Create comprehensive validation result with specialization.
    pub fn with_specialization(
        active_id: String,
        active_gen: u64,
        active_spec: AdapterSpecialization,
        candidate_id: Option<String>,
        candidate_gen: Option<u64>,
        candidate_spec: Option<AdapterSpecialization>,
        lineage_valid: bool,
        output_match: bool,
        kv_count_match: bool,
    ) -> Self {
        let specialization_valid = match &candidate_spec {
            Some(spec) => *spec == AdapterSpecialization::Candidate,
            None => true,
        };

        let is_acceptable = lineage_valid
            && specialization_valid
            && output_match
            && kv_count_match;

        let status = if !lineage_valid {
            ValidationStatus::LineageInvalid
        } else if !specialization_valid {
            ValidationStatus::SpecializationInvalid
        } else if !output_match {
            ValidationStatus::OutputMismatch
        } else if !kv_count_match {
            ValidationStatus::KvMismatch
        } else if candidate_id.is_some() {
            ValidationStatus::ShadowValid
        } else {
            ValidationStatus::ServeValid
        };

        let promote_recommendation = if is_acceptable {
            PromoteRecommendation::Approve
        } else if !lineage_valid || !specialization_valid {
            PromoteRecommendation::Reject
        } else {
            PromoteRecommendation::Undecided
        };

        Self {
            active_adapter_id: active_id,
            active_generation: active_gen,
            active_specialization: active_spec,
            candidate_adapter_id: candidate_id,
            candidate_generation: candidate_gen,
            candidate_specialization: candidate_spec,
            lineage_valid,
            specialization_valid,
            output_match,
            kv_count_match,
            is_acceptable,
            status,
            promote_recommendation,
        }
    }

    /// Check if validation permits promotion.
    pub fn can_promote(&self) -> bool {
        self.promote_recommendation == PromoteRecommendation::Approve
            && self.lineage_valid
            && self.specialization_valid
    }
}
