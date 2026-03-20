use axum::{extract::State, http::StatusCode, response::IntoResponse, routing::post, Json, Router};
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

pub async fn run_server(addr: &str) -> Result<(), String> {
    let listener = tokio::net::TcpListener::bind(addr)
        .await
        .map_err(|e| format!("bind {addr}: {e}"))?;
    axum::serve(listener, app())
        .await
        .map_err(|e| format!("serve: {e}"))
}
