# Architecture Overview

First-draft structure. Not frozen.

---

## Five Layers

```
┌─────────────────────────────────────────┐
│   Sovereign Agent Container (SAC)       │  ← Sovereignty
├─────────────────────────────────────────┤
│   Intent Interface Protocol (IIP)       │  ← Interaction
├─────────────────────────────────────────┤
│   Open Compute Interface (OCI)          │  ← Compute
├─────────────────────────────────────────┤
│   Federated Intelligence Layer (FIL)    │  ← Intelligence
├─────────────────────────────────────────┤
│   Compatibility Layer                    │  ← Compatibility
└─────────────────────────────────────────┘
```

---

## 1. Sovereign Agent Container (SAC)

Defines the sovereignty boundary of an Agent: identity, keys, memory root, and permission state.

Core components:
- Root key binding (passkey / hardware key)
- Persona configuration
- Memory root (encrypted references)
- Permission cage
- Recovery metadata
- Derived agents

Properties:
- User control
- Portable
- Recoverable
- Forkable
- No single-vendor dependency

See [specs/sovereign-agent-container.md](../specs/sovereign-agent-container.md)

---

## 2. Intent Interface Protocol (IIP)

Defines the boundary between Agents and services: intent representation, capability declaration, and invocation protocol.

Core objects:
- Intent
- Capability description
- Constraints
- Response proposal
- Confirmation boundary

Properties:
- Capability-based discovery
- Intent decomposition and composition
- Multi-provider comparison
- Explicit confirmation boundaries

See [specs/intent-interface-protocol.md](../specs/intent-interface-protocol.md)

---

## 3. Open Compute Interface (OCI)

Defines the boundary for compute resource access, scheduling, and execution.

Core objects:
- Compute request
- Execution class
- Privacy requirement
- Latency class
- Verification surface
- Settlement hooks

Properties:
- Local-first, remote-optional
- Multi-source compute
- Tiered outsourcing (sensitive tasks stay local)
- Verifiable execution

See [specs/open-compute-interface.md](../specs/open-compute-interface.md)

---

## 4. Federated Intelligence Layer (FIL)

Defines the mechanism for cross-Agent shared updates, federated learning, and intelligence distribution.

Core components:
- Memory federation
- Skill federation
- Model federation
- Evaluation federation

Properties:
- Individual memory not uploaded by default
- Collective intelligence inheritable, auditable, rollbackable
- Skills shareable but not mandatory
- Evaluation public, subjects anonymous

See [specs/federated-intelligence-layer.md](../specs/federated-intelligence-layer.md)

---

## 5. Compatibility Layer

Defines the interface boundary for accessing existing networks, platform APIs, and external systems.

Compatibility targets:
- Websites / HTML
- Existing APIs
- Legacy auth (OAuth, SAML, etc.)
- Cloud runtimes
- Payment rails
- App ecosystems

Principle:
Efferva can call the old world.
The old world cannot remain the only sovereignty entry point.

See [specs/compatibility-layer.md](../specs/compatibility-layer.md)

---

## Why SAC Is the Starting Point

Without user-owned containers, all other layers revert to platform dependency.

SAC establishes sovereignty.
Other layers build on that foundation.

---

## Layer Relationships

- SAC: Users control Agents
- IIP: Agents discover and invoke services
- OCI: Agents access compute
- FIL: Agents participate in collective intelligence
- Compatibility: Agents access old systems when needed

---

## Data Flow Example

```
User intent
  ↓
SAC (sovereign Agent)
  ↓
IIP (intent parsing → capability discovery → provider comparison)
  ↓
OCI (compute invocation)
  ↓
FIL (skill/model invocation)
  ↓
Compatibility Layer (old API calls, if needed)
  ↓
Result returns to SAC
  ↓
User confirmation
```

---

## Identity and Keys

Root key:
- User holds root key (passkey / hardware key)
- Root key binds to SAC
- Root key not stored on any platform

Derived keys:
- SAC can derive child Agents
- Child Agents have independent permission scopes
- Child Agents can be revoked

Recovery:
- User configures recovery mechanisms
- Recovery does not depend on a single platform
- Recovery can use social recovery or backup keys

---

## Not Yet Defined

- Specific encryption schemes
- Specific consensus mechanisms (if needed)
- Specific settlement methods
- Specific identity recovery details

These will be clarified through RFCs and implementations.
