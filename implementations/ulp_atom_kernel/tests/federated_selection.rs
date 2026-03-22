use ulp_atom_kernel::atom::{AtomKind, Region};
use ulp_atom_kernel::runtime::{DiscoveryPool, SlotOffer};

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
        capabilities: vec![],
    });

    pool.register(SlotOffer {
        node_id: "node-with-kv".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://with-kv:3000/execute".into()),
        kv_available: true,
        capabilities: vec![],
    });

    let candidates = pool.candidates_with_hints(&AtomKind::Decode, None, true);
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
        capabilities: vec![],
    });

    pool.register(SlotOffer {
        node_id: "node-b".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Prefill],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://b:3000/execute".into()),
        kv_available: true,
        capabilities: vec![],
    });

    let candidates = pool.candidates_with_hints(&AtomKind::Prefill, None, false);
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
        capabilities: vec![],
    });

    pool.register(SlotOffer {
        node_id: "decode-node".into(),
        region: Region("us-west".into()),
        supported_kinds: vec![AtomKind::Decode],
        capacity_hint: 4,
        expires_in_ms: 5000,
        endpoint: Some("http://decode:3000/execute".into()),
        kv_available: true,
        capabilities: vec![],
    });

    let prefill_candidates = pool.candidates_with_hints(&AtomKind::Prefill, None, false);
    assert_eq!(prefill_candidates.len(), 1);
    assert_eq!(prefill_candidates[0].node_id, "prefill-node");

    let decode_candidates = pool.candidates_with_hints(&AtomKind::Decode, None, true);
    assert_eq!(decode_candidates.len(), 1);
    assert_eq!(decode_candidates[0].node_id, "decode-node");
}
