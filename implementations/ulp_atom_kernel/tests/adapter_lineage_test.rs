//! Test adapter lineage propagation through atom execution.

use ulp_atom_kernel::adapter::{AdapterContext, AdapterMode, AdapterRef};
use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
use ulp_atom_kernel::backend::mock::MockBackend;
use ulp_atom_kernel::kernel::{self, AtomRequest};
use ulp_atom_kernel::router::NodeProfile;
use ulp_atom_kernel::capacity::NodeCapacity;

#[test]
fn test_adapter_context_resolve_active() {
    let ctx = AdapterContext {
        active_adapter: AdapterRef {
            adapter_id: "active".to_string(),
            generation: 1,
            mode: AdapterMode::Serve,
        },
        candidate_adapter: None,
    };

    let resolved = ctx.resolve_adapter();
    assert_eq!(resolved.adapter_id, "active");
    assert_eq!(resolved.generation, 1);
}

#[test]
fn test_adapter_context_resolve_shadow_eval() {
    let ctx = AdapterContext {
        active_adapter: AdapterRef {
            adapter_id: "active".to_string(),
            generation: 1,
            mode: AdapterMode::Serve,
        },
        candidate_adapter: Some(AdapterRef {
            adapter_id: "candidate".to_string(),
            generation: 2,
            mode: AdapterMode::ShadowEval,
        }),
    };

    let resolved = ctx.resolve_adapter();
    assert_eq!(resolved.adapter_id, "candidate");
    assert_eq!(resolved.generation, 2);
}

#[test]
fn test_adapter_lineage_in_exec_response() {
    let backend = MockBackend;
    let atom = ComputeAtom {
        id: "test-atom".to_string(),
        kind: AtomKind::Prefill,
        region: Region("us-west".to_string()),
        model_id: "test-model".to_string(),
        shard_count: 0,
    };

    let adapter_ctx = AdapterContext {
        active_adapter: AdapterRef {
            adapter_id: "test-adapter".to_string(),
            generation: 5,
            mode: AdapterMode::Serve,
        },
        candidate_adapter: None,
    };

    let request = AtomRequest {
        atom,
        input: b"test".to_vec(),
        kv_state: vec![],
        candidates: vec![NodeProfile {
            node_id: "node1".to_string(),
            region: Region("us-west".to_string()),
            latency_ms: 10.0,
            hotness: 0.5,
            supported_kinds: vec![AtomKind::Prefill],
            sovereignty_zone: "zone1".to_string(),
            prefill_affinity: 1.0,
            decode_affinity: 0.5,
            capacity: NodeCapacity::default(),
            base_model_id: None,
            compute_flops: 1e12,
            kv_capacity_bytes: 1_000_000_000,
        }],
        adapter_context: Some(adapter_ctx),
    };

    let response = kernel::dispatch(&backend, request).unwrap();

    assert_eq!(response.exec_response.adapter_id, Some("test-adapter".to_string()));
    assert_eq!(response.exec_response.adapter_generation, Some(5));
}

#[test]
fn test_adapter_lineage_with_candidate() {
    let backend = MockBackend;
    let atom = ComputeAtom {
        id: "test-atom".to_string(),
        kind: AtomKind::Decode,
        region: Region("us-west".to_string()),
        model_id: "test-model".to_string(),
        shard_count: 0,
    };

    let adapter_ctx = AdapterContext {
        active_adapter: AdapterRef {
            adapter_id: "active".to_string(),
            generation: 1,
            mode: AdapterMode::Serve,
        },
        candidate_adapter: Some(AdapterRef {
            adapter_id: "candidate".to_string(),
            generation: 2,
            mode: AdapterMode::ShadowEval,
        }),
    };

    let request = AtomRequest {
        atom,
        input: b"test".to_vec(),
        kv_state: vec![],
        candidates: vec![NodeProfile {
            node_id: "node1".to_string(),
            region: Region("us-west".to_string()),
            latency_ms: 10.0,
            hotness: 0.5,
            supported_kinds: vec![AtomKind::Decode],
            sovereignty_zone: "zone1".to_string(),
            prefill_affinity: 0.5,
            decode_affinity: 1.0,
            capacity: NodeCapacity::default(),
            base_model_id: None,
            compute_flops: 1e12,
            kv_capacity_bytes: 1_000_000_000,
        }],
        adapter_context: Some(adapter_ctx),
    };

    let response = kernel::dispatch(&backend, request).unwrap();

    // Should resolve to candidate in shadow_eval mode
    assert_eq!(response.exec_response.adapter_id, Some("candidate".to_string()));
    assert_eq!(response.exec_response.adapter_generation, Some(2));
}
