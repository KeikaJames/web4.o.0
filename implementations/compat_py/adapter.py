"""
Compatibility adapter: action governance boundary.

A SAC-backed agent requests an action. The adapter checks
the permission cage, confines the target, performs or denies,
and returns an explicit result with an audit entry.

This is the first real action boundary of the protocol.
"""

import os
import tempfile
from typing import Tuple

from implementations.compat_py.path_security import (
    ensure_write_target_within_memory_root,
    resolve_within_memory_root,
)
from implementations.compat_py.types import (
    AdapterRequest,
    AdapterResult,
    AuditEntry,
    ReasonCode,
)

SUPPORTED_ACTIONS = frozenset({"file.write"})


def _deny(request: AdapterRequest, code: ReasonCode, message: str) -> AdapterResult:
    return AdapterResult(
        performed=False,
        reason_code=code,
        message=message,
        operation=request.operation,
        target=request.target,
    )


def _check_permission(sac, request: AdapterRequest) -> Tuple[bool, ReasonCode, str]:
    ctx = {}
    if request.agent_id is not None:
        ctx["agent_id"] = request.agent_id

    if request.requires_confirmation:
        ctx["confirmed"] = True

    allowed, reason = sac.check_permission(request.operation, ctx)
    if not allowed:
        if "revoked" in reason.lower():
            return False, ReasonCode.AGENT_REVOKED, reason
        if "not allowed" in reason.lower() or "unsupported" in reason.lower():
            code = ReasonCode.AGENT_SCOPE_DENIED if request.agent_id else ReasonCode.PERMISSION_DENIED
            return False, code, reason
        if "confirmation" in reason.lower():
            return False, ReasonCode.REQUIRES_CONFIRMATION, reason
        return False, ReasonCode.PERMISSION_DENIED, reason
    return True, ReasonCode.SUCCESS, reason


def _safe_write(sac, target_path, content_bytes: bytes) -> None:
    """
    Atomic, symlink-safe file write.

    1. Re-validate the parent chain inside memory_root and create any missing
       directories only if they are plain directories, not symlinks.
    2. Write to a temp file in the same directory.
    3. Use os.open() with O_NOFOLLOW on the final path before rename so that
       if a symlink was planted between resolve() and the write, the open
       fails with OSError rather than following the link.
    4. Re-check the parent chain, then rename the temp file into place
       (atomic on POSIX).

    O_NOFOLLOW is POSIX-only.  On Windows (no O_NOFOLLOW) we fall back to the
    rename-only path, which still defends against most races but not a
    concurrent symlink replacement — acceptable for a prototype on POSIX.
    """
    target_path = ensure_write_target_within_memory_root(sac, target_path)
    parent = target_path.parent

    # Write to a temp file first (never follows symlinks at its own path)
    fd, tmp_path = tempfile.mkstemp(dir=str(parent), prefix=".tmp_")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content_bytes)
            f.flush()
            os.fsync(f.fileno())

        # Before rename, try to open the *final* path with O_NOFOLLOW to
        # detect a race.  On Linux O_NOFOLLOW | O_PATH is enough; on macOS
        # O_NOFOLLOW alone works.  If the path doesn't exist yet this open
        # will fail with FileNotFoundError — that's fine, it just means no
        # symlink was planted, so we proceed to rename safely.
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        if nofollow:
            try:
                probe_fd = os.open(
                    str(target_path),
                    os.O_WRONLY | nofollow,
                )
                os.close(probe_fd)
            except FileNotFoundError:
                pass  # Target doesn't exist yet — clean to create
            except OSError as exc:
                # ELOOP (too many levels of symbolic links) or similar — symlink planted
                import errno as _errno
                if exc.errno in (_errno.ELOOP,):
                    raise PermissionError(
                        f"Symlink detected at target path, write refused: {target_path}"
                    ) from exc
                raise

        target_path = ensure_write_target_within_memory_root(sac, target_path)
        os.replace(tmp_path, str(target_path))
        tmp_path = None  # ownership transferred
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def file_write(sac, request: AdapterRequest) -> Tuple[AdapterResult, AuditEntry]:
    """
    Governance boundary: agent requests a local file write.

    Returns (result, audit_entry). Every call produces both.
    """
    if request.operation not in SUPPORTED_ACTIONS:
        result = _deny(request, ReasonCode.ACTION_NOT_SUPPORTED,
                        f"Unsupported action: {request.operation}")
        return result, AuditEntry.from_result(request, result)

    allowed, code, message = _check_permission(sac, request)
    if not allowed:
        result = _deny(request, code, message)
        return result, AuditEntry.from_result(request, result)

    try:
        target = resolve_within_memory_root(sac, request.target, must_exist=False)
    except (OSError, RuntimeError, PermissionError) as exc:
        result = _deny(request, ReasonCode.TARGET_NOT_ALLOWED, str(exc))
        return result, AuditEntry.from_result(request, result)

    try:
        content_bytes = request.content.encode("utf-8")
        _safe_write(sac, target, content_bytes)
    except PermissionError as e:
        result = AdapterResult(
            performed=False,
            reason_code=ReasonCode.TARGET_NOT_ALLOWED,
            message=f"Symlink-safe write refused: {e}",
            operation=request.operation,
            target=str(target),
        )
        return result, AuditEntry.from_result(request, result)
    except OSError as e:
        result = AdapterResult(
            performed=False,
            reason_code=ReasonCode.PERMISSION_DENIED,
            message=f"OS error: {e}",
            operation=request.operation,
            target=str(target),
        )
        return result, AuditEntry.from_result(request, result)

    result = AdapterResult(
        performed=True,
        reason_code=ReasonCode.SUCCESS,
        message="OK",
        operation=request.operation,
        target=str(target),
        bytes_written=len(request.content.encode("utf-8")),
    )
    return result, AuditEntry.from_result(request, result)
