use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

/// Unique shard identifier.
pub type ShardId = String;

/// Where a shard lives.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ShardSource {
    Local(String),
    Http(String),
    /// Object store: endpoint/bucket/key structure
    ObjectStore {
        endpoint: String,
        bucket: String,
        key: String,
    },
}

/// Reference to a shard — enough to locate and load it.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShardRef {
    pub shard_id: ShardId,
    pub source: ShardSource,
    #[serde(default)]
    pub byte_size: Option<u64>,
    #[serde(default)]
    pub checksum: Option<String>,
}

/// Shard distribution manifest — describes how to load all shards for a model.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ShardManifest {
    pub model_id: String,
    pub shards: Vec<ShardRef>,
    #[serde(default)]
    pub base_url: Option<String>,
    #[serde(default)]
    pub version: Option<String>,
}

impl ShardManifest {
    pub fn from_json(json: &str) -> Result<Self, serde_json::Error> {
        serde_json::from_str(json)
    }

    /// Resolve a shard by id from this manifest.
    pub fn get_shard(&self, shard_id: &str) -> Option<&ShardRef> {
        self.shards.iter().find(|s| s.shard_id == shard_id)
    }

    /// Load all shards from the manifest.
    ///
    /// Validates and loads remote shard URLs against concrete resolved socket
    /// addresses to prevent SSRF when manifests come from untrusted sources.
    pub fn load_all_shards(&self) -> Result<Vec<LoadedShard>, String> {
        self.shards
            .iter()
            .map(|shard| load_shard_from_manifest(shard, self))
            .collect()
    }
}

/// A shard that has been loaded into memory.
#[derive(Debug, Clone)]
pub struct LoadedShard {
    pub shard_id: ShardId,
    pub data: Vec<u8>,
    pub byte_size: u64,
    pub checksum_verified: bool,
}

/// Load a shard from its source. Supports local filesystem and plain HTTP.
pub fn load_shard(shard: &ShardRef) -> Result<LoadedShard, String> {
    load_shard_with_base(shard, None, false)
}

/// Explicitly load a shard without endpoint trust checks.
///
/// This is intended only for tests and trusted local development flows.
pub fn load_shard_trusted(shard: &ShardRef) -> Result<LoadedShard, String> {
    load_shard_with_base(shard, None, true)
}

/// Load a shard from manifest context (allows base_url override).
///
/// Enforces checksum for Http and ObjectStore sources — a manifest
/// without checksums on remote shards is rejected to prevent model
/// substitution attacks.
///
/// SSRF validation and socket pinning (blocking private / loopback
/// resolution) are enforced on every call.
pub fn load_shard_from_manifest(
    shard: &ShardRef,
    manifest: &ShardManifest,
) -> Result<LoadedShard, String> {
    load_shard_with_base(shard, manifest.base_url.as_deref(), false)
}

/// Explicitly load a manifest shard without endpoint trust checks.
///
/// This keeps checksum enforcement but allows trusted local loopback endpoints.
pub fn load_shard_from_manifest_trusted(
    shard: &ShardRef,
    manifest: &ShardManifest,
) -> Result<LoadedShard, String> {
    load_shard_with_base(shard, manifest.base_url.as_deref(), true)
}

fn load_shard_with_base(
    shard: &ShardRef,
    base_url: Option<&str>,
    trusted: bool,
) -> Result<LoadedShard, String> {
    require_remote_checksum(shard)?;

    let data = match &shard.source {
        ShardSource::Local(path) => load_local(path)?,
        ShardSource::Http(url) => {
            let resolved = resolve_http_url(url, base_url);
            let endpoint = resolve_remote_endpoint(&resolved, trusted)
                .map_err(|e| format!("shard '{}' URL blocked: {}", shard.shard_id, e))?;
            load_http(&endpoint)?
        }
        ShardSource::ObjectStore {
            endpoint,
            bucket,
            key,
        } => {
            let config = crate::object_store::ObjectStoreConfig::new(endpoint, bucket, key);
            let url = config
                .resolve_url()
                .map_err(|e| format!("shard objectstore resolve '{}': {}", shard.shard_id, e))?;
            let endpoint = resolve_remote_endpoint(&url, trusted)
                .map_err(|e| format!("shard '{}' URL blocked: {}", shard.shard_id, e))?;
            load_http(&endpoint)?
        }
    };

    // Verify declared byte_size if provided
    if let Some(expected_size) = shard.byte_size {
        if data.len() as u64 != expected_size {
            return Err(format!(
                "shard '{}' size mismatch: expected {} bytes, got {}",
                shard.shard_id,
                expected_size,
                data.len()
            ));
        }
    }

    // Cryptographic checksum verification (if provided)
    let checksum_verified = if let Some(expected) = &shard.checksum {
        let actual = sha256_checksum(&data);
        if actual != *expected {
            return Err(format!(
                "shard '{}' checksum mismatch: expected {}, got {}",
                shard.shard_id, expected, actual
            ));
        }
        true
    } else {
        false
    };

    Ok(LoadedShard {
        shard_id: shard.shard_id.clone(),
        byte_size: data.len() as u64,
        data,
        checksum_verified,
    })
}

fn load_local(path: &str) -> Result<Vec<u8>, String> {
    std::fs::read(path).map_err(|e| format!("shard load local '{}': {}", path, e))
}

fn load_http(endpoint: &crate::client::ResolvedEndpoint) -> Result<Vec<u8>, String> {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    let mut last_connect_error = None;
    let mut stream = None;
    for sock_addr in endpoint.socket_addrs() {
        match TcpStream::connect_timeout(sock_addr, Duration::from_secs(5)) {
            Ok(connected) => {
                stream = Some(connected);
                break;
            }
            Err(err) => last_connect_error = Some(format!("{}: {}", sock_addr, err)),
        }
    }
    let mut stream = stream.ok_or_else(|| {
        format!(
            "shard http connect '{}': {}",
            endpoint.url(),
            last_connect_error.unwrap_or_else(|| "no reachable addresses".to_string())
        )
    })?;
    stream.set_read_timeout(Some(Duration::from_secs(10))).ok();

    // For https, wrap in TLS
    let mut buf = Vec::new();
    if endpoint.url().scheme() == "https" {
        let connector = native_tls::TlsConnector::builder()
            .danger_accept_invalid_certs(false)
            .build()
            .map_err(|e| format!("shard https tls setup: {}", e))?;

        let mut tls_stream = connector
            .connect(endpoint.host(), stream)
            .map_err(|e| format!("shard https tls connect: {}", e))?;

        let req = format!(
            "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
            endpoint.request_target(),
            endpoint.authority()
        );
        tls_stream
            .write_all(req.as_bytes())
            .map_err(|e| format!("shard https write: {}", e))?;

        tls_stream
            .read_to_end(&mut buf)
            .map_err(|e| format!("shard https read: {}", e))?;
    } else {
        let req = format!(
            "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
            endpoint.request_target(),
            endpoint.authority()
        );
        stream
            .write_all(req.as_bytes())
            .map_err(|e| format!("shard http write: {}", e))?;

        stream
            .read_to_end(&mut buf)
            .map_err(|e| format!("shard http read: {}", e))?;
    }

    let hdr_end = buf
        .windows(4)
        .position(|w| w == b"\r\n\r\n")
        .ok_or_else(|| "shard http: malformed response (no header end)".to_string())?;

    // Parse status line
    let header = std::str::from_utf8(&buf[..hdr_end])
        .map_err(|_| "shard http: invalid UTF-8 in response header".to_string())?;

    let status_line = header
        .lines()
        .next()
        .ok_or_else(|| "shard http: empty response".to_string())?;

    // Status line format: "HTTP/1.x STATUS_CODE REASON"
    let status_code = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse::<u16>().ok())
        .ok_or_else(|| format!("shard http: invalid status line '{}'", status_line))?;

    if status_code != 200 {
        return Err(format!(
            "shard http '{}': got HTTP {}",
            endpoint.url(),
            status_code
        ));
    }

    Ok(buf[hdr_end + 4..].to_vec())
}

/// SHA-256 checksum for shard verification.
fn sha256_checksum(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}

fn resolve_http_url(url: &str, base_url: Option<&str>) -> String {
    if let Some(base) = base_url {
        if !url.starts_with("http://") && !url.starts_with("https://") {
            return format!(
                "{}/{}",
                base.trim_end_matches('/'),
                url.trim_start_matches('/')
            );
        }
    }
    url.to_string()
}

fn require_remote_checksum(shard: &ShardRef) -> Result<(), String> {
    match &shard.source {
        ShardSource::Http(_) | ShardSource::ObjectStore { .. } => {
            if shard.checksum.is_none() {
                return Err(format!(
                    "shard '{}': checksum is required for remote sources",
                    shard.shard_id
                ));
            }
        }
        ShardSource::Local(_) => {}
    }
    Ok(())
}

fn resolve_remote_endpoint(
    url: &str,
    trusted: bool,
) -> Result<crate::client::ResolvedEndpoint, String> {
    if trusted {
        crate::client::resolve_endpoint_url_trusted(url)
    } else {
        crate::client::resolve_endpoint_url(url)
    }
}

#[cfg(test)]
mod tests {
    use super::{load_shard, sha256_checksum, ShardRef, ShardSource};

    #[test]
    fn local_shard_checksum_uses_sha256() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("model.bin");
        std::fs::write(&path, b"abc").unwrap();

        let shard = ShardRef {
            shard_id: "local".to_string(),
            source: ShardSource::Local(path.to_string_lossy().into_owned()),
            byte_size: Some(3),
            checksum: Some(sha256_checksum(b"abc")),
        };

        let loaded = load_shard(&shard).unwrap();
        assert!(loaded.checksum_verified);
    }

    #[test]
    fn local_shard_rejects_legacy_fnv_checksum_values() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("model.bin");
        std::fs::write(&path, b"abc").unwrap();

        let shard = ShardRef {
            shard_id: "local".to_string(),
            source: ShardSource::Local(path.to_string_lossy().into_owned()),
            byte_size: Some(3),
            checksum: Some("e71fa2190541574b".to_string()),
        };

        let err = load_shard(&shard).unwrap_err();
        assert!(err.contains("checksum mismatch"));
    }
}
