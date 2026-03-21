//! Minimum node runtime: slot lifecycle, discovery pool, nonce, timeout, retry.
//!
//! This module adds the "who takes a job, when does it expire, how do we retry"
//! layer on top of the existing sovereignty execution boundary.
//!
//! ## Objects
//! - `Nonce`: single-use request token for slot claim/response matching
//! - `RelativeTimeout`: deadline expressed in milliseconds from "now"
//! - `SlotOffer`: ephemeral node advertising it can accept a job
//! - `SlotClaim`: home node claiming a slot (carries nonce)
//! - `SlotClaimResponse`: ephemeral node accepting (echoes nonce) or rejecting
//! - `DiscoveryPool`: local registry of known ephemeral nodes
//!
//! ## Invariants
//! - Nonce must be echoed unchanged; mismatch → rejection
//! - If a claim times out or is rejected, the pool advances to next candidate

use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::atom::{AtomKind, Region};

// ---------------------------------------------------------------------------
// Primitives
// ---------------------------------------------------------------------------

/// Single-use token that binds a SlotClaim to its response.
/// Mismatch → reject.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Nonce(pub u64);

impl Nonce {
    /// Generate from a simple counter seed. In production this would be random.
    pub fn new(seed: u64) -> Self {
        Nonce(seed)
    }

    pub fn matches(&self, other: &Nonce) -> bool {
        self.0 == other.0
    }
}

/// Deadline expressed as milliseconds from "now" at construction time.
#[derive(Debug, Clone)]
pub struct RelativeTimeout {
    deadline: Instant,
}

impl RelativeTimeout {
    pub fn from_millis(ms: u64) -> Self {
        RelativeTimeout {
            deadline: Instant::now() + Duration::from_millis(ms),
        }
    }

    pub fn is_expired(&self) -> bool {
        Instant::now() >= self.deadline
    }

    /// Remaining time, or zero if already expired.
    pub fn remaining_ms(&self) -> u64 {
        let now = Instant::now();
        if now >= self.deadline {
            0
        } else {
            (self.deadline - now).as_millis() as u64
        }
    }
}

// ---------------------------------------------------------------------------
// Slot lifecycle
// ---------------------------------------------------------------------------

/// Ephemeral node advertising it can accept execution of `supported_kinds`
/// within `region` before `expires_in_ms` milliseconds.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SlotOffer {
    pub node_id: String,
    pub region: Region,
    pub supported_kinds: Vec<AtomKind>,
    pub capacity_hint: u32, // rough concurrent-job capacity
    pub expires_in_ms: u64,
}

/// Home node claiming a slot on a specific ephemeral node.
/// The `nonce` must be echoed back in the response unchanged.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SlotClaim {
    pub home_node_id: String,
    pub target_node_id: String,
    pub nonce: Nonce,
    pub requested_kind: AtomKind,
    pub timeout_ms: u64,
}

/// Ephemeral node's response to a slot claim.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SlotClaimResponse {
    /// Slot accepted. `nonce` must match the claim's nonce.
    Accepted { node_id: String, nonce: Nonce },
    /// Slot rejected (busy, unsupported kind, etc.)
    Rejected { node_id: String, reason: String },
}

impl SlotClaimResponse {
    /// Verify that the response nonce matches the claim nonce.
    pub fn verify_nonce(&self, claim: &SlotClaim) -> Result<(), String> {
        match self {
            SlotClaimResponse::Accepted { nonce, .. } => {
                if nonce.matches(&claim.nonce) {
                    Ok(())
                } else {
                    Err(format!(
                        "nonce mismatch: expected {}, got {}",
                        claim.nonce.0, nonce.0
                    ))
                }
            }
            SlotClaimResponse::Rejected { reason, .. } => {
                Err(format!("slot rejected: {}", reason))
            }
        }
    }

    pub fn is_accepted(&self) -> bool {
        matches!(self, SlotClaimResponse::Accepted { .. })
    }

    pub fn node_id(&self) -> &str {
        match self {
            SlotClaimResponse::Accepted { node_id, .. } => node_id,
            SlotClaimResponse::Rejected { node_id, .. } => node_id,
        }
    }
}

// ---------------------------------------------------------------------------
// Discovery pool
// ---------------------------------------------------------------------------

/// Local registry of known ephemeral nodes.
/// No network discovery — nodes are registered manually.
#[derive(Debug, Clone)]
pub struct DiscoveryPool {
    offers: Vec<SlotOffer>,
}

impl DiscoveryPool {
    pub fn new() -> Self {
        DiscoveryPool { offers: Vec::new() }
    }

    /// Register an ephemeral node's slot offer.
    pub fn register(&mut self, offer: SlotOffer) {
        // Replace existing offer from same node
        if let Some(pos) = self.offers.iter().position(|o| o.node_id == offer.node_id) {
            self.offers[pos] = offer;
        } else {
            self.offers.push(offer);
        }
    }

    /// Remove a node from the pool.
    pub fn deregister(&mut self, node_id: &str) {
        self.offers.retain(|o| o.node_id != node_id);
    }

    pub fn len(&self) -> usize {
        self.offers.len()
    }

    pub fn is_empty(&self) -> bool {
        self.offers.is_empty()
    }

    /// Return ordered candidate list for `kind`, filtering by region if given.
    pub fn candidates_for(
        &self,
        kind: &AtomKind,
        region: Option<&Region>,
    ) -> Vec<&SlotOffer> {
        self.offers
            .iter()
            .filter(|o| {
                o.supported_kinds.contains(kind)
                    && region.map_or(true, |r| o.region.0 == r.0)
            })
            .collect()
    }
}

impl Default for DiscoveryPool {
    fn default() -> Self {
        DiscoveryPool::new()
    }
}

// ---------------------------------------------------------------------------
// Slot manager — claim loop with timeout and retry
// ---------------------------------------------------------------------------

/// Result of attempting to claim a slot from the pool.
#[derive(Debug)]
pub struct ClaimResult {
    pub node_id: String,
    pub nonce: Nonce,
    /// How many candidates were tried before success.
    pub attempts: usize,
}

/// Try to claim a slot for `kind` from the pool, using a nonce and timeout.
/// On timeout or nonce mismatch, advance to the next candidate.
///
/// `simulate_response` is a closure that simulates what an ephemeral node
/// returns when given a claim. In production this would be a network call.
pub fn claim_slot<F>(
    pool: &DiscoveryPool,
    home_node_id: &str,
    kind: &AtomKind,
    region: Option<&Region>,
    nonce_seed: u64,
    timeout_ms: u64,
    mut simulate_response: F,
) -> Result<ClaimResult, String>
where
    F: FnMut(&SlotClaim) -> SlotClaimResponse,
{
    let candidates = pool.candidates_for(kind, region);
    if candidates.is_empty() {
        return Err("discovery pool: no candidates available".to_string());
    }

    let mut last_err = String::new();
    for (attempt, offer) in candidates.iter().enumerate() {
        let nonce = Nonce::new(nonce_seed + attempt as u64);
        let claim = SlotClaim {
            home_node_id: home_node_id.to_string(),
            target_node_id: offer.node_id.clone(),
            nonce: nonce.clone(),
            requested_kind: kind.clone(),
            timeout_ms,
        };

        let timeout = RelativeTimeout::from_millis(timeout_ms);

        // Check timeout before sending (in tests this is instant)
        if timeout.is_expired() {
            last_err = format!("timeout before claim to '{}'", offer.node_id);
            continue;
        }

        let response = simulate_response(&claim);

        match response.verify_nonce(&claim) {
            Ok(()) => {
                return Ok(ClaimResult {
                    node_id: offer.node_id.clone(),
                    nonce,
                    attempts: attempt + 1,
                });
            }
            Err(e) => {
                last_err = format!("candidate '{}': {}", offer.node_id, e);
                // continue to next candidate
            }
        }
    }

    Err(format!("all candidates failed: {}", last_err))
}
