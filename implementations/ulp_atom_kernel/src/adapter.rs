use serde::{Deserialize, Serialize};

/// Adapter execution mode.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AdapterMode {
    Serve,
    Validation,
    ShadowEval,
}

/// Adapter specialization role.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Default)]
#[serde(rename_all = "snake_case")]
pub enum AdapterSpecialization {
    #[default]
    Stable,
    Shared,
    Candidate,
}

/// Reference to a specific adapter generation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterRef {
    pub adapter_id: String,
    pub generation: u64,
    pub mode: AdapterMode,
    #[serde(default)]
    pub specialization: AdapterSpecialization,
}

/// Adapter selection combining specialization layers.
/// Represents the current serve-time adapter composition.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterSelection {
    /// Long-term validated preferences (fallback base)
    pub stable: AdapterRef,
    /// Cross-task shared parameters (optional augmentation)
    #[serde(default)]
    pub shared: Option<AdapterRef>,
    /// Experimental candidate (isolated, not yet promoted)
    #[serde(default)]
    pub candidate: Option<AdapterRef>,
}

/// Adapter context for atom execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterContext {
    pub active_adapter: AdapterRef,
    #[serde(default)]
    pub candidate_adapter: Option<AdapterRef>,
    #[serde(default)]
    pub shared_adapter: Option<AdapterRef>,
    #[serde(default)]
    pub stable_adapter: Option<AdapterRef>,
}

impl Default for AdapterContext {
    fn default() -> Self {
        Self {
            active_adapter: AdapterRef {
                adapter_id: "default".to_string(),
                generation: 1,
                mode: AdapterMode::Serve,
                specialization: AdapterSpecialization::Stable,
            },
            candidate_adapter: None,
            shared_adapter: None,
            stable_adapter: None,
        }
    }
}

impl AdapterContext {
    /// Get the adapter to use for execution based on mode.
    pub fn resolve_adapter(&self) -> &AdapterRef {
        if let Some(candidate) = &self.candidate_adapter {
            match candidate.mode {
                AdapterMode::ShadowEval | AdapterMode::Validation => candidate,
                AdapterMode::Serve => &self.active_adapter,
            }
        } else {
            &self.active_adapter
        }
    }

    /// Get specialization-aware adapter selection.
    pub fn get_selection(&self) -> AdapterSelection {
        AdapterSelection {
            stable: self.stable_adapter.clone().unwrap_or_else(|| self.active_adapter.clone()),
            shared: self.shared_adapter.clone(),
            candidate: self.candidate_adapter.clone(),
        }
    }

    /// Check if specialization chain is valid.
    /// Candidate must not serve directly; stable must be present for serve.
    pub fn validate_specialization_chain(&self) -> Result<(), String> {
        // Serve path: active must be stable or shared (not candidate)
        if self.active_adapter.specialization == AdapterSpecialization::Candidate {
            return Err("candidate cannot serve directly".to_string());
        }

        // If candidate exists, it must be candidate specialization
        if let Some(ref candidate) = self.candidate_adapter {
            if candidate.specialization != AdapterSpecialization::Candidate {
                return Err("candidate adapter must have Candidate specialization".to_string());
            }
        }

        // If shared exists, it must be shared specialization
        if let Some(ref shared) = self.shared_adapter {
            if shared.specialization != AdapterSpecialization::Shared {
                return Err("shared adapter must have Shared specialization".to_string());
            }
        }

        Ok(())
    }
}
