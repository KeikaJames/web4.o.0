"""
CLI entry: first executable local agent command.

Loads a SAC, reads input, runs agent loop through compat_py,
prints the governance decision. That's it.
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from implementations.sac_py.sac import SACContainer
from implementations.compat_py.agent_loop import run_once
from implementations.compat_py.model import get_model


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="run-local-agent",
        description="Run one local agent loop iteration through the SAC action boundary.",
    )
    parser.add_argument("--sac", required=True, help="Path to SAC container file")
    parser.add_argument("--input", required=True, dest="input_file", help="Input file path")
    parser.add_argument("--output", required=True, dest="output_file", help="Output file path")
    parser.add_argument("--passphrase", default=None, help="SAC passphrase (or set SAC_PASSPHRASE)")
    parser.add_argument("--agent-id", default=None, help="Derived agent ID to act as")
    parser.add_argument("--confirm", action="store_true", help="Provide user confirmation for the action")
    parser.add_argument("--json", action="store_true", dest="json_output", help="Output as JSON")
    parser.add_argument("--model-provider", default=None,
                        help="Model provider: mock, anthropic (or set MODEL_PROVIDER)")

    args = parser.parse_args(argv)

    passphrase = args.passphrase or os.environ.get("SAC_PASSPHRASE", "")
    if not passphrase and sys.stdin.isatty() and sys.stderr.isatty():
        passphrase = getpass.getpass("SAC passphrase: ")
    if not passphrase:
        print("error: passphrase required (--passphrase or SAC_PASSPHRASE)", file=sys.stderr)
        return 1

    try:
        sac = SACContainer.load(Path(args.sac), passphrase)
    except Exception as e:
        print(f"error: failed to load SAC: {e}", file=sys.stderr)
        return 1

    ctx = {}
    if args.confirm:
        ctx["user_confirmed"] = True

    model = get_model(provider=args.model_provider)

    try:
        result = run_once(
            sac,
            args.input_file,
            args.output_file,
            context=ctx,
            agent_id=args.agent_id,
            model=model,
        )
    except PermissionError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"error: agent loop failed: {e}", file=sys.stderr)
        return 1

    r = result.adapter_result
    a = result.audit

    if args.json_output:
        print(json.dumps({
            "performed": r.performed,
            "reason_code": r.reason_code.value,
            "message": r.message,
            "operation": r.operation,
            "target": r.target,
            "bytes_written": r.bytes_written,
            "agent_id": a.agent_id,
            "timestamp": a.timestamp,
        }, indent=2))
    else:
        print(f"operation:   {r.operation}")
        print(f"performed:   {r.performed}")
        print(f"reason_code: {r.reason_code.value}")
        print(f"message:     {r.message}")
        if r.performed:
            print(f"target:      {r.target}")
            print(f"bytes:       {r.bytes_written}")

    return 0 if r.performed else 1


if __name__ == "__main__":
    sys.exit(main())
