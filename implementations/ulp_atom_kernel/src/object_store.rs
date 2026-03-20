/// Minimal object store backend for shard loading.
///
/// Provides S3-style bucket/key/endpoint resolution without requiring
/// a full SDK dependency.

use serde::{Deserialize, Serialize};

/// Object store configuration for shard loading.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObjectStoreConfig {
    pub endpoint: String,
    pub bucket: String,
    pub key: String,
    #[serde(default)]
    pub region: Option<String>,
    #[serde(default)]
    pub access_key: Option<String>,
    #[serde(default)]
    pub secret_key: Option<String>,
}

impl ObjectStoreConfig {
    pub fn new(endpoint: impl Into<String>, bucket: impl Into<String>, key: impl Into<String>) -> Self {
        Self {
            endpoint: endpoint.into(),
            bucket: bucket.into(),
            key: key.into(),
            region: None,
            access_key: None,
            secret_key: None,
        }
    }

    /// Validate configuration fields.
    pub fn validate(&self) -> Result<(), String> {
        if self.endpoint.is_empty() {
            return Err("endpoint required".into());
        }
        if self.bucket.is_empty() {
            return Err("bucket required".into());
        }
        if self.key.is_empty() {
            return Err("key required".into());
        }
        Ok(())
    }

    /// Resolve to HTTP/HTTPS URL for fetching.
    /// Format: {endpoint}/{bucket}/{key}
    pub fn resolve_url(&self) -> Result<String, String> {
        self.validate()?;
        let endpoint = self.endpoint.trim_end_matches('/');
        let key = self.key.trim_start_matches('/');
        Ok(format!("{}/{}/{}", endpoint, self.bucket, key))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn config_validates_required_fields() {
        let config = ObjectStoreConfig::new("", "bucket", "key");
        assert!(config.validate().is_err());

        let config = ObjectStoreConfig::new("http://s3.example.com", "", "key");
        assert!(config.validate().is_err());

        let config = ObjectStoreConfig::new("http://s3.example.com", "bucket", "");
        assert!(config.validate().is_err());

        let config = ObjectStoreConfig::new("http://s3.example.com", "bucket", "key");
        assert!(config.validate().is_ok());
    }

    #[test]
    fn resolve_url_constructs_proper_path() {
        let config = ObjectStoreConfig::new("http://s3.example.com", "my-bucket", "path/to/shard.bin");
        let url = config.resolve_url().unwrap();
        assert_eq!(url, "http://s3.example.com/my-bucket/path/to/shard.bin");
    }

    #[test]
    fn resolve_url_handles_trailing_slash() {
        let config = ObjectStoreConfig::new("http://s3.example.com/", "bucket", "key.bin");
        let url = config.resolve_url().unwrap();
        assert_eq!(url, "http://s3.example.com/bucket/key.bin");
    }

    #[test]
    fn resolve_url_handles_leading_slash_in_key() {
        let config = ObjectStoreConfig::new("http://s3.example.com", "bucket", "/models/shard.bin");
        let url = config.resolve_url().unwrap();
        assert_eq!(url, "http://s3.example.com/bucket/models/shard.bin");
    }

    #[test]
    fn resolve_url_supports_https() {
        let config = ObjectStoreConfig::new("https://s3.amazonaws.com", "my-bucket", "data.bin");
        let url = config.resolve_url().unwrap();
        assert_eq!(url, "https://s3.amazonaws.com/my-bucket/data.bin");
    }
}
