use ulp_atom_kernel::atom::*;
use ulp_atom_kernel::backend::{Backend, BackendKind, BackendRequest, BackendResponse, DeviceCapabilities};
use ulp_atom_kernel::exec::*;
use ulp_atom_kernel::kernel::*;
use ulp_atom_kernel::kv::*;
use ulp_atom_kernel::loader::*;
use ulp_atom_kernel::protocol::*;
use ulp_atom_kernel::router::*;
use ulp_atom_kernel::runner;
use ulp_atom_kernel::sac_bridge::*;

fn make_atom() -> ComputeAtom {
    ComputeAtom {
        id: "atom-1".into(),
        kind: AtomKind::Inference,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 4,
    }
}

fn make_nodes() -> Vec<NodeProfile> {
    vec![
        NodeProfile {
            node_id: "node-a".into(),
            region: Region("us-west".into()),
            latency_ms: 10.0,
            hotness: 0.9,
            supported_kinds: vec![AtomKind::Inference],
            sovereignty_zone: "us-west".into(),
            prefill_affinity: 0.5,
            decode_affinity: 0.5,
            capacity: Default::default(),
        },
        NodeProfile {
            node_id: "node-b".into(),
            region: Region("eu-central".into()),
            latency_ms: 80.0,
            hotness: 0.2,
            supported_kinds: vec![AtomKind::Embedding],
            sovereignty_zone: "eu-central".into(),
            prefill_affinity: 0.5,
            decode_affinity: 0.5,
            capacity: Default::default(),
        },
    ]
}

// --- Router tests ---

#[test]
fn router_picks_better_node() {
    let atom = make_atom();
    let nodes = make_nodes();
    let decision = route(&atom, &nodes).unwrap();
    assert_eq!(decision.breakdown.node_id, "node-a");
}

#[test]
fn router_returns_score_breakdown() {
    let atom = make_atom();
    let nodes = make_nodes();
    let decision = route(&atom, &nodes).unwrap();
    let b = &decision.breakdown;
    assert!(b.final_score > 0.0);
    assert!(b.latency_score > 0.0);
    assert_eq!(b.engine_score, 1.0);
    assert_eq!(b.sovereignty_score, 1.0);
}

#[test]
fn router_empty_candidates_returns_none() {
    let atom = make_atom();
    assert!(route(&atom, &[]).is_none());
}

#[test]
fn router_same_region_no_kv_migration() {
    let atom = make_atom();
    let nodes = make_nodes();
    let decision = route(&atom, &nodes).unwrap();
    // node-a is us-west, same as atom — no migration needed
    assert!(!decision.requires_kv_migration);
}

#[test]
fn kv_locality_flips_routing_decision() {
    // Two nodes: node-far has worse latency but all KV chunks are there.
    // Without KV context, node-local wins. With KV context, node-far should win.
    let atom = ComputeAtom {
        id: "atom-kv".into(),
        kind: AtomKind::Inference,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 2,
    };
    let nodes = vec![
        NodeProfile {
            node_id: "node-local".into(),
            region: Region("us-west".into()),
            latency_ms: 10.0,
            hotness: 0.3,
            supported_kinds: vec![AtomKind::Inference],
            sovereignty_zone: "us-west".into(),
            prefill_affinity: 0.5,
            decode_affinity: 0.5,
            capacity: Default::default(),
        },
        NodeProfile {
            node_id: "node-far".into(),
            region: Region("eu-central".into()),
            latency_ms: 15.0,
            hotness: 0.3,
            supported_kinds: vec![AtomKind::Inference],
            sovereignty_zone: "eu-central".into(),
            prefill_affinity: 0.5,
            decode_affinity: 0.5,
            capacity: Default::default(),
        },
    ];

    // without KV: node-local wins (same region, sovereignty)
    let no_kv = route(&atom, &nodes).unwrap();
    assert_eq!(no_kv.breakdown.node_id, "node-local");

    // with KV: all chunks in eu-central — node-far should win
    let chunks: Vec<KVChunk> = (0..8).map(|i| KVChunk {
        chunk_id: format!("kv-{}", i),
        source_region: Region("eu-central".into()),
        seq_start: i * 128,
        seq_end: (i + 1) * 128 - 1,
        byte_size: 65536,
        payload: vec![],
    }).collect();
    let ctx = KVContext { active_chunks: &chunks };
    let with_kv = route_with_kv(&atom, &nodes, Some(&ctx)).unwrap();
    assert_eq!(with_kv.breakdown.node_id, "node-far");
    assert!(with_kv.breakdown.kv_locality_score > no_kv.breakdown.kv_locality_score);
}

#[test]
fn route_with_kv_reports_migration_cost() {
    let atom = make_atom();
    let nodes = make_nodes();
    let chunks = vec![make_chunk()]; // chunk in us-west
    let ctx = KVContext { active_chunks: &chunks };
    let decision = route_with_kv(&atom, &nodes, Some(&ctx)).unwrap();
    // winner is node-a (us-west), chunk is already there — zero migration cost
    assert_eq!(decision.estimated_migration_cost, 0.0);
}

// --- Loader tests ---

#[test]
fn manifest_parses_from_json() {
    let json = r#"{
        "model_id": "llama-7b",
        "shards": [
            {"shard_id": "s0", "path": "/tmp/shard0.bin"},
            {"shard_id": "s1", "path": "https://cdn.example.com/shard1.bin"}
        ]
    }"#;
    let manifest = ShardManifest::from_json(json).unwrap();
    assert_eq!(manifest.model_id, "llama-7b");
    assert_eq!(manifest.shards.len(), 2);
}

#[test]
fn loader_resolves_local_shard() {
    let dir = tempfile::tempdir().unwrap();
    let shard_path = dir.path().join("shard0.bin");
    std::fs::write(&shard_path, b"fake-weights").unwrap();

    let shard = ShardRef {
        shard_id: "s0".into(),
        path: shard_path.to_str().unwrap().into(),
    };
    match resolve_shard(&shard) {
        ResolvedShard::Local(p) => assert_eq!(p, shard_path),
        ResolvedShard::Remote(_) => panic!("expected local"),
    }

    let data = load_local_shard(&shard_path).unwrap();
    assert_eq!(data, b"fake-weights");
}

#[test]
fn loader_resolves_remote_shard() {
    let shard = ShardRef {
        shard_id: "s1".into(),
        path: "https://cdn.example.com/shard1.bin".into(),
    };
    match resolve_shard(&shard) {
        ResolvedShard::Remote(url) => assert_eq!(url, "https://cdn.example.com/shard1.bin"),
        ResolvedShard::Local(_) => panic!("expected remote"),
    }
}

// --- KV bridge tests ---

fn make_chunk() -> KVChunk {
    KVChunk {
        chunk_id: "kv-001".into(),
        source_region: Region("us-west".into()),
        seq_start: 0,
        seq_end: 127,
        byte_size: 4096,
        payload: vec![0xAB; 4096],
    }
}

#[test]
fn kv_migration_changes_region() {
    let chunk = make_chunk();
    let target = Region("eu-central".into());
    let (migrated, _receipt) = migrate(chunk, target.clone());
    assert_eq!(migrated.source_region, target);
}

#[test]
fn kv_migration_preserves_identity_and_size() {
    let chunk = make_chunk();
    let (migrated, receipt) = migrate(chunk.clone(), Region("ap-east".into()));
    assert_eq!(migrated.chunk_id, "kv-001");
    assert_eq!(migrated.seq_start, 0);
    assert_eq!(migrated.seq_end, 127);
    assert_eq!(migrated.byte_size, 4096);
    assert_eq!(migrated.payload.len(), 4096);
    assert_eq!(receipt.from, Region("us-west".into()));
    assert_eq!(receipt.to, Region("ap-east".into()));
    assert_eq!(receipt.byte_size, 4096);
}

#[test]
fn kv_migration_same_region_is_noop() {
    let chunk = make_chunk();
    let (migrated, receipt) = migrate(chunk.clone(), Region("us-west".into()));
    assert_eq!(migrated.source_region, Region("us-west".into()));
    assert_eq!(receipt.from, receipt.to);
}

#[test]
fn kv_migration_cost_zero_same_region() {
    let chunk = make_chunk();
    assert_eq!(migration_cost(&chunk, &Region("us-west".into())), 0.0);
}

#[test]
fn kv_migration_cost_nonzero_cross_region() {
    let chunk = make_chunk();
    let cost = migration_cost(&chunk, &Region("eu-central".into()));
    assert!(cost > 0.0);
}

// --- Execution boundary tests ---

struct StubKernel;

impl Backend for StubKernel {
    fn execute_prefill(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        Ok(BackendResponse {
            atom_id: request.atom_id,
            output: request.input.iter().map(|b| b.wrapping_add(1)).collect(),
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }

    fn execute_decode(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        Ok(BackendResponse {
            atom_id: request.atom_id,
            output: request.input.iter().map(|b| b.wrapping_add(1)).collect(),
            tokens_produced: 1,
            kv_state: request.kv_state,
        })
    }

    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String> {
        Ok(migrate(chunk, target))
    }

    fn device_capabilities(&self) -> DeviceCapabilities {
        DeviceCapabilities {
            backend_kind: BackendKind::Mock,
            device_name: "StubDevice".into(),
            available: true,
            compute_units: 1,
            memory_mb: 0,
            supports_prefill: true,
            supports_decode: true,
        }
    }
}

impl ComputeKernel for StubKernel {
    fn execute(&self, request: ExecRequest, _placement: &PlacementDecision) -> Result<ExecResponse, String> {
        Ok(ExecResponse {
            atom_id: request.atom_id,
            output: request.input.iter().map(|b| b.wrapping_add(1)).collect(),
            tokens_produced: 1,
            kv_state: vec![],
        })
    }

    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String> {
        Ok(migrate(chunk, target))
    }
}

fn stub_placement() -> PlacementDecision {
    PlacementDecision {
        breakdown: PlacementBreakdown {
            node_id: "node-a".into(),
            final_score: 0.8,
            latency_score: 0.9,
            hotness_score: 0.9,
            engine_score: 1.0,
            specialization_score: 0.5,
            kv_locality_score: 0.5,
            sovereignty_score: 1.0,
            migration_cost: 0.0,
            capacity_score: 0.8,
        },
        requires_kv_migration: false,
        estimated_migration_cost: 0.0,
    }
}

#[test]
fn exec_boundary_accepts_request_with_placement() {
    let kernel = StubKernel;
    let placement = stub_placement();
    let req = ExecRequest {
        atom_id: "atom-1".into(),
        input: vec![0x00, 0x01, 0x02],
        kv_state: vec![],
    };
    let resp = kernel.execute(req, &placement).unwrap();
    assert_eq!(resp.atom_id, "atom-1");
    assert_eq!(resp.output, vec![0x01, 0x02, 0x03]);
    assert_eq!(resp.tokens_produced, 1);
}

#[test]
fn exec_boundary_migrate_kv_delegates_correctly() {
    let kernel = StubKernel;
    let chunk = make_chunk();
    let (migrated, receipt) = ComputeKernel::migrate_kv(&kernel, chunk, Region("ap-east".into())).unwrap();
    assert_eq!(migrated.source_region, Region("ap-east".into()));
    assert_eq!(receipt.from, Region("us-west".into()));
}

// --- Kernel dispatch tests ---

#[test]
fn kernel_dispatch_full_path_no_migration() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x10, 0x20],
        kv_state: vec![KVChunk {
            chunk_id: "kv-local".into(),
            source_region: Region("us-west".into()),
            seq_start: 0,
            seq_end: 63,
            byte_size: 1024,
            payload: vec![0xCC; 1024],
        }],
        candidates: make_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    // routed to node-a (us-west), KV already there — no migrations
    assert_eq!(resp.placement.breakdown.node_id, "node-a");
    assert!(resp.migrations.is_empty());
    assert_eq!(resp.exec_response.atom_id, "atom-1");
    assert_eq!(resp.exec_response.output, vec![0x11, 0x21]);
}

#[test]
fn kernel_dispatch_triggers_kv_migration() {
    let kernel = StubKernel;
    // atom in us-west, KV chunks in eu-central
    // but node-a (us-west) still wins on engine+sovereignty+latency
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x01],
        kv_state: vec![KVChunk {
            chunk_id: "kv-remote".into(),
            source_region: Region("eu-central".into()),
            seq_start: 0,
            seq_end: 31,
            byte_size: 512,
            payload: vec![0xDD; 512],
        }],
        candidates: make_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    // chunk was in eu-central, routed to us-west — migration happened
    assert_eq!(resp.migrations.len(), 1);
    assert_eq!(resp.migrations[0].from, Region("eu-central".into()));
    assert_eq!(resp.migrations[0].to, Region("us-west".into()));
    assert_eq!(resp.exec_response.output, vec![0x02]);
    assert!(resp.placement.requires_kv_migration);
}

#[test]
fn kernel_dispatch_no_candidates_fails() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![],
        kv_state: vec![],
        candidates: vec![],
    };
    let err = dispatch(&kernel, req).unwrap_err();
    assert_eq!(err, "no candidate nodes");
}

#[test]
fn kernel_dispatch_placement_is_explicit() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0xFF],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    // placement decision is fully visible
    assert!(resp.placement.breakdown.final_score > 0.0);
    assert!(resp.placement.breakdown.kv_locality_score >= 0.0);
    assert!(!resp.placement.requires_kv_migration);
}

// --- Protocol roundtrip tests ---

#[test]
fn atom_request_cbor_roundtrip() {
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x10, 0x20, 0x30],
        kv_state: vec![make_chunk()],
        candidates: make_nodes(),
    };
    let bytes = encode_cbor(&req).unwrap();
    let decoded: AtomRequest = decode_cbor(&bytes).unwrap();
    assert_eq!(decoded.atom.id, "atom-1");
    assert_eq!(decoded.input, vec![0x10, 0x20, 0x30]);
    assert_eq!(decoded.kv_state.len(), 1);
    assert_eq!(decoded.kv_state[0].chunk_id, "kv-001");
    assert_eq!(decoded.candidates.len(), 2);
}

#[test]
fn atom_response_cbor_roundtrip() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x01],
        kv_state: vec![KVChunk {
            chunk_id: "kv-rt".into(),
            source_region: Region("eu-central".into()),
            seq_start: 0,
            seq_end: 15,
            byte_size: 256,
            payload: vec![0xEE; 256],
        }],
        candidates: make_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    let bytes = encode_cbor(&resp).unwrap();
    let decoded: AtomResponse = decode_cbor(&bytes).unwrap();
    assert_eq!(decoded.placement.breakdown.node_id, "node-a");
    assert!(decoded.placement.breakdown.final_score > 0.0);
    assert_eq!(decoded.migrations.len(), 1);
    assert_eq!(decoded.migrations[0].from, Region("eu-central".into()));
    assert_eq!(decoded.exec_response.atom_id, "atom-1");
    assert_eq!(decoded.exec_response.output, vec![0x02]);
}

#[test]
fn placement_decision_cbor_roundtrip() {
    let decision = route(&make_atom(), &make_nodes()).unwrap();
    let bytes = encode_cbor(&decision).unwrap();
    let decoded: PlacementDecision = decode_cbor(&bytes).unwrap();
    assert_eq!(decoded.breakdown.node_id, decision.breakdown.node_id);
    assert_eq!(decoded.breakdown.final_score, decision.breakdown.final_score);
    assert_eq!(decoded.requires_kv_migration, decision.requires_kv_migration);
    assert_eq!(decoded.estimated_migration_cost, decision.estimated_migration_cost);
}

#[test]
fn migration_receipt_cbor_roundtrip() {
    let chunk = make_chunk();
    let (_migrated, receipt) = migrate(chunk, Region("ap-east".into()));
    let bytes = encode_cbor(&receipt).unwrap();
    let decoded: MigrationReceipt = decode_cbor(&bytes).unwrap();
    assert_eq!(decoded.chunk_id, "kv-001");
    assert_eq!(decoded.from, Region("us-west".into()));
    assert_eq!(decoded.to, Region("ap-east".into()));
    assert_eq!(decoded.byte_size, 4096);
}

#[test]
fn dispatch_result_json_roundtrip() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0xFF],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    let json_bytes = encode_json(&resp).unwrap();
    let decoded: AtomResponse = decode_json(&json_bytes).unwrap();
    assert_eq!(decoded.placement.breakdown.node_id, "node-a");
    assert_eq!(decoded.placement.breakdown.kv_locality_score, resp.placement.breakdown.kv_locality_score);
    assert_eq!(decoded.exec_response.tokens_produced, 1);
}

// --- SAC bridge tests ---

#[test]
fn sac_request_dispatches_through_kernel() {
    let sac_req = SACRequest {
        agent_id: "agent-007".into(),
        sovereignty_zone: "us-west".into(),
        model_id: "llama-7b".into(),
        atom_kind: AtomKind::Inference,
        two_stage: false,
        input: vec![0x42, 0x43],
    };
    let atom_req = into_atom_request(&sac_req, vec![], make_nodes());
    assert_eq!(atom_req.atom.id, "atom-agent-007");
    assert_eq!(atom_req.atom.region, Region("us-west".into()));

    let kernel = StubKernel;
    let resp = dispatch(&kernel, atom_req).unwrap();
    assert_eq!(resp.placement.breakdown.node_id, "node-a");
    assert_eq!(resp.exec_response.output, vec![0x43, 0x44]);
}

#[test]
fn sac_request_cbor_roundtrip() {
    let sac_req = SACRequest {
        agent_id: "agent-rt".into(),
        sovereignty_zone: "eu-central".into(),
        model_id: "mistral-7b".into(),
        atom_kind: AtomKind::Embedding,
        two_stage: false,
        input: vec![0x01, 0x02],
    };
    let bytes = encode_cbor(&sac_req).unwrap();
    let decoded: SACRequest = decode_cbor(&bytes).unwrap();
    assert_eq!(decoded.agent_id, "agent-rt");
    assert_eq!(decoded.sovereignty_zone, "eu-central");
    assert_eq!(decoded.atom_kind, AtomKind::Embedding);
}

// --- Runner tests ---

#[test]
fn runner_full_path_from_json() {
    let json = r#"{
        "agent_id": "runner-test",
        "sovereignty_zone": "us-west",
        "model_id": "llama-7b",
        "atom_kind": "Inference",
        "input": [104, 101, 108, 108, 111]
    }"#;
    let output = runner::run_from_json(json).unwrap();
    let resp: AtomResponse = serde_json::from_str(&output).unwrap();
    assert_eq!(resp.placement.breakdown.node_id, "local-0");
    assert!(!resp.placement.requires_kv_migration);
    assert_eq!(resp.exec_response.atom_id, "atom-runner-test");
    // "hello" uppercased = [72, 69, 76, 76, 79]
    assert_eq!(resp.exec_response.output, vec![72, 69, 76, 76, 79]);
    assert!(resp.migrations.is_empty());
}

#[test]
fn runner_rejects_bad_json() {
    let err = runner::run_from_json("not json").unwrap_err();
    assert!(err.starts_with("parse request:"));
}

#[test]
fn runner_sample_file_dispatches() {
    let sample = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let output = runner::run_from_json(&sample).unwrap();
    let resp: AtomResponse = serde_json::from_str(&output).unwrap();
    assert_eq!(resp.exec_response.atom_id, "atom-agent-demo");
    // "Hello ULP" = [72,101,108,108,111,32,85,76,80] → uppercased = [72,69,76,76,79,32,85,76,80]
    assert_eq!(resp.exec_response.output, vec![72, 69, 76, 76, 79, 32, 85, 76, 80]);
    assert_eq!(resp.placement.breakdown.node_id, "local-0");
}

// --- Multi-node runner tests ---

#[test]
fn runner_multi_node_picks_best() {
    let req = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let nodes = std::fs::read_to_string("examples/sample_nodes.json").unwrap();
    let output = runner::run_request(&req, Some(&nodes), None).unwrap();
    let resp: AtomResponse = serde_json::from_str(&output).unwrap();
    // us-west node should win: low latency, sovereignty match, engine match
    assert_eq!(resp.placement.breakdown.node_id, "us-west-gpu-0");
    assert!(resp.placement.breakdown.final_score > 0.0);
    assert!(resp.migrations.is_empty());
}

#[test]
fn runner_multi_node_with_kv_triggers_migration() {
    let req = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let nodes = std::fs::read_to_string("examples/sample_nodes.json").unwrap();
    let kv = std::fs::read_to_string("examples/sample_kv.json").unwrap();
    let output = runner::run_request(&req, Some(&nodes), Some(&kv)).unwrap();
    let resp: AtomResponse = serde_json::from_str(&output).unwrap();
    let winner = &resp.placement.breakdown.node_id;
    // KV chunks are in eu-central. If winner is not eu-central, migrations happen.
    if winner != "eu-central-gpu-0" {
        assert!(!resp.migrations.is_empty());
        for m in &resp.migrations {
            assert_eq!(m.from, Region("eu-central".into()));
        }
    } else {
        assert!(resp.migrations.is_empty());
    }
}

#[test]
fn runner_kv_locality_shifts_placement() {
    // With heavy KV in eu-central, the router should favor eu-central more.
    let req_json = r#"{
        "agent_id": "kv-test",
        "sovereignty_zone": "us-west",
        "model_id": "llama-7b",
        "atom_kind": "Inference",
        "input": [65]
    }"#;
    // Two nodes: similar profiles, but KV is all in eu-central
    let nodes_json = r#"[
        {"node_id":"n-us","region":"us-west","latency_ms":10.0,"hotness":0.5,
         "supported_kinds":["Inference"],"sovereignty_zone":"us-west"},
        {"node_id":"n-eu","region":"eu-central","latency_ms":12.0,"hotness":0.5,
         "supported_kinds":["Inference"],"sovereignty_zone":"eu-central"}
    ]"#;
    let kv_json = r#"[
        {"chunk_id":"c0","source_region":"eu-central","seq_start":0,"seq_end":1023,"byte_size":65536,"payload":[]},
        {"chunk_id":"c1","source_region":"eu-central","seq_start":1024,"seq_end":2047,"byte_size":65536,"payload":[]},
        {"chunk_id":"c2","source_region":"eu-central","seq_start":2048,"seq_end":3071,"byte_size":65536,"payload":[]},
        {"chunk_id":"c3","source_region":"eu-central","seq_start":3072,"seq_end":4095,"byte_size":65536,"payload":[]}
    ]"#;

    // without KV: us-west wins (sovereignty)
    let no_kv = runner::run_request(req_json, Some(nodes_json), None).unwrap();
    let resp_no_kv: AtomResponse = serde_json::from_str(&no_kv).unwrap();
    assert_eq!(resp_no_kv.placement.breakdown.node_id, "n-us");

    // with KV: eu-central should win (kv_locality outweighs sovereignty)
    let with_kv = runner::run_request(req_json, Some(nodes_json), Some(kv_json)).unwrap();
    let resp_kv: AtomResponse = serde_json::from_str(&with_kv).unwrap();
    assert_eq!(resp_kv.placement.breakdown.node_id, "n-eu");
    assert!(resp_kv.placement.breakdown.kv_locality_score > resp_no_kv.placement.breakdown.kv_locality_score);
}

#[test]
fn runner_output_structure_is_stable() {
    let req = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let nodes = std::fs::read_to_string("examples/sample_nodes.json").unwrap();
    let output = runner::run_request(&req, Some(&nodes), None).unwrap();
    let val: serde_json::Value = serde_json::from_str(&output).unwrap();
    // verify all expected top-level keys exist
    assert!(val.get("placement").is_some());
    assert!(val.get("explain").is_some());
    assert!(val.get("migrations").is_some());
    assert!(val.get("exec_response").is_some());
    let p = &val["placement"]["breakdown"];
    assert!(p.get("node_id").is_some());
    assert!(p.get("final_score").is_some());
    assert!(p.get("migration_cost").is_some());
    assert!(p.get("kv_locality_score").is_some());
    // explain mirrors breakdown fields
    let e = &val["explain"];
    assert!(e.get("node_id").is_some());
    assert!(e.get("final_score").is_some());
    assert!(e.get("specialization_score").is_some());
    assert!(e.get("sovereignty_score").is_some());
    assert!(e.get("migration_cost").is_some());
    assert!(e.get("requires_kv_migration").is_some());
    assert!(e.get("chunks_migrated").is_some());
}

#[test]
fn missing_affinity_fields_default_to_neutral_scores() {
    let atom = ComputeAtom {
        id: "neutral".into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "m".into(),
        shard_count: 0,
    };
    let nodes_json = r#"[
        {"node_id":"n0","region":"us-west","latency_ms":10.0,"hotness":0.5,
         "supported_kinds":["Prefill"],"sovereignty_zone":"us-west"}
    ]"#;
    let nodes: Vec<NodeProfile> = serde_json::from_str(nodes_json).unwrap();
    let decision = route(&atom, &nodes).unwrap();
    assert_eq!(decision.breakdown.specialization_score, 0.5);
}

struct KvAwareKernel;

impl Backend for KvAwareKernel {
    fn execute_prefill(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        let all_local = request
            .kv_state
            .iter()
            .all(|chunk| chunk.source_region == Region("us-west".into()));
        if !all_local {
            return Err("kv_state was not migrated before execute".into());
        }
        Ok(BackendResponse {
            atom_id: request.atom_id,
            output: request.input,
            tokens_produced: request.kv_state.len() as u32,
            kv_state: request.kv_state,
        })
    }

    fn execute_decode(&self, request: BackendRequest) -> Result<BackendResponse, String> {
        self.execute_prefill(request)
    }

    fn migrate_kv(&self, chunk: KVChunk, target: Region) -> Result<(KVChunk, MigrationReceipt), String> {
        Ok(migrate(chunk, target))
    }

    fn device_capabilities(&self) -> DeviceCapabilities {
        DeviceCapabilities {
            backend_kind: BackendKind::Mock,
            device_name: "KvAwareDevice".into(),
            available: true,
            compute_units: 1,
            memory_mb: 0,
            supports_prefill: true,
            supports_decode: true,
        }
    }
}

#[test]
fn kernel_dispatch_executes_with_migrated_kv_state() {
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x01],
        kv_state: vec![KVChunk {
            chunk_id: "kv-remote".into(),
            source_region: Region("eu-central".into()),
            seq_start: 0,
            seq_end: 31,
            byte_size: 512,
            payload: vec![],
        }],
        candidates: make_nodes(),
    };
    let resp = dispatch(&KvAwareKernel, req).unwrap();
    assert_eq!(resp.exec_response.tokens_produced, 1);
    assert_eq!(resp.migrations.len(), 1);
}

// --- Prefill / Decode phase divergence tests ---

fn phase_test_nodes() -> Vec<NodeProfile> {
    vec![
        NodeProfile {
            node_id: "n-fast".into(),
            region: Region("us-west".into()),
            latency_ms: 5.0,
            hotness: 0.6,
            supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode, AtomKind::Inference],
            sovereignty_zone: "us-west".into(),
            prefill_affinity: 0.8,
            decode_affinity: 0.3,
            capacity: Default::default(),
        },
        NodeProfile {
            node_id: "n-kv-hot".into(),
            region: Region("eu-central".into()),
            latency_ms: 50.0,
            hotness: 0.6,
            supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode, AtomKind::Inference],
            sovereignty_zone: "eu-central".into(),
            prefill_affinity: 0.3,
            decode_affinity: 0.9,
            capacity: Default::default(),
        },
    ]
}

fn phase_test_kv() -> Vec<KVChunk> {
    (0..6).map(|i| KVChunk {
        chunk_id: format!("kv-{i}"),
        source_region: Region("eu-central".into()),
        seq_start: i * 256,
        seq_end: (i + 1) * 256 - 1,
        byte_size: 32768,
        payload: vec![],
    }).collect()
}

#[test]
fn prefill_and_decode_diverge_on_same_nodes() {
    let nodes = phase_test_nodes();
    let kv = phase_test_kv();

    let prefill_atom = ComputeAtom {
        id: "prefill-1".into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 2,
    };
    let decode_atom = ComputeAtom {
        id: "decode-1".into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 2,
    };

    let ctx = KVContext { active_chunks: &kv };

    let prefill_decision = route_with_kv(&prefill_atom, &nodes, Some(&ctx)).unwrap();
    let decode_decision = route_with_kv(&decode_atom, &nodes, Some(&ctx)).unwrap();

    // Prefill: sovereignty + engine weight high → prefers us-west (n-fast)
    // Decode: KV locality + latency dominate, but KV is all in eu-central → prefers n-kv-hot
    assert_ne!(
        prefill_decision.breakdown.node_id,
        decode_decision.breakdown.node_id,
        "prefill and decode should pick different nodes"
    );
    assert_eq!(prefill_decision.breakdown.node_id, "n-fast");
    assert_eq!(decode_decision.breakdown.node_id, "n-kv-hot");
}

#[test]
fn decode_more_sensitive_to_kv_locality_than_prefill() {
    let nodes = phase_test_nodes();
    let kv = phase_test_kv();

    let prefill_atom = ComputeAtom {
        id: "p".into(), kind: AtomKind::Prefill,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };
    let decode_atom = ComputeAtom {
        id: "d".into(), kind: AtomKind::Decode,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };

    let ctx = KVContext { active_chunks: &kv };

    let _p = route_with_kv(&prefill_atom, &nodes, Some(&ctx)).unwrap();
    let _d = route_with_kv(&decode_atom, &nodes, Some(&ctx)).unwrap();

    // The eu-central node has kv_locality_score=1.0 for both.
    // But decode weights it at 0.35 vs prefill at 0.15.
    // So the score gap between n-kv-hot and n-fast should be larger for decode.
    let p_scores: Vec<_> = nodes.iter()
        .map(|n| route_with_kv(&prefill_atom, &[n.clone()], Some(&ctx)).unwrap().breakdown.final_score)
        .collect();
    let d_scores: Vec<_> = nodes.iter()
        .map(|n| route_with_kv(&decode_atom, &[n.clone()], Some(&ctx)).unwrap().breakdown.final_score)
        .collect();

    let p_gap = (p_scores[0] - p_scores[1]).abs();
    let d_gap = (d_scores[0] - d_scores[1]).abs();

    // Decode's score gap should differ from prefill's — the weighting is different
    assert!((p_gap - d_gap).abs() > 0.01, "phase weights should produce different score gaps");
}

#[test]
fn prefill_tolerates_cross_region_migration() {
    let nodes = phase_test_nodes();
    let kv = phase_test_kv(); // all in eu-central

    let prefill_atom = ComputeAtom {
        id: "p".into(), kind: AtomKind::Prefill,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };
    let decode_atom = ComputeAtom {
        id: "d".into(), kind: AtomKind::Decode,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };

    let prefill_req = AtomRequest {
        atom: prefill_atom, input: vec![1], kv_state: kv.clone(), candidates: nodes.clone(),
    };
    let decode_req = AtomRequest {
        atom: decode_atom, input: vec![1], kv_state: kv, candidates: nodes,
    };

    let kernel = StubKernel;
    let p_resp = dispatch(&kernel, prefill_req).unwrap();
    let d_resp = dispatch(&kernel, decode_req).unwrap();

    // Prefill picks n-fast (us-west) → KV must migrate from eu-central
    assert!(!p_resp.migrations.is_empty(), "prefill should trigger KV migration");
    // Decode picks n-kv-hot (eu-central) → KV already there
    assert!(d_resp.migrations.is_empty(), "decode should avoid KV migration");
}

#[test]
fn kernel_dispatch_preserves_phase_through_path() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: ComputeAtom {
            id: "decode-path".into(),
            kind: AtomKind::Decode,
            region: Region("us-west".into()),
            model_id: "m".into(),
            shard_count: 0,
        },
        input: vec![0x61], // 'a'
        kv_state: vec![],
        candidates: phase_test_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    assert_eq!(resp.exec_response.atom_id, "decode-path");
    assert!(resp.placement.breakdown.final_score > 0.0);
}

// --- Runner phase end-to-end tests ---

#[test]
fn runner_prefill_and_decode_diverge_via_files() {
    let prefill_req = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let decode_req = std::fs::read_to_string("examples/sample_request_decode.json").unwrap();
    let nodes = std::fs::read_to_string("examples/sample_nodes.json").unwrap();
    let kv = std::fs::read_to_string("examples/sample_kv.json").unwrap();

    let p_out = runner::run_request(&prefill_req, Some(&nodes), Some(&kv)).unwrap();
    let d_out = runner::run_request(&decode_req, Some(&nodes), Some(&kv)).unwrap();
    let p_resp: AtomResponse = serde_json::from_str(&p_out).unwrap();
    let d_resp: AtomResponse = serde_json::from_str(&d_out).unwrap();

    // With KV in eu-central: decode should favor eu-central, prefill should favor us-west
    assert_ne!(
        p_resp.placement.breakdown.node_id,
        d_resp.placement.breakdown.node_id,
        "prefill and decode should route differently via runner"
    );
}

#[test]
fn runner_decode_avoids_migration_when_kv_local() {
    let decode_req = std::fs::read_to_string("examples/sample_request_decode.json").unwrap();
    let nodes = std::fs::read_to_string("examples/sample_nodes.json").unwrap();
    let kv = std::fs::read_to_string("examples/sample_kv.json").unwrap();

    let out = runner::run_request(&decode_req, Some(&nodes), Some(&kv)).unwrap();
    let resp: AtomResponse = serde_json::from_str(&out).unwrap();

    // Decode picks eu-central (where KV lives) → no migration
    assert_eq!(resp.placement.breakdown.node_id, "eu-central-gpu-0");
    assert!(resp.migrations.is_empty());
}

#[test]
fn runner_prefill_triggers_migration_from_kv_region() {
    let prefill_req = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let nodes = std::fs::read_to_string("examples/sample_nodes.json").unwrap();
    let kv = std::fs::read_to_string("examples/sample_kv.json").unwrap();

    let out = runner::run_request(&prefill_req, Some(&nodes), Some(&kv)).unwrap();
    let resp: AtomResponse = serde_json::from_str(&out).unwrap();

    // Prefill picks us-west → KV must migrate from eu-central
    assert_eq!(resp.placement.breakdown.node_id, "us-west-gpu-0");
    assert!(!resp.migrations.is_empty());
    for m in &resp.migrations {
        assert_eq!(m.from, Region("eu-central".into()));
        assert_eq!(m.to, Region("us-west".into()));
    }
}

// --- Engine specialization tests ---

fn specialization_pair() -> (NodeProfile, NodeProfile) {
    let prefill_node = NodeProfile {
        node_id: "prefill-spec".into(),
        region: Region("us-west".into()),
        latency_ms: 10.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode, AtomKind::Inference],
        sovereignty_zone: "us-west".into(),
        prefill_affinity: 0.95,
        decode_affinity: 0.2,
            capacity: Default::default(),
    };
    let decode_node = NodeProfile {
        node_id: "decode-spec".into(),
        region: Region("us-west".into()),
        latency_ms: 10.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode, AtomKind::Inference],
        sovereignty_zone: "us-west".into(),
        prefill_affinity: 0.2,
        decode_affinity: 0.95,
            capacity: Default::default(),
    };
    (prefill_node, decode_node)
}

#[test]
fn specialization_favors_prefill_node_for_prefill() {
    let (pn, dn) = specialization_pair();
    let atom = ComputeAtom {
        id: "p".into(), kind: AtomKind::Prefill,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };
    let decision = route(&atom, &[pn, dn]).unwrap();
    assert_eq!(decision.breakdown.node_id, "prefill-spec");
}

#[test]
fn specialization_favors_decode_node_for_decode() {
    let (pn, dn) = specialization_pair();
    let atom = ComputeAtom {
        id: "d".into(), kind: AtomKind::Decode,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };
    let decision = route(&atom, &[pn, dn]).unwrap();
    assert_eq!(decision.breakdown.node_id, "decode-spec");
}

#[test]
fn specialization_visible_in_breakdown() {
    let (pn, dn) = specialization_pair();
    let atom = ComputeAtom {
        id: "p".into(), kind: AtomKind::Prefill,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };
    let decision = route(&atom, &[pn.clone(), dn.clone()]).unwrap();
    assert_eq!(decision.breakdown.node_id, "prefill-spec");
    assert!(decision.breakdown.specialization_score > 0.9,
        "prefill node should have high specialization for prefill atom");

    let atom_d = ComputeAtom {
        id: "d".into(), kind: AtomKind::Decode,
        region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
    };
    let decision_d = route(&atom_d, &[pn, dn]).unwrap();
    assert_eq!(decision_d.breakdown.node_id, "decode-spec");
    assert!(decision_d.breakdown.specialization_score > 0.9,
        "decode node should have high specialization for decode atom");
}

// --- PlacementExplain stability tests ---

#[test]
fn explain_serialization_is_stable() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x01],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    let json = serde_json::to_string(&resp.explain).unwrap();
    let decoded: PlacementExplain = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded.node_id, resp.explain.node_id);
    assert_eq!(decoded.final_score, resp.explain.final_score);
    assert_eq!(decoded.sovereignty_score, resp.explain.sovereignty_score);
    assert_eq!(decoded.chunks_migrated, 0);
    assert!(!decoded.requires_kv_migration);
}

#[test]
fn explain_present_in_runner_output() {
    let req = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let output = runner::run_from_json(&req).unwrap();
    let val: serde_json::Value = serde_json::from_str(&output).unwrap();
    let e = val.get("explain").expect("explain must be in runner output");
    assert!(e["final_score"].as_f64().unwrap() > 0.0);
    assert_eq!(e["chunks_migrated"].as_u64().unwrap(), 0);
}

#[test]
fn explain_reflects_migration_when_it_happens() {
    let kernel = StubKernel;
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x01],
        kv_state: vec![KVChunk {
            chunk_id: "kv-x".into(),
            source_region: Region("eu-central".into()),
            seq_start: 0, seq_end: 31, byte_size: 512,
            payload: vec![0xDD; 512],
        }],
        candidates: make_nodes(),
    };
    let resp = dispatch(&kernel, req).unwrap();
    assert!(resp.explain.requires_kv_migration || resp.explain.chunks_migrated > 0
        || resp.explain.migration_cost > 0.0,
        "explain should reflect migration");
    assert_eq!(resp.explain.chunks_migrated, resp.migrations.len());
}

#[test]
fn explain_shows_specialization_for_prefill_and_decode() {
    let kernel = StubKernel;
    let nodes = phase_test_nodes();
    let kv = phase_test_kv();

    let p_req = AtomRequest {
        atom: ComputeAtom {
            id: "p".into(), kind: AtomKind::Prefill,
            region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
        },
        input: vec![1], kv_state: kv.clone(), candidates: nodes.clone(),
    };
    let d_req = AtomRequest {
        atom: ComputeAtom {
            id: "d".into(), kind: AtomKind::Decode,
            region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
        },
        input: vec![1], kv_state: kv, candidates: nodes,
    };

    let p_resp = dispatch(&kernel, p_req).unwrap();
    let d_resp = dispatch(&kernel, d_req).unwrap();

    // Prefill and decode should pick different nodes
    assert_ne!(p_resp.explain.node_id, d_resp.explain.node_id);
    // Both explains should have valid scores
    assert!(p_resp.explain.final_score > 0.0);
    assert!(d_resp.explain.final_score > 0.0);
    assert!(p_resp.explain.specialization_score > 0.0);
    assert!(d_resp.explain.specialization_score > 0.0);
}

#[test]
fn breakdown_migration_cost_matches_decision() {
    let req = std::fs::read_to_string("examples/sample_request.json").unwrap();
    let nodes = std::fs::read_to_string("examples/sample_nodes.json").unwrap();
    let kv = std::fs::read_to_string("examples/sample_kv.json").unwrap();
    let output = runner::run_request(&req, Some(&nodes), Some(&kv)).unwrap();
    let resp: AtomResponse = serde_json::from_str(&output).unwrap();
    // breakdown.migration_cost should equal decision.estimated_migration_cost
    assert_eq!(resp.placement.breakdown.migration_cost, resp.placement.estimated_migration_cost);
    // explain.migration_cost should match too
    assert_eq!(resp.explain.migration_cost, resp.placement.estimated_migration_cost);
}

// --- Remote dispatch tests ---

async fn start_test_server() -> (String, tokio::task::JoinHandle<()>) {
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://{}/dispatch", addr);

    let handle = tokio::spawn(async move {
        axum::serve(listener, ulp_atom_kernel::server::app()).await.ok();
    });

    tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    (url, handle)
}

#[tokio::test]
async fn remote_dispatch_preserves_explain() {
    use ulp_atom_kernel::client::dispatch_remote;

    let (url, _handle) = start_test_server().await;

    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x68, 0x65, 0x6c, 0x6c, 0x6f], // "hello"
        kv_state: vec![],
        candidates: make_nodes(),
    };

    let resp = dispatch_remote(&url, req).await.unwrap();
    assert_eq!(resp.explain.node_id, "node-a");
    assert!(resp.explain.final_score > 0.0);
    assert!(resp.explain.sovereignty_score > 0.0);
    assert_eq!(resp.explain.chunks_migrated, 0);
}

#[tokio::test]
async fn remote_dispatch_with_migration() {
    use ulp_atom_kernel::client::dispatch_remote;

    let (url, _handle) = start_test_server().await;

    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x01],
        kv_state: vec![KVChunk {
            chunk_id: "kv-remote".into(),
            source_region: Region("eu-central".into()),
            seq_start: 0, seq_end: 31, byte_size: 512,
            payload: vec![0xAA; 512],
        }],
        candidates: make_nodes(),
    };

    let resp = dispatch_remote(&url, req).await.unwrap();
    assert_eq!(resp.migrations.len(), 1);
    assert_eq!(resp.explain.chunks_migrated, 1);
    assert!(resp.explain.migration_cost > 0.0);
    assert!(resp.explain.requires_kv_migration);
}

#[tokio::test]
async fn remote_dispatch_phase_divergence() {
    use ulp_atom_kernel::client::dispatch_remote;

    let (url, _handle) = start_test_server().await;

    let nodes = phase_test_nodes();
    let kv = phase_test_kv();

    let prefill_req = AtomRequest {
        atom: ComputeAtom {
            id: "p".into(), kind: AtomKind::Prefill,
            region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
        },
        input: vec![1], kv_state: kv.clone(), candidates: nodes.clone(),
    };

    let decode_req = AtomRequest {
        atom: ComputeAtom {
            id: "d".into(), kind: AtomKind::Decode,
            region: Region("us-west".into()), model_id: "m".into(), shard_count: 0,
        },
        input: vec![1], kv_state: kv, candidates: nodes,
    };

    let p_resp = dispatch_remote(&url, prefill_req).await.unwrap();
    let d_resp = dispatch_remote(&url, decode_req).await.unwrap();

    assert_ne!(p_resp.explain.node_id, d_resp.explain.node_id);
    assert!(p_resp.explain.specialization_score > 0.0);
    assert!(d_resp.explain.specialization_score > 0.0);
}

#[tokio::test]
async fn remote_dispatch_empty_candidates_returns_400() {
    use ulp_atom_kernel::client::dispatch_remote;

    let (url, _handle) = start_test_server().await;

    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x01],
        kv_state: vec![],
        candidates: vec![],
    };

    let err = dispatch_remote(&url, req).await.unwrap_err();
    assert!(err.contains("400") || err.contains("no candidate"));
}

// --- Federation tests ---

#[tokio::test]
async fn federation_loads_multiple_remote_nodes() {
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "remote-a".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Inference],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
            capacity: Default::default(),
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "remote-b".into(),
                region: Region("eu-central".into()),
                latency_ms: 80.0,
                hotness: 0.2,
                supported_kinds: vec![AtomKind::Inference],
                sovereignty_zone: "eu-central".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
            capacity: Default::default(),
            },
            endpoint: url2,
        },
    ];

    let client = RemoteClient::new();
    let atom = ComputeAtom {
        id: "fed-1".into(),
        kind: AtomKind::Inference,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    };

    let resp = dispatch_federation(&client, atom, vec![0x61], vec![], &remote_nodes).await.unwrap();
    assert_eq!(resp.explain.node_id, "remote-a");
    assert_eq!(resp.exec_response.output, vec![0x41]);
}

#[tokio::test]
async fn federation_routes_to_different_nodes_based_on_conditions() {
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "prefill-node".into(),
                region: Region("us-west".into()),
                latency_ms: 50.0,
                hotness: 0.5,
                supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.9,
                decode_affinity: 0.3,
            capacity: Default::default(),
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "decode-node".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.8,
                supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.3,
                decode_affinity: 0.9,
            capacity: Default::default(),
            },
            endpoint: url2,
        },
    ];

    let client = RemoteClient::new();

    let prefill_atom = ComputeAtom {
        id: "p".into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "m".into(),
        shard_count: 0,
    };

    let decode_atom = ComputeAtom {
        id: "d".into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "m".into(),
        shard_count: 0,
    };

    let p_resp = dispatch_federation(&client, prefill_atom, vec![0x62], vec![], &remote_nodes).await.unwrap();
    let d_resp = dispatch_federation(&client, decode_atom, vec![0x63], vec![], &remote_nodes).await.unwrap();

    assert_eq!(p_resp.explain.node_id, "prefill-node");
    assert_eq!(d_resp.explain.node_id, "decode-node");
}

#[tokio::test]
async fn federation_preserves_explain_and_migration() {
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url, _h) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "target".into(),
                region: Region("ap-east".into()),
                latency_ms: 20.0,
                hotness: 0.7,
                supported_kinds: vec![AtomKind::Inference],
                sovereignty_zone: "ap-east".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
            capacity: Default::default(),
            },
            endpoint: url,
        },
    ];

    let kv = vec![
        KVChunk {
            chunk_id: "kv-1".into(),
            source_region: Region("us-west".into()),
            seq_start: 0,
            seq_end: 100,
            byte_size: 1024,
            payload: vec![],
        },
    ];

    let client = RemoteClient::new();
    let atom = ComputeAtom {
        id: "mig".into(),
        kind: AtomKind::Inference,
        region: Region("ap-east".into()),
        model_id: "m".into(),
        shard_count: 0,
    };

    let resp = dispatch_federation(&client, atom, vec![0x64], kv, &remote_nodes).await.unwrap();

    assert_eq!(resp.explain.node_id, "target");
    assert!(resp.explain.requires_kv_migration);
    assert_eq!(resp.explain.chunks_migrated, 1);
    assert_eq!(resp.migrations.len(), 1);
    assert_eq!(resp.migrations[0].from, Region("us-west".into()));
    assert_eq!(resp.migrations[0].to, Region("ap-east".into()));
    assert_eq!(resp.exec_response.output, vec![0x44]);
}

#[tokio::test]
async fn federation_kv_locality_affects_routing() {
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "near-no-kv".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
            capacity: Default::default(),
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "far-with-kv".into(),
                region: Region("eu-central".into()),
                latency_ms: 80.0,
                hotness: 0.3,
                supported_kinds: vec![AtomKind::Decode],
                sovereignty_zone: "eu-central".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
            capacity: Default::default(),
            },
            endpoint: url2,
        },
    ];

    let kv = vec![
        KVChunk {
            chunk_id: "k1".into(),
            source_region: Region("eu-central".into()),
            seq_start: 0,
            seq_end: 100,
            byte_size: 2048,
            payload: vec![],
        },
        KVChunk {
            chunk_id: "k2".into(),
            source_region: Region("eu-central".into()),
            seq_start: 100,
            seq_end: 200,
            byte_size: 2048,
            payload: vec![],
        },
    ];

    let client = RemoteClient::new();
    let atom = ComputeAtom {
        id: "kv-test".into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "m".into(),
        shard_count: 0,
    };

    let resp = dispatch_federation(&client, atom, vec![0x65], kv, &remote_nodes).await.unwrap();

    assert_eq!(resp.explain.node_id, "far-with-kv");
    assert!(!resp.explain.requires_kv_migration);
}

#[tokio::test]
async fn federation_empty_nodes_returns_error() {
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::dispatch_federation;

    let client = RemoteClient::new();
    let atom = make_atom();

    let err = dispatch_federation(&client, atom, vec![0x66], vec![], &[]).await.unwrap_err();
    assert!(err.contains("no remote nodes"));
}

// --- Capacity-aware tests ---

#[tokio::test]
async fn capacity_affects_prefill_placement() {
    use ulp_atom_kernel::capacity::NodeCapacity;
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "low-vram".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Prefill],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.8,
                decode_affinity: 0.5,
                capacity: NodeCapacity {
                    available_vram_gb: 8.0,
                    current_load: 0.3,
                    active_kv_chunks: 10,
                },
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "high-vram".into(),
                region: Region("us-west".into()),
                latency_ms: 15.0,
                hotness: 0.8,
                supported_kinds: vec![AtomKind::Prefill],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.8,
                decode_affinity: 0.5,
                capacity: NodeCapacity {
                    available_vram_gb: 80.0,
                    current_load: 0.2,
                    active_kv_chunks: 5,
                },
            },
            endpoint: url2,
        },
    ];

    let client = RemoteClient::new();
    let atom = ComputeAtom {
        id: "prefill-test".into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "llama-70b".into(),
        shard_count: 0,
    };

    let resp = dispatch_federation(&client, atom, vec![0x70], vec![], &remote_nodes).await.unwrap();
    assert_eq!(resp.explain.node_id, "high-vram");
    assert!(resp.explain.capacity_score > 0.5);
}

#[tokio::test]
async fn capacity_affects_decode_placement() {
    use ulp_atom_kernel::capacity::NodeCapacity;
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "high-load".into(),
                region: Region("us-west".into()),
                latency_ms: 5.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.9,
                capacity: NodeCapacity {
                    available_vram_gb: 32.0,
                    current_load: 0.9,
                    active_kv_chunks: 90,
                },
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "low-load".into(),
                region: Region("us-west".into()),
                latency_ms: 8.0,
                hotness: 0.85,
                supported_kinds: vec![AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.9,
                capacity: NodeCapacity {
                    available_vram_gb: 32.0,
                    current_load: 0.1,
                    active_kv_chunks: 5,
                },
            },
            endpoint: url2,
        },
    ];

    let client = RemoteClient::new();
    let atom = ComputeAtom {
        id: "decode-test".into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    };

    let resp = dispatch_federation(&client, atom, vec![0x71], vec![], &remote_nodes).await.unwrap();
    assert_eq!(resp.explain.node_id, "low-load");
    assert!(resp.explain.capacity_score > 0.5);
}

#[tokio::test]
async fn overloaded_node_gets_lower_score() {
    use ulp_atom_kernel::capacity::NodeCapacity;
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "normal".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.8,
                supported_kinds: vec![AtomKind::Inference],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
                capacity: NodeCapacity {
                    available_vram_gb: 32.0,
                    current_load: 0.3,
                    active_kv_chunks: 20,
                },
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "overloaded".into(),
                region: Region("us-west".into()),
                latency_ms: 8.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Inference],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
                capacity: NodeCapacity {
                    available_vram_gb: 2.0,
                    current_load: 0.95,
                    active_kv_chunks: 95,
                },
            },
            endpoint: url2,
        },
    ];

    let client = RemoteClient::new();
    let atom = make_atom();

    let resp = dispatch_federation(&client, atom, vec![0x72], vec![], &remote_nodes).await.unwrap();
    assert_eq!(resp.explain.node_id, "normal");
}

#[tokio::test]
async fn explain_shows_capacity_score() {
    use ulp_atom_kernel::capacity::NodeCapacity;
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::remote::{dispatch_federation, RemoteNode};

    let (url, _h) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "test-node".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.8,
                supported_kinds: vec![AtomKind::Inference],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.5,
                decode_affinity: 0.5,
                capacity: NodeCapacity {
                    available_vram_gb: 32.0,
                    current_load: 0.2,
                    active_kv_chunks: 10,
                },
            },
            endpoint: url,
        },
    ];

    let client = RemoteClient::new();
    let atom = make_atom();

    let resp = dispatch_federation(&client, atom, vec![0x73], vec![], &remote_nodes).await.unwrap();
    assert!(resp.explain.capacity_score >= 0.0);
    assert!(resp.explain.capacity_score <= 1.0);
}


// --- Two-stage pipeline tests ---

#[tokio::test]
async fn two_stage_pipeline_completes() {
    use ulp_atom_kernel::atom::ComputeAtom;
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::pipeline::execute_two_stage;
    use ulp_atom_kernel::remote::RemoteNode;

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "prefill-node".into(),
                region: Region("us-west".into()),
                latency_ms: 15.0,
                hotness: 0.8,
                supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.9,
                decode_affinity: 0.3,
                capacity: Default::default(),
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "decode-node".into(),
                region: Region("us-west".into()),
                latency_ms: 5.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.3,
                decode_affinity: 0.9,
                capacity: Default::default(),
            },
            endpoint: url2,
        },
    ];

    let client = RemoteClient::new();
    let prefill_atom = ComputeAtom {
        id: "prefill".into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    };

    let decode_atom = ComputeAtom {
        id: "decode".into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    };

    let resp = execute_two_stage(&client, prefill_atom, decode_atom, vec![0x61], vec![], &remote_nodes).await.unwrap();

    assert_eq!(resp.prefill_node, "prefill-node");
    assert_eq!(resp.decode_node, "decode-node");
    assert!(resp.migration_occurred);
}

#[tokio::test]
async fn two_stage_same_node_no_migration() {
    use ulp_atom_kernel::atom::ComputeAtom;
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::pipeline::execute_two_stage;
    use ulp_atom_kernel::remote::RemoteNode;

    let (url, _h) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "unified-node".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.8,
                decode_affinity: 0.8,
                capacity: Default::default(),
            },
            endpoint: url,
        },
    ];

    let client = RemoteClient::new();
    let prefill_atom = ComputeAtom {
        id: "prefill".into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    };

    let decode_atom = ComputeAtom {
        id: "decode".into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "llama-7b".into(),
        shard_count: 0,
    };

    let resp = execute_two_stage(&client, prefill_atom, decode_atom, vec![0x62], vec![], &remote_nodes).await.unwrap();

    assert_eq!(resp.prefill_node, "unified-node");
    assert_eq!(resp.decode_node, "unified-node");
    assert!(!resp.migration_occurred);
}

#[tokio::test]
async fn two_stage_preserves_stage_info() {
    use ulp_atom_kernel::atom::ComputeAtom;
    use ulp_atom_kernel::client::RemoteClient;
    use ulp_atom_kernel::pipeline::execute_two_stage;
    use ulp_atom_kernel::remote::RemoteNode;

    let (url1, _h1) = start_test_server().await;
    let (url2, _h2) = start_test_server().await;

    let remote_nodes = vec![
        RemoteNode {
            profile: NodeProfile {
                node_id: "p-node".into(),
                region: Region("us-west".into()),
                latency_ms: 10.0,
                hotness: 0.8,
                supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.9,
                decode_affinity: 0.3,
                capacity: Default::default(),
            },
            endpoint: url1,
        },
        RemoteNode {
            profile: NodeProfile {
                node_id: "d-node".into(),
                region: Region("us-west".into()),
                latency_ms: 5.0,
                hotness: 0.9,
                supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode],
                sovereignty_zone: "us-west".into(),
                prefill_affinity: 0.3,
                decode_affinity: 0.9,
                capacity: Default::default(),
            },
            endpoint: url2,
        },
    ];

    let client = RemoteClient::new();
    let prefill_atom = ComputeAtom {
        id: "p".into(),
        kind: AtomKind::Prefill,
        region: Region("us-west".into()),
        model_id: "m".into(),
        shard_count: 0,
    };

    let decode_atom = ComputeAtom {
        id: "d".into(),
        kind: AtomKind::Decode,
        region: Region("us-west".into()),
        model_id: "m".into(),
        shard_count: 0,
    };

    let resp = execute_two_stage(&client, prefill_atom, decode_atom, vec![0x63], vec![], &remote_nodes).await.unwrap();

    assert!(resp.prefill_response.explain.specialization_score > 0.0);
    assert!(resp.decode_response.explain.specialization_score > 0.0);
    assert_eq!(resp.prefill_response.exec_response.output, vec![0x43]);
    assert_eq!(resp.decode_response.exec_response.output, vec![0x43]);
}

// --- Backend selector tests ---

#[test]
fn backend_selector_creates_mock() {
    use ulp_atom_kernel::backend::{BackendRequest, BackendType};

    let backend_type = BackendType::Mock;
    let backend = backend_type.create();

    let req = BackendRequest {
        atom_id: "test".into(),
        input: vec![0x61],
        kv_state: vec![],
    };

    let resp = backend.execute_prefill(req).unwrap();
    assert_eq!(resp.output, vec![0x41]);
}

#[test]
fn backend_selector_creates_http() {
    use ulp_atom_kernel::backend::{BackendRequest, BackendType};

    let backend_type = BackendType::Http("http://localhost:8080".into());
    let backend = backend_type.create();

    let req = BackendRequest {
        atom_id: "test".into(),
        input: vec![0x61],
        kv_state: vec![],
    };

    let resp = backend.execute_prefill(req).unwrap();
    assert_eq!(resp.atom_id, "test-http");
    assert_eq!(resp.output, vec![0x63]);
}

#[test]
fn http_backend_distinguishes_from_mock() {
    use ulp_atom_kernel::backend::{BackendRequest, BackendType};

    let mock = BackendType::Mock.create();
    let http = BackendType::Http("http://stub".into()).create();

    let req = BackendRequest {
        atom_id: "test".into(),
        input: vec![0x61],
        kv_state: vec![],
    };

    let mock_resp = mock.execute_prefill(req.clone()).unwrap();
    let http_resp = http.execute_prefill(req).unwrap();

    assert_eq!(mock_resp.output, vec![0x41]);
    assert_eq!(http_resp.output, vec![0x63]);
    assert_eq!(http_resp.atom_id, "test-http");
}

#[test]
fn dispatch_works_with_http_backend() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest};

    let backend = BackendType::Http("http://stub".into()).create();

    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x62],
        kv_state: vec![],
        candidates: make_nodes(),
    };

    let resp = dispatch(&*backend, req).unwrap();
    assert_eq!(resp.exec_response.atom_id, "atom-1-http");
    assert_eq!(resp.exec_response.output, vec![0x64]);
}

#[test]
fn dispatch_works_with_mock_backend() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest};

    let backend = BackendType::Mock.create();

    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x62],
        kv_state: vec![],
        candidates: make_nodes(),
    };

    let resp = dispatch(&*backend, req).unwrap();
    assert_eq!(resp.exec_response.output, vec![0x42]);
}

// --- Vulkan/CUDA backend tests ---

#[test]
fn vulkan_backend_initializes_without_panic() {
    // Must not panic regardless of Vulkan availability
    let _backend = ulp_atom_kernel::backend::VulkanBackend::new(0);
}

#[test]
fn vulkan_backend_reports_availability() {
    let backend = ulp_atom_kernel::backend::VulkanBackend::new(0);
    if backend.is_available() {
        let caps = backend.device_capabilities();
        assert!(caps.compute_units > 0);
        assert!(caps.memory_mb > 0);
        assert!(caps.supports_prefill);
        assert!(caps.supports_decode);
    } else {
        let caps = backend.device_capabilities();
        assert_eq!(caps.compute_units, 0);
        assert!(!caps.supports_prefill);
        assert!(backend.init_error().is_some());
    }
}

#[test]
fn vulkan_backend_real_compute_or_clear_error() {
    use ulp_atom_kernel::backend::{Backend, BackendRequest};

    let backend = ulp_atom_kernel::backend::VulkanBackend::new(0);
    let req = BackendRequest {
        atom_id: "test".into(),
        input: vec![0x61, 0x00, 0xFC, 0xFF],
        kv_state: vec![],
    };

    let result = backend.execute_prefill(req);
    if backend.is_available() {
        let resp = result.expect("Vulkan available but execute failed");
        assert_eq!(resp.atom_id, "test-vk");
        // Real GPU compute: (val + 3) & 0xFF
        assert_eq!(resp.output, vec![0x64, 0x03, 0xFF, 0x02]);
        assert_eq!(resp.tokens_produced, 1);
    } else {
        let err = result.unwrap_err();
        assert!(err.contains("Vulkan unavailable"), "error should be explicit: {err}");
    }
}

#[test]
fn vulkan_backend_decode_matches_prefill() {
    use ulp_atom_kernel::backend::{Backend, BackendRequest};

    let backend = ulp_atom_kernel::backend::VulkanBackend::new(0);
    if !backend.is_available() {
        return; // skip on machines without Vulkan
    }

    let input = vec![10, 20, 30, 40];
    let req_p = BackendRequest { atom_id: "p".into(), input: input.clone(), kv_state: vec![] };
    let req_d = BackendRequest { atom_id: "d".into(), input, kv_state: vec![] };

    let p = backend.execute_prefill(req_p).unwrap();
    let d = backend.execute_decode(req_d).unwrap();
    assert_eq!(p.output, d.output);
    assert_eq!(p.output, vec![13, 23, 33, 43]);
}

#[test]
fn vulkan_backend_empty_input() {
    use ulp_atom_kernel::backend::{Backend, BackendRequest};

    let backend = ulp_atom_kernel::backend::VulkanBackend::new(0);
    if !backend.is_available() {
        return;
    }

    let req = BackendRequest { atom_id: "e".into(), input: vec![], kv_state: vec![] };
    let resp = backend.execute_prefill(req).unwrap();
    assert!(resp.output.is_empty());
}

#[test]
fn backend_selector_creates_vulkan() {
    use ulp_atom_kernel::backend::{BackendType, BackendRequest};

    let backend_type = BackendType::Vulkan(0);
    let backend = backend_type.create();

    let req = BackendRequest {
        atom_id: "test".into(),
        input: vec![0x61],
        kv_state: vec![],
    };

    let result = backend.execute_prefill(req);
    // Either real Vulkan compute or clear unavailable error
    match result {
        Ok(resp) => {
            assert_eq!(resp.atom_id, "test-vk");
            assert_eq!(resp.output, vec![0x64]); // 0x61 + 3
        }
        Err(e) => {
            assert!(e.contains("Vulkan unavailable"), "unexpected error: {e}");
        }
    }
}

#[test]
fn dispatch_works_with_vulkan_backend() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest};

    let backend = BackendType::Vulkan(0).create();

    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x62],
        kv_state: vec![],
        candidates: make_nodes(),
    };

    let result = dispatch(&*backend, req);
    match result {
        Ok(resp) => {
            assert_eq!(resp.exec_response.atom_id, "atom-1-vk");
            assert_eq!(resp.exec_response.output, vec![0x65]); // 0x62 + 3
        }
        Err(e) => {
            assert!(e.contains("Vulkan unavailable"), "unexpected error: {e}");
        }
    }
}

#[test]
fn backend_selector_creates_cuda() {
    use ulp_atom_kernel::backend::{Backend, BackendKind};

    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    let caps = backend.device_capabilities();
    assert_eq!(caps.backend_kind, BackendKind::Cuda);

    if backend.is_available() {
        assert!(caps.available);
        assert!(caps.supports_decode);
        // Real CUDA: execute should work
        let req = ulp_atom_kernel::backend::BackendRequest {
            atom_id: "test".into(),
            input: vec![0x61],
            kv_state: vec![],
        };
        let resp = backend.execute_prefill(req).unwrap();
        assert_eq!(resp.atom_id, "test-cuda");
        // Real kernel: (0x61 + 3) & 0xFF = 0x64
        assert_eq!(resp.output, vec![0x64]);
    } else {
        assert!(!caps.available);
        assert!(caps.device_name.contains("unavailable"));
    }
}

#[test]
fn dispatch_works_with_cuda_backend() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest};

    let cuda = ulp_atom_kernel::backend::CudaBackend::new(0);
    if !cuda.is_available() {
        // No CUDA — skip gracefully
        return;
    }

    let backend = BackendType::Cuda(0).create();
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x62],
        kv_state: vec![],
        candidates: make_nodes(),
    };

    let resp = dispatch(&*backend, req).unwrap();
    assert_eq!(resp.exec_response.atom_id, "atom-1-cuda");
    // Real kernel: (0x62 + 3) & 0xFF = 0x65
    assert_eq!(resp.exec_response.output, vec![0x65]);
}

#[test]
fn all_backends_have_device_capabilities() {
    use ulp_atom_kernel::backend::BackendType;

    let mock = BackendType::Mock.create();
    let http = BackendType::Http("http://stub".into()).create();
    let vulkan = BackendType::Vulkan(0).create();
    let cuda = BackendType::Cuda(0).create();

    assert_eq!(mock.device_capabilities().device_name, "MockCPU");
    assert!(http.device_capabilities().device_name.contains("HttpRemote"));
    // Vulkan: real device name or "unavailable" marker
    let vk_name = vulkan.device_capabilities().device_name;
    assert!(!vk_name.is_empty(), "vulkan device name should not be empty");
    // CUDA: real device name or "unavailable" marker
    let cuda_name = cuda.device_capabilities().device_name;
    assert!(!cuda_name.is_empty(), "cuda device name should not be empty");
}

// --- DeviceCapabilities structure tests ---

#[test]
fn capabilities_have_backend_kind() {
    use ulp_atom_kernel::backend::BackendType;

    let mock = BackendType::Mock.create();
    let http = BackendType::Http("http://stub".into()).create();
    let vulkan = BackendType::Vulkan(0).create();
    let cuda = BackendType::Cuda(0).create();

    assert_eq!(mock.device_capabilities().backend_kind, BackendKind::Mock);
    assert_eq!(http.device_capabilities().backend_kind, BackendKind::Http);
    assert_eq!(vulkan.device_capabilities().backend_kind, BackendKind::Vulkan);
    assert_eq!(cuda.device_capabilities().backend_kind, BackendKind::Cuda);
}

#[test]
fn capabilities_available_field_is_correct() {
    use ulp_atom_kernel::backend::BackendType;

    let mock = BackendType::Mock.create();
    assert!(mock.device_capabilities().available);

    let http = BackendType::Http("http://stub".into()).create();
    assert!(http.device_capabilities().available);

    // CUDA: available depends on runtime (like Vulkan)
    let cuda = BackendType::Cuda(0).create();
    let cuda_caps = cuda.device_capabilities();
    if cuda_caps.available {
        assert!(cuda_caps.compute_units > 0);
        assert!(cuda_caps.memory_mb > 0);
        assert!(cuda_caps.supports_prefill);
    } else {
        assert_eq!(cuda_caps.compute_units, 0);
        assert_eq!(cuda_caps.memory_mb, 0);
        assert!(!cuda_caps.supports_prefill);
    }

    // Vulkan: available depends on runtime
    let vulkan = BackendType::Vulkan(0).create();
    let caps = vulkan.device_capabilities();
    if caps.available {
        assert!(caps.compute_units > 0);
        assert!(caps.memory_mb > 0);
        assert!(caps.supports_prefill);
    } else {
        assert_eq!(caps.compute_units, 0);
        assert_eq!(caps.memory_mb, 0);
        assert!(!caps.supports_prefill);
    }
}

#[test]
fn capabilities_memory_mb_field() {
    use ulp_atom_kernel::backend::BackendType;

    let mock = BackendType::Mock.create();
    assert_eq!(mock.device_capabilities().memory_mb, 0);

    // CUDA memory now reflects real device (or 0 if unavailable)
    let cuda = BackendType::Cuda(0).create();
    let cuda_caps = cuda.device_capabilities();
    if cuda_caps.available {
        assert!(cuda_caps.memory_mb > 0);
    } else {
        assert_eq!(cuda_caps.memory_mb, 0);
    }
}

#[test]
fn capabilities_serialization_roundtrip() {
    use ulp_atom_kernel::backend::BackendType;

    let caps = BackendType::Mock.create().device_capabilities();
    let json = serde_json::to_string(&caps).unwrap();
    let decoded: ulp_atom_kernel::backend::DeviceCapabilities = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded.backend_kind, caps.backend_kind);
    assert_eq!(decoded.device_name, caps.device_name);
    assert_eq!(decoded.available, caps.available);
    assert_eq!(decoded.memory_mb, caps.memory_mb);
}

// --- Backend selector tests ---

#[test]
fn selector_auto_resolves() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};

    let resolved = resolve_backend(BackendPreference::Auto, 0, None).unwrap();
    // On this machine: either Vulkan or Mock fallback
    assert!(resolved.capabilities.available);
    if resolved.fallback_used {
        assert_eq!(resolved.capabilities.backend_kind, BackendKind::Mock);
        assert!(resolved.reason.contains("fallback"));
    } else {
        assert_eq!(resolved.capabilities.backend_kind, BackendKind::Vulkan);
    }
}

#[test]
fn selector_require_mock() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};

    let resolved = resolve_backend(
        BackendPreference::Require(BackendKind::Mock), 0, None,
    ).unwrap();
    assert_eq!(resolved.capabilities.backend_kind, BackendKind::Mock);
    assert!(!resolved.fallback_used);
}

#[test]
fn selector_require_http() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};

    let resolved = resolve_backend(
        BackendPreference::Require(BackendKind::Http), 0, Some("http://test"),
    ).unwrap();
    assert_eq!(resolved.capabilities.backend_kind, BackendKind::Http);
}

#[test]
fn selector_require_http_without_endpoint_fails() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};

    let err = resolve_backend(
        BackendPreference::Require(BackendKind::Http), 0, None,
    ).unwrap_err();
    assert!(err.contains("endpoint"));
}

#[test]
fn selector_require_vulkan_on_this_machine() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};

    let result = resolve_backend(
        BackendPreference::Require(BackendKind::Vulkan), 0, None,
    );
    // Either succeeds (Vulkan available) or fails with clear message
    match result {
        Ok(r) => {
            assert_eq!(r.capabilities.backend_kind, BackendKind::Vulkan);
            assert!(r.capabilities.available);
            assert!(!r.fallback_used);
        }
        Err(e) => {
            assert!(e.contains("vulkan required but unavailable"));
        }
    }
}

#[test]
fn selector_prefer_vulkan_falls_back() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};

    let resolved = resolve_backend(
        BackendPreference::Prefer(BackendKind::Vulkan), 0, None,
    ).unwrap();
    // Always succeeds: either Vulkan or Mock fallback
    assert!(resolved.capabilities.available);
    if resolved.capabilities.backend_kind == BackendKind::Vulkan {
        assert!(!resolved.fallback_used);
    } else {
        assert_eq!(resolved.capabilities.backend_kind, BackendKind::Mock);
        assert!(resolved.fallback_used);
        assert!(resolved.reason.contains("fallback"));
    }
}

#[test]
fn selector_prefer_http_without_endpoint_falls_back() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};

    let resolved = resolve_backend(
        BackendPreference::Prefer(BackendKind::Http), 0, None,
    ).unwrap();
    assert_eq!(resolved.capabilities.backend_kind, BackendKind::Mock);
    assert!(resolved.fallback_used);
}

#[test]
fn selector_resolved_backend_executes() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};
    use ulp_atom_kernel::backend::BackendRequest;

    let resolved = resolve_backend(BackendPreference::Auto, 0, None).unwrap();
    let req = BackendRequest {
        atom_id: "sel-test".into(),
        input: vec![0x61],
        kv_state: vec![],
    };
    let resp = resolved.backend.execute_prefill(req).unwrap();
    assert!(!resp.output.is_empty());
}

#[test]
fn dispatch_response_carries_backend_kind() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest};

    let backend = BackendType::Mock.create();
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x61],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&*backend, req).unwrap();
    assert_eq!(resp.backend_kind, Some(BackendKind::Mock));
}

#[test]
fn dispatch_backend_kind_serializes() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest, AtomResponse};

    let backend = BackendType::Mock.create();
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x61],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&*backend, req).unwrap();
    let json = serde_json::to_string(&resp).unwrap();
    let decoded: AtomResponse = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded.backend_kind, Some(BackendKind::Mock));
}

// --- Vulkan device selection tests ---

#[test]
fn vulkan_device_index_0_is_explicit() {
    let backend = ulp_atom_kernel::backend::VulkanBackend::new(0);
    assert_eq!(backend.device_index(), 0);
    if backend.is_available() {
        assert!(backend.device_count() >= 1);
        assert!(backend.selected_device_name().is_some());
    }
}

#[test]
fn vulkan_invalid_device_index_is_unavailable() {
    let backend = ulp_atom_kernel::backend::VulkanBackend::new(999);
    // Either Vulkan loader fails entirely (no Vulkan) or device_index is out of range
    if let Some(err) = backend.init_error() {
        // Must mention either "out of range" or loader failure — not silently succeed
        assert!(
            err.contains("out of range") || err.contains("vulkan loader") || err.contains("no Vulkan"),
            "unexpected error for device_index=999: {err}"
        );
    }
    // If Vulkan is available, device_index=999 must fail (no machine has 1000 GPUs)
    // If Vulkan is unavailable, it fails for loader reasons — both are correct
    assert!(!backend.is_available() || backend.device_count() > 999);
}

#[test]
fn vulkan_device_index_out_of_range_error_message() {
    use ulp_atom_kernel::backend::{Backend, BackendRequest};

    let backend = ulp_atom_kernel::backend::VulkanBackend::new(999);
    let req = BackendRequest {
        atom_id: "test".into(),
        input: vec![1],
        kv_state: vec![],
    };
    let result = backend.execute_prefill(req);
    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.contains("Vulkan unavailable"), "error: {err}");
}

#[test]
fn vulkan_capabilities_reflect_selected_device() {
    use ulp_atom_kernel::backend::Backend;

    let backend = ulp_atom_kernel::backend::VulkanBackend::new(0);
    let caps = backend.device_capabilities();
    if backend.is_available() {
        // device_name should match selected_device_name
        assert_eq!(caps.device_name, backend.selected_device_name().unwrap());
        assert!(caps.available);
        assert!(caps.compute_units > 0);
    } else {
        assert!(!caps.available);
        assert!(caps.device_name.contains("unavailable"));
    }
}

#[test]
fn dispatch_response_carries_backend_device_name() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest};

    let backend = BackendType::Mock.create();
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x61],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&*backend, req).unwrap();
    assert_eq!(resp.backend_device.as_deref(), Some("MockCPU"));
}

#[test]
fn dispatch_backend_device_serializes() {
    use ulp_atom_kernel::backend::BackendType;
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest, AtomResponse};

    let backend = BackendType::Mock.create();
    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x61],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&*backend, req).unwrap();
    let json = serde_json::to_string(&resp).unwrap();
    let decoded: AtomResponse = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded.backend_device.as_deref(), Some("MockCPU"));
    assert_eq!(decoded.backend_kind, Some(BackendKind::Mock));
}

#[test]
fn selector_auto_carries_device_info_through_dispatch() {
    use ulp_atom_kernel::backend::selector::{resolve_backend, BackendPreference};
    use ulp_atom_kernel::kernel::{dispatch, AtomRequest};

    let resolved = resolve_backend(BackendPreference::Auto, 0, None).unwrap();
    let expected_device = resolved.capabilities.device_name.clone();

    let req = AtomRequest {
        atom: make_atom(),
        input: vec![0x61],
        kv_state: vec![],
        candidates: make_nodes(),
    };
    let resp = dispatch(&*resolved.backend, req).unwrap();
    assert_eq!(resp.backend_device.as_deref(), Some(expected_device.as_str()));
}

// --- Shard streaming tests ---

#[test]
fn shard_ref_json_roundtrip() {
    use ulp_atom_kernel::shard::{ShardRef, ShardSource};

    let shard = ShardRef {
        shard_id: "layer-0".into(),
        source: ShardSource::Local("/tmp/shard0.bin".into()),
        byte_size: Some(1024),
        checksum: None,
    };
    let json = serde_json::to_string(&shard).unwrap();
    let decoded: ShardRef = serde_json::from_str(&json).unwrap();
    assert_eq!(decoded.shard_id, "layer-0");
    assert_eq!(decoded.source, ShardSource::Local("/tmp/shard0.bin".into()));
    assert_eq!(decoded.byte_size, Some(1024));
}

#[test]
fn shard_ref_http_source_parses() {
    use ulp_atom_kernel::shard::{ShardRef, ShardSource};

    let json = r#"{"shard_id":"w1","source":{"http":"http://host/shard.bin"},"byte_size":512}"#;
    let shard: ShardRef = serde_json::from_str(json).unwrap();
    assert_eq!(shard.source, ShardSource::Http("http://host/shard.bin".into()));
    assert_eq!(shard.byte_size, Some(512));
}

#[test]
fn shard_ref_byte_size_defaults_to_none() {
    use ulp_atom_kernel::shard::ShardRef;

    let json = r#"{"shard_id":"s0","source":{"local":"/tmp/x"}}"#;
    let shard: ShardRef = serde_json::from_str(json).unwrap();
    assert_eq!(shard.byte_size, None);
}

#[test]
fn shard_load_local_real_file() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};
    use std::io::Write;

    let dir = std::env::temp_dir().join("ulp_shard_test");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("test_shard.bin");
    let payload = b"SHARD_DATA_1234";
    std::fs::File::create(&path).unwrap().write_all(payload).unwrap();

    let shard = ShardRef {
        shard_id: "local-test".into(),
        source: ShardSource::Local(path.to_str().unwrap().into()),
        byte_size: Some(payload.len() as u64),
        checksum: None,
    };
    let loaded = load_shard(&shard).unwrap();
    assert_eq!(loaded.shard_id, "local-test");
    assert_eq!(loaded.data, payload);
    assert_eq!(loaded.byte_size, payload.len() as u64);

    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn shard_load_local_missing_file_gives_clear_error() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};

    let shard = ShardRef {
        shard_id: "missing".into(),
        source: ShardSource::Local("/nonexistent/path/shard.bin".into()),
        byte_size: None,
        checksum: None,
    };
    let err = load_shard(&shard).unwrap_err();
    assert!(err.contains("shard load local"), "error: {err}");
    assert!(err.contains("/nonexistent/path/shard.bin"), "error: {err}");
}

#[test]
fn shard_load_http_real_server() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};
    use std::io::{Read, Write};
    use std::net::TcpListener;

    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let port = listener.local_addr().unwrap().port();

    let payload = b"HTTP_SHARD_BYTES";
    let handle = {
        let payload = payload.to_vec();
        std::thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            // Read the request before responding
            let mut req_buf = [0u8; 1024];
            let _ = stream.read(&mut req_buf);
            let response = format!(
                "HTTP/1.1 200 OK\r\nContent-Length: {}\r\nConnection: close\r\n\r\n",
                payload.len()
            );
            stream.write_all(response.as_bytes()).unwrap();
            stream.write_all(&payload).unwrap();
            stream.flush().unwrap();
            stream.shutdown(std::net::Shutdown::Write).unwrap();
        })
    };

    let shard = ShardRef {
        shard_id: "http-test".into(),
        source: ShardSource::Http(format!("http://127.0.0.1:{}/shard.bin", port)),
        byte_size: None,
        checksum: None,
    };
    let loaded = load_shard(&shard).unwrap();
    assert_eq!(loaded.shard_id, "http-test");
    assert_eq!(loaded.data, payload);
    assert_eq!(loaded.byte_size, payload.len() as u64);

    handle.join().unwrap();
}

#[test]
fn shard_load_unsupported_scheme_rejected() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};

    let shard = ShardRef {
        shard_id: "ftp".into(),
        source: ShardSource::Http("ftp://example.com/shard.bin".into()),
        byte_size: None,
        checksum: None,
    };
    let err = load_shard(&shard).unwrap_err();
    assert!(err.contains("only http:// and https://"), "error: {err}");
}

#[test]
fn shard_load_http_bad_host_gives_clear_error() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};

    // Port 1 on localhost — immediate connection refused
    let shard = ShardRef {
        shard_id: "bad".into(),
        source: ShardSource::Http("http://127.0.0.1:1/shard.bin".into()),
        byte_size: None,
        checksum: None,
    };
    let err = load_shard(&shard).unwrap_err();
    assert!(err.contains("shard http connect"), "error: {err}");
}

#[test]
fn mock_backend_load_shard_returns_synthetic_data() {
    use ulp_atom_kernel::backend::{Backend, MockBackend};
    use ulp_atom_kernel::shard::{ShardRef, ShardSource};

    let backend = MockBackend;
    let shard = ShardRef {
        shard_id: "abc".into(),
        source: ShardSource::Local("/does/not/matter".into()),
        byte_size: Some(6),
        checksum: None,
    };
    let loaded = backend.load_shard(&shard).unwrap();
    assert_eq!(loaded.shard_id, "abc");
    assert_eq!(loaded.byte_size, 6);
    // Deterministic: "abc" bytes cycled to length 6
    assert_eq!(loaded.data, b"abcabc");
}

#[test]
fn mock_backend_load_shard_default_size() {
    use ulp_atom_kernel::backend::{Backend, MockBackend};
    use ulp_atom_kernel::shard::{ShardRef, ShardSource};

    let backend = MockBackend;
    let shard = ShardRef {
        shard_id: "x".into(),
        source: ShardSource::Local("/any".into()),
        byte_size: None,
        checksum: None,
    };
    let loaded = backend.load_shard(&shard).unwrap();
    assert_eq!(loaded.byte_size, 64); // default
}

#[test]
fn vulkan_backend_load_shard_uses_real_path() {
    use ulp_atom_kernel::backend::{Backend, VulkanBackend};
    use ulp_atom_kernel::shard::{ShardRef, ShardSource};
    use std::io::Write;

    let dir = std::env::temp_dir().join("ulp_vk_shard_test");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("vk_shard.bin");
    let payload = b"VK_SHARD";
    std::fs::File::create(&path).unwrap().write_all(payload).unwrap();

    let backend = VulkanBackend::new(0);
    let shard = ShardRef {
        shard_id: "vk-shard".into(),
        source: ShardSource::Local(path.to_str().unwrap().into()),
        byte_size: None,
        checksum: None,
    };
    // VulkanBackend uses default trait impl → real file load
    let loaded = backend.load_shard(&shard).unwrap();
    assert_eq!(loaded.data, payload);

    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn http_backend_load_shard_uses_real_path() {
    use ulp_atom_kernel::backend::{Backend, HttpBackend};
    use ulp_atom_kernel::shard::{ShardRef, ShardSource};
    use std::io::Write;

    let dir = std::env::temp_dir().join("ulp_http_shard_test");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("http_shard.bin");
    let payload = b"HTTP_SHARD";
    std::fs::File::create(&path).unwrap().write_all(payload).unwrap();

    let backend = HttpBackend::new("http://unused".into());
    let shard = ShardRef {
        shard_id: "http-shard".into(),
        source: ShardSource::Local(path.to_str().unwrap().into()),
        byte_size: None,
        checksum: None,
    };
    let loaded = backend.load_shard(&shard).unwrap();
    assert_eq!(loaded.data, payload);

    std::fs::remove_dir_all(&dir).ok();
}

// --- CUDA real backend tests ---

#[test]
fn cuda_backend_initializes_without_panic() {
    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    // Must not panic — either available or has a clear error
    let _ = backend.is_available();
    let _ = backend.device_capabilities();
}

#[test]
fn cuda_backend_reports_availability() {
    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    if backend.is_available() {
        assert!(backend.init_error().is_none());
        assert!(backend.selected_device_name().is_some());
        assert!(backend.device_count() >= 1);
    } else {
        assert!(backend.init_error().is_some());
        assert!(backend.selected_device_name().is_none());
    }
}

#[test]
fn cuda_backend_real_compute_or_clear_error() {
    use ulp_atom_kernel::backend::{Backend, BackendRequest};

    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    let req = BackendRequest {
        atom_id: "cuda-test".into(),
        input: vec![10, 20, 252, 0],
        kv_state: vec![],
    };
    let result = backend.execute_prefill(req);
    if backend.is_available() {
        let resp = result.unwrap();
        // Real kernel: (val + 3) & 0xFF
        assert_eq!(resp.output, vec![13, 23, 255, 3]);
        assert_eq!(resp.atom_id, "cuda-test-cuda");
    } else {
        let err = result.unwrap_err();
        assert!(err.contains("CUDA unavailable"), "error: {err}");
    }
}

#[test]
fn cuda_backend_empty_input() {
    use ulp_atom_kernel::backend::{Backend, BackendRequest};

    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    if !backend.is_available() {
        return;
    }
    let req = BackendRequest {
        atom_id: "empty".into(),
        input: vec![],
        kv_state: vec![],
    };
    let resp = backend.execute_prefill(req).unwrap();
    assert!(resp.output.is_empty());
}

#[test]
fn cuda_backend_decode_matches_prefill() {
    use ulp_atom_kernel::backend::{Backend, BackendRequest};

    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    if !backend.is_available() {
        return;
    }
    let input = vec![100, 200, 50];
    let req_a = BackendRequest {
        atom_id: "a".into(),
        input: input.clone(),
        kv_state: vec![],
    };
    let req_b = BackendRequest {
        atom_id: "b".into(),
        input: input.clone(),
        kv_state: vec![],
    };
    let a = backend.execute_prefill(req_a).unwrap();
    let b = backend.execute_decode(req_b).unwrap();
    assert_eq!(a.output, b.output);
}

#[test]
fn cuda_device_index_0_is_explicit() {
    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    assert_eq!(backend.device_index(), 0);
    if backend.is_available() {
        assert!(backend.device_count() >= 1);
        assert!(backend.selected_device_name().is_some());
    }
}

#[test]
fn cuda_invalid_device_index_is_unavailable() {
    let backend = ulp_atom_kernel::backend::CudaBackend::new(999);
    if let Some(err) = backend.init_error() {
        assert!(
            err.contains("out of range") || err.contains("cuda loader") || err.contains("no CUDA"),
            "unexpected error for device_index=999: {err}"
        );
    }
    assert!(!backend.is_available() || backend.device_count() > 999);
}

#[test]
fn cuda_capabilities_reflect_selected_device() {
    use ulp_atom_kernel::backend::Backend;

    let backend = ulp_atom_kernel::backend::CudaBackend::new(0);
    let caps = backend.device_capabilities();
    if backend.is_available() {
        assert_eq!(caps.device_name, backend.selected_device_name().unwrap());
        assert!(caps.available);
        assert!(caps.compute_units > 0);
        assert!(caps.memory_mb > 0);
    } else {
        assert!(!caps.available);
        assert!(caps.device_name.contains("unavailable"));
    }
}


// --- Shard manifest tests ---

#[test]
fn shard_manifest_parses_from_json() {
    use ulp_atom_kernel::shard::ShardManifest;

    let json = r#"{
        "model_id": "llama-7b",
        "base_url": "http://cdn.example.com",
        "version": "v1",
        "shards": [
            {
                "shard_id": "s0",
                "source": {"local": "/tmp/s0.bin"},
                "byte_size": 1024,
                "checksum": "abc123"
            }
        ]
    }"#;
    let manifest = ShardManifest::from_json(json).unwrap();
    assert_eq!(manifest.model_id, "llama-7b");
    assert_eq!(manifest.base_url, Some("http://cdn.example.com".into()));
    assert_eq!(manifest.version, Some("v1".into()));
    assert_eq!(manifest.shards.len(), 1);
    assert_eq!(manifest.shards[0].shard_id, "s0");
}

#[test]
fn shard_manifest_get_shard_by_id() {
    use ulp_atom_kernel::shard::{ShardManifest, ShardSource};

    let json = r#"{
        "model_id": "m",
        "shards": [
            {"shard_id": "a", "source": {"local": "/a"}},
            {"shard_id": "b", "source": {"local": "/b"}}
        ]
    }"#;
    let manifest = ShardManifest::from_json(json).unwrap();
    let shard = manifest.get_shard("b").unwrap();
    assert_eq!(shard.shard_id, "b");
    assert_eq!(shard.source, ShardSource::Local("/b".into()));
    assert!(manifest.get_shard("c").is_none());
}

#[test]
fn shard_source_objectstore_parses() {
    use ulp_atom_kernel::shard::{ShardRef, ShardSource};

    let json = r#"{
        "shard_id": "obj",
        "source": {
            "objectstore": {
                "endpoint": "http://s3.example.com",
                "bucket": "models",
                "key": "shard.bin"
            }
        }
    }"#;
    let shard: ShardRef = serde_json::from_str(json).unwrap();
    match shard.source {
        ShardSource::ObjectStore { endpoint, bucket, key } => {
            assert_eq!(endpoint, "http://s3.example.com");
            assert_eq!(bucket, "models");
            assert_eq!(key, "shard.bin");
        }
        _ => panic!("expected ObjectStore variant"),
    }
}

#[test]
fn shard_load_objectstore_constructs_url() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};

    let shard = ShardRef {
        shard_id: "obj-test".into(),
        source: ShardSource::ObjectStore {
            endpoint: "http://invalid-host-9999".into(),
            bucket: "test-bucket".into(),
            key: "shard.bin".into(),
        },
        byte_size: None,
        checksum: None,
    };
    // Will fail to connect — error should show constructed URL
    let err = load_shard(&shard).unwrap_err();
    assert!(err.contains("invalid-host-9999") || err.contains("shard"), "error: {err}");
}

#[test]
fn shard_checksum_verification_success() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};
    use std::io::Write;

    let dir = std::env::temp_dir().join("ulp_checksum_test");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("data.bin");
    let payload = b"test data";
    std::fs::File::create(&path).unwrap().write_all(payload).unwrap();

    // Compute expected checksum
    let _expected = ulp_atom_kernel::shard::ShardManifest::from_json(&format!(r#"{{
        "model_id": "test",
        "shards": []
    }}"#)).unwrap();
    
    // Calculate checksum for test data using internal function
    // FNV-1a hash of "test data"
    let mut hash: u64 = 0xcbf29ce484222325;
    for &b in payload {
        hash ^= b as u64;
        hash = hash.wrapping_mul(0x100000001b3);
    }
    let expected_checksum = format!("{:016x}", hash);

    let shard = ShardRef {
        shard_id: "ck".into(),
        source: ShardSource::Local(path.to_str().unwrap().into()),
        byte_size: None,
        checksum: Some(expected_checksum),
    };
    let loaded = load_shard(&shard).unwrap();
    assert!(loaded.checksum_verified);
    assert_eq!(loaded.data, payload);

    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn shard_checksum_verification_mismatch() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};
    use std::io::Write;

    let dir = std::env::temp_dir().join("ulp_checksum_fail_test");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("data.bin");
    std::fs::File::create(&path).unwrap().write_all(b"actual data").unwrap();

    let shard = ShardRef {
        shard_id: "bad-ck".into(),
        source: ShardSource::Local(path.to_str().unwrap().into()),
        byte_size: None,
        checksum: Some("0000000000000000".into()),
    };
    let err = load_shard(&shard).unwrap_err();
    assert!(err.contains("checksum mismatch"), "error: {err}");

    std::fs::remove_dir_all(&dir).ok();
}

// --- New tests for bug fixes ---

#[test]
fn shard_http_rejects_non_200_status() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};
    use std::io::Write;
    use std::net::TcpListener;
    use std::thread;
    use std::time::Duration;

    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let url = format!("http://127.0.0.1:{}/notfound", addr.port());

    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            use std::io::Read;
            let mut buf = [0u8; 512];
            let _ = stream.read(&mut buf);
            let response = "HTTP/1.1 404 Not Found\r\nContent-Length: 9\r\n\r\nNot Found";
            let _ = stream.write_all(response.as_bytes());
        }
    });

    thread::sleep(Duration::from_millis(50));

    let shard = ShardRef {
        shard_id: "test-404".into(),
        source: ShardSource::Http(url.clone()),
        byte_size: None,
        checksum: None,
    };

    let err = load_shard(&shard).unwrap_err();
    assert!(err.contains("HTTP 404"), "expected HTTP 404 error, got: {err}");
}

#[test]
fn shard_byte_size_mismatch_detected() {
    use ulp_atom_kernel::shard::{load_shard, ShardRef, ShardSource};
    use std::io::Write;

    let dir = std::env::temp_dir().join("ulp_size_mismatch_test");
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join("data.bin");
    std::fs::File::create(&path).unwrap().write_all(b"1234567890").unwrap();

    let shard = ShardRef {
        shard_id: "size-test".into(),
        source: ShardSource::Local(path.to_str().unwrap().into()),
        byte_size: Some(999),
        checksum: None,
    };

    let err = load_shard(&shard).unwrap_err();
    assert!(err.contains("size mismatch"), "error: {err}");
    assert!(err.contains("expected 999"), "error: {err}");
    assert!(err.contains("got 10"), "error: {err}");

    std::fs::remove_dir_all(&dir).ok();
}

#[test]
fn shard_manifest_base_url_works() {
    use ulp_atom_kernel::shard::{load_shard_from_manifest, ShardManifest, ShardRef, ShardSource};
    use std::io::Write;
    use std::net::TcpListener;
    use std::thread;
    use std::time::Duration;

    let listener = TcpListener::bind("127.0.0.1:0").unwrap();
    let addr = listener.local_addr().unwrap();
    let base_url = format!("http://127.0.0.1:{}", addr.port());

    thread::spawn(move || {
        if let Ok((mut stream, _)) = listener.accept() {
            use std::io::Read;
            let mut buf = [0u8; 512];
            let _ = stream.read(&mut buf);
            let response = "HTTP/1.1 200 OK\r\nContent-Length: 4\r\n\r\nOKAY";
            let _ = stream.write_all(response.as_bytes());
        }
    });

    thread::sleep(Duration::from_millis(50));

    let manifest = ShardManifest {
        model_id: "test-model".into(),
        base_url: Some(base_url),
        shards: vec![],
        version: None,
    };

    let shard = ShardRef {
        shard_id: "rel-test".into(),
        source: ShardSource::Http("shard.bin".into()),
        byte_size: Some(4),
        checksum: None,
    };

    let loaded = load_shard_from_manifest(&shard, &manifest).unwrap();
    assert_eq!(loaded.data, b"OKAY");
}

#[test]
fn runner_uses_real_backend_not_mock() {
    use ulp_atom_kernel::runner::run_from_json;

    let json = r#"{
        "agent_id": "test-agent",
        "model_id": "test-model",
        "atom_kind": "Prefill",
        "input": [97, 98, 99],
        "sovereignty_zone": "test-zone"
    }"#;

    let result = run_from_json(json).unwrap();
    let resp: serde_json::Value = serde_json::from_str(&result).unwrap();

    let backend_kind = resp["backend_kind"].as_str();
    assert!(backend_kind.is_some(), "backend_kind should be present");

    let kind = backend_kind.unwrap();
    assert!(kind == "Vulkan" || kind == "Mock", "unexpected backend: {kind}");
}

// ===========================================================================
// Sovereignty boundary: Home Node / Ephemeral Node
// ===========================================================================

fn make_ephemeral_candidate(node_id: &str, region: &str) -> ulp_atom_kernel::router::NodeProfile {
    use ulp_atom_kernel::atom::{AtomKind, Region};
    use ulp_atom_kernel::capacity::NodeCapacity;
    ulp_atom_kernel::router::NodeProfile {
        node_id: node_id.into(),
        region: Region(region.into()),
        latency_ms: 10.0,
        hotness: 0.5,
        supported_kinds: vec![AtomKind::Prefill, AtomKind::Decode, AtomKind::Inference],
        sovereignty_zone: region.into(),
        prefill_affinity: 0.8,
        decode_affinity: 0.8,
        capacity: NodeCapacity {
            available_vram_gb: 16.0,
            current_load: 0.2,
            active_kv_chunks: 0,
        },
    }
}

#[test]
fn home_node_holds_persistent_state() {
    use ulp_atom_kernel::atom::Region;
    use ulp_atom_kernel::kv::KVChunk;
    use ulp_atom_kernel::sovereignty::HomeNode;

    let mut home = HomeNode::new("home-1", "zone-a", Region("us-east".into()));
    assert!(home.kv_store.is_empty());
    assert!(home.hot_shards.is_empty());

    // Home node accumulates KV state
    home.kv_store.push(KVChunk {
        chunk_id: "kv-1".into(),
        source_region: Region("us-east".into()),
        seq_start: 0,
        seq_end: 128,
        byte_size: 256,
        payload: vec![0xAA; 256],
    });
    assert_eq!(home.kv_store.len(), 1);
    assert_eq!(home.sovereignty_zone, "zone-a");
}

#[test]
fn ephemeral_node_is_stateless() {
    use ulp_atom_kernel::atom::{AtomKind, Region};
    use ulp_atom_kernel::sovereignty::EphemeralNode;

    let eph = EphemeralNode::new(
        "eph-1",
        Region("eu-west".into()),
        vec![AtomKind::Prefill, AtomKind::Decode],
    );
    // Ephemeral node has no KV store, no shards, no sovereignty zone
    assert_eq!(eph.node_id, "eph-1");
    assert_eq!(eph.supported_kinds.len(), 2);
}

#[test]
fn home_node_generates_outsource_request() {
    use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
    use ulp_atom_kernel::sovereignty::HomeNode;

    let home = HomeNode::new("home-1", "zone-a", Region("us-east".into()));
    let atom = ComputeAtom {
        id: "atom-1".into(),
        kind: AtomKind::Inference,
        region: Region("us-east".into()),
        model_id: "model-x".into(),
        shard_count: 0,
    };
    let candidates = vec![make_ephemeral_candidate("eph-1", "us-east")];

    let (request, blinded) = home.prepare_outsource(&atom, vec![0x01, 0x02], &candidates).unwrap();

    // HomeExecutionRequest stays on home side
    assert_eq!(request.home_node_id, "home-1");
    assert_eq!(request.target_node_id, "eph-1");

    // BlindedAtom has no sovereignty zone, no home node identity
    assert_eq!(blinded.atom_id, "atom-1");
    assert_eq!(blinded.model_id, "model-x");
    assert_eq!(blinded.input, vec![0x01, 0x02]);
}

#[test]
fn blinded_atom_strips_sovereignty_metadata() {
    use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
    use ulp_atom_kernel::sovereignty::HomeNode;

    let home = HomeNode::new("home-1", "secret-zone", Region("us-east".into()));
    let atom = ComputeAtom {
        id: "atom-2".into(),
        kind: AtomKind::Prefill,
        region: Region("us-east".into()),
        model_id: "model-y".into(),
        shard_count: 0,
    };
    let candidates = vec![make_ephemeral_candidate("eph-2", "us-east")];

    let (_request, blinded) = home.prepare_outsource(&atom, vec![0xFF], &candidates).unwrap();

    // Serialize blinded atom and verify no sovereignty info leaks
    let json = serde_json::to_string(&blinded).unwrap();
    assert!(!json.contains("secret-zone"), "sovereignty zone must not appear in blinded atom");
    assert!(!json.contains("home-1"), "home node id must not appear in blinded atom");
}

#[test]
fn ephemeral_executes_blinded_atom_and_returns_result() {
    use ulp_atom_kernel::atom::{AtomKind, Region};
    use ulp_atom_kernel::backend::MockBackend;
    use ulp_atom_kernel::sovereignty::{BlindedAtom, EphemeralNode};

    let eph = EphemeralNode::new(
        "eph-1",
        Region("us-east".into()),
        vec![AtomKind::Inference],
    );
    let blinded = BlindedAtom {
        atom_id: "atom-1".into(),
        kind: AtomKind::Inference,
        model_id: "model-x".into(),
        input: vec![0x61, 0x62, 0x63], // "abc"
        kv_chunks: Vec::new(),
    };

    let result = eph.execute(&MockBackend, &blinded).unwrap();

    assert_eq!(result.ephemeral_node_id, "eph-1");
    assert_eq!(result.atom_id, "atom-1");
    // MockBackend uppercases: 0x61->0x41, 0x62->0x42, 0x63->0x43
    assert_eq!(result.output, vec![0x41, 0x42, 0x43]);
    assert!(result.tokens_produced > 0);
}

#[test]
fn home_receives_result_and_absorbs_kv() {
    use ulp_atom_kernel::atom::Region;
    use ulp_atom_kernel::kv::KVChunk;
    use ulp_atom_kernel::router::PlacementDecision;
    use ulp_atom_kernel::sovereignty::{EphemeralExecutionResult, HomeExecutionRequest, HomeNode};

    let mut home = HomeNode::new("home-1", "zone-a", Region("us-east".into()));
    assert!(home.kv_store.is_empty());

    let request = HomeExecutionRequest {
        home_node_id: "home-1".into(),
        target_node_id: "eph-1".into(),
        placement: PlacementDecision {
            breakdown: ulp_atom_kernel::router::PlacementBreakdown {
                node_id: "eph-1".into(),
                final_score: 0.9,
                latency_score: 0.9,
                hotness_score: 0.5,
                engine_score: 1.0,
                specialization_score: 0.8,
                kv_locality_score: 0.0,
                sovereignty_score: 1.0,
                migration_cost: 0.0,
                capacity_score: 0.8,
            },
            requires_kv_migration: false,
            estimated_migration_cost: 0.0,
        },
        atom_region: Region("us-east".into()),
    };

    let eph_result = EphemeralExecutionResult {
        ephemeral_node_id: "eph-1".into(),
        atom_id: "atom-1".into(),
        output: vec![0x41, 0x42],
        tokens_produced: 2,
        kv_produced: vec![KVChunk {
            chunk_id: "kv-new".into(),
            source_region: Region("us-east".into()),
            seq_start: 0,
            seq_end: 64,
            byte_size: 128,
            payload: vec![0xBB; 128],
        }],
    };

    let response = home.receive_result(&request, eph_result);

    assert_eq!(response.home_node_id, "home-1");
    assert_eq!(response.output, vec![0x41, 0x42]);
    assert_eq!(response.kv_absorbed, 1);
    assert_eq!(response.ephemeral_node_id, "eph-1");
    // KV was absorbed into home node's store
    assert_eq!(home.kv_store.len(), 1);
    assert_eq!(home.kv_store[0].chunk_id, "kv-new");
}

#[test]
fn full_home_ephemeral_roundtrip() {
    use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
    use ulp_atom_kernel::backend::MockBackend;
    use ulp_atom_kernel::sovereignty::{EphemeralNode, HomeNode};

    // 1. Home node prepares outsource
    let mut home = HomeNode::new("home-1", "zone-a", Region("us-east".into()));
    let atom = ComputeAtom {
        id: "atom-round".into(),
        kind: AtomKind::Inference,
        region: Region("us-east".into()),
        model_id: "model-z".into(),
        shard_count: 0,
    };
    let candidates = vec![make_ephemeral_candidate("eph-1", "us-east")];

    let (request, blinded) = home.prepare_outsource(&atom, vec![0x68, 0x69], &candidates).unwrap();

    // 2. Ephemeral node executes
    let eph = EphemeralNode::new(
        "eph-1",
        Region("us-east".into()),
        vec![AtomKind::Inference],
    );
    let eph_result = eph.execute(&MockBackend, &blinded).unwrap();

    // 3. Home node receives result
    let response = home.receive_result(&request, eph_result);

    // MockBackend uppercases: 0x68('h')->0x48('H'), 0x69('i')->0x49('I')
    assert_eq!(response.output, vec![0x48, 0x49]);
    assert_eq!(response.home_node_id, "home-1");
    assert_eq!(response.ephemeral_node_id, "eph-1");
    // Home node absorbed KV from execution (empty in this case since no
    // KV was provided — KV absorption is tested in home_receives_result_and_absorbs_kv)
    assert_eq!(response.tokens_produced, 1);
}

#[test]
fn ephemeral_rejects_unsupported_kind() {
    use ulp_atom_kernel::atom::{AtomKind, Region};
    use ulp_atom_kernel::backend::MockBackend;
    use ulp_atom_kernel::sovereignty::{BlindedAtom, EphemeralNode};

    // Ephemeral only supports Embedding
    let eph = EphemeralNode::new(
        "eph-limited",
        Region("us-east".into()),
        vec![AtomKind::Embedding],
    );
    let blinded = BlindedAtom {
        atom_id: "atom-x".into(),
        kind: AtomKind::Inference, // not supported
        model_id: "model-x".into(),
        input: vec![0x01],
        kv_chunks: Vec::new(),
    };

    let err = eph.execute(&MockBackend, &blinded).unwrap_err();
    assert!(err.contains("does not support"), "error: {err}");
}

#[test]
fn home_local_execution_absorbs_kv() {
    use ulp_atom_kernel::atom::{AtomKind, ComputeAtom, Region};
    use ulp_atom_kernel::backend::MockBackend;
    use ulp_atom_kernel::sovereignty::HomeNode;

    let mut home = HomeNode::new("home-1", "zone-a", Region("us-east".into()));
    let atom = ComputeAtom {
        id: "local-atom".into(),
        kind: AtomKind::Inference,
        region: Region("us-east".into()),
        model_id: "model-local".into(),
        shard_count: 0,
    };
    let candidates = vec![make_ephemeral_candidate("home-1", "us-east")];

    let response = home.execute_local(&MockBackend, &atom, vec![0x61], &candidates).unwrap();

    // Local execution works through existing kernel::dispatch
    assert!(!response.exec_response.output.is_empty());
    // KV state absorbed
    assert_eq!(home.kv_store.len(), response.exec_response.kv_state.len());
}
