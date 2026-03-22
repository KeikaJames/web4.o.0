# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Project Is

Efferva is a **protocol specification** for sovereign Agent ownership — not a platform, blockchain, or product. It defines how individuals own and control their own Agents, access compute without platform lock-in, and participate in federated intelligence networks. The methodology is "advancement by replacement": identify protocol fulcrums, separate necessity from habit, rewrite with new primitives, maintain backward compatibility.

## Commands

### Python (sac_py, compat_py)

```bash
# Run tests
pytest implementations/sac_py/tests/
pytest implementations/compat_py/tests/

# Run single test
pytest implementations/sac_py/tests/test_sac.py::test_name

# SAC CLI
python -m implementations.sac_py.cli create --name "Agent" --memory-path ./mem --financial-limit 1000.0 --output ./sac.json
python -m implementations.sac_py.cli show ./sac.json
python -m implementations.sac_py.cli derive-agent ./sac.json --purpose "email" --scope "email,calendar"
python -m implementations.sac_py.cli check-permission ./sac.json --operation "financial.transaction" --amount 500.0
```

Requires Python 3.11+, `pytest`, `jsonschema`.

### Rust (sac_rs, ulp_atom_kernel)

```bash
# From the implementation directory
cargo build
cargo test

# Run single test
cargo test test_name

# ULP Atom Kernel server mode
cargo run -- --server 127.0.0.1:3000

# ULP Atom Kernel with request file
cargo run -- --nodes nodes.json --kv kv.json request.json
```

## Architecture

The protocol is a five-layer stack:

```
SAC  → IIP → OCI → FIL → Compatibility Layer
(own)  (talk) (run) (learn) (legacy)
```

**SAC (Sovereign Agent Container)** — The sovereignty boundary. User holds the root key (never uploaded). Contains identity, encrypted memory root, permission cage, and derived agents. Portable, recoverable, forkable. Python and Rust prototypes exist.

**IIP (Intent Interface Protocol)** — The interaction boundary between Agents and services. Replaces API calls with capability-based intent routing. Draft spec only.

**OCI (Open Compute Interface)** — The compute boundary. Local-first, multi-source, verifiable. Draft spec only.

**FIL (Federated Intelligence Layer)** — Cross-Agent intelligence distribution. Memory not uploaded by default. Draft spec only.

**Compatibility Layer** — Lets Agents call existing systems (OAuth, cloud APIs, payment rails). Old world can be *called* but not *required*. Python prototype in `compat_py/`.

### ULP Atom Kernel

The atom kernel (`implementations/ulp_atom_kernel/`) is the compute routing prototype. Key concepts:
- **Placement routing**: multi-dimensional node scoring (latency, hotness, specialization, KV-locality, sovereignty, capacity)
- **Two-stage pipeline**: Prefill node → Decode node, crossing the sovereignty boundary
- **PRIB** (Privacy-preserving Remote Inference Boundary): XOR blind/unblind ensures `unblind(f(blind(x,m)),m)==f(x)`; minimum correctness path in `prib.rs`
- **Backend abstraction**: Vulkan GPU, CUDA, HTTP remote, mock backend; selector pattern in `src/backend/`
- **SAC bridge** (`sac_bridge.rs`): converts `SACRequest` (agent_id, sovereignty_zone, atom_kind) into kernel routing request
- **Routing weights**: Decode phase prioritizes KV-locality (0.30) > latency (0.25) > capacity (0.20); Prefill phase prioritizes sovereignty (0.25) > capacity (0.25) > specialization (0.15)
- **Server/federation modes**: `--server` runs axum HTTP server; `--remote-nodes` enables multi-node federation via HTTP client

**Module map** (`src/`):
```
atom.rs       → AtomKind, Region, ComputeAtom
router.rs     → NodeProfile, PlacementBreakdown, PlacementDecision
kernel.rs     → dispatch(): route → migrate KV → execute
pipeline.rs   → two-stage Prefill/Decode pipeline
prib.rs       → blind/unblind XOR masking
sac_bridge.rs → SACRequest → atom request
backend/      → trait.rs, mock.rs, http.rs, vulkan.rs, cuda.rs, selector.rs
server.rs     → axum HTTP server
client.rs     → remote node HTTP client
protocol.rs   → CBOR/JSON encode/decode (ciborium)
capacity.rs   → node capacity tracking
shard.rs      → shard management
kv.rs         → KV chunk migration
```

### SAC Data Model

```
SACContainer
├── RootKeyMaterial    (never exported; PBKDF2 100K iters → HMAC-SHA256 stream XOR + MAC)
├── MemoryRoot         (encrypted reference to memory store)
├── PermissionCage     (financial limits, data scopes, confirmation requirements)
└── DerivedAgent[]     (child agents with restricted scopes, revocable)
```

- **Two schemas**: `sac.v1.container.schema.json` (full local, never transmit) vs `sac.v1.metadata.schema.json` (no key_bytes, safe to share)
- **Cross-language parity**: Python (`sac_py/sac.py`) and Rust (`sac_rs/src/sac.rs`) use identical crypto; validated via `fixtures/sac_v1/`
- Serialization validates against JSON Schema. Atomic writes via temp file + fsync + rename.
- `DerivedAgent` permissions must be a strict subset of parent `PermissionCage` (enforced in `is_subset_of`)

### Compatibility Adapter Pattern

`compat_py/adapter.py` enforces: SAC validation → permission check → path security → audit log → old-system call. Denials use typed `ReasonCode` (AGENT_REVOKED, PERMISSION_DENIED, SCOPE_DENIED, etc.).

**Security enforcements**:
- `path_security.py`: resolves path inside `memory_root`, blocks directory traversal
- `adapter.py`: uses `O_NOFOLLOW` (POSIX) to prevent symlink TOCTOU races; atomic writes via temp file in same directory
- Every decision produces an `AuditEntry` with timestamp, agent_id, reason_code

**Model integration** (`compat_py/model.py`):
- `MockModel`: deterministic uppercase transform + `file.write` proposal (tests)
- `AnthropicModel`: calls Claude API, parses structured JSON proposal for action governance

## Repository Layout

- `docs/` — manifesto, methodology, principles, architecture, roadmap
- `specs/` — draft protocol specifications (SAC, IIP, OCI, FIL, compat)
- `rfcs/` — formal RFCs for core axioms and substantial changes
- `schemas/` — JSON Schemas for SAC v1 wire format
- `implementations/` — reference implementations (prototypes)
- `fixtures/sac_v1/` — cross-language test fixtures

## Contribution Constraints

Per `CONTRIBUTING.md`: do not introduce platform businesses, token economics, vendor lock-in, or buzzwords. Contributions fall into three types — Core Axioms (`docs/`, `rfcs/`), Protocol Specifications (`specs/`), or Reference Implementations (`implementations/`). Substantial changes require an RFC first.
