//! Test StageReceipt adapter lineage verification.

use ulp_atom_kernel::adapter::AdapterSpecialization;
use ulp_atom_kernel::kv::KVChunk;
use ulp_atom_kernel::runtime::Nonce;
use ulp_atom_kernel::sovereignty::{StageReceipt, KVHandoff, KVHandoffMetadata};
use ulp_atom_kernel::atom::Region;

#[test]
fn test_stage_receipt_adapter_lineage_match() {
    let receipt = StageReceipt {
        stage_id: "test:prefill".to_string(),
        stage_kind: "prefill".to_string(),
        owner_node_id: "home1".to_string(),
        nonce: Nonce::new(42),
        output_size: 100,
        kv_summary: (2, 200),
        handoff_id: Some("handoff1".to_string()),
        adapter_id: Some("adapter1".to_string()),
        adapter_generation: Some(5),
        adapter_specialization: Some(AdapterSpecialization::Stable),
    };

    let handoff = KVHandoff {
        source_stage: "prefill".to_string(),
        chunks: vec![
            KVChunk {
                chunk_id: "c1".to_string(),
                byte_size: 100,
                source_region: Region("us-west".to_string()),
                seq_start: 0,
                seq_end: 10,
                payload: vec![1, 2, 3],
            },
            KVChunk {
                chunk_id: "c2".to_string(),
                byte_size: 100,
                source_region: Region("us-west".to_string()),
                seq_start: 10,
                seq_end: 20,
                payload: vec![4, 5, 6],
            },
        ],
        metadata: KVHandoffMetadata {
            handoff_id: "handoff1".to_string(),
            chunk_count: 2,
            total_bytes: 200,
            ownership_hint: Some("home1".to_string()),
            migration_hint: None,
            adapter_generation: Some(5),
            adapter_specialization: Some(AdapterSpecialization::Stable),
        },
    };

    let result = receipt.verify_with_handoff("prefill", &Nonce::new(42), &handoff);
    assert!(result.is_ok());
}

#[test]
fn test_stage_receipt_adapter_lineage_mismatch() {
    let receipt = StageReceipt {
        stage_id: "test:prefill".to_string(),
        stage_kind: "prefill".to_string(),
        owner_node_id: "home1".to_string(),
        nonce: Nonce::new(42),
        output_size: 100,
        kv_summary: (2, 200),
        handoff_id: Some("handoff1".to_string()),
        adapter_id: Some("adapter1".to_string()),
        adapter_generation: Some(5),
        adapter_specialization: Some(AdapterSpecialization::Stable),
    };

    let handoff = KVHandoff {
        source_stage: "prefill".to_string(),
        chunks: vec![
            KVChunk {
                chunk_id: "c1".to_string(),
                byte_size: 100,
                source_region: Region("us-west".to_string()),
                seq_start: 0,
                seq_end: 10,
                payload: vec![1, 2, 3],
            },
            KVChunk {
                chunk_id: "c2".to_string(),
                byte_size: 100,
                source_region: Region("us-west".to_string()),
                seq_start: 10,
                seq_end: 20,
                payload: vec![4, 5, 6],
            },
        ],
        metadata: KVHandoffMetadata {
            handoff_id: "handoff1".to_string(),
            chunk_count: 2,
            total_bytes: 200,
            ownership_hint: Some("home1".to_string()),
            migration_hint: None,
            adapter_generation: Some(3), // Mismatch
            adapter_specialization: Some(AdapterSpecialization::Candidate), // Specialization mismatch
        },
    };

    let result = receipt.verify_with_handoff("prefill", &Nonce::new(42), &handoff);
    assert!(result.is_err());
    assert!(result.unwrap_err().contains("adapter generation mismatch"));
}

#[test]
fn test_stage_receipt_adapter_lineage_both_none() {
    let receipt = StageReceipt {
        stage_id: "test:prefill".to_string(),
        stage_kind: "prefill".to_string(),
        owner_node_id: "home1".to_string(),
        nonce: Nonce::new(42),
        output_size: 100,
        kv_summary: (2, 200),
        handoff_id: Some("handoff1".to_string()),
        adapter_id: None,
        adapter_generation: None,
        adapter_specialization: None,
    };

    let handoff = KVHandoff {
        source_stage: "prefill".to_string(),
        chunks: vec![
            KVChunk {
                chunk_id: "c1".to_string(),
                byte_size: 100,
                source_region: Region("us-west".to_string()),
                seq_start: 0,
                seq_end: 10,
                payload: vec![1, 2, 3],
            },
            KVChunk {
                chunk_id: "c2".to_string(),
                byte_size: 100,
                source_region: Region("us-west".to_string()),
                seq_start: 10,
                seq_end: 20,
                payload: vec![4, 5, 6],
            },
        ],
        metadata: KVHandoffMetadata {
            handoff_id: "handoff1".to_string(),
            chunk_count: 2,
            total_bytes: 200,
            ownership_hint: Some("home1".to_string()),
            migration_hint: None,
            adapter_generation: None,
            adapter_specialization: None,
        },
    };

    let result = receipt.verify_with_handoff("prefill", &Nonce::new(42), &handoff);
    assert!(result.is_ok());
}
