use axum::{
    extract::State,
    http::StatusCode,
    response::IntoResponse,
    routing::post,
    Json, Router,
};
use std::sync::Arc;

use crate::backend::{resolve_backend, Backend, BackendPreference};
use crate::kernel::{dispatch, AtomRequest};

pub struct ServerState {
    pub backend: Box<dyn Backend>,
}

async fn handle_dispatch(
    State(state): State<Arc<ServerState>>,
    Json(request): Json<AtomRequest>,
) -> impl IntoResponse {
    match dispatch(state.backend.as_ref(), request) {
        Ok(response) => (StatusCode::OK, Json(response)).into_response(),
        Err(e) => {
            let status = if e.contains("no candidate") {
                StatusCode::BAD_REQUEST
            } else {
                StatusCode::INTERNAL_SERVER_ERROR
            };
            (status, e).into_response()
        }
    }
}

pub fn app() -> Router {
    // Auto-resolve backend: try Vulkan, fallback to Mock
    let resolved = resolve_backend(BackendPreference::Auto, 0, None)
        .expect("backend resolution failed");

    let state = Arc::new(ServerState {
        backend: resolved.backend,
    });
    Router::new()
        .route("/dispatch", post(handle_dispatch))
        .with_state(state)
}

/// Bind and serve.
///
/// # Security note
/// This server has no authentication. It is intended for local / intra-cluster
/// use only. Binding to a non-loopback address exposes an unauthenticated
/// compute endpoint to the network — only do this inside a trusted private
/// network with appropriate firewall rules.
pub async fn run_server(addr: &str) -> Result<(), String> {
    if !is_loopback_addr(addr) {
        eprintln!(
            "WARNING: server binding to '{}' (non-loopback). \
             POST /dispatch is unauthenticated — ensure this is behind a \
             firewall or trusted private network.",
            addr
        );
    }

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| format!("bind {addr}: {e}"))?;
    axum::serve(listener, app())
        .await
        .map_err(|e| format!("serve: {e}"))
}

/// Returns true if the bind address is a loopback address (127.x.x.x or ::1).
pub fn is_loopback_addr(addr: &str) -> bool {
    let host = if let Some(bracket_end) = addr.rfind(']') {
        &addr[1..bracket_end]
    } else if let Some(colon) = addr.rfind(':') {
        &addr[..colon]
    } else {
        addr
    };

    use std::net::IpAddr;
    match host.parse::<IpAddr>() {
        Ok(ip) => ip.is_loopback(),
        Err(_) => host == "localhost",
    }
}

#[cfg(test)]
mod tests {
    use super::is_loopback_addr;

    #[test]
    fn loopback_detection() {
        assert!(is_loopback_addr("127.0.0.1:3000"));
        assert!(is_loopback_addr("127.0.0.1"));
        assert!(is_loopback_addr("[::1]:3000"));
        assert!(is_loopback_addr("localhost:8080"));
        assert!(!is_loopback_addr("0.0.0.0:3000"));
        assert!(!is_loopback_addr("192.168.1.1:3000"));
        assert!(!is_loopback_addr("10.0.0.1:3000"));
    }
}
