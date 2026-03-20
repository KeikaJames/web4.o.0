"""Filesystem confinement helpers for compatibility adapters."""

from pathlib import Path


def resolve_within_memory_root(sac, requested_path: str, *, must_exist: bool) -> Path:
    """Resolve a path and ensure it stays inside the SAC memory root."""
    root = Path(sac.memory_root.reference).expanduser().resolve(strict=False)
    requested = Path(requested_path).expanduser()
    candidate = requested if requested.is_absolute() else root / requested
    target = candidate.resolve(strict=must_exist)

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path escapes memory root: {requested_path}") from exc

    return target
