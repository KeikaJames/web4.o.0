use ulp_atom_kernel::kv::KVChunk;
use ulp_atom_kernel::atom::Region;
use ulp_atom_kernel::runtime::Nonce;
use ulp_atom_kernel::sovereignty::{KVHandoff, KVHandoffMetadata, StageReceipt};

#[test]
fn stage_receipt_verify_with_handoff_success() {
    let chunks = vec![KVChunk {
        chunk_id: "chunk-1".into(),
        source_region: Region("us-west".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 1024,
        payload: vec![0u8; 1024],
    }];

    let handoff = KVHandoff {
        source_stage: "prefill".into(),
        chunks: chunks.clone(),
        metadata: KVHandoffMetadata::from_chunks("test-handoff".into(), &chunks),
    };

    let receipt = StageReceipt {
        stage_id: "atom-1:prefill".into(),
        stage_kind: "prefill".into(),
        owner_node_id: "home-1".into(),
        nonce: Nonce::new(42),
        output_size: 512,
        kv_summary: (1, 1024),
        handoff_id: Some("test-handoff".into()),
    };

    assert!(receipt.verify_with_handoff("prefill", &Nonce::new(42), &handoff).is_ok());
}

#[test]
fn stage_receipt_verify_with_handoff_id_mismatch() {
    let chunks = vec![KVChunk {
        chunk_id: "chunk-1".into(),
        source_region: Region("us-west".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 1024,
        payload: vec![0u8; 1024],
    }];

    let handoff = KVHandoff {
        source_stage: "prefill".into(),
        chunks: chunks.clone(),
        metadata: KVHandoffMetadata::from_chunks("handoff-A".into(), &chunks),
    };

    let receipt = StageReceipt {
        stage_id: "atom-1:prefill".into(),
        stage_kind: "prefill".into(),
        owner_node_id: "home-1".into(),
        nonce: Nonce::new(42),
        output_size: 512,
        kv_summary: (1, 1024),
        handoff_id: Some("handoff-B".into()),
    };

    let result = receipt.verify_with_handoff("prefill", &Nonce::new(42), &handoff);
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("handoff ID mismatch"));
}

#[test]
fn stage_receipt_verify_with_handoff_kv_summary_mismatch() {
    let chunks = vec![KVChunk {
        chunk_id: "chunk-1".into(),
        source_region: Region("us-west".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 1024,
        payload: vec![0u8; 1024],
    }];

    let handoff = KVHandoff {
        source_stage: "prefill".into(),
        chunks: chunks.clone(),
        metadata: KVHandoffMetadata::from_chunks("test-handoff".into(), &chunks),
    };

    let receipt = StageReceipt {
        stage_id: "atom-1:prefill".into(),
        stage_kind: "prefill".into(),
        owner_node_id: "home-1".into(),
        nonce: Nonce::new(42),
        output_size: 512,
        kv_summary: (2, 2048),
        handoff_id: Some("test-handoff".into()),
    };

    let result = receipt.verify_with_handoff("prefill", &Nonce::new(42), &handoff);
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("KV summary mismatch"));
}
