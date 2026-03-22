//! Test shadow evaluation dual-path execution.

use ulp_atom_kernel::adapter::{AdapterContext, AdapterMode, AdapterRef};
use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
use ulp_atom_kernel::backend::mock::MockBackend;
use ulp_atom_kernel::kernel::{self, AtomRequest};
use ulp_atom_kernel::router::NodeProfile;
use ulp_atom_kernel::capacity::NodeCapacity;

#[test]
fn test_dispatch_shadow_dual_path() {
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
            adapter_id: "active".to_string(),
            generation: 1,
            mode: AdapterMode::Serve,
        },
        candidate_adapter: Some(AdapterRef {
            adapter_id: "active".to_string(),
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

    let result = kernel::dispatch_shadow(&backend, request);
    assert!(result.is_ok());

    let (active_resp, comparison) = result.unwrap();
    assert_eq!(active_resp.exec_response.adapter_generation, Some(1));
    assert_eq!(comparison.shadow_response.adapter_generation, Some(2));
    assert!(comparison.lineage_valid);
    assert!(comparison.is_acceptable);
}
