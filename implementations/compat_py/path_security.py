"""Filesystem confinement helpers for compatibility adapters."""

import stat
from pathlib import Path


def memory_root_path(sac) -> Path:
    """Return the canonical memory root path used for confinement checks."""
    return Path(sac.memory_root.reference).expanduser().resolve(strict=False)


def resolve_within_memory_root(sac, requested_path: str, *, must_exist: bool) -> Path:
    """Resolve a path and ensure it stays inside the SAC memory root."""
    root = memory_root_path(sac)
    requested = Path(requested_path).expanduser()
    candidate = requested if requested.is_absolute() else root / requested
    target = candidate.resolve(strict=must_exist)

    try:
        target.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path escapes memory root: {requested_path}") from exc

    return target


def ensure_write_target_within_memory_root(sac, target: Path) -> Path:
    """
    Ensure a write target stays inside the SAC memory root at write time.

    This re-checks every ancestor directory immediately before a write so a
    symlink planted after an earlier `resolve()` call cannot redirect the write
    outside the confinement root.
    """
    root = memory_root_path(sac)
    root.parent.mkdir(parents=True, exist_ok=True)
    _ensure_real_directory(root, create=True)
    root = root.resolve(strict=True)
    target = Path(target)

    try:
        relative_target = target.relative_to(root)
    except ValueError as exc:
        raise PermissionError(f"Path escapes memory root: {target}") from exc
    if target == root:
        raise PermissionError("Target path must not be the memory root directory")

    current = root
    for component in relative_target.parent.parts:
        current = current / component
        _ensure_real_directory(current, create=True)

    if current.resolve(strict=True) != target.parent.resolve(strict=True):
        raise PermissionError(f"Write parent changed during validation: {target.parent}")

    return current / target.name


def _ensure_real_directory(path: Path, *, create: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if not create:
            raise
        path.mkdir()
        metadata = path.lstat()

    if stat.S_ISLNK(metadata.st_mode):
        raise PermissionError(f"Symlinked directory not allowed within memory root: {path}")
    if not stat.S_ISDIR(metadata.st_mode):
        raise PermissionError(f"Expected directory inside memory root, found: {path}")
