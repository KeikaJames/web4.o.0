use ulp_atom_kernel::atom::Region;
use ulp_atom_kernel::kv::KVChunk;
use ulp_atom_kernel::sovereignty::{KVHandoff, KVHandoffMetadata};

#[test]
fn handoff_with_ownership_provenance() {
    let chunks = vec![KVChunk {
        chunk_id: "c1".into(),
        source_region: Region("us".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 100,
        payload: vec![0u8; 100],
    }];

    let metadata = KVHandoffMetadata::from_chunks_with_provenance(
        "test:prefill".into(),
        &chunks,
        "home-1".into(),
        None,
    );

    assert_eq!(metadata.ownership_hint, Some("home-1".into()));
    assert_eq!(metadata.migration_hint, None);
}

#[test]
fn handoff_with_migration_provenance() {
    let chunks = vec![KVChunk {
        chunk_id: "c1".into(),
        source_region: Region("us".into()),
        seq_start: 0,
        seq_end: 10,
        byte_size: 100,
        payload: vec![0u8; 100],
    }];

    let metadata = KVHandoffMetadata::from_chunks_with_provenance(
        "test:prefill".into(),
        &chunks,
        "home-1".into(),
        Some("eph-remote".into()),
    );

    assert_eq!(metadata.ownership_hint, Some("home-1".into()));
    assert_eq!(metadata.migration_hint, Some("from:eph-remote".into()));
}

#[test]
fn handoff_verify_with_owner_rejects_mismatch() {
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
        metadata: KVHandoffMetadata::from_chunks_with_provenance(
            "test:prefill".into(),
            &chunks,
            "home-1".into(),
            None,
        ),
    };

    assert!(handoff.verify_with_owner("prefill", "home-1").is_ok());
    assert!(handoff.verify_with_owner("prefill", "home-2").is_err());
}
