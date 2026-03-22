use crate::kernel::{AtomRequest, AtomResponse};
use crate::runtime::{SlotClaim, SlotClaimResponse};
use crate::sovereignty::{BlindedAtomRequest, BlindedAtomResponse, RemoteExecutionError};
use std::net::ToSocketAddrs;
use std::time::Duration;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum EndpointTrust {
    Enforce,
    Trusted,
}

/// Validate that a URL is safe to connect to.
///
/// Rejects:
/// - Non-http(s) schemes
/// - RFC 1918 private ranges (10.x, 172.16-31.x, 192.168.x)
/// - Loopback (127.x / ::1)
/// - Link-local (169.254.x / fe80::)
/// - AWS/GCP/Azure metadata service addresses
pub fn validate_endpoint_url(url: &str) -> Result<(), String> {
    let parsed = reqwest::Url::parse(url)
        .map_err(|e| format!("endpoint URL parse failed for '{}': {}", url, e))?;

    if parsed.scheme() != "http" && parsed.scheme() != "https" {
        return Err(format!(
            "endpoint URL must use http:// or https://, got: '{}'",
            url
        ));
    }

    let host = parsed
        .host_str()
        .ok_or_else(|| format!("endpoint URL is missing a host: '{}'", url))?
        .trim_end_matches('.')
        .to_ascii_lowercase();

    const BLOCKED_HOSTS: &[&str] = &[
        "localhost",
        "169.254.169.254",
        "metadata.google.internal",
        "metadata.goog",
    ];
    if BLOCKED_HOSTS.contains(&host.as_str()) {
        return Err(format!("endpoint URL targets a blocked host: '{}'", host));
    }

    let port = parsed
        .port_or_known_default()
        .ok_or_else(|| format!("endpoint URL is missing a usable port: '{}'", url))?;
    let resolved: Vec<_> = (host.as_str(), port)
        .to_socket_addrs()
        .map_err(|e| format!("endpoint URL host resolution failed for '{}': {}", host, e))?
        .collect();
    if resolved.is_empty() {
        return Err(format!(
            "endpoint URL host resolution returned no addresses for '{}'",
            host
        ));
    }

    for addr in resolved {
        if is_blocked_ip(&addr.ip()) {
            return Err(format!(
                "endpoint URL targets a blocked IP range: '{}'",
                addr.ip()
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
            v6.is_loopback() || (v6.segments()[0] & 0xffc0 == 0xfe80) || v6.is_unspecified()
        }
    }
}

pub struct RemoteClient {
    pub(crate) client: reqwest::Client,
    endpoint_trust: EndpointTrust,
}

impl RemoteClient {
    pub fn new() -> Self {
        Self::with_trust(EndpointTrust::Enforce)
    }

    /// Explicitly allow private / loopback endpoints.
    ///
    /// This is intended only for tests and trusted local development flows.
    pub fn new_trusted() -> Self {
        Self::with_trust(EndpointTrust::Trusted)
    }

    fn with_trust(endpoint_trust: EndpointTrust) -> Self {
        Self {
            client: reqwest::Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .expect("failed to build http client"),
            endpoint_trust,
        }
    }

    fn validate_if_required(&self, url: &str) -> Result<(), String> {
        if self.endpoint_trust == EndpointTrust::Enforce {
            validate_endpoint_url(url)?;
        }
        Ok(())
    }

    pub async fn dispatch(&self, url: &str, request: AtomRequest) -> Result<AtomResponse, String> {
        self.validate_if_required(url)?;

        let response = self
            .client
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

    pub async fn claim_slot(
        &self,
        url: &str,
        claim: &SlotClaim,
    ) -> Result<SlotClaimResponse, String> {
        self.validate_if_required(url)?;

        let response = self
            .client
            .post(url)
            .timeout(Duration::from_millis(claim.timeout_ms.max(1)))
            .json(claim)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    format!("slot claim timeout: {e}")
                } else {
                    format!("slot claim send: {e}")
                }
            })?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(format!("slot claim server error {status}: {body}"));
        }

        response
            .json::<SlotClaimResponse>()
            .await
            .map_err(|e| format!("slot claim parse response: {e}"))
    }

    pub async fn execute_blinded(
        &self,
        url: &str,
        request: &BlindedAtomRequest,
        timeout_ms: u64,
    ) -> Result<BlindedAtomResponse, String> {
        self.validate_if_required(url)?;

        let response = self
            .client
            .post(url)
            .timeout(Duration::from_millis(timeout_ms.max(1)))
            .json(request)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    format!("blinded execute timeout: {e}")
                } else {
                    format!("blinded execute send: {e}")
                }
            })?;

        if !response.status().is_success() {
            return Err(parse_remote_execute_error(response).await);
        }

        response
            .json::<BlindedAtomResponse>()
            .await
            .map_err(|e| format!("blinded execute parse response: {e}"))
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

pub async fn dispatch_remote_trusted(
    url: &str,
    request: AtomRequest,
) -> Result<AtomResponse, String> {
    RemoteClient::new_trusted().dispatch(url, request).await
}

async fn parse_remote_execute_error(response: reqwest::Response) -> String {
    let status = response.status();
    let body = response.text().await.unwrap_or_default();
    if let Ok(err) = serde_json::from_str::<RemoteExecutionError>(&body) {
        format!(
            "blinded execute server error {status}: {} ({})",
            err.message, err.code
        )
    } else {
        format!("blinded execute server error {status}: {body}")
    }
}
