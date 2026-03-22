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
use crate::client::RemoteClient;
use crate::kernel::{self, AtomRequest, AtomResponse};
use crate::kv::KVChunk;
use crate::router::{NodeProfile, PlacementDecision};
use crate::runtime::{claim_slot_http, DiscoveryPool, Nonce};
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
        self.finish_result(&request.home_node_id, result)
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
        let real_output = crate::prib::unblind(&result.output, &request.prib_mask);
        self.finish_result_with_output(&request.home_node_id, real_output, result)
    }

    /// Two-stage outsourced execution: Prefill → Decode through the sovereignty
    /// boundary. HomeNode orchestrates both stages. EphemeralNode is stateless.
    ///
    /// Flow:
    ///   1. Blind prefill input → BlindedAtom
    ///   2. Ephemeral executes Prefill → EphemeralExecutionResult
    ///   3. Home receives prefill result, builds PrefillReceipt
    ///   4. Blind decode input (prefill output) → BlindedAtom
    ///   5. Ephemeral executes Decode (with prefill KV) → EphemeralExecutionResult
    ///   6. Home unblind decode result → TwoStageOutsourcedResponse
    pub fn execute_two_stage_outsourced(
        &mut self,
        backend: &dyn Backend,
        prefill_atom: &ComputeAtom,
        decode_atom: &ComputeAtom,
        input: Vec<u8>,
        prefill_candidates: &[NodeProfile],
        decode_candidates: &[NodeProfile],
    ) -> Result<TwoStageOutsourcedResponse, String> {
        // --- Stage 1: Prefill ---

        // Route and blind the prefill input
        let (prefill_request, prefill_blinded) =
            self.prepare_outsource_blinded(prefill_atom, input, prefill_candidates)?;

        // Build the ephemeral node for prefill (stateless, no home state)
        let prefill_eph = EphemeralNode {
            node_id: prefill_request.target_node_id.clone(),
            region: prefill_atom.region.clone(),
            supported_kinds: vec![prefill_atom.kind.clone()],
        };
        let prefill_eph_result = prefill_eph.execute(backend, &prefill_blinded)?;

        // Home receives prefill, unblind output, build receipt
        let prefill_real_output =
            crate::prib::unblind(&prefill_eph_result.output, &prefill_request.prib_mask);

        // Absorb prefill KV into home store
        for chunk in &prefill_eph_result.kv_produced {
            if let Some(pos) = self
                .kv_store
                .iter()
                .position(|c| c.chunk_id == chunk.chunk_id)
            {
                self.kv_store[pos] = chunk.clone();
            } else {
                self.kv_store.push(chunk.clone());
            }
        }

        let prefill_receipt = PrefillReceipt {
            atom_id: prefill_atom.id.clone(),
            prefill_node_id: prefill_request.target_node_id.clone(),
            tokens_produced: prefill_eph_result.tokens_produced,
            stage_receipt: StageReceipt {
                stage_id: format!("{}:prefill", prefill_atom.id),
                stage_kind: "prefill".to_string(),
                nonce: Nonce::new(0),
                output_size: prefill_real_output.len(),
                kv_summary: (
                    prefill_eph_result.kv_produced.len(),
                    prefill_eph_result.kv_produced.iter().map(|c| c.byte_size).sum(),
                ),
            },
            kv_handoff: KVHandoff {
                source_stage: "prefill".to_string(),
                chunks: prefill_eph_result.kv_produced.clone(),
                metadata: KVHandoffMetadata::from_chunks(
                    format!("{}:prefill", prefill_atom.id),
                    &prefill_eph_result.kv_produced,
                ),
            },
            prefill_output: prefill_real_output.clone(),
        };

        // --- Stage 2: Decode ---

        // Verify handoff before decode
        prefill_receipt.kv_handoff.verify("prefill")?;

        // Verify stage receipt
        prefill_receipt.stage_receipt.verify("prefill", &Nonce::new(0))?;

        // Decode input is the real prefill output
        let (decode_request, mut decode_blinded) =
            self.prepare_outsource_blinded(decode_atom, prefill_real_output, decode_candidates)?;

        // Carry prefill KV into decode blinded atom
        decode_blinded.kv_chunks = prefill_receipt.kv_handoff.chunks.clone();

        let kv_migrated = prefill_request.target_node_id != decode_request.target_node_id;

        let decode_eph = EphemeralNode {
            node_id: decode_request.target_node_id.clone(),
            region: decode_atom.region.clone(),
            supported_kinds: vec![decode_atom.kind.clone()],
        };
        let decode_eph_result = decode_eph.execute(backend, &decode_blinded)?;

        // Home unblind decode result
        let decode_real_output =
            crate::prib::unblind(&decode_eph_result.output, &decode_request.prib_mask);

        let kv_absorbed = decode_eph_result.kv_produced.len();
        for chunk in &decode_eph_result.kv_produced {
            if let Some(pos) = self
                .kv_store
                .iter()
                .position(|c| c.chunk_id == chunk.chunk_id)
            {
                self.kv_store[pos] = chunk.clone();
            } else {
                self.kv_store.push(chunk.clone());
            }
        }

        Ok(TwoStageOutsourcedResponse {
            home_node_id: self.node_id.clone(),
            prefill_node_id: prefill_receipt.prefill_node_id,
            decode_node_id: decode_request.target_node_id,
            output: decode_real_output,
            tokens_produced: decode_eph_result.tokens_produced,
            kv_absorbed,
            kv_migrated,
        })
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
        self.kv_store = response.exec_response.kv_state.clone();
        Ok(response)
    }

    fn absorb_kv(&mut self, chunks: &[KVChunk]) -> usize {
        for chunk in chunks {
            if let Some(pos) = self
                .kv_store
                .iter()
                .position(|c| c.chunk_id == chunk.chunk_id)
            {
                self.kv_store[pos] = chunk.clone();
            } else {
                self.kv_store.push(chunk.clone());
            }
        }
        chunks.len()
    }

    fn finish_result(
        &mut self,
        home_node_id: &str,
        result: EphemeralExecutionResult,
    ) -> HomeExecutionResponse {
        self.finish_result_with_output(home_node_id, result.output.clone(), result)
    }

    fn finish_result_with_output(
        &mut self,
        home_node_id: &str,
        output: Vec<u8>,
        result: EphemeralExecutionResult,
    ) -> HomeExecutionResponse {
        let kv_absorbed = self.absorb_kv(&result.kv_produced);
        HomeExecutionResponse {
            home_node_id: home_node_id.to_string(),
            output,
            tokens_produced: result.tokens_produced,
            kv_absorbed,
            ephemeral_node_id: result.ephemeral_node_id,
        }
    }

    pub async fn execute_remote_with_runtime(
        &mut self,
        client: &RemoteClient,
        atom: &ComputeAtom,
        input: Vec<u8>,
        pool: &DiscoveryPool,
        nonce_seed: u64,
        timeout_ms: u64,
    ) -> Result<HomeExecutionResponse, String> {
        let stage = self
            .execute_remote_stage(
                client,
                atom,
                input,
                self.kv_store.clone(),
                pool,
                nonce_seed,
                timeout_ms,
            )
            .await?;

        Ok(HomeExecutionResponse {
            home_node_id: self.node_id.clone(),
            output: stage.output,
            tokens_produced: stage.tokens_produced,
            kv_absorbed: stage.kv_produced.len(),
            ephemeral_node_id: stage.node_id,
        })
    }

    pub async fn execute_two_stage_remote_with_runtime(
        &mut self,
        client: &RemoteClient,
        prefill_atom: &ComputeAtom,
        decode_atom: &ComputeAtom,
        input: Vec<u8>,
        pool: &DiscoveryPool,
        prefill_nonce_seed: u64,
        decode_nonce_seed: u64,
        timeout_ms: u64,
    ) -> Result<TwoStageOutsourcedResponse, String> {
        let prefill_stage = self
            .execute_remote_stage(
                client,
                prefill_atom,
                input,
                self.kv_store.clone(),
                pool,
                prefill_nonce_seed,
                timeout_ms,
            )
            .await?;

        let prefill_receipt = PrefillReceipt {
            atom_id: prefill_atom.id.clone(),
            prefill_node_id: prefill_stage.node_id.clone(),
            tokens_produced: prefill_stage.tokens_produced,
            stage_receipt: prefill_stage.stage_receipt.clone(),
            kv_handoff: KVHandoff {
                source_stage: "prefill".to_string(),
                chunks: prefill_stage.kv_produced.clone(),
                metadata: KVHandoffMetadata::from_chunks(
                    format!("{}:prefill", prefill_atom.id),
                    &prefill_stage.kv_produced,
                ),
            },
            prefill_output: prefill_stage.output.clone(),
        };

        // Verify handoff before decode
        prefill_receipt.kv_handoff.verify("prefill")?;

        // Verify stage receipt
        prefill_receipt.stage_receipt.verify("prefill", &prefill_receipt.stage_receipt.nonce)?;

        let decode_stage = self
            .execute_remote_stage(
                client,
                decode_atom,
                prefill_receipt.prefill_output.clone(),
                prefill_receipt.kv_handoff.chunks.clone(),
                pool,
                decode_nonce_seed,
                timeout_ms,
            )
            .await?;

        Ok(TwoStageOutsourcedResponse {
            home_node_id: self.node_id.clone(),
            prefill_node_id: prefill_receipt.prefill_node_id,
            decode_node_id: decode_stage.node_id.clone(),
            output: decode_stage.output,
            tokens_produced: decode_stage.tokens_produced,
            kv_absorbed: decode_stage.kv_produced.len(),
            kv_migrated: prefill_stage.node_id != decode_stage.node_id,
        })
    }

    /// Convenience wrapper for explicit, trusted endpoints.
    pub async fn execute_two_stage_remote(
        &mut self,
        prefill_atom: &ComputeAtom,
        decode_atom: &ComputeAtom,
        input: Vec<u8>,
        prefill_endpoint: &str,
        decode_endpoint: &str,
        prefill_nonce: Nonce,
        decode_nonce: Nonce,
    ) -> Result<TwoStageOutsourcedResponse, String> {
        let mut pool = DiscoveryPool::new();
        pool.register(remote_offer(
            "prefill-remote",
            prefill_endpoint,
            &prefill_atom.region,
            vec![prefill_atom.kind.clone()],
            1,
            30_000,
        ));
        pool.register(remote_offer(
            "decode-remote",
            decode_endpoint,
            &decode_atom.region,
            vec![decode_atom.kind.clone()],
            1,
            30_000,
        ));

        self.execute_two_stage_remote_with_runtime(
            &RemoteClient::new_trusted(),
            prefill_atom,
            decode_atom,
            input,
            &pool,
            prefill_nonce.0,
            decode_nonce.0,
            30_000,
        )
        .await
    }

    async fn execute_remote_stage(
        &mut self,
        client: &RemoteClient,
        atom: &ComputeAtom,
        input: Vec<u8>,
        kv_chunks: Vec<KVChunk>,
        pool: &DiscoveryPool,
        nonce_seed: u64,
        timeout_ms: u64,
    ) -> Result<RemoteStageReceipt, String> {
        let stage = ExecutionStage::for_atom_kind(&atom.kind);
        let mut remaining = pool.clone();
        let mut next_seed = nonce_seed;
        let mut last_err = String::new();

        while !remaining.is_empty() {
            let claimed = match claim_slot_http(
                client,
                &remaining,
                &self.node_id,
                &atom.kind,
                None,
                next_seed,
                timeout_ms,
            )
            .await
            {
                Ok(claimed) => claimed,
                Err(e) => {
                    return Err(if last_err.is_empty() {
                        e
                    } else {
                        format!("{last_err}; {e}")
                    })
                }
            };
            next_seed += claimed.attempts as u64;

            let endpoint = match claimed.offer.endpoint.as_deref() {
                Some(endpoint) => endpoint,
                None => {
                    last_err = format!("candidate '{}': missing endpoint", claimed.offer.node_id);
                    remaining.deregister(&claimed.offer.node_id);
                    continue;
                }
            };

            let mask =
                crate::prib::derive_mask(&format!("{}:{}", atom.id, self.node_id), input.len());
            let request = BlindedAtomRequest {
                blinded: BlindedAtom {
                    atom_id: atom.id.clone(),
                    kind: atom.kind.clone(),
                    model_id: atom.model_id.clone(),
                    input: crate::prib::blind(&input, &mask),
                    kv_chunks: kv_chunks.clone(),
                },
                nonce: claimed.claim.nonce.clone(),
                stage: stage.clone(),
            };

            match client.execute_blinded(endpoint, &request, timeout_ms).await {
                Ok(response) => {
                    if response.stage != stage {
                        last_err = format!(
                            "candidate '{}': stage mismatch: expected {:?}, got {:?}",
                            claimed.offer.node_id, stage, response.stage
                        );
                        remaining.deregister(&claimed.offer.node_id);
                        continue;
                    }
                    if !response.nonce.matches(&claimed.claim.nonce) {
                        last_err = format!(
                            "candidate '{}': nonce mismatch: expected {}, got {}",
                            claimed.offer.node_id, claimed.claim.nonce.0, response.nonce.0
                        );
                        remaining.deregister(&claimed.offer.node_id);
                        continue;
                    }

                    let output = crate::prib::unblind(&response.output, &mask);
                    let kv_produced = response.kv_produced;
                    self.absorb_kv(&kv_produced);

                    let stage_kind = match stage {
                        ExecutionStage::Prefill => "prefill",
                        ExecutionStage::Decode => "decode",
                        ExecutionStage::General => "general",
                    };

                    return Ok(RemoteStageReceipt {
                        node_id: response.ephemeral_node_id,
                        output: output.clone(),
                        tokens_produced: response.tokens_produced,
                        kv_produced: kv_produced.clone(),
                        stage_receipt: StageReceipt {
                            stage_id: format!("{}:{}", atom.id, stage_kind),
                            stage_kind: stage_kind.to_string(),
                            nonce: response.nonce.clone(),
                            output_size: output.len(),
                            kv_summary: (
                                kv_produced.len(),
                                kv_produced.iter().map(|c| c.byte_size).sum(),
                            ),
                        },
                    });
                }
                Err(e) => {
                    last_err = format!("candidate '{}': {}", claimed.offer.node_id, e);
                    remaining.deregister(&claimed.offer.node_id);
                }
            }
        }

        Err(if last_err.is_empty() {
            "no remote candidates available".to_string()
        } else {
            last_err
        })
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
            nonce: None,
        })
    }
}

// ---------------------------------------------------------------------------
// Boundary objects
// ---------------------------------------------------------------------------

/// Execution stage identifier for two-stage pipeline.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(deny_unknown_fields)]
pub enum ExecutionStage {
    Prefill,
    Decode,
    General,
}

impl ExecutionStage {
    pub fn for_atom_kind(kind: &AtomKind) -> Self {
        match kind {
            AtomKind::Prefill => ExecutionStage::Prefill,
            AtomKind::Decode => ExecutionStage::Decode,
            _ => ExecutionStage::General,
        }
    }
}

/// Remote execution request: BlindedAtom + nonce + stage.
/// This is what HomeNode sends to Ephemeral HTTP endpoint.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BlindedAtomRequest {
    pub blinded: BlindedAtom,
    pub nonce: Nonce,
    pub stage: ExecutionStage,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BlindedAtomResponse {
    pub ephemeral_node_id: String,
    pub atom_id: String,
    pub stage: ExecutionStage,
    pub nonce: Nonce,
    pub output: Vec<u8>,
    pub tokens_produced: u32,
    pub kv_produced: Vec<KVChunk>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct RemoteExecutionError {
    pub code: String,
    pub message: String,
    pub stage: ExecutionStage,
    pub nonce: Nonce,
}

/// A compute atom stripped of sovereignty metadata. This is what crosses
/// the boundary from Home Node to Ephemeral Node.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
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
    /// Nonce echoed back from the slot claim, for verification.
    #[serde(default)]
    pub nonce: Option<Nonce>,
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

// ---------------------------------------------------------------------------
// Two-stage sovereignty objects
// ---------------------------------------------------------------------------

/// KV handoff object: explicit KV state transfer from Prefill to Decode.
/// Held exclusively on the Home Node. Represents the KV-centric boundary
/// between stages, with ownership and lifecycle metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KVHandoff {
    /// Source stage that produced this KV state.
    pub source_stage: String,
    /// KV chunks being handed off to the next stage.
    pub chunks: Vec<KVChunk>,
    /// Minimal metadata for future verification hooks.
    #[serde(default)]
    pub metadata: KVHandoffMetadata,
}

impl KVHandoff {
    /// Verify handoff consistency before consumption.
    pub fn verify(&self, expected_source: &str) -> Result<(), String> {
        if self.source_stage != expected_source {
            return Err(format!(
                "handoff source mismatch: expected '{}', got '{}'",
                expected_source, self.source_stage
            ));
        }
        if self.metadata.chunk_count != self.chunks.len() {
            return Err(format!(
                "handoff chunk count mismatch: metadata says {}, actual {}",
                self.metadata.chunk_count,
                self.chunks.len()
            ));
        }
        let actual_bytes: usize = self.chunks.iter().map(|c| c.byte_size).sum();
        if self.metadata.total_bytes != actual_bytes {
            return Err(format!(
                "handoff total bytes mismatch: metadata says {}, actual {}",
                self.metadata.total_bytes, actual_bytes
            ));
        }
        Ok(())
    }
}

/// Minimal metadata for KV handoff, with basic verification fields.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KVHandoffMetadata {
    /// Unique handoff identifier for tracking.
    pub handoff_id: String,
    /// Number of chunks in this handoff.
    pub chunk_count: usize,
    /// Total bytes across all chunks.
    pub total_bytes: usize,
    /// Reserved for future KV ownership proof.
    #[serde(default)]
    pub ownership_hint: Option<String>,
    /// Reserved for future KV migration proof.
    #[serde(default)]
    pub migration_hint: Option<String>,
}

impl KVHandoffMetadata {
    /// Generate metadata from chunks for verification.
    pub fn from_chunks(handoff_id: String, chunks: &[KVChunk]) -> Self {
        let chunk_count = chunks.len();
        let total_bytes = chunks.iter().map(|c| c.byte_size).sum();
        Self {
            handoff_id,
            chunk_count,
            total_bytes,
            ownership_hint: None,
            migration_hint: None,
        }
    }
}

impl Default for KVHandoffMetadata {
    fn default() -> Self {
        Self {
            handoff_id: String::new(),
            chunk_count: 0,
            total_bytes: 0,
            ownership_hint: None,
            migration_hint: None,
        }
    }
}

/// Minimal stage execution receipt for verification.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StageReceipt {
    /// Unique stage execution identifier.
    pub stage_id: String,
    /// Stage kind (prefill/decode).
    pub stage_kind: String,
    /// Nonce from slot claim.
    pub nonce: Nonce,
    /// Output size in bytes.
    pub output_size: usize,
    /// KV summary: chunk count and total bytes.
    pub kv_summary: (usize, usize),
}

impl StageReceipt {
    /// Verify receipt consistency.
    pub fn verify(&self, expected_kind: &str, expected_nonce: &Nonce) -> Result<(), String> {
        if self.stage_kind != expected_kind {
            return Err(format!(
                "stage kind mismatch: expected '{}', got '{}'",
                expected_kind, self.stage_kind
            ));
        }
        if !self.nonce.matches(expected_nonce) {
            return Err(format!(
                "nonce mismatch: expected {}, got {}",
                expected_nonce.0, self.nonce.0
            ));
        }
        Ok(())
    }
}

/// Intermediate state produced after Prefill and passed into Decode.
/// Held exclusively on the Home Node between stages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PrefillReceipt {
    pub atom_id: String,
    pub prefill_node_id: String,
    pub tokens_produced: u32,
    /// Stage execution receipt for verification.
    pub stage_receipt: StageReceipt,
    /// KV handoff: explicit KV-centric transfer to Decode stage.
    pub kv_handoff: KVHandoff,
    /// Unblinded prefill output, stored on Home Node only.
    pub prefill_output: Vec<u8>,
}

/// Final result of a two-stage outsourced execution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TwoStageOutsourcedResponse {
    pub home_node_id: String,
    pub prefill_node_id: String,
    pub decode_node_id: String,
    /// Unblinded final output from the Decode stage.
    pub output: Vec<u8>,
    pub tokens_produced: u32,
    pub kv_absorbed: usize,
    /// Whether KV was migrated between Prefill and Decode nodes.
    pub kv_migrated: bool,
}

// ---------------------------------------------------------------------------
// Remote execution helpers
// ---------------------------------------------------------------------------

#[derive(Debug, Clone)]
struct RemoteStageReceipt {
    node_id: String,
    output: Vec<u8>,
    tokens_produced: u32,
    kv_produced: Vec<KVChunk>,
    stage_receipt: StageReceipt,
}

fn remote_offer(
    node_id: &str,
    endpoint: &str,
    region: &Region,
    supported_kinds: Vec<AtomKind>,
    capacity_hint: u32,
    expires_in_ms: u64,
) -> crate::runtime::SlotOffer {
    crate::runtime::SlotOffer {
        node_id: node_id.to_string(),
        region: region.clone(),
        supported_kinds,
        capacity_hint,
        expires_in_ms,
        endpoint: Some(endpoint.to_string()),
    }
}
