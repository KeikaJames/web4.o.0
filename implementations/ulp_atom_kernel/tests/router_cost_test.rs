//! Test router with unified cost model.

use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
use ulp_atom_kernel::router::{NodeProfile, route};
use ulp_atom_kernel::capacity::NodeCapacity;

#[test]
fn test_model_mismatch_rejection() {
    let atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Prefill,
        region: Region("us-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let node = NodeProfile {
        node_id: "node1".to_string(),
        region: Region("us-west".to_string()),
        latency_ms: 10.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Prefill],
        sovereignty_zone: "us-west".to_string(),
        prefill_affinity: 1.0,
        decode_affinity: 0.5,
        capacity: NodeCapacity::default(),
        base_model_id: Some("gpt-4".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let decision = route(&atom, &[node]);
    assert!(decision.is_some());
    let d = decision.unwrap();
    assert_eq!(d.breakdown.final_score, 0.0);
}

#[test]
fn test_model_match_routes() {
    let atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Prefill,
        region: Region("us-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let node = NodeProfile {
        node_id: "node1".to_string(),
        region: Region("us-west".to_string()),
        latency_ms: 10.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Prefill],
        sovereignty_zone: "us-west".to_string(),
        prefill_affinity: 1.0,
        decode_affinity: 0.5,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let decision = route(&atom, &[node]);
    assert!(decision.is_some());
    let d = decision.unwrap();
    assert!(d.breakdown.final_score > 0.0);
}
