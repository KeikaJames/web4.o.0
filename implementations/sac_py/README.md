# SAC Reference Implementation (Python)

Minimal, local-first prototype implementation of the Sovereign Agent Container specification.

## What This Is

This is a reference implementation that validates the object boundaries defined in [specs/sovereign-agent-container.md](../../specs/sovereign-agent-container.md).

It implements:
- Core SAC objects (RootKeyMaterial, PersonaConfig, MemoryRoot, PermissionCage, DerivedAgent)
- Local JSON storage
- Basic operations (create, load, derive-agent, rotate-key, export-metadata, check-permission)
- Minimal CLI
- Test coverage

## What This Is Not

This is NOT:
- Production-ready code
- A complete agent runtime
- A wallet or account system
- A cloud service
- A final cryptographic design

## Prototype Boundaries

**Storage**: Uses simple JSON files. Not final format.

**Cryptography**: Uses Python standard library (secrets, hashlib, hmac). Not final cryptographic design. Does not implement:
- Hardware key binding
- Social recovery
- ZK proofs
- MPC

**Scope**: Local-only. No network, no cloud, no distributed features.

**Permission Model**: Minimal prototype covering financial limits, data scopes, confirmation requirements. Not exhaustive.

## Installation

Requires Python 3.11+

```bash
# Install dependencies
pip install pytest

# Run from repository root
cd /path/to/web4.0
```

## Usage

### Create SAC

```bash
python -m implementations.sac_py.cli create \
  --name "My Agent" \
  --memory-path ./my-memory \
  --financial-limit 1000.0 \
  --output ./my-sac.json
```

### Show SAC

```bash
python -m implementations.sac_py.cli show ./my-sac.json
```

### Derive Child Agent

```bash
python -m implementations.sac_py.cli derive-agent ./my-sac.json \
  --purpose "email-handler" \
  --scope "email,calendar"
```

### Rotate Root Key

```bash
python -m implementations.sac_py.cli rotate-key ./my-sac.json
```

### Export Metadata

```bash
python -m implementations.sac_py.cli export-metadata ./my-sac.json
python -m implementations.sac_py.cli export-metadata ./my-sac.json --output metadata.json
```

### Check Permission

```bash
# Check financial transaction
python -m implementations.sac_py.cli check-permission ./my-sac.json \
  --operation "financial.transaction" \
  --amount 500.0

# Check data access
python -m implementations.sac_py.cli check-permission ./my-sac.json \
  --operation "data.read" \
  --scope "calendar"

# Check with confirmation
python -m implementations.sac_py.cli check-permission ./my-sac.json \
  --operation "delete.account" \
  --confirmed
```

## Running Tests

```bash
# From repository root
pytest implementations/sac_py/tests/

# With coverage
pytest implementations/sac_py/tests/ --cov=implementations.sac_py
```

## File Structure

```
implementations/sac_py/
├── __init__.py          # Package exports
├── __main__.py          # CLI entry point
├── sac.py               # Core SAC implementation
├── cli.py               # CLI commands
├── tests/
│   └── test_sac.py      # Test suite
└── README.md            # This file
```

## Core Objects

### SACContainer
Main container holding all SAC state.

### RootKeyMaterial
Root key for sovereignty. Never exported in metadata.

### PersonaConfig
Agent behavior and boundaries configuration.

### MemoryRoot
Encrypted reference to user's memory store.

### PermissionCage
Defines what Agent can do. Supports:
- Financial limits (daily, single transaction)
- Data scopes (allowed, blocked)
- Confirmation requirements

### DerivedAgent
Child agent with limited scope. Can be revoked.

## Security Notes

**PROTOTYPE ONLY**:
- Root key stored in JSON file (not secure for production)
- Simple HMAC-based key derivation (not final design)
- No hardware key binding
- No social recovery implementation
- No encryption at rest

**For production**, would need:
- Proper secret storage (OS keychain, hardware key, etc.)
- Formal cryptographic protocol design
- Security audit
- Threat model analysis

## Next Steps

This prototype validates SAC object boundaries.

Future work:
- Hardware key binding
- Social recovery protocol
- Encrypted cloud backup
- Integration with IIP (Intent Interface Protocol)
- Integration with OCI (Open Compute Interface)

## References

- [specs/sovereign-agent-container.md](../../specs/sovereign-agent-container.md)
- [RFC 0002: Web4.0 Core Axioms](../../rfcs/0002-web4-core-axioms.md)
- [docs/architecture-overview.md](../../docs/architecture-overview.md)
