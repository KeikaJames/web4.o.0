# Reference Implementations

This directory contains reference implementations of Web4.0 / ULP protocols.

## Status

Early stage: SAC Python reference implementation exists.

These are NOT production-ready implementations.
They are minimal, local-first prototypes designed to validate object boundaries and protocol feasibility.

## Available Implementations

### SAC (Sovereign Agent Container) - Python

**Path**: `sac_py/`

**Status**: Prototype

**What it implements**:
- Core SAC objects (RootKeyMaterial, MemoryRoot, PermissionCage, DerivedAgent)
- Local JSON storage
- Basic operations (create, load, derive-agent, rotate-key, export-metadata, check-permission)
- Minimal CLI
- Test coverage

**What it does NOT implement**:
- Hardware key binding
- Social recovery
- Network features
- Cloud integration
- Production-grade cryptography

See [sac_py/README.md](sac_py/README.md) for details.

---

## Implementation Principles

Reference implementations should:
1. Validate protocol specifications
2. Be minimal and readable
3. Serve as teaching tools
4. Not become the only way to implement protocols
5. Clearly mark prototype boundaries

Reference implementations should NOT:
1. Be production-ready
2. Include speculative features
3. Optimize prematurely
4. Hide complexity behind abstractions
5. Claim completeness

---

## Future Implementations

Planned reference implementations:
- IIP (Intent Interface Protocol)
- OCI (Open Compute Interface)
- FIL (Federated Intelligence Layer)
- Compatibility adapters

These will be added as protocol specifications stabilize.

---

## Contributing

See [../CONTRIBUTING.md](../CONTRIBUTING.md) for contribution guidelines.

When contributing reference implementations:
- Keep them minimal
- Document prototype boundaries clearly
- Write tests
- Follow existing code style
- Do not add unnecessary dependencies

---

## References

- [specs/](../specs/) - Protocol specifications
- [rfcs/](../rfcs/) - Request for Comments
- [docs/](../docs/) - Core documentation
