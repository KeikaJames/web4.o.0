use ulp_atom_kernel::runtime::Nonce;
use ulp_atom_kernel::sovereignty::StageReceipt;

#[test]
fn stage_receipt_verify_rejects_kind_mismatch() {
    let receipt = StageReceipt {
        stage_id: "atom1:prefill".into(),
        stage_kind: "prefill".into(),
        owner_node_id: "home-1".into(),
        nonce: Nonce::new(100),
        output_size: 1024,
        kv_summary: (2, 2048),
    };

    assert!(receipt.verify("prefill", &Nonce::new(100)).is_ok());
    assert!(receipt.verify("decode", &Nonce::new(100)).is_err());
}

#[test]
fn stage_receipt_verify_rejects_nonce_mismatch() {
    let receipt = StageReceipt {
        stage_id: "atom1:prefill".into(),
        stage_kind: "prefill".into(),
        owner_node_id: "home-1".into(),
        nonce: Nonce::new(100),
        output_size: 1024,
        kv_summary: (2, 2048),
    };

    assert!(receipt.verify("prefill", &Nonce::new(100)).is_ok());
    assert!(receipt.verify("prefill", &Nonce::new(999)).is_err());
}

#[test]
fn stage_receipt_tracks_output_and_kv_summary() {
    let receipt = StageReceipt {
        stage_id: "atom1:decode".into(),
        stage_kind: "decode".into(),
        owner_node_id: "home-1".into(),
        nonce: Nonce::new(200),
        output_size: 512,
        kv_summary: (3, 4096),
    };

    assert_eq!(receipt.output_size, 512);
    assert_eq!(receipt.kv_summary, (3, 4096));
    assert_eq!(receipt.owner_node_id, "home-1");
}
