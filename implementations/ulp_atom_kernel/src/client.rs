use std::net::{IpAddr, SocketAddr, ToSocketAddrs};
use std::time::Duration;

use crate::kernel::{AtomRequest, AtomResponse};
use crate::runtime::{SlotClaim, SlotClaimResponse};
use crate::sovereignty::{BlindedAtomRequest, BlindedAtomResponse, RemoteExecutionError};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum EndpointTrust {
    Enforce,
    Trusted,
}

#[derive(Clone, Debug)]
pub struct ResolvedEndpoint {
    url: reqwest::Url,
    host: String,
    authority: String,
    socket_addrs: Vec<SocketAddr>,
}

impl ResolvedEndpoint {
    fn parse(url: &str, endpoint_trust: EndpointTrust) -> Result<Self, String> {
        let mut parsed = reqwest::Url::parse(url)
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
            .trim_start_matches('[')
            .trim_end_matches(']')
            .trim_end_matches('.')
            .to_ascii_lowercase();

        const BLOCKED_HOSTS: &[&str] = &[
            "localhost",
            "169.254.169.254",
            "metadata.google.internal",
            "metadata.goog",
        ];
        if endpoint_trust == EndpointTrust::Enforce && BLOCKED_HOSTS.contains(&host.as_str()) {
            return Err(format!("endpoint URL targets a blocked host: '{}'", host));
        }

        if host.parse::<IpAddr>().is_err() {
            parsed
                .set_host(Some(&host))
                .map_err(|_| format!("endpoint URL contains an invalid host: '{}'", url))?;
        }

        let port = parsed
            .port_or_known_default()
            .ok_or_else(|| format!("endpoint URL is missing a usable port: '{}'", url))?;
        let socket_addrs: Vec<_> = (host.as_str(), port)
            .to_socket_addrs()
            .map_err(|e| format!("endpoint URL host resolution failed for '{}': {}", host, e))?
            .collect();
        if socket_addrs.is_empty() {
            return Err(format!(
                "endpoint URL host resolution returned no addresses for '{}'",
                host
            ));
        }

        if endpoint_trust == EndpointTrust::Enforce {
            for addr in &socket_addrs {
                if is_blocked_ip(&addr.ip()) {
                    return Err(format!(
                        "endpoint URL targets a blocked IP range: '{}'",
                        addr.ip()
                    ));
                }
            }
        }

        Ok(Self {
            authority: format_authority(&host, parsed.port()),
            url: parsed,
            host,
            socket_addrs,
        })
    }

    pub fn url(&self) -> &reqwest::Url {
        &self.url
    }

    pub fn authority(&self) -> &str {
        &self.authority
    }

    pub fn host(&self) -> &str {
        &self.host
    }

    pub fn socket_addrs(&self) -> &[SocketAddr] {
        &self.socket_addrs
    }

    pub fn request_target(&self) -> String {
        match self.url.query() {
            Some(query) => format!("{}?{}", self.url.path(), query),
            None => self.url.path().to_string(),
        }
    }

    fn build_http_client(&self, timeout: Duration) -> Result<reqwest::Client, String> {
        let builder = reqwest::Client::builder().no_proxy().timeout(timeout);
        let builder = if self.host.parse::<IpAddr>().is_err() {
            builder.resolve_to_addrs(self.host.as_str(), &self.socket_addrs)
        } else {
            builder
        };

        builder
            .build()
            .map_err(|e| format!("failed to build http client: {e}"))
    }
}

/// Validate that a URL is safe to connect to.
///
/// Rejects:
/// - Non-http(s) schemes
/// - RFC 1918 private ranges (10.x, 172.16-31.x, 192.168.x)
/// - Loopback (127.x / ::1)
/// - Link-local (169.254.x / fe80::)
/// - IPv6 unique-local ranges (fc00::/7)
/// - AWS/GCP/Azure metadata service addresses
pub fn validate_endpoint_url(url: &str) -> Result<(), String> {
    resolve_endpoint_url(url).map(|_| ())
}

pub fn resolve_endpoint_url(url: &str) -> Result<ResolvedEndpoint, String> {
    ResolvedEndpoint::parse(url, EndpointTrust::Enforce)
}

pub fn resolve_endpoint_url_trusted(url: &str) -> Result<ResolvedEndpoint, String> {
    ResolvedEndpoint::parse(url, EndpointTrust::Trusted)
}

fn format_authority(host: &str, explicit_port: Option<u16>) -> String {
    let rendered_host = if host.contains(':') {
        format!("[{}]", host)
    } else {
        host.to_string()
    };
    match explicit_port {
        Some(port) => format!("{rendered_host}:{port}"),
        None => rendered_host,
    }
}

fn is_blocked_ip(ip: &IpAddr) -> bool {
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
            if let Some(mapped_v4) = v6.to_ipv4_mapped() {
                return is_blocked_ip(&IpAddr::V4(mapped_v4));
            }

            let first_segment = v6.segments()[0];
            v6.is_loopback()
                || (first_segment & 0xffc0 == 0xfe80)
                || (first_segment & 0xfe00 == 0xfc00)
                || v6.is_unspecified()
        }
    }
}

pub struct RemoteClient {
    endpoint_trust: EndpointTrust,
    default_timeout: Duration,
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
            endpoint_trust,
            default_timeout: Duration::from_secs(30),
        }
    }

    fn resolve_endpoint(&self, url: &str) -> Result<ResolvedEndpoint, String> {
        ResolvedEndpoint::parse(url, self.endpoint_trust)
    }

    pub async fn dispatch(&self, url: &str, request: AtomRequest) -> Result<AtomResponse, String> {
        let endpoint = self.resolve_endpoint(url)?;
        let client = endpoint.build_http_client(self.default_timeout)?;

        let response = client
            .post(endpoint.url().clone())
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
        let endpoint = self.resolve_endpoint(url)?;
        let client = endpoint.build_http_client(Duration::from_millis(claim.timeout_ms.max(1)))?;

        let response = client
            .post(endpoint.url().clone())
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
        let endpoint = self.resolve_endpoint(url)?;
        let client = endpoint.build_http_client(Duration::from_millis(timeout_ms.max(1)))?;

        let response = client
            .post(endpoint.url().clone())
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

#[cfg(test)]
mod tests {
    use super::{
        resolve_endpoint_url, resolve_endpoint_url_trusted, validate_endpoint_url,
    };
    use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};

    #[test]
    fn validation_rejects_loopback_and_private_targets() {
        assert!(validate_endpoint_url("http://127.0.0.1:3000").is_err());
        assert!(validate_endpoint_url("http://10.1.2.3:3000").is_err());
        assert!(validate_endpoint_url("http://[fc00::1]:3000").is_err());
    }

    #[test]
    fn trusted_resolution_preserves_resolved_addresses() {
        let endpoint = resolve_endpoint_url_trusted("http://127.0.0.1:3000/path?q=1").unwrap();
        assert_eq!(endpoint.host(), "127.0.0.1");
        assert_eq!(endpoint.authority(), "127.0.0.1:3000");
        assert_eq!(endpoint.request_target(), "/path?q=1");
        assert_eq!(
            endpoint.socket_addrs(),
            &[SocketAddr::new(IpAddr::V4(Ipv4Addr::LOCALHOST), 3000)]
        );
    }

    #[test]
    fn trusted_resolution_formats_ipv6_authority() {
        let endpoint = resolve_endpoint_url_trusted("http://[::1]:8080/").unwrap();
        assert_eq!(endpoint.authority(), "[::1]:8080");
        assert_eq!(
            endpoint.socket_addrs(),
            &[SocketAddr::new(IpAddr::V6(Ipv6Addr::LOCALHOST), 8080)]
        );
    }

    #[test]
    fn enforced_resolution_rejects_loopback_after_resolution() {
        assert!(resolve_endpoint_url("http://[::1]:8080").is_err());
    }
}
