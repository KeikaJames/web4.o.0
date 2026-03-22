use ulp_atom_kernel::atom::Region;
use ulp_atom_kernel::kv::KVChunk;
use ulp_atom_kernel::sovereignty::{KVHandoff, KVHandoffMetadata};

#[test]
fn handoff_verify_rejects_source_mismatch() {
    let chunks = vec![KVChunk {
        chunk_id: "c1".into(),
        source_region: Region("us".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 100,
        payload: vec![0u8; 100],
    }];

    let handoff = KVHandoff {
        source_stage: "prefill".into(),
        chunks: chunks.clone(),
        metadata: KVHandoffMetadata::from_chunks("test:prefill".into(), &chunks),
    };

    assert!(handoff.verify("prefill").is_ok());
    assert!(handoff.verify("decode").is_err());
}

#[test]
fn handoff_verify_rejects_chunk_count_mismatch() {
    let chunks = vec![KVChunk {
        chunk_id: "c1".into(),
        source_region: Region("us".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 100,
        payload: vec![0u8; 100],
    }];

    let mut handoff = KVHandoff {
        source_stage: "prefill".into(),
        chunks: chunks.clone(),
        metadata: KVHandoffMetadata::from_chunks("test:prefill".into(), &chunks),
    };

    handoff.metadata.chunk_count = 999;
    assert!(handoff.verify("prefill").is_err());
}

#[test]
fn handoff_verify_rejects_total_bytes_mismatch() {
    let chunks = vec![KVChunk {
        chunk_id: "c1".into(),
        source_region: Region("us".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 100,
        payload: vec![0u8; 100],
    }];

    let mut handoff = KVHandoff {
        source_stage: "prefill".into(),
        chunks: chunks.clone(),
        metadata: KVHandoffMetadata::from_chunks("test:prefill".into(), &chunks),
    };

    handoff.metadata.total_bytes = 999;
    assert!(handoff.verify("prefill").is_err());
}

#[test]
fn handoff_metadata_from_chunks_calculates_correctly() {
    let chunks = vec![
        KVChunk {
            chunk_id: "c1".into(),
            source_region: Region("us".into()),
            seq_start: 0,
            seq_end: 10,
            byte_size: 100,
            payload: vec![0u8; 100],
        },
        KVChunk {
            chunk_id: "c2".into(),
            source_region: Region("us".into()),
            seq_start: 10,
            seq_end: 20,
            byte_size: 200,
            payload: vec![0u8; 200],
        },
    ];

    let metadata = KVHandoffMetadata::from_chunks("test:id".into(), &chunks);
    assert_eq!(metadata.handoff_id, "test:id");
    assert_eq!(metadata.chunk_count, 2);
    assert_eq!(metadata.total_bytes, 300);
}
