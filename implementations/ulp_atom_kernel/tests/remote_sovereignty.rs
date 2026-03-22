use axum::{extract::State, http::StatusCode, response::IntoResponse, routing::post, Json, Router};
use std::sync::Arc;

use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
use ulp_atom_kernel::backend::{
    Backend, BackendKind, BackendRequest, BackendResponse, DeviceCapabilities,
};
use ulp_atom_kernel::client::RemoteClient;
use ulp_atom_kernel::kv::{KVChunk, MigrationReceipt};
use ulp_atom_kernel::runtime::{DiscoveryPool, Nonce, SlotClaim, SlotClaimResponse, SlotOffer};
use ulp_atom_kernel::server::app_with_backend;
use ulp_atom_kernel::sovereignty::{
    BlindedAtomRequest, BlindedAtomResponse, ExecutionStage, HomeNode, RemoteExecutionError,
};

struct EchoBackend;

impl Backend for EchoBackend {
    fn execute_prefill(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        Ok(BackendResponse {
            atom_id: request.atom_id,
            output: request.input,
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }

    fn execute_decode(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        self.execute_prefill(request)
    }

    fn migrate_kv(
        &self,
        chunk: KVChunk,
        target: Region,
    ) -> Result<(KVChunk, MigrationReceipt), String> {
        Ok(ulp_atom_kernel::kv::migrate(chunk, target))
    }

    fn device_capabilities(&self) -> DeviceCapabilities {
        DeviceCapabilities {
            backend_kind: BackendKind::Mock,
            device_name: "EchoBackend".into(),
            available: true,
            compute_units: 1,
            memory_mb: 0,
            supports_prefill: true,
            supports_decode: true,
        }
    }
}

#[derive(Clone)]
struct FaultyState {
    node_id: String,
    nonce_offset: u64,
    delay_ms: u64,
}

async fn claim_slot(Json(claim): Json<SlotClaim>) -> impl IntoResponse {
    (
        StatusCode::OK,
        Json(SlotClaimResponse::Accepted {
            node_id: claim.target_node_id,
            nonce: claim.nonce,
        }),
    )
}

async fn faulty_execute(
    State(state): State<Arc<FaultyState>>,
    Json(request): Json<BlindedAtomRequest>,
) -> impl IntoResponse {
    if state.delay_ms > 0 {
        tokio::time::sleep(tokio::time::Duration::from_millis(state.delay_ms)).await;
    }

    if request.stage == ExecutionStage::General {
        let err = RemoteExecutionError {
            code: "GENERAL_STAGE_NOT_ALLOWED".into(),
            message: "test server expects prefill/decode".into(),
            stage: request.stage,
            nonce: request.nonce,
        };
        return (StatusCode::BAD_REQUEST, Json(err)).into_response();
    }

    let response = BlindedAtomResponse {
        ephemeral_node_id: state.node_id.clone(),
        atom_id: request.blinded.atom_id,
        stage: request.stage,
        nonce: Nonce(request.nonce.0 + state.nonce_offset),
        output: request.blinded.input,
        tokens_produced: 1,
        kv_produced: request.blinded.kv_chunks,
    };
    (StatusCode::OK, Json(response)).into_response()
}

fn faulty_app(node_id: &str, nonce_offset: u64, delay_ms: u64) -> Router {
    let state = Arc::new(FaultyState {
        node_id: node_id.to_string(),
        nonce_offset,
        delay_ms,
    });
    Router::new()
        .route("/slot/claim", post(claim_slot))
        .route("/execute", post(faulty_execute))
        .with_state(state)
}

async fn spawn_router(router: Router) -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let execute_url = format!("http://{}/execute", addr);

    let handle = tokio::spawn(async move {
        axum::serve(listener, router).await.ok();
    });

    tokio::time::sleep(tokio::time::Duration::from_millis(50)).await;
    (execute_url, handle)
}

fn offer(node_id: &str, endpoint: &str, supported_kinds: Vec<AtomKind>) -> SlotOffer {
    SlotOffer {
        node_id: node_id.into(),
        region: Region("us-west".into()),
        supported_kinds,
        capacity_hint: 4,
        expires_in_ms: 30_000,
        endpoint: Some(endpoint.into()),
        kv_available: false,
        capabilities: vec![],
    }
}

fn prefill_atom(id: &str) -> ComputeAtom {
    ComputeAtom {
        id: id.into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    }
}

fn decode_atom(id: &str) -> ComputeAtom {
    ComputeAtom {
        id: id.into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    }
}

#[tokio::test]
async fn home_node_executes_blinded_request_over_http_and_unblinds() {
    let (endpoint, handle) =
        spawn_router(app_with_backend("eph-good", Box::new(EchoBackend))).await;

    let mut pool = DiscoveryPool::new();
    pool.register(offer("eph-good", &endpoint, vec![AtomKind::Prefill]));

    let mut home = HomeNode::new("home-1", "zone-1", Region("us-west".into()));
    let result = home
        .execute_remote_with_runtime(
            &RemoteClient::new_trusted(),
            &prefill_atom("atom-prefill"),
            b"hello remote".to_vec(),
            &pool,
            1000,
            200,
        )
        .await
        .unwrap();

    assert_eq!(result.home_node_id, "home-1");
    assert_eq!(result.ephemeral_node_id, "eph-good");
    assert_eq!(result.output, b"hello remote");

    handle.abort();
}

#[tokio::test]
async fn timeout_retries_next_remote_candidate() {
    let (slow_endpoint, slow_handle) = spawn_router(faulty_app("slow-node", 0, 200)).await;
    let (fast_endpoint, fast_handle) =
        spawn_router(app_with_backend("fast-node", Box::new(EchoBackend))).await;

    let mut pool = DiscoveryPool::new();
    pool.register(offer("slow-node", &slow_endpoint, vec![AtomKind::Prefill]));
    pool.register(offer("fast-node", &fast_endpoint, vec![AtomKind::Prefill]));

    let mut home = HomeNode::new("home-timeout", "zone", Region("us-west".into()));
    let result = home
        .execute_remote_with_runtime(
            &RemoteClient::new_trusted(),
            &prefill_atom("timeout-prefill"),
            b"timeout retry".to_vec(),
            &pool,
            2000,
            50,
        )
        .await
        .unwrap();

    assert_eq!(result.ephemeral_node_id, "fast-node");
    assert_eq!(result.output, b"timeout retry");

    slow_handle.abort();
    fast_handle.abort();
}

#[tokio::test]
async fn nonce_mismatch_rejected_and_retried() {
    let (bad_endpoint, bad_handle) = spawn_router(faulty_app("bad-node", 1, 0)).await;
    let (good_endpoint, good_handle) =
        spawn_router(app_with_backend("good-node", Box::new(EchoBackend))).await;

    let mut pool = DiscoveryPool::new();
    pool.register(offer("bad-node", &bad_endpoint, vec![AtomKind::Prefill]));
    pool.register(offer("good-node", &good_endpoint, vec![AtomKind::Prefill]));

    let mut home = HomeNode::new("home-nonce", "zone", Region("us-west".into()));
    let result = home
        .execute_remote_with_runtime(
            &RemoteClient::new_trusted(),
            &prefill_atom("nonce-prefill"),
            b"nonce retry".to_vec(),
            &pool,
            3000,
            200,
        )
        .await
        .unwrap();

    assert_eq!(result.ephemeral_node_id, "good-node");
    assert_eq!(result.output, b"nonce retry");

    bad_handle.abort();
    good_handle.abort();
}

#[tokio::test]
async fn two_stage_remote_runtime_pipeline_flows_prefill_into_decode() {
    let (prefill_endpoint, prefill_handle) =
        spawn_router(app_with_backend("prefill-node", Box::new(EchoBackend))).await;
    let (decode_endpoint, decode_handle) =
        spawn_router(app_with_backend("decode-node", Box::new(EchoBackend))).await;

    let mut pool = DiscoveryPool::new();
    pool.register(offer(
        "prefill-node",
        &prefill_endpoint,
        vec![AtomKind::Prefill],
    ));
    pool.register(offer(
        "decode-node",
        &decode_endpoint,
        vec![AtomKind::Decode],
    ));

    let mut home = HomeNode::new("home-2stage", "zone", Region("us-west".into()));
    let result = home
        .execute_two_stage_remote_with_runtime(
            &RemoteClient::new_trusted(),
            &prefill_atom("prefill-stage"),
            &decode_atom("decode-stage"),
            b"prefill then decode".to_vec(),
            &pool,
            4000,
            5000,
            200,
        )
        .await
        .unwrap();

    assert_eq!(result.prefill_node_id, "prefill-node");
    assert_eq!(result.decode_node_id, "decode-node");
    assert!(result.kv_migrated);
    assert_eq!(result.output, b"prefill then decode");

    prefill_handle.abort();
    decode_handle.abort();
}
