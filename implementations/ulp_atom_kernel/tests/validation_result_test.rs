use ulp_atom_kernel::validation::ValidationResult;

#[test]
fn test_validation_result_serve_only() {
    let result = ValidationResult::serve_only("adapter-1".to_string(), 1);

    assert_eq!(result.active_adapter_id, "adapter-1");
    assert_eq!(result.active_generation, 1);
    assert!(result.candidate_adapter_id.is_none());
    assert!(result.candidate_generation.is_none());
    assert!(result.lineage_valid);
    assert!(result.is_acceptable);
}

#[test]
fn test_validation_result_shadow_eval_valid() {
    let result = ValidationResult::shadow_eval(
        "adapter-1".to_string(),
        1,
        "adapter-1".to_string(),
        2,
        true,
        true,
        true,
    );

    assert_eq!(result.active_adapter_id, "adapter-1");
    assert_eq!(result.active_generation, 1);
    assert_eq!(result.candidate_adapter_id, Some("adapter-1".to_string()));
    assert_eq!(result.candidate_generation, Some(2));
    assert!(result.lineage_valid);
    assert!(result.is_acceptable);
}

#[test]
fn test_validation_result_shadow_eval_lineage_invalid() {
    let result = ValidationResult::shadow_eval(
        "adapter-1".to_string(),
        1,
        "adapter-2".to_string(),
        2,
        false,
        false,
        false,
    );

    assert!(!result.lineage_valid);
    assert!(!result.is_acceptable);
}

#[test]
fn test_validation_result_shadow_eval_kv_mismatch() {
    let result = ValidationResult::shadow_eval(
        "adapter-1".to_string(),
        1,
        "adapter-1".to_string(),
        2,
        true,
        true,
        false, // kv_count_match = false
    );

    assert!(result.lineage_valid);
    assert!(!result.is_acceptable); // Not acceptable due to kv mismatch
}
