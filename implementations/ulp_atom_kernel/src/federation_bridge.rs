use serde::{Deserialize, Serialize};

use crate::adapter::AdapterSpecialization;
use crate::sovereignty::{
    HomeExecutionResponse, PrefillReceipt, StageReceipt, TwoStageOutsourcedResponse,
};

const BRIDGE_KIND: &str = "remote_execution_admission_bridge";
const BRIDGE_VERSION: &str = "1.0";
const BRIDGE_TIMESTAMP: &str = "1970-01-01T00:00:00Z";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum BridgeDecision {
    BridgeAccept,
    BridgeHold,
    BridgeReject,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RemoteExecutionIdentity {
    pub execution_id: String,
    pub execution_kind: String,
    pub source_node_id: String,
    pub source_tag: String,
    pub home_node_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct StageReceiptSummary {
    pub stage_id: String,
    pub stage_kind: String,
    pub owner_node_id: String,
    pub output_size: usize,
    pub kv_chunk_count: usize,
    pub kv_total_bytes: usize,
    pub handoff_id: Option<String>,
}

impl From<&StageReceipt> for StageReceiptSummary {
    fn from(receipt: &StageReceipt) -> Self {
        Self {
            stage_id: receipt.stage_id.clone(),
            stage_kind: receipt.stage_kind.clone(),
            owner_node_id: receipt.owner_node_id.clone(),
            output_size: receipt.output_size,
            kv_chunk_count: receipt.kv_summary.0,
            kv_total_bytes: receipt.kv_summary.1,
            handoff_id: receipt.handoff_id.clone(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RemoteExecutionStageSummary {
    pub stage: String,
    pub tokens_produced: u32,
    pub kv_absorbed: usize,
    pub kv_migrated: bool,
    pub receipt: Option<StageReceiptSummary>,
    pub prefill_receipt: Option<StageReceiptSummary>,
    pub decode_receipt: Option<StageReceiptSummary>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct BridgeValidationSummary {
    pub receipt_verified: bool,
    pub handoff_verified: bool,
    pub output_match: bool,
    pub lineage_complete: bool,
    pub lineage_consistent: bool,
    pub specialization_attached: bool,
    pub remote_execution_acceptable: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AdapterLineageSummary {
    pub adapter_id: Option<String>,
    pub adapter_generation: Option<u64>,
    pub specialization: Option<AdapterSpecialization>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RemoteExecutionAdmissionBridge {
    pub bridge_kind: String,
    pub identity: RemoteExecutionIdentity,
    pub stage_summary: RemoteExecutionStageSummary,
    pub validation_summary: BridgeValidationSummary,
    pub adapter_lineage: AdapterLineageSummary,
    pub remote_execution_acceptable: bool,
    pub bridge_decision: BridgeDecision,
    pub recommendation: String,
    pub reason: String,
    pub fallback_used: bool,
    pub version: String,
    pub timestamp: String,
}

impl RemoteExecutionAdmissionBridge {
    pub fn from_home_response(response: &HomeExecutionResponse) -> Self {
        let stage_receipt = response.stage_receipt.as_ref();
        let receipt_verified = stage_receipt
            .map(|receipt| {
                receipt.stage_kind == "general" && receipt.output_size == response.output.len()
            })
            .unwrap_or(false);
        let lineage_complete = stage_receipt
            .map(|receipt| receipt.adapter_id.is_some() && receipt.adapter_generation.is_some())
            .unwrap_or(false);
        let specialization_attached = stage_receipt
            .map(|receipt| receipt.adapter_specialization.is_some())
            .unwrap_or(false);
        let acceptable = receipt_verified && lineage_complete && specialization_attached;
        let decision = if acceptable {
            BridgeDecision::BridgeAccept
        } else if stage_receipt.is_some() {
            BridgeDecision::BridgeHold
        } else {
            BridgeDecision::BridgeReject
        };
        let reason = if acceptable {
            "general_remote_execution_ready"
        } else if stage_receipt.is_some() {
            "general_remote_execution_missing_lineage"
        } else {
            "general_remote_execution_missing_receipt"
        }
        .to_string();
        let recommendation = match decision {
            BridgeDecision::BridgeAccept => "bridge_into_remote_intake",
            BridgeDecision::BridgeHold => "stage_for_conservative_observation",
            BridgeDecision::BridgeReject => "retain_trace_only",
        }
        .to_string();

        Self {
            bridge_kind: BRIDGE_KIND.to_string(),
            identity: RemoteExecutionIdentity {
                execution_id: stage_receipt
                    .map(|receipt| receipt.stage_id.clone())
                    .unwrap_or_else(|| format!("general:{}", response.ephemeral_node_id)),
                execution_kind: "general_remote_execution".to_string(),
                source_node_id: response.ephemeral_node_id.clone(),
                source_tag: "general".to_string(),
                home_node_id: response.home_node_id.clone(),
            },
            stage_summary: RemoteExecutionStageSummary {
                stage: "general".to_string(),
                tokens_produced: response.tokens_produced,
                kv_absorbed: response.kv_absorbed,
                kv_migrated: false,
                receipt: stage_receipt.map(StageReceiptSummary::from),
                prefill_receipt: None,
                decode_receipt: None,
            },
            validation_summary: BridgeValidationSummary {
                receipt_verified,
                handoff_verified: false,
                output_match: receipt_verified,
                lineage_complete,
                lineage_consistent: lineage_complete,
                specialization_attached,
                remote_execution_acceptable: acceptable,
            },
            adapter_lineage: AdapterLineageSummary {
                adapter_id: stage_receipt.and_then(|receipt| receipt.adapter_id.clone()),
                adapter_generation: stage_receipt.and_then(|receipt| receipt.adapter_generation),
                specialization: stage_receipt
                    .and_then(|receipt| receipt.adapter_specialization.clone()),
            },
            remote_execution_acceptable: acceptable,
            bridge_decision: decision,
            recommendation,
            reason,
            fallback_used: false,
            version: BRIDGE_VERSION.to_string(),
            timestamp: BRIDGE_TIMESTAMP.to_string(),
        }
    }

    pub fn from_two_stage_response(
        response: &TwoStageOutsourcedResponse,
        prefill_receipt: Option<&PrefillReceipt>,
    ) -> Self {
        let decode_receipt = response.decode_stage_receipt.as_ref();
        let prefill_summary =
            prefill_receipt.map(|receipt| StageReceiptSummary::from(&receipt.stage_receipt));
        let decode_summary = decode_receipt.map(StageReceiptSummary::from);
        let handoff_verified = prefill_receipt
            .map(|receipt| {
                receipt
                    .stage_receipt
                    .verify_with_handoff(
                        "prefill",
                        &receipt.stage_receipt.nonce,
                        &receipt.kv_handoff,
                    )
                    .is_ok()
            })
            .unwrap_or(false);
        let decode_verified = decode_receipt
            .map(|receipt| {
                receipt.stage_kind == "decode" && receipt.output_size == response.output.len()
            })
            .unwrap_or(false);
        let output_match = decode_receipt
            .map(|receipt| receipt.output_size == response.output.len())
            .unwrap_or(false);
        let prefill_lineage = prefill_receipt.map(|receipt| {
            (
                receipt.stage_receipt.adapter_id.clone(),
                receipt.stage_receipt.adapter_generation,
                receipt.stage_receipt.adapter_specialization.clone(),
            )
        });
        let decode_lineage = decode_receipt.map(|receipt| {
            (
                receipt.adapter_id.clone(),
                receipt.adapter_generation,
                receipt.adapter_specialization.clone(),
            )
        });
        let lineage_complete = decode_lineage
            .as_ref()
            .map(|(adapter_id, generation, _)| adapter_id.is_some() && generation.is_some())
            .unwrap_or(false)
            || prefill_lineage
                .as_ref()
                .map(|(adapter_id, generation, _)| adapter_id.is_some() && generation.is_some())
                .unwrap_or(false);
        let lineage_consistent = match (&prefill_lineage, &decode_lineage) {
            (Some(prefill), Some(decode)) => prefill == decode,
            _ => true,
        };
        let specialization_attached = decode_lineage
            .as_ref()
            .and_then(|(_, _, specialization)| specialization.clone())
            .is_some()
            || prefill_lineage
                .as_ref()
                .and_then(|(_, _, specialization)| specialization.clone())
                .is_some();
        let acceptable = handoff_verified
            && decode_verified
            && output_match
            && lineage_complete
            && lineage_consistent;
        let fallback_used = decode_lineage.is_none() && prefill_lineage.is_some();
        let decision = if !acceptable {
            BridgeDecision::BridgeReject
        } else if response.kv_migrated || fallback_used {
            BridgeDecision::BridgeHold
        } else {
            BridgeDecision::BridgeAccept
        };
        let reason = match decision {
            BridgeDecision::BridgeAccept => "two_stage_remote_execution_ready",
            BridgeDecision::BridgeHold if response.kv_migrated => {
                "two_stage_remote_execution_requires_observation"
            }
            BridgeDecision::BridgeHold => "two_stage_remote_execution_used_lineage_fallback",
            BridgeDecision::BridgeReject => "two_stage_remote_execution_not_acceptable",
        }
        .to_string();
        let recommendation = match decision {
            BridgeDecision::BridgeAccept => "bridge_into_remote_intake",
            BridgeDecision::BridgeHold => "stage_for_conservative_observation",
            BridgeDecision::BridgeReject => "retain_trace_only",
        }
        .to_string();
        let lineage = decode_lineage
            .clone()
            .or(prefill_lineage.clone())
            .unwrap_or((None, None, None));

        Self {
            bridge_kind: BRIDGE_KIND.to_string(),
            identity: RemoteExecutionIdentity {
                execution_id: decode_receipt
                    .map(|receipt| receipt.stage_id.clone())
                    .or_else(|| {
                        prefill_receipt.map(|receipt| receipt.stage_receipt.stage_id.clone())
                    })
                    .unwrap_or_else(|| format!("decode:{}", response.decode_node_id)),
                execution_kind: "two_stage_remote_execution".to_string(),
                source_node_id: response.decode_node_id.clone(),
                source_tag: "decode".to_string(),
                home_node_id: response.home_node_id.clone(),
            },
            stage_summary: RemoteExecutionStageSummary {
                stage: "two_stage".to_string(),
                tokens_produced: response.tokens_produced,
                kv_absorbed: response.kv_absorbed,
                kv_migrated: response.kv_migrated,
                receipt: None,
                prefill_receipt: prefill_summary,
                decode_receipt: decode_summary,
            },
            validation_summary: BridgeValidationSummary {
                receipt_verified: handoff_verified && decode_verified,
                handoff_verified,
                output_match,
                lineage_complete,
                lineage_consistent,
                specialization_attached,
                remote_execution_acceptable: acceptable,
            },
            adapter_lineage: AdapterLineageSummary {
                adapter_id: lineage.0,
                adapter_generation: lineage.1,
                specialization: lineage.2,
            },
            remote_execution_acceptable: acceptable,
            bridge_decision: decision,
            recommendation,
            reason,
            fallback_used,
            version: BRIDGE_VERSION.to_string(),
            timestamp: BRIDGE_TIMESTAMP.to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{BridgeDecision, RemoteExecutionAdmissionBridge};
    use crate::adapter::AdapterSpecialization;
    use crate::atom::Region;
    use crate::kv::KVChunk;
    use crate::runtime::Nonce;
    use crate::sovereignty::{
        HomeExecutionResponse, KVHandoff, KVHandoffMetadata, PrefillReceipt, StageReceipt,
        TwoStageOutsourcedResponse,
    };

    fn decode_receipt() -> StageReceipt {
        StageReceipt {
            stage_id: "atom-1:decode".to_string(),
            stage_kind: "decode".to_string(),
            owner_node_id: "home-1".to_string(),
            nonce: Nonce::new(9),
            output_size: 4,
            kv_summary: (1, 8),
            handoff_id: Some("atom-1:prefill".to_string()),
            adapter_id: Some("adapter-a".to_string()),
            adapter_generation: Some(2),
            adapter_specialization: Some(AdapterSpecialization::Stable),
        }
    }

    fn prefill_receipt() -> PrefillReceipt {
        let chunk = KVChunk {
            chunk_id: "kv-1".to_string(),
            source_region: Region("local".to_string()),
            seq_start: 0,
            seq_end: 1,
            byte_size: 8,
            payload: vec![1, 2, 3, 4],
        };
        PrefillReceipt {
            atom_id: "atom-1".to_string(),
            prefill_node_id: "prefill-1".to_string(),
            tokens_produced: 3,
            stage_receipt: StageReceipt {
                stage_id: "atom-1:prefill".to_string(),
                stage_kind: "prefill".to_string(),
                owner_node_id: "home-1".to_string(),
                nonce: Nonce::new(7),
                output_size: 3,
                kv_summary: (1, 8),
                handoff_id: Some("atom-1:prefill".to_string()),
                adapter_id: Some("adapter-a".to_string()),
                adapter_generation: Some(2),
                adapter_specialization: Some(AdapterSpecialization::Stable),
            },
            kv_handoff: KVHandoff {
                source_stage: "prefill".to_string(),
                chunks: vec![chunk],
                metadata: KVHandoffMetadata {
                    handoff_id: "atom-1:prefill".to_string(),
                    chunk_count: 1,
                    total_bytes: 8,
                    ownership_hint: Some("home-1".to_string()),
                    migration_hint: Some("from:prefill-1".to_string()),
                    adapter_generation: Some(2),
                    adapter_specialization: Some(AdapterSpecialization::Stable),
                },
            },
            prefill_output: vec![1, 2, 3],
        }
    }

    #[test]
    fn extracts_bridge_from_general_response() {
        let response = HomeExecutionResponse {
            home_node_id: "home-1".to_string(),
            output: vec![1, 2, 3, 4],
            tokens_produced: 4,
            kv_absorbed: 1,
            ephemeral_node_id: "remote-1".to_string(),
            stage_receipt: Some(StageReceipt {
                stage_id: "atom-1:general".to_string(),
                stage_kind: "general".to_string(),
                owner_node_id: "home-1".to_string(),
                nonce: Nonce::new(5),
                output_size: 4,
                kv_summary: (1, 8),
                handoff_id: None,
                adapter_id: Some("adapter-a".to_string()),
                adapter_generation: Some(2),
                adapter_specialization: Some(AdapterSpecialization::Stable),
            }),
        };

        let bridge = RemoteExecutionAdmissionBridge::from_home_response(&response);
        assert_eq!(bridge.bridge_decision, BridgeDecision::BridgeAccept);
        assert!(bridge.remote_execution_acceptable);
        assert_eq!(
            bridge.adapter_lineage.adapter_id.as_deref(),
            Some("adapter-a")
        );
        assert_eq!(
            bridge
                .stage_summary
                .receipt
                .as_ref()
                .map(|r| r.stage_kind.as_str()),
            Some("general")
        );
    }

    #[test]
    fn preserves_two_stage_lineage_and_specialization() {
        let response = TwoStageOutsourcedResponse {
            home_node_id: "home-1".to_string(),
            prefill_node_id: "prefill-1".to_string(),
            decode_node_id: "decode-1".to_string(),
            output: vec![4, 5, 6, 7],
            tokens_produced: 4,
            kv_absorbed: 1,
            kv_migrated: false,
            prefill_receipt: Some(prefill_receipt()),
            decode_stage_receipt: Some(decode_receipt()),
        };

        let bridge = RemoteExecutionAdmissionBridge::from_two_stage_response(
            &response,
            response.prefill_receipt.as_ref(),
        );
        assert_eq!(bridge.bridge_decision, BridgeDecision::BridgeAccept);
        assert_eq!(bridge.adapter_lineage.adapter_generation, Some(2));
        assert_eq!(
            bridge.adapter_lineage.specialization,
            Some(AdapterSpecialization::Stable)
        );
        assert!(bridge.validation_summary.handoff_verified);
    }

    #[test]
    fn holds_two_stage_bridge_when_kv_migrated() {
        let response = TwoStageOutsourcedResponse {
            home_node_id: "home-1".to_string(),
            prefill_node_id: "prefill-1".to_string(),
            decode_node_id: "decode-2".to_string(),
            output: vec![4, 5, 6, 7],
            tokens_produced: 4,
            kv_absorbed: 1,
            kv_migrated: true,
            prefill_receipt: Some(prefill_receipt()),
            decode_stage_receipt: Some(decode_receipt()),
        };

        let bridge = RemoteExecutionAdmissionBridge::from_two_stage_response(
            &response,
            response.prefill_receipt.as_ref(),
        );
        assert_eq!(bridge.bridge_decision, BridgeDecision::BridgeHold);
        assert!(bridge.remote_execution_acceptable);
        assert_eq!(
            bridge.reason,
            "two_stage_remote_execution_requires_observation"
        );
    }

    #[test]
    fn rejects_two_stage_bridge_when_receipt_semantics_break() {
        let mut bad_decode = decode_receipt();
        bad_decode.output_size = 9;
        let response = TwoStageOutsourcedResponse {
            home_node_id: "home-1".to_string(),
            prefill_node_id: "prefill-1".to_string(),
            decode_node_id: "decode-1".to_string(),
            output: vec![4, 5, 6, 7],
            tokens_produced: 4,
            kv_absorbed: 1,
            kv_migrated: false,
            prefill_receipt: Some(prefill_receipt()),
            decode_stage_receipt: Some(bad_decode),
        };

        let bridge = RemoteExecutionAdmissionBridge::from_two_stage_response(
            &response,
            response.prefill_receipt.as_ref(),
        );
        assert_eq!(bridge.bridge_decision, BridgeDecision::BridgeReject);
        assert!(!bridge.remote_execution_acceptable);
    }
}
