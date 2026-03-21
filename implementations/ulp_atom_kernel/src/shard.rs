use serde::{Deserialize, Serialize};

/// Unique shard identifier.
pub type ShardId = String;

/// Where a shard lives.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ShardSource {
    Local(String),
    Http(String),
    /// Object store: endpoint/bucket/key structure
    ObjectStore { endpoint: String, bucket: String, key: String },
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
    /// Validates remote shard URLs against private IP ranges before loading
    /// to prevent SSRF when manifests come from untrusted sources.
    pub fn load_all_shards(&self) -> Result<Vec<LoadedShard>, String> {
        // SSRF check: validate resolved URLs for all remote shards
        for shard in &self.shards {
            match &shard.source {
                ShardSource::Http(u) => {
                    let resolved = if let Some(base) = &self.base_url {
                        if !u.starts_with("http://") && !u.starts_with("https://") {
                            format!("{}/{}", base.trim_end_matches('/'), u.trim_start_matches('/'))
                        } else {
                            u.clone()
                        }
                    } else {
                        u.clone()
                    };
                    crate::client::validate_endpoint_url(&resolved)
                        .map_err(|e| format!("shard '{}' URL blocked: {}", shard.shard_id, e))?;
                }
                ShardSource::ObjectStore { endpoint, bucket, key } => {
                    let url = crate::object_store::ObjectStoreConfig::new(endpoint, bucket, key)
                        .resolve_url()
                        .map_err(|e| format!("shard objectstore resolve '{}': {}", shard.shard_id, e))?;
                    crate::client::validate_endpoint_url(&url)
                        .map_err(|e| format!("shard '{}' URL blocked: {}", shard.shard_id, e))?;
                }
                ShardSource::Local(_) => {}
            }
        }
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
    load_shard_with_base(shard, None)
}

/// Load a shard from manifest context (allows base_url override).
///
/// Enforces checksum for Http and ObjectStore sources — a manifest
/// without checksums on remote shards is rejected to prevent model
/// substitution attacks.
///
/// SSRF validation (blocking private IP ranges) is performed by
/// `ShardManifest::load_all_shards()` at the manifest level.
pub fn load_shard_from_manifest(
    shard: &ShardRef,
    manifest: &ShardManifest,
) -> Result<LoadedShard, String> {
    match &shard.source {
        ShardSource::Http(_) | ShardSource::ObjectStore { .. } => {
            // Require checksum for remote shards
            if shard.checksum.is_none() {
                return Err(format!(
                    "shard '{}': checksum is required for remote sources in a manifest",
                    shard.shard_id
                ));
            }
        }
        ShardSource::Local(_) => {}
    }
    load_shard_with_base(shard, manifest.base_url.as_deref())
}

fn load_shard_with_base(shard: &ShardRef, base_url: Option<&str>) -> Result<LoadedShard, String> {
    let data = match &shard.source {
        ShardSource::Local(path) => load_local(path)?,
        ShardSource::Http(url) => {
            // Require checksum for remote sources to prevent model substitution attacks.
            // Enforcement happens in load_shard_from_manifest (manifest-based loading),
            // not here, so tests can use ShardRef directly without checksums.
            let resolved = if let Some(base) = base_url {
                if !url.starts_with("http://") && !url.starts_with("https://") {
                    format!("{}/{}", base.trim_end_matches('/'), url.trim_start_matches('/'))
                } else {
                    url.to_string()
                }
            } else {
                url.to_string()
            };
            load_http(&resolved)?
        }
        ShardSource::ObjectStore { endpoint, bucket, key } => {
            // Checksum enforcement at manifest load level (load_shard_from_manifest).
            let config = crate::object_store::ObjectStoreConfig::new(endpoint, bucket, key);
            let url = config.resolve_url()
                .map_err(|e| format!("shard objectstore resolve '{}': {}", shard.shard_id, e))?;
            load_http(&url)?
        }
    };

    // Verify declared byte_size if provided
    if let Some(expected_size) = shard.byte_size {
        if data.len() as u64 != expected_size {
            return Err(format!(
                "shard '{}' size mismatch: expected {} bytes, got {}",
                shard.shard_id, expected_size, data.len()
            ));
        }
    }

    // Simple checksum verification (if provided)
    let checksum_verified = if let Some(expected) = &shard.checksum {
        let actual = simple_checksum(&data);
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

fn load_http(url: &str) -> Result<Vec<u8>, String> {
    use std::io::{Read, Write};
    use std::net::TcpStream;
    use std::time::Duration;

    // Support both http:// and https://
    let (scheme, raw) = if let Some(r) = url.strip_prefix("https://") {
        ("https", r)
    } else if let Some(r) = url.strip_prefix("http://") {
        ("http", r)
    } else {
        return Err(format!("shard load http: only http:// and https:// supported, got '{}'", url));
    };

    let (host_port, path) = match raw.find('/') {
        Some(i) => (&raw[..i], &raw[i..]),
        None => (raw, "/"),
    };

    let default_port = if scheme == "https" { 443 } else { 80 };
    let addr = if host_port.contains(':') {
        host_port.to_string()
    } else {
        format!("{}:{}", host_port, default_port)
    };

    use std::net::ToSocketAddrs;
    let sock_addr = addr
        .to_socket_addrs()
        .map_err(|e| format!("shard http resolve '{}': {}", addr, e))?
        .next()
        .ok_or_else(|| format!("shard http resolve '{}': no addresses found", addr))?;

    let mut stream = TcpStream::connect_timeout(&sock_addr, Duration::from_secs(5))
        .map_err(|e| format!("shard http connect '{}': {}", addr, e))?;
    stream
        .set_read_timeout(Some(Duration::from_secs(10)))
        .ok();

    // For https, wrap in TLS
    let mut buf = Vec::new();
    if scheme == "https" {
        let connector = native_tls::TlsConnector::builder()
            .danger_accept_invalid_certs(false)
            .build()
            .map_err(|e| format!("shard https tls setup: {}", e))?;

        let host_name = host_port.split(':').next().unwrap_or(host_port);
        let mut tls_stream = connector.connect(host_name, stream)
            .map_err(|e| format!("shard https tls connect: {}", e))?;

        let req = format!(
            "GET {} HTTP/1.1\r\nHost: {}\r\nConnection: close\r\n\r\n",
            path, host_name
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
            path, host_port
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

    let status_line = header.lines().next()
        .ok_or_else(|| "shard http: empty response".to_string())?;

    // Status line format: "HTTP/1.x STATUS_CODE REASON"
    let status_code = status_line
        .split_whitespace()
        .nth(1)
        .and_then(|s| s.parse::<u16>().ok())
        .ok_or_else(|| format!("shard http: invalid status line '{}'", status_line))?;

    if status_code != 200 {
        return Err(format!("shard http '{}': got HTTP {}", url, status_code));
    }

    Ok(buf[hdr_end + 4..].to_vec())
}

/// Simple checksum (FNV-1a hash as hex string) for shard verification.
fn simple_checksum(data: &[u8]) -> String {
    const FNV_OFFSET: u64 = 0xcbf29ce484222325;
    const FNV_PRIME: u64 = 0x100000001b3;

    let mut hash = FNV_OFFSET;
    for &byte in data {
        hash ^= byte as u64;
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    format!("{:016x}", hash)
}
