use serde::{Deserialize, Serialize};

use crate::atom::{AtomKind, ComputeAtom, Region};
use crate::capacity::NodeCapacity;
use crate::kv::KVChunk;
use crate::link::{Link, Direction, should_transfer};

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
    #[serde(default)]
    pub base_model_id: Option<String>,
    #[serde(default = "default_compute_flops")]
    pub compute_flops: f64,
    #[serde(default = "default_kv_capacity")]
    pub kv_capacity_bytes: usize,
}

fn default_compute_flops() -> f64 {
    1e12
}

fn default_kv_capacity() -> usize {
    1_000_000_000
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
    pub should_transfer_kv: bool,
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
    let engine_score = 1.0;

    let specialization_score = match atom.kind {
        AtomKind::Prefill => node.prefill_affinity,
        AtomKind::Decode => node.decode_affinity,
        _ => (node.prefill_affinity + node.decode_affinity) / 2.0,
    };

    // KV availability cost
    let (kv_locality_score, kv_cost) = match kv_ctx {
        Some(ctx) if !ctx.active_chunks.is_empty() => {
            let total_kv_bytes: usize = ctx.active_chunks.iter().map(|c| c.byte_size).sum();
            let link = if node.region.0.starts_with("dc-") { Link::datacenter() } else { Link::p2p() };

            let local = ctx.active_chunks.iter().filter(|c| c.source_region == node.region).count();
            let locality = local as f64 / ctx.active_chunks.len() as f64;

            let transfer_decision = should_transfer(
                total_kv_bytes, &link, Direction::Download, node.compute_flops, false
            );

            let cost = if transfer_decision {
                link.transfer_cost(total_kv_bytes, Direction::Download)
            } else {
                crate::link::recompute_cost_kv(total_kv_bytes, node.compute_flops)
            };

            (locality, cost)
        }
        _ => (0.5, 0.0),
    };

    let sovereignty_score = if node.sovereignty_zone == atom.region.0 { 1.0 } else { 0.3 };

    let is_prefill = atom.kind == AtomKind::Prefill;
    let is_decode = atom.kind.is_decode_phase();
    let (capacity_score, _vram, _load) = crate::capacity::score_capacity(&node.capacity, is_prefill, is_decode);

    // Load penalty
    let load_penalty = if node.capacity.current_load > 0.0 {
        node.capacity.current_load / 100.0
    } else {
        0.0
    };

    let score = w.latency * latency_score
        + w.hotness * hotness_score
        + w.engine * engine_score
        + w.specialization * specialization_score
        + w.kv_locality * kv_locality_score
        + w.sovereignty * sovereignty_score
        + w.capacity * capacity_score
        - load_penalty * 0.1;

    PlacementBreakdown {
        node_id: node.node_id.clone(), final_score: score, latency_score, hotness_score,
        engine_score, specialization_score, kv_locality_score, sovereignty_score,
        migration_cost: kv_cost, capacity_score,
    }
}

pub fn route(atom: &ComputeAtom, candidates: &[NodeProfile]) -> Option<PlacementDecision> {
    route_with_kv(atom, candidates, None)
}

pub fn route_with_kv(
    atom: &ComputeAtom, candidates: &[NodeProfile], kv_ctx: Option<&KVContext>,
) -> Option<PlacementDecision> {
    let total_kv_bytes: usize = kv_ctx.map(|ctx| ctx.active_chunks.iter().map(|c| c.byte_size).sum()).unwrap_or(0);

    let compatible: Vec<_> = candidates.iter().filter(|n| {
        // Hard constraint: model must match
        if let Some(ref model_id) = n.base_model_id {
            if model_id != &atom.model_id {
                return false;
            }
        }
        // Hard constraint: must support atom kind
        if !n.supported_kinds.contains(&atom.kind) {
            return false;
        }
        // Hard constraint: KV capacity must be sufficient
        if total_kv_bytes > n.kv_capacity_bytes {
            return false;
        }
        true
    }).collect();

    if compatible.is_empty() {
        return None;
    }

    let best = compatible.iter().map(|n| {
        let mut breakdown = score_node(atom, n, kv_ctx);
        let (mc, should_transfer) = match kv_ctx {
            Some(ctx) if !ctx.active_chunks.is_empty() => {
                let link = if n.region.0.starts_with("dc-") { Link::datacenter() } else { Link::p2p() };
                let should = should_transfer(total_kv_bytes, &link, Direction::Download, n.compute_flops, false);
                let cost = if should {
                    link.transfer_cost(total_kv_bytes, Direction::Download)
                } else {
                    crate::link::recompute_cost_kv(total_kv_bytes, n.compute_flops)
                };
                (cost, should)
            }
            _ => (0.0, false),
        };
        breakdown.migration_cost = mc;
        (breakdown, mc > 0.0, mc, should_transfer)
    }).max_by(|a, b| a.0.final_score.partial_cmp(&b.0.final_score).unwrap())?;

    Some(PlacementDecision {
        breakdown: best.0,
        requires_kv_migration: best.1,
        estimated_migration_cost: best.2,
        should_transfer_kv: best.3,
    })
}
