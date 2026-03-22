use ulp_atom_kernel::atom::{AtomKind, Region};
use ulp_atom_kernel::runtime::{DiscoveryPool, SlotOffer};
use ulp_atom_kernel::sovereignty::{KVAvailability, KVStorageScope};

#[test]
fn candidates_with_hints_prioritizes_kv_available_for_decode() {
    let mut pool = DiscoveryPool::new();

    pool.register(SlotOffer {
        node_id: "node-no-kv".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://no-kv:3000/execute".into()),
        kv_available: false,
        kv_availability: vec![],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    pool.register(SlotOffer {
        node_id: "node-with-kv".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://with-kv:3000/execute".into()),
        kv_available: true,
        kv_availability: vec![],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    let candidates = pool.candidates_with_hints(&AtomKind::Decode, None, true, None);
    assert_eq!(candidates.len(), 2);
    assert_eq!(candidates[0].node_id, "node-with-kv");
    assert_eq!(candidates[1].node_id, "node-no-kv");
}

#[test]
fn candidates_with_hints_without_preference_maintains_order() {
    let mut pool = DiscoveryPool::new();

    pool.register(SlotOffer {
        node_id: "node-a".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Prefill],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://a:3000/execute".into()),
        kv_available: false,
        kv_availability: vec![],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    pool.register(SlotOffer {
        node_id: "node-b".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Prefill],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://b:3000/execute".into()),
        kv_available: true,
        kv_availability: vec![],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    let candidates = pool.candidates_with_hints(&AtomKind::Prefill, None, false, None);
    assert_eq!(candidates.len(), 2);
}

#[test]
fn candidates_with_hints_filters_by_kind() {
    let mut pool = DiscoveryPool::new();

    pool.register(SlotOffer {
        node_id: "prefill-node".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Prefill],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://prefill:3000/execute".into()),
        kv_available: false,
        kv_availability: vec![],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    pool.register(SlotOffer {
        node_id: "decode-node".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://decode:3000/execute".into()),
        kv_available: true,
        kv_availability: vec![],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    let prefill_candidates = pool.candidates_with_hints(&AtomKind::Prefill, None, false, None);
    assert_eq!(prefill_candidates.len(), 1);
    assert_eq!(prefill_candidates[0].node_id, "prefill-node");

    let decode_candidates = pool.candidates_with_hints(&AtomKind::Decode, None, true, None);
    assert_eq!(decode_candidates.len(), 1);
    assert_eq!(decode_candidates[0].node_id, "decode-node");
}

#[test]
fn candidates_with_hints_prioritizes_matching_handoff_id() {
    let mut pool = DiscoveryPool::new();

    pool.register(SlotOffer {
        node_id: "node-generic-kv".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://generic:3000/execute".into()),
        kv_available: true,
        kv_availability: vec![],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    pool.register(SlotOffer {
        node_id: "node-matching-handoff".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://matching:3000/execute".into()),
        kv_available: false,
        kv_availability: vec![KVAvailability {
            handoff_id: "test-handoff-123".into(),
            node_id: "node-matching-handoff".into(),
            scope: KVStorageScope::RemoteAvailable,
            chunk_summary: (2, 1024),
            owner_hint: Some("home-node".into()),
        }],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: None,
    });

    let candidates = pool.candidates_with_hints(&AtomKind::Decode, None, true, Some("test-handoff-123"));
    assert_eq!(candidates.len(), 2);
    assert_eq!(candidates[0].node_id, "node-matching-handoff");
    assert_eq!(candidates[1].node_id, "node-generic-kv");
}

#[test]
fn candidates_with_hints_considers_latency_and_ownership() {
    let mut pool = DiscoveryPool::new();

    pool.register(SlotOffer {
        node_id: "node-high-latency".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://high-latency:3000/execute".into()),
        kv_available: false,
        kv_availability: vec![KVAvailability {
            handoff_id: "handoff-x".into(),
            node_id: "node-high-latency".into(),
            scope: KVStorageScope::RemoteAvailable,
            chunk_summary: (1, 512),
            owner_hint: None,
        }],
        capabilities: vec![],
        ownership_context: None,
        latency_hint_ms: Some(500),
    });

    pool.register(SlotOffer {
        node_id: "node-low-latency-owner".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://low-latency:3000/execute".into()),
        kv_available: false,
        kv_availability: vec![KVAvailability {
            handoff_id: "handoff-x".into(),
            node_id: "node-low-latency-owner".into(),
            scope: KVStorageScope::RemoteAvailable,
            chunk_summary: (1, 512),
            owner_hint: Some("home-1".into()),
        }],
        capabilities: vec![],
        ownership_context: Some("home-1".into()),
        latency_hint_ms: Some(100),
    });

    let candidates = pool.candidates_with_hints(&AtomKind::Decode, None, true, Some("handoff-x"));
    assert_eq!(candidates.len(), 2);
    assert_eq!(candidates[0].node_id, "node-low-latency-owner");
    assert_eq!(candidates[1].node_id, "node-high-latency");
}
