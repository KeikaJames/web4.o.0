use serde::{de::DeserializeOwned, Serialize};

/// Encode any protocol type to CBOR bytes.
pub fn encode_cbor<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    let mut buf = Vec::new();
    ciborium::into_writer(value, &mut buf).map_err(|e| format!("cbor encode: {e}"))?;
    Ok(buf)
}

/// Decode any protocol type from CBOR bytes.
pub fn decode_cbor<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, String> {
    ciborium::from_reader(bytes).map_err(|e| format!("cbor decode: {e}"))
}

/// Encode any protocol type to JSON bytes (for debug / interop).
pub fn encode_json<T: Serialize>(value: &T) -> Result<Vec<u8>, String> {
    serde_json::to_vec(value).map_err(|e| format!("json encode: {e}"))
}

/// Decode any protocol type from JSON bytes.
pub fn decode_json<T: DeserializeOwned>(bytes: &[u8]) -> Result<T, String> {
    serde_json::from_slice(bytes).map_err(|e| format!("json decode: {e}"))
}
