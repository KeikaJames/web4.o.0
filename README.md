# Efferva

Protocol for sovereign Agent ownership.

---

## What This Defines

This repository defines protocols that let individuals own and control their own Agents, access compute without platform lock-in, and participate in federated intelligence networks.

Not a platform. Not a blockchain. Not a product.
A protocol specification.

---

## What This Is Not

- Platform business
- Governance system
- Token project
- Product company

---

## Core Statements

Every person should own their own Agent.
Intelligence circulates by use, not enclosure.
Rules are public; persons remain private.

---

## Repository Structure

```
docs/              Problem definition, methodology, axioms
implementations/   Reference implementations (Python, Rust)
specs/             Protocol specifications (draft)
schemas/           JSON Schema definitions
rfcs/              Request for Comments
fixtures/          Test fixtures for cross-language validation
```

---

## Five-Layer Architecture

1. **SAC (Sovereign Agent Container)** — Defines the sovereignty boundary of an Agent: identity, keys, memory root, and permission state
2. **IIP (Intent Interface Protocol)** — Defines the boundary between Agents and services: intent representation, capability declaration, and invocation protocol
3. **OCI (Open Compute Interface)** — Defines the boundary for compute resource access, scheduling, and execution
4. **FIL (Federated Intelligence Layer)** — Defines the mechanism for cross-Agent shared updates, federated learning, and intelligence distribution
5. **Compatibility Layer** — Defines the interface boundary for accessing existing networks, platform APIs, and external systems

See [docs/architecture-overview.md](docs/architecture-overview.md) for details.

---

## Current Status

Early stage: SAC draft spec and reference implementations (Python, Rust) exist. Compatibility layer prototype demonstrates SAC-backed Agents acting into existing systems. The atom kernel prototype implements multi-node routing with KV-locality awareness.

Reference implementations are prototypes, not production-ready.

No token.
No platform.

---

## Entry Points

- [docs/manifesto.md](docs/manifesto.md) — Why this exists
- [docs/methodology.md](docs/methodology.md) — How replacement works
- [docs/principles.md](docs/principles.md) — Design axioms
- [docs/architecture-overview.md](docs/architecture-overview.md) — Structure
- [implementations/](implementations/) — Reference implementations
- [specs/](specs/) — Protocol drafts

See [CONTRIBUTING.md](CONTRIBUTING.md) to participate.

---

## License

MIT. See [LICENSE](LICENSE).

---

Efferva advances by replacement.
