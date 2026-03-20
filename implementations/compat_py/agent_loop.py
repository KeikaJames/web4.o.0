"""
Local agent loop.

Reads input file, runs model, proposes action through
the compatibility adapter, returns result.

This is the first behavioral proof: SAC-backed agent
acting into the old world through an explicit boundary.
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from implementations.compat_py.model import ModelClient, ModelOutput, MockModel, get_model
from implementations.compat_py.adapter import file_write
from implementations.compat_py.path_security import resolve_within_memory_root
from implementations.compat_py.types import AdapterRequest, AdapterResult, AuditEntry


@dataclass
class LoopResult:
    """Full trace of one agent loop iteration."""
    input_path: str
    input_text: str
    model_output: ModelOutput
    adapter_result: AdapterResult
    audit: AuditEntry


def run_once(
    sac,
    input_path: str,
    output_path: str,
    context: Optional[Dict[str, Any]] = None,
    agent_id: Optional[str] = None,
    model: Optional[ModelClient] = None,
) -> LoopResult:
    """
    One iteration of the local agent loop.

    1. Read input file (confined to memory root)
    2. Run model (mock or real, caller's choice)
    3. Build explicit AdapterRequest from model proposal
    4. Pass through adapter (permission check + action)
    5. Return full trace with audit entry
    """
    ctx = context or {}
    if model is None:
        model = get_model()

    safe_input_path = resolve_within_memory_root(sac, input_path, must_exist=True)
    safe_output_path = resolve_within_memory_root(sac, output_path, must_exist=False)
    text = safe_input_path.read_text(encoding="utf-8")

    model_out = model.run(text, str(safe_output_path))

    request = AdapterRequest(
        operation=model_out.proposed_action,
        target=model_out.proposed_path,
        content=model_out.transformed_text,
        agent_id=agent_id,
        requires_confirmation=ctx.get("user_confirmed", False),
    )

    result, audit = file_write(sac, request)

    return LoopResult(
        input_path=str(safe_input_path),
        input_text=text,
        model_output=model_out,
        adapter_result=result,
        audit=audit,
    )
