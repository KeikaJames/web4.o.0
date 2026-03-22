//! Integration tests for unified cost-driven transport (RFC scenarios).

use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
use ulp_atom_kernel::router::{NodeProfile, route_with_kv, KVContext};
use ulp_atom_kernel::capacity::NodeCapacity;
use ulp_atom_kernel::kv::KVChunk;

#[test]
fn test_dc_to_dc_transfer_kv() {
    let atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Decode,
        region: Region("dc-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let node = NodeProfile {
        node_id: "dc-east".to_string(),
        region: Region("dc-east".to_string()),
        latency_ms: 5.0,
        hotness: 0.8,
        supported_kinds: vec![AtomKind::Decode],
        sovereignty_zone: "dc-east".to_string(),
        prefill_affinity: 0.5,
        decode_affinity: 1.0,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let kv_chunk = KVChunk {
        chunk_id: "kv1".to_string(),
        source_region: Region("dc-west".to_string()),
        seq_start: 0,
        seq_end: 100,
        byte_size: 1_000_000,
        payload: vec![0u8; 1_000_000],
    };

    let kv_ctx = KVContext { active_chunks: &[kv_chunk] };
    let decision = route_with_kv(&atom, &[node], Some(&kv_ctx));

    assert!(decision.is_some());
    let d = decision.unwrap();
    assert!(d.should_transfer_kv);
}

#[test]
fn test_p2p_keep_kv_local() {
    let atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Decode,
        region: Region("p2p-node1".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let node = NodeProfile {
        node_id: "p2p-node2".to_string(),
        region: Region("p2p-node2".to_string()),
        latency_ms: 50.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Decode],
        sovereignty_zone: "p2p-node2".to_string(),
        prefill_affinity: 0.5,
        decode_affinity: 1.0,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let kv_chunk = KVChunk {
        chunk_id: "kv1".to_string(),
        source_region: Region("p2p-node1".to_string()),
        seq_start: 0,
        seq_end: 100,
        byte_size: 10_000_000,
        payload: vec![0u8; 10_000_000],
    };

    let kv_ctx = KVContext { active_chunks: &[kv_chunk] };
    let decision = route_with_kv(&atom, &[node], Some(&kv_ctx));

    assert!(decision.is_some());
    let d = decision.unwrap();
    assert!(!d.should_transfer_kv);
}

#[test]
fn test_kv_capacity_rejection() {
    let atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Decode,
        region: Region("dc-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let node = NodeProfile {
        node_id: "small-node".to_string(),
        region: Region("dc-east".to_string()),
        latency_ms: 5.0,
        hotness: 0.8,
        supported_kinds: vec![AtomKind::Decode],
        sovereignty_zone: "dc-east".to_string(),
        prefill_affinity: 0.5,
        decode_affinity: 1.0,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000,
    };

    let kv_chunk = KVChunk {
        chunk_id: "kv1".to_string(),
        source_region: Region("dc-west".to_string()),
        seq_start: 0,
        seq_end: 100,
        byte_size: 10_000_000,
        payload: vec![0u8; 10_000_000],
    };

    let kv_ctx = KVContext { active_chunks: &[kv_chunk] };
    let decision = route_with_kv(&atom, &[node], Some(&kv_ctx));

    assert!(decision.is_none());
}

#[test]
fn test_model_pool_routing() {
    let atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Prefill,
        region: Region("dc-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let node1 = NodeProfile {
        node_id: "gpt4-node".to_string(),
        region: Region("dc-west".to_string()),
        latency_ms: 5.0,
        hotness: 0.9,
        supported_kinds: vec![AtomKind::Prefill],
        sovereignty_zone: "dc-west".to_string(),
        prefill_affinity: 1.0,
        decode_affinity: 0.5,
        capacity: NodeCapacity::default(),
        base_model_id: Some("gpt-4".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let node2 = NodeProfile {
        node_id: "llama3-node".to_string(),
        region: Region("dc-east".to_string()),
        latency_ms: 10.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Prefill],
        sovereignty_zone: "dc-east".to_string(),
        prefill_affinity: 1.0,
        decode_affinity: 0.5,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let decision = route_with_kv(&atom, &[node1, node2], None);

    assert!(decision.is_some());
    let d = decision.unwrap();
    assert_eq!(d.breakdown.node_id, "llama3-node");
}

#[test]
fn test_stage_aware_routing() {
    let prefill_atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Prefill,
        region: Region("dc-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let decode_atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Decode,
        region: Region("dc-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let node = NodeProfile {
        node_id: "specialized".to_string(),
        region: Region("dc-west".to_string()),
        latency_ms: 5.0,
        hotness: 0.8,
        supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
        sovereignty_zone: "dc-west".to_string(),
        prefill_affinity: 0.9,
        decode_affinity: 0.3,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let prefill_decision = route_with_kv(&prefill_atom, &[node.clone()], None);
    let decode_decision = route_with_kv(&decode_atom, &[node], None);

    assert!(prefill_decision.is_some());
    assert!(decode_decision.is_some());
    assert!(prefill_decision.unwrap().breakdown.final_score > decode_decision.unwrap().breakdown.final_score);
}

#[test]
fn test_kv_locality_preference() {
    let atom = ComputeAtom {
        id: "test".to_string(),
        kind: AtomKind::Decode,
        region: Region("dc-west".to_string()),
        model_id: "llama-3".to_string(),
        shard_count: 0,
    };

    let local_node = NodeProfile {
        node_id: "local".to_string(),
        region: Region("dc-west".to_string()),
        latency_ms: 10.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Decode],
        sovereignty_zone: "dc-west".to_string(),
        prefill_affinity: 0.5,
        decode_affinity: 1.0,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let remote_node = NodeProfile {
        node_id: "remote".to_string(),
        region: Region("dc-east".to_string()),
        latency_ms: 5.0,
        hotness: 0.9,
        supported_kinds: vec![AtomKind::Decode],
        sovereignty_zone: "dc-east".to_string(),
        prefill_affinity: 0.5,
        decode_affinity: 1.0,
        capacity: NodeCapacity::default(),
        base_model_id: Some("llama-3".to_string()),
        compute_flops: 1e12,
        kv_capacity_bytes: 1_000_000_000,
    };

    let kv_chunk = KVChunk {
        chunk_id: "kv1".to_string(),
        source_region: Region("dc-west".to_string()),
        seq_start: 0,
        seq_end: 100,
        byte_size: 5_000_000,
        payload: vec![0u8; 5_000_000],
    };

    let kv_ctx = KVContext { active_chunks: &[kv_chunk] };
    let decision = route_with_kv(&atom, &[local_node, remote_node], Some(&kv_ctx));

    assert!(decision.is_some());
    let d = decision.unwrap();
    assert_eq!(d.breakdown.node_id, "local");
}
