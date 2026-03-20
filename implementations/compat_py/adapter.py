"""
Compatibility adapter: action governance boundary.

A SAC-backed agent requests an action. The adapter checks
the permission cage, confines the target, performs or denies,
and returns an explicit result with an audit entry.

This is the first real action boundary of the protocol.
"""

from typing import Tuple

from implementations.compat_py.path_security import resolve_within_memory_root
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
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(request.content, encoding="utf-8")
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
