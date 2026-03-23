use serde::{Deserialize, Serialize};

use crate::atom::{AtomKind, ComputeAtom, Region};
use crate::backend::{Backend, BackendKind, BackendRequest};
use crate::exec::ExecResponse;
use crate::kv::{KVChunk, MigrationReceipt};
use crate::router::{self, KVContext, NodeProfile, PlacementDecision};
use crate::shadow::ComparisonResult;

/// Stable explain output for a placement decision.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlacementExplain {
    pub node_id: String,
    pub final_score: f64,
    pub latency_score: f64,
    pub hotness_score: f64,
    pub specialization_score: f64,
    pub migration_cost: f64,
    pub sovereignty_score: f64,
    pub kv_locality_score: f64,
    pub engine_score: f64,
    pub capacity_score: f64,
    pub requires_kv_migration: bool,
    pub chunks_migrated: usize,
}

impl PlacementExplain {
    pub fn from_decision(decision: &PlacementDecision, chunks_migrated: usize) -> Self {
        let b = &decision.breakdown;
        PlacementExplain {
            node_id: b.node_id.clone(),
            final_score: b.final_score,
            latency_score: b.latency_score,
            hotness_score: b.hotness_score,
            specialization_score: b.specialization_score,
            migration_cost: b.migration_cost,
            sovereignty_score: b.sovereignty_score,
            kv_locality_score: b.kv_locality_score,
            engine_score: b.engine_score,
            capacity_score: b.capacity_score,
            requires_kv_migration: decision.requires_kv_migration,
            chunks_migrated,
        }
    }
}

/// What enters the kernel.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AtomRequest {
    pub atom: ComputeAtom,
    pub input: Vec<u8>,
    pub kv_state: Vec<KVChunk>,
    pub candidates: Vec<NodeProfile>,
    #[serde(default)]
    pub adapter_context: Option<crate::adapter::AdapterContext>,
}

/// What the kernel returns.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AtomResponse {
    pub placement: PlacementDecision,
    pub explain: PlacementExplain,
    pub migrations: Vec<MigrationReceipt>,
    pub exec_response: ExecResponse,
    #[serde(default)]
    pub backend_kind: Option<BackendKind>,
    #[serde(default)]
    pub backend_device: Option<String>,
    #[serde(default)]
    pub validation_result: Option<crate::validation::ValidationResult>,
}

/// Run one request through the full kernel path:
/// 1. Route — choose placement with KV-locality awareness
/// 2. Migrate — move KV chunks that aren't on the chosen node's region
/// 3. Execute — run the compute through the backend
pub fn dispatch(
    backend: &dyn Backend,
    request: AtomRequest,
) -> Result<AtomResponse, String> {
    // 1. route
    let kv_ctx = KVContext { active_chunks: &request.kv_state };
    let placement = router::route_with_kv(&request.atom, &request.candidates, Some(&kv_ctx))
        .ok_or_else(|| "no candidate nodes".to_string())?;

    let target_region = Region(placement.breakdown.node_id.clone());
    // use the actual region from the winning node
    let target_region = request.candidates.iter()
        .find(|n| n.node_id == placement.breakdown.node_id)
        .map(|n| n.region.clone())
        .unwrap_or(target_region);

    // 2. migrate KV chunks based on transport decision
    let mut migrations = Vec::new();
    let mut migrated_chunks = Vec::new();

    if placement.should_transfer_kv {
        for chunk in request.kv_state {
            if chunk.source_region != target_region {
                let (moved, receipt) = backend.migrate_kv(chunk, target_region.clone())?;
                migrations.push(receipt);
                migrated_chunks.push(moved);
            } else {
                migrated_chunks.push(chunk);
            }
        }
    } else {
        // Recompute path: don't transfer KV, pass empty state
        migrated_chunks = vec![];
    }

    // 3. execute via backend
    let backend_req = BackendRequest {
        atom_id: request.atom.id.clone(),
        input: request.input,
        kv_state: migrated_chunks,
    };

    let backend_resp = match request.atom.kind {
        AtomKind::Prefill => backend.execute_prefill(backend_req)?,
        AtomKind::Decode => backend.execute_decode(backend_req)?,
        AtomKind::Inference | AtomKind::Embedding | AtomKind::FineTune => {
            return Err(format!("AtomKind::{:?} not implemented", request.atom.kind));
        }
    };

    let exec_response = {
        let resolved = request.adapter_context.as_ref().map(|ctx| ctx.resolve_adapter());
        ExecResponse {
            atom_id: backend_resp.atom_id,
            output: backend_resp.output,
            tokens_produced: backend_resp.tokens_produced,
            kv_state: backend_resp.kv_state,
            adapter_id: resolved.map(|a| a.adapter_id.clone()),
            adapter_generation: resolved.map(|a| a.generation),
            adapter_specialization: resolved.map(|a| a.specialization.clone()),
            specialization_summary: request.adapter_context.as_ref().and_then(|ctx| {
                let selection = ctx.get_selection();
                Some(crate::exec::SpecializationSummary {
                    stable_generation: selection.stable.generation,
                    shared_generation: selection.shared.as_ref().map(|a| a.generation),
                    candidate_generation: selection.candidate.as_ref().map(|a| a.generation),
                    stable_adapter_id: selection.stable.adapter_id.clone(),
                })
            }),
        }
    };

    let explain = PlacementExplain::from_decision(&placement, migrations.len());

    let caps = backend.device_capabilities();

    // Generate validation result for serve mode
    let validation_result = request.adapter_context.as_ref().map(|ctx| {
        let adapter = ctx.resolve_adapter();
        crate::validation::ValidationResult::serve_only(
            adapter.adapter_id.clone(),
            adapter.generation,
        )
    });

    Ok(AtomResponse {
        placement,
        explain,
        migrations,
        exec_response,
        backend_kind: Some(caps.backend_kind),
        backend_device: Some(caps.device_name),
        validation_result,
    })
}

/// Dual-path dispatch: active + shadow execution for adapter validation.
pub fn dispatch_shadow(
    backend: &dyn Backend,
    request: AtomRequest,
) -> Result<(AtomResponse, ComparisonResult), String> {
    let adapter_ctx = request.adapter_context.as_ref()
        .ok_or_else(|| "shadow dispatch requires adapter_context".to_string())?;

    let candidate = adapter_ctx.candidate_adapter.as_ref()
        .ok_or_else(|| "shadow dispatch requires candidate_adapter".to_string())?;

    // Active path: use active adapter
    let mut active_req = request.clone();
    if let Some(ctx) = &mut active_req.adapter_context {
        ctx.candidate_adapter = None;
    }
    let active_resp = dispatch(backend, active_req)?;

    // Shadow path: use candidate adapter
    let mut shadow_req = request.clone();
    if let Some(ctx) = &mut shadow_req.adapter_context {
        ctx.active_adapter = candidate.clone();
        ctx.candidate_adapter = None;
    }
    let shadow_resp = dispatch(backend, shadow_req)?;

    // Extract specialization info for comparison
    let active_spec = active_resp.exec_response.adapter_specialization.clone();
    let candidate_spec = shadow_resp.exec_response.adapter_specialization.clone();

    let comparison = ComparisonResult::compare(
        active_resp.exec_response.clone(),
        shadow_resp.exec_response.clone(),
        active_spec,
        candidate_spec,
    );

    // Generate validation result from shadow comparison
    let validation_result = crate::validation::ValidationResult::shadow_eval(
        adapter_ctx.active_adapter.adapter_id.clone(),
        adapter_ctx.active_adapter.generation,
        candidate.adapter_id.clone(),
        candidate.generation,
        comparison.lineage_valid,
        comparison.output_match,
        comparison.kv_count_match,
    );

    // Attach validation result to active response
    let mut final_resp = active_resp;
    final_resp.validation_result = Some(validation_result);

    Ok((final_resp, comparison))
}
