use axum::{extract::State, http::StatusCode, response::IntoResponse, routing::post, Json, Router};
use std::sync::Arc;

use crate::backend::{resolve_backend, Backend, BackendPreference};
use crate::kernel::{dispatch, AtomRequest};
use crate::runtime::{SlotClaim, SlotClaimResponse};
use crate::sovereignty::{
    BlindedAtomRequest, BlindedAtomResponse, ExecutionStage, RemoteExecutionError,
};

pub struct ServerState {
    pub backend: Box<dyn Backend>,
    pub node_id: String,
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

async fn handle_slot_claim(
    State(state): State<Arc<ServerState>>,
    Json(claim): Json<SlotClaim>,
) -> impl IntoResponse {
    let _ = state;
    let response = SlotClaimResponse::Accepted {
        node_id: claim.target_node_id,
        nonce: claim.nonce,
    };
    (StatusCode::OK, Json(response)).into_response()
}

/// Handle blinded atom execution request from Home Node.
/// This is the remote Ephemeral Node HTTP entry point.
async fn handle_execute_blinded(
    State(state): State<Arc<ServerState>>,
    Json(request): Json<BlindedAtomRequest>,
) -> impl IntoResponse {
    if stage_for_kind(&request.blinded.kind) != request.stage {
        let err = RemoteExecutionError {
            code: "STAGE_MISMATCH".into(),
            message: format!(
                "request stage {:?} does not match atom kind {:?}",
                request.stage, request.blinded.kind
            ),
            stage: request.stage,
            nonce: request.nonce,
        };
        return (StatusCode::BAD_REQUEST, Json(err)).into_response();
    }

    // Extract blinded atom
    let blinded = &request.blinded;

    // Execute via backend
    let backend_req = crate::backend::BackendRequest {
        atom_id: blinded.atom_id.clone(),
        input: blinded.input.clone(),
        kv_state: blinded.kv_chunks.clone(),
    };

    let backend_resp = match blinded.kind {
        crate::atom::AtomKind::Prefill => state.backend.execute_prefill(backend_req),
        crate::atom::AtomKind::Decode => state.backend.execute_decode(backend_req),
        _ => state.backend.execute_prefill(backend_req),
    };

    match backend_resp {
        Ok(resp) => {
            let result = BlindedAtomResponse {
                ephemeral_node_id: state.node_id.clone(),
                atom_id: blinded.atom_id.clone(),
                stage: request.stage,
                nonce: request.nonce,
                output: resp.output,
                tokens_produced: resp.tokens_produced,
                kv_produced: resp.kv_state,
            };
            (StatusCode::OK, Json(result)).into_response()
        }
        Err(e) => {
            let err = RemoteExecutionError {
                code: "BACKEND_EXECUTION_FAILED".into(),
                message: e,
                stage: request.stage,
                nonce: request.nonce,
            };
            (StatusCode::INTERNAL_SERVER_ERROR, Json(err)).into_response()
        }
    }
}

pub fn app() -> Router {
    app_with_node_id("ephemeral-http")
}

pub fn app_with_node_id(node_id: &str) -> Router {
    // Auto-resolve backend: try Vulkan, fallback to Mock
    let resolved =
        resolve_backend(BackendPreference::Auto, 0, None).expect("backend resolution failed");

    app_with_backend(node_id, resolved.backend)
}

pub fn app_with_backend(node_id: &str, backend: Box<dyn Backend>) -> Router {
    let state = Arc::new(ServerState {
        backend,
        node_id: node_id.to_string(),
    });
    Router::new()
        .route("/dispatch", post(handle_dispatch))
        .route("/slot/claim", post(handle_slot_claim))
        .route("/execute", post(handle_execute_blinded))
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
        return Err(format!(
            "refusing to bind unauthenticated /dispatch server to non-loopback address '{}'",
            addr
        ));
    }

    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| format!("bind {addr}: {e}"))?;
    axum::serve(listener, app())
        .await
        .map_err(|e| format!("serve: {e}"))
}

fn stage_for_kind(kind: &crate::atom::AtomKind) -> ExecutionStage {
    match kind {
        crate::atom::AtomKind::Prefill => ExecutionStage::Prefill,
        crate::atom::AtomKind::Decode => ExecutionStage::Decode,
        _ => ExecutionStage::General,
    }
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
