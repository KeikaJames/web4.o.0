use crate::kernel::{AtomRequest, AtomResponse};
use std::time::Duration;

/// Validate that a URL is safe to connect to.
///
/// Rejects:
/// - Non-http(s) schemes
/// - RFC 1918 private ranges (10.x, 172.16-31.x, 192.168.x)
/// - Loopback (127.x / ::1)
/// - Link-local (169.254.x / fe80::)
/// - AWS/GCP/Azure metadata service addresses
pub fn validate_endpoint_url(url: &str) -> Result<(), String> {
    if !url.starts_with("http://") && !url.starts_with("https://") {
        return Err(format!(
            "endpoint URL must use http:// or https://, got: '{}'",
            url
        ));
    }

    let without_scheme = url
        .strip_prefix("https://")
        .or_else(|| url.strip_prefix("http://"))
        .unwrap_or(url);

    let host_port = match without_scheme.find('/') {
        Some(i) => &without_scheme[..i],
        None => without_scheme,
    };
    let host = if host_port.starts_with('[') {
        match host_port.find(']') {
            Some(i) => &host_port[1..i],
            None => host_port,
        }
    } else if let Some(colon) = host_port.rfind(':') {
        &host_port[..colon]
    } else {
        host_port
    };

    const BLOCKED_HOSTS: &[&str] = &[
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.goog",
    ];
    if BLOCKED_HOSTS.contains(&host) {
        return Err(format!("endpoint URL targets a blocked host: '{}'", host));
    }

    if let Ok(ip) = host.parse::<std::net::IpAddr>() {
        if is_blocked_ip(&ip) {
            return Err(format!(
                "endpoint URL targets a blocked IP range: '{}'",
                ip
            ));
        }
    }

    Ok(())
}

fn is_blocked_ip(ip: &std::net::IpAddr) -> bool {
    use std::net::IpAddr;
    match ip {
        IpAddr::V4(v4) => {
            let o = v4.octets();
            v4.is_loopback()
                || v4.is_link_local()
                || o[0] == 10
                || (o[0] == 172 && o[1] >= 16 && o[1] <= 31)
                || (o[0] == 192 && o[1] == 168)
                || v4.is_unspecified()
        }
        IpAddr::V6(v6) => {
            v6.is_loopback()
                || (v6.segments()[0] & 0xffc0 == 0xfe80)
                || v6.is_unspecified()
        }
    }
}

pub struct RemoteClient {
    client: reqwest::Client,
}

impl RemoteClient {
    pub fn new() -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .expect("failed to build http client"),
        }
    }

    pub async fn dispatch(&self, url: &str, request: AtomRequest) -> Result<AtomResponse, String> {
        let response = self.client
            .post(url)
            .json(&request)
            .send()
            .await
            .map_err(|e| format!("send: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(format!("server error {status}: {body}"));
        }

        response
            .json::<AtomResponse>()
            .await
            .map_err(|e| format!("parse response: {e}"))
    }
}

impl Default for RemoteClient {
    fn default() -> Self {
        Self::new()
    }
}

pub async fn dispatch_remote(url: &str, request: AtomRequest) -> Result<AtomResponse, String> {
    RemoteClient::new().dispatch(url, request).await
}
