use serde::{Deserialize, Serialize};

/// Adapter execution mode.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AdapterMode {
    Serve,
    Validation,
    ShadowEval,
}

/// Reference to a specific adapter generation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterRef {
    pub adapter_id: String,
    pub generation: u64,
    pub mode: AdapterMode,
}

/// Adapter context for atom execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AdapterContext {
    pub active_adapter: AdapterRef,
    #[serde(default)]
    pub candidate_adapter: Option<AdapterRef>,
}

impl Default for AdapterContext {
    fn default() -> Self {
        Self {
            active_adapter: AdapterRef {
                adapter_id: "default".to_string(),
                generation: 1,
                mode: AdapterMode::Serve,
            },
            candidate_adapter: None,
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
}
