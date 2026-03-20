use serde::{Deserialize, Serialize};

use crate::atom::{AtomKind, ComputeAtom, Region};
use crate::capacity::NodeCapacity;
use crate::kv::{self, KVChunk};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NodeProfile {
    pub node_id: String,
    pub region: Region,
    pub latency_ms: f64,
    pub hotness: f64,
    pub supported_kinds: Vec<AtomKind>,
    pub sovereignty_zone: String,
    #[serde(default = "default_affinity")]
    pub prefill_affinity: f64,
    #[serde(default = "default_affinity")]
    pub decode_affinity: f64,
    #[serde(default)]
    pub capacity: NodeCapacity,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlacementBreakdown {
    pub node_id: String,
    pub final_score: f64,
    pub latency_score: f64,
    pub hotness_score: f64,
    pub engine_score: f64,
    pub specialization_score: f64,
    pub kv_locality_score: f64,
    pub sovereignty_score: f64,
    pub migration_cost: f64,
    pub capacity_score: f64,
}

/// Full routing decision: which node, why, and what migration is implied.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlacementDecision {
    pub breakdown: PlacementBreakdown,
    pub requires_kv_migration: bool,
    pub estimated_migration_cost: f64,
}

/// Context the router uses to factor in KV state locality.
pub struct KVContext<'a> {
    pub active_chunks: &'a [KVChunk],
}

struct Weights {
    latency: f64,
    hotness: f64,
    engine: f64,
    specialization: f64,
    kv_locality: f64,
    sovereignty: f64,
    capacity: f64,
}

fn default_affinity() -> f64 {
    0.5
}

fn weights_for(atom: &ComputeAtom) -> Weights {
    if atom.kind.is_decode_phase() {
        Weights { latency: 0.25, hotness: 0.05, engine: 0.05, specialization: 0.10, kv_locality: 0.30, sovereignty: 0.05, capacity: 0.20 }
    } else if atom.kind == AtomKind::Prefill {
        Weights { latency: 0.10, hotness: 0.05, engine: 0.10, specialization: 0.15, kv_locality: 0.10, sovereignty: 0.25, capacity: 0.25 }
    } else {
        Weights { latency: 0.15, hotness: 0.10, engine: 0.15, specialization: 0.05, kv_locality: 0.20, sovereignty: 0.15, capacity: 0.20 }
    }
}

fn score_node(atom: &ComputeAtom, node: &NodeProfile, kv_ctx: Option<&KVContext>) -> PlacementBreakdown {
    let w = weights_for(atom);
    let latency_score = 1.0 / (1.0 + node.latency_ms / 100.0);
    let hotness_score = node.hotness;
    let engine_score = if node.supported_kinds.contains(&atom.kind) { 1.0 } else { 0.0 };

    let specialization_score = match atom.kind {
        AtomKind::Prefill => node.prefill_affinity,
        AtomKind::Decode => node.decode_affinity,
        _ => (node.prefill_affinity + node.decode_affinity) / 2.0,
    };

    let kv_locality_score = match kv_ctx {
        Some(ctx) if !ctx.active_chunks.is_empty() => {
            let local = ctx.active_chunks.iter().filter(|c| c.source_region == node.region).count();
            local as f64 / ctx.active_chunks.len() as f64
        }
        _ => 0.5,
    };

    let sovereignty_score = if node.sovereignty_zone == atom.region.0 { 1.0 } else { 0.3 };

    let is_prefill = atom.kind == AtomKind::Prefill;
    let is_decode = atom.kind.is_decode_phase();
    let (capacity_score, _vram, _load) = crate::capacity::score_capacity(&node.capacity, is_prefill, is_decode);

    let score = w.latency * latency_score
        + w.hotness * hotness_score
        + w.engine * engine_score
        + w.specialization * specialization_score
        + w.kv_locality * kv_locality_score
        + w.sovereignty * sovereignty_score
        + w.capacity * capacity_score;

    PlacementBreakdown {
        node_id: node.node_id.clone(), final_score: score, latency_score, hotness_score,
        engine_score, specialization_score, kv_locality_score, sovereignty_score,
        migration_cost: 0.0, capacity_score,
    }
}

pub fn route(atom: &ComputeAtom, candidates: &[NodeProfile]) -> Option<PlacementDecision> {
    route_with_kv(atom, candidates, None)
}

pub fn route_with_kv(
    atom: &ComputeAtom, candidates: &[NodeProfile], kv_ctx: Option<&KVContext>,
) -> Option<PlacementDecision> {
    let best = candidates.iter().map(|n| {
        let mut breakdown = score_node(atom, n, kv_ctx);
        let mc: f64 = match kv_ctx {
            Some(ctx) => {
                let raw: f64 = ctx.active_chunks.iter()
                    .filter(|c| c.source_region != n.region)
                    .map(|c| kv::migration_cost(c, &n.region)).sum();
                if raw == 0.0 { 0.0 } else { raw }
            }
            None => 0.0,
        };
        breakdown.migration_cost = mc;
        (breakdown, mc > 0.0, mc)
    }).max_by(|a, b| a.0.final_score.partial_cmp(&b.0.final_score).unwrap())?;

    Some(PlacementDecision {
        breakdown: best.0, requires_kv_migration: best.1, estimated_migration_cost: best.2,
    })
}
