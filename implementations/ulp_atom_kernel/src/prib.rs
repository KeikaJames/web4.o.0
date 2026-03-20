//! PRIB — Privacy-preserving Remote Inference Boundary (minimal correctness path).
//!
//! This module provides the minimum blind/unblind primitives needed to establish
//! the PRIB boundary between Home Node and Ephemeral Node.
//!
//! ## What this is
//! A reversible XOR mask applied to the input payload before it leaves the
//! Home Node. The Ephemeral Node only ever sees the blinded bytes. The Home
//! Node holds the mask and applies it again on the output to recover the
//! real result.
//!
//! ## What this is NOT
//! This is not a cryptographic privacy guarantee. It is the minimum structural
//! path that proves blind → execute → unblind is closed and correct. A real
//! PRIB implementation would use homomorphic encryption or secure enclaves.
//!
//! ## Correctness property
//! For any input `x` and mask `m`:
//!   unblind(f(blind(x, m)), m) == f(x)
//!
//! This holds when `f` is byte-wise (e.g. MockBackend's uppercase transform),
//! because XOR distributes over byte-wise functions:
//!   f(x XOR m) XOR m == f(x)  when f is byte-wise and m cycles.

/// Apply a cycling XOR mask to `payload`. Calling this twice with the same
/// mask is the identity: `xor_mask(xor_mask(x, m), m) == x`.
pub fn xor_mask(payload: &[u8], mask: &[u8]) -> Vec<u8> {
    if mask.is_empty() {
        return payload.to_vec();
    }
    payload
        .iter()
        .enumerate()
        .map(|(i, b)| b ^ mask[i % mask.len()])
        .collect()
}

/// Blind an input payload before sending to an Ephemeral Node.
/// The mask must be kept on the Home Node side.
pub fn blind(input: &[u8], mask: &[u8]) -> Vec<u8> {
    xor_mask(input, mask)
}

/// Unblind an output payload received from an Ephemeral Node.
/// Must use the same mask that was used to blind the input.
pub fn unblind(output: &[u8], mask: &[u8]) -> Vec<u8> {
    xor_mask(output, mask)
}

/// Generate a deterministic mask from a seed (e.g. atom_id + home_node_id).
/// In a real PRIB this would be a cryptographically random nonce.
pub fn derive_mask(seed: &str, length: usize) -> Vec<u8> {
    if length == 0 {
        return Vec::new();
    }
    // Simple deterministic derivation: FNV-1a hash cycling
    let seed_bytes = seed.as_bytes();
    let mut mask = Vec::with_capacity(length);
    let mut h: u64 = 0xcbf29ce484222325;
    for i in 0..length {
        h ^= seed_bytes[i % seed_bytes.len()] as u64;
        h = h.wrapping_mul(0x100000001b3);
        mask.push((h & 0xFF) as u8);
    }
    mask
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn blind_unblind_is_identity() {
        let input = b"hello world";
        let mask = b"secret";
        let blinded = blind(input, mask);
        assert_ne!(blinded, input, "blinded should differ from input");
        let recovered = unblind(&blinded, mask);
        assert_eq!(recovered, input, "unblind must recover original");
    }

    #[test]
    fn empty_mask_is_passthrough() {
        let input = b"abc";
        assert_eq!(blind(input, b""), input.to_vec());
        assert_eq!(unblind(input, b""), input.to_vec());
    }

    #[test]
    fn derive_mask_is_deterministic() {
        let m1 = derive_mask("atom-1:home-1", 16);
        let m2 = derive_mask("atom-1:home-1", 16);
        assert_eq!(m1, m2);
    }

    #[test]
    fn derive_mask_differs_by_seed() {
        let m1 = derive_mask("atom-1:home-1", 16);
        let m2 = derive_mask("atom-2:home-1", 16);
        assert_ne!(m1, m2);
    }
}
