# SAC Reference Implementation (Python)

Minimal, local-first prototype implementation of the Sovereign Agent Container specification.

## What This Is

This is a reference implementation that validates the object boundaries defined in [specs/sovereign-agent-container.md](../../specs/sovereign-agent-container.md).

It implements:
- Core SAC objects (RootKeyMaterial, MemoryRoot, PermissionCage, DerivedAgent)
- Local JSON storage
- Basic operations (create, load, derive-agent, rotate-key, export-metadata, check-permission)
- Encrypted-at-rest container serialization with passphrase-derived keys
- Minimal CLI
- Test coverage
- `chronara_nexus/` governance and pre-federation prototype layers

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

**Permission Model**: Minimal prototype covering `file.write`, `financial.transaction`, financial limits, and confirmation requirements. Not exhaustive.

## Installation

Requires Python 3.11+

```bash
# Install dependencies
pip install pytest

# Run from repository root
cd /path/to/Efferva
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

# Check with confirmation
python -m implementations.sac_py.cli check-permission ./my-sac.json \
  --operation "file.write" \
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
├── chronara_nexus/      # Chronara governance / federation prototype layers
├── tests/
│   └── ...              # SAC + Chronara test suites
└── README.md            # This file
```

## Core Objects

### SACContainer
Main container holding all SAC state.

### RootKeyMaterial
Root key for sovereignty. Never exported in metadata.

### MemoryRoot
Encrypted reference to user's memory store.

### PermissionCage
Defines what Agent can do. Supports:
- Financial limits (daily, single transaction)
- Explicit allowed operations (`file.write`, `financial.transaction`)
- Confirmation requirements

### DerivedAgent
Child agent with limited scope. Can be revoked.

## Security Notes

**PROTOTYPE ONLY**:
- Root key material is serialized only inside the encrypted container envelope
- Simple HMAC-based key derivation and stream construction (not final design)
- No hardware key binding
- No social recovery implementation
- No formally reviewed cryptographic design

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
- [RFC 0002: Efferva Core Axioms](../../rfcs/0002-web4-core-axioms.md)
- [docs/architecture-overview.md](../../docs/architecture-overview.md)
