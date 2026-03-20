//! Home Node / Ephemeral Node sovereignty execution boundary.
//!
//! Home Node: holds persistent state (KV, shards, memory boundary), makes
//! placement decisions, generates outbound execution requests, receives results.
//!
//! Ephemeral Node: stateless executor. Receives a blinded atom, runs it through
//! the backend, returns the result. Never retains user state.

use serde::{Deserialize, Serialize};

use crate::atom::{AtomKind, ComputeAtom, Region};
use crate::backend::Backend;
use crate::kernel::{self, AtomRequest, AtomResponse};
use crate::kv::KVChunk;
use crate::router::{NodeProfile, PlacementDecision};
use crate::shard::LoadedShard;

// ---------------------------------------------------------------------------
// Home Node
// ---------------------------------------------------------------------------

/// Persistent, user-sovereign node. Holds KV cache, hot shards, and the
/// placement decision authority. All blinding/unblinding happens here.
#[derive(Debug, Clone)]
pub struct HomeNode {
    pub node_id: String,
    pub sovereignty_zone: String,
    pub region: Region,
    /// KV chunks owned by this home node.
    pub kv_store: Vec<KVChunk>,
    /// Shards currently loaded locally.
    pub hot_shards: Vec<LoadedShard>,
}

impl HomeNode {
    pub fn new(node_id: &str, sovereignty_zone: &str, region: Region) -> Self {
        Self {
            node_id: node_id.into(),
            sovereignty_zone: sovereignty_zone.into(),
            region,
            kv_store: Vec::new(),
            hot_shards: Vec::new(),
        }
    }

    /// Prepare an execution request for outsourcing to an ephemeral node.
    /// The home node decides placement, blinds the atom (strips sovereignty
    /// metadata), and packages only what the ephemeral node needs.
    pub fn prepare_outsource(
        &self,
        atom: &ComputeAtom,
        input: Vec<u8>,
        candidates: &[NodeProfile],
    ) -> Result<(HomeExecutionRequest, BlindedAtom), String> {
        // Route using home node's KV context
        let kv_ctx = crate::router::KVContext {
            active_chunks: &self.kv_store,
        };
        let decision = crate::router::route_with_kv(atom, candidates, Some(&kv_ctx))
            .ok_or_else(|| "no suitable ephemeral node found".to_string())?;

        let target_node_id = decision.breakdown.node_id.clone();

        // Blind: strip sovereignty zone and home node identity from the atom
        let blinded = BlindedAtom {
            atom_id: atom.id.clone(),
            kind: atom.kind.clone(),
            model_id: atom.model_id.clone(),
            input,
            // Only include KV chunks that need migration to the target region
            kv_chunks: if decision.requires_kv_migration {
                self.kv_store.clone()
            } else {
                Vec::new()
            },
        };

        let request = HomeExecutionRequest {
            home_node_id: self.node_id.clone(),
            target_node_id,
            placement: decision,
            atom_region: atom.region.clone(),
            prib_mask: vec![],
        };

        Ok((request, blinded))
    }

    /// Receive an execution result back from an ephemeral node.
    /// Unblind: absorb KV state produced by the execution back into the
    /// home node's local store.
    pub fn receive_result(
        &mut self,
        request: &HomeExecutionRequest,
        result: EphemeralExecutionResult,
    ) -> HomeExecutionResponse {
        // Absorb any KV chunks produced by the ephemeral execution
        for chunk in &result.kv_produced {
            // Replace existing chunk with same id, or append
            if let Some(pos) = self.kv_store.iter().position(|c| c.chunk_id == chunk.chunk_id) {
                self.kv_store[pos] = chunk.clone();
            } else {
                self.kv_store.push(chunk.clone());
            }
        }

        HomeExecutionResponse {
            home_node_id: request.home_node_id.clone(),
            output: result.output,
            tokens_produced: result.tokens_produced,
            kv_absorbed: result.kv_produced.len(),
            ephemeral_node_id: result.ephemeral_node_id,
        }
    }

    /// PRIB path: blind the input, prepare outsource request with mask.
    /// The mask is stored in HomeExecutionRequest and never sent to the
    /// Ephemeral Node. BlindedAtom only contains the blinded payload.
    pub fn prepare_outsource_blinded(
        &self,
        atom: &ComputeAtom,
        input: Vec<u8>,
        candidates: &[NodeProfile],
    ) -> Result<(HomeExecutionRequest, BlindedAtom), String> {
        let kv_ctx = crate::router::KVContext {
            active_chunks: &self.kv_store,
        };
        let decision = crate::router::route_with_kv(atom, candidates, Some(&kv_ctx))
            .ok_or_else(|| "no suitable ephemeral node found".to_string())?;

        let target_node_id = decision.breakdown.node_id.clone();

        // Derive mask from atom_id + home_node_id — stays on home side only
        let mask_seed = format!("{}:{}", atom.id, self.node_id);
        let mask = crate::prib::derive_mask(&mask_seed, input.len());

        // Blind the input before it leaves the home node
        let blinded_input = crate::prib::blind(&input, &mask);

        let blinded = BlindedAtom {
            atom_id: atom.id.clone(),
            kind: atom.kind.clone(),
            model_id: atom.model_id.clone(),
            input: blinded_input, // ephemeral node only sees this
            kv_chunks: if decision.requires_kv_migration {
                self.kv_store.clone()
            } else {
                Vec::new()
            },
        };

        let request = HomeExecutionRequest {
            home_node_id: self.node_id.clone(),
            target_node_id,
            placement: decision,
            atom_region: atom.region.clone(),
            prib_mask: mask, // never leaves home node
        };

        Ok((request, blinded))
    }

    /// PRIB path: receive blinded result and unblind using the stored mask.
    /// Absorbs KV state as usual.
    pub fn receive_result_blinded(
        &mut self,
        request: &HomeExecutionRequest,
        result: EphemeralExecutionResult,
    ) -> HomeExecutionResponse {
        // Unblind the output using the mask from the original request
        let real_output = crate::prib::unblind(&result.output, &request.prib_mask);

        // Absorb KV chunks
        for chunk in &result.kv_produced {
            if let Some(pos) = self.kv_store.iter().position(|c| c.chunk_id == chunk.chunk_id) {
                self.kv_store[pos] = chunk.clone();
            } else {
                self.kv_store.push(chunk.clone());
            }
        }

        HomeExecutionResponse {
            home_node_id: request.home_node_id.clone(),
            output: real_output,
            tokens_produced: result.tokens_produced,
            kv_absorbed: result.kv_produced.len(),
            ephemeral_node_id: result.ephemeral_node_id,
        }
    }

    /// Execute locally using the home node's own backend, without outsourcing.
    pub fn execute_local(
        &mut self,
        backend: &dyn Backend,
        atom: &ComputeAtom,
        input: Vec<u8>,
        candidates: &[NodeProfile],
    ) -> Result<AtomResponse, String> {
        let request = AtomRequest {
            atom: atom.clone(),
            input,
            kv_state: self.kv_store.clone(),
            candidates: candidates.to_vec(),
        };
        let response = kernel::dispatch(backend, request)?;

        // Absorb KV state from local execution
        self.kv_store = response.exec_response.kv_state.clone();

        Ok(response)
    }
}

// ---------------------------------------------------------------------------
// Ephemeral Node
// ---------------------------------------------------------------------------

/// Stateless execution node. Receives a blinded atom, executes it, returns
/// the result. Does not retain any user state after execution.
#[derive(Debug, Clone)]
pub struct EphemeralNode {
    pub node_id: String,
    pub region: Region,
    pub supported_kinds: Vec<AtomKind>,
}

impl EphemeralNode {
    pub fn new(node_id: &str, region: Region, supported_kinds: Vec<AtomKind>) -> Self {
        Self {
            node_id: node_id.into(),
            region,
            supported_kinds,
        }
    }

    /// Execute a blinded atom. The ephemeral node has no knowledge of the
    /// home node's sovereignty zone or identity. It simply runs the compute
    /// and returns the result.
    pub fn execute(
        &self,
        backend: &dyn Backend,
        blinded: &BlindedAtom,
    ) -> Result<EphemeralExecutionResult, String> {
        if !self.supported_kinds.contains(&blinded.kind) {
            return Err(format!(
                "ephemeral node '{}' does not support {:?}",
                self.node_id, blinded.kind
            ));
        }

        let backend_request = crate::backend::BackendRequest {
            atom_id: blinded.atom_id.clone(),
            input: blinded.input.clone(),
            kv_state: blinded.kv_chunks.clone(),
        };

        let backend_response = match blinded.kind {
            AtomKind::Prefill => backend.execute_prefill(backend_request),
            AtomKind::Decode => backend.execute_decode(backend_request),
            _ => backend.execute_prefill(backend_request), // default path
        }?;

        Ok(EphemeralExecutionResult {
            ephemeral_node_id: self.node_id.clone(),
            atom_id: blinded.atom_id.clone(),
            output: backend_response.output,
            tokens_produced: backend_response.tokens_produced,
            kv_produced: backend_response.kv_state,
        })
    }
}

// ---------------------------------------------------------------------------
// Boundary objects
// ---------------------------------------------------------------------------

/// A compute atom stripped of sovereignty metadata. This is what crosses
/// the boundary from Home Node to Ephemeral Node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BlindedAtom {
    pub atom_id: String,
    pub kind: AtomKind,
    pub model_id: String,
    pub input: Vec<u8>,
    /// KV chunks needed for execution (migrated from home node if required).
    pub kv_chunks: Vec<KVChunk>,
}

/// Home node's record of an outsourced execution. Stays on the home side.
/// The `prib_mask` is the blind material — never sent to the Ephemeral Node.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HomeExecutionRequest {
    pub home_node_id: String,
    pub target_node_id: String,
    pub placement: PlacementDecision,
    pub atom_region: Region,
    /// PRIB mask held exclusively by the Home Node. Not included in BlindedAtom.
    #[serde(default)]
    pub prib_mask: Vec<u8>,
}

/// What the ephemeral node returns after execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EphemeralExecutionResult {
    pub ephemeral_node_id: String,
    pub atom_id: String,
    pub output: Vec<u8>,
    pub tokens_produced: u32,
    /// KV chunks produced during execution — will be absorbed by home node.
    pub kv_produced: Vec<KVChunk>,
}

/// Home node's final response after receiving and unblinding the result.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HomeExecutionResponse {
    pub home_node_id: String,
    pub output: Vec<u8>,
    pub tokens_produced: u32,
    pub kv_absorbed: usize,
    pub ephemeral_node_id: String,
}
