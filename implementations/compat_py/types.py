"""
Action-governance types for the compatibility boundary.

Every adapter decision flows through these structures.
No exceptions, no ad hoc dicts.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class ReasonCode(str, Enum):
    SUCCESS = "SUCCESS"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    TARGET_NOT_ALLOWED = "TARGET_NOT_ALLOWED"
    ACTION_NOT_SUPPORTED = "ACTION_NOT_SUPPORTED"
    AGENT_REVOKED = "AGENT_REVOKED"
    AGENT_SCOPE_DENIED = "AGENT_SCOPE_DENIED"


@dataclass
class AdapterRequest:
    """What the agent requests through the boundary."""
    operation: str
    target: str
    content: str
    agent_id: Optional[str] = None
    requires_confirmation: bool = False


@dataclass
class AdapterResult:
    """What comes back from the boundary."""
    performed: bool
    reason_code: ReasonCode
    message: str
    operation: str
    target: str
    bytes_written: Optional[int] = None


@dataclass
class AuditEntry:
    """One decision record. Minimal, explicit, no framework."""
    timestamp: str
    operation: str
    target: str
    agent_id: Optional[str]
    performed: bool
    reason_code: ReasonCode

    @classmethod
    def from_result(cls, request: "AdapterRequest", result: "AdapterResult") -> "AuditEntry":
        return cls(
            timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            operation=result.operation,
            target=result.target,
            agent_id=request.agent_id,
            performed=result.performed,
            reason_code=result.reason_code,
        )
