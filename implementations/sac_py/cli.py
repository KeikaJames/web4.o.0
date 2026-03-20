"""
CLI for SAC reference implementation.

Usage:
    python -m implementations.sac_py.cli create --output ./my-sac.json
    python -m implementations.sac_py.cli show ./my-sac.json
    python -m implementations.sac_py.cli derive-agent ./my-sac.json --purpose "email-handler"
    python -m implementations.sac_py.cli rotate-key ./my-sac.json
    python -m implementations.sac_py.cli export-metadata ./my-sac.json
    python -m implementations.sac_py.cli check-permission ./my-sac.json --operation "financial.transaction" --amount 500
"""

import argparse
import getpass
import json
import os
import sys
from pathlib import Path

from .sac import SACContainer


def _require_passphrase(args) -> str:
    passphrase = getattr(args, "passphrase", None) or os.environ.get("SAC_PASSPHRASE")
    if not passphrase and sys.stdin.isatty() and sys.stderr.isatty():
        passphrase = getpass.getpass("SAC passphrase: ")
    if not passphrase:
        raise SystemExit("Passphrase required: use --passphrase or SAC_PASSPHRASE")
    return passphrase


def _add_passphrase_argument(parser):
    parser.add_argument("--passphrase", help="Container passphrase (or use SAC_PASSPHRASE)")


def cmd_create(args):
    """Create new SAC container."""
    sac = SACContainer.create(memory_path=args.memory_path)
    passphrase = _require_passphrase(args)

    if args.financial_limit:
        sac.permissions.financial_single_tx_limit = args.financial_limit
    if args.daily_limit:
        sac.permissions.financial_daily_limit = args.daily_limit

    output_path = Path(args.output)
    sac.save(output_path, passphrase)

    print(f"Created SAC: {sac.sac_id}")
    print(f"Saved to: {output_path}")
    print(f"Root key ID: {sac.root_key.key_id}")


def cmd_show(args):
    """Show SAC container details."""
    sac = SACContainer.load(Path(args.container), _require_passphrase(args))

    print(f"SAC ID: {sac.sac_id}")
    print(f"Created: {sac.created_at}")
    print(f"Root Key ID: {sac.root_key.key_id}")
    print(f"Memory Root: {sac.memory_root.reference}")
    print(f"Derived Agents: {len(sac.derived_agents)}")

    if sac.derived_agents:
        print("\nDerived Agents:")
        for agent in sac.derived_agents:
            status = "REVOKED" if agent.revoked else "ACTIVE"
            print(f"  - {agent.agent_id[:8]}... | {agent.purpose} | {status}")


def cmd_derive_agent(args):
    """Derive child agent."""
    passphrase = _require_passphrase(args)
    sac = SACContainer.load(Path(args.container), passphrase)

    agent = sac.derive_agent(args.purpose)
    sac.save(Path(args.container), passphrase)

    print(f"Derived agent: {agent.agent_id}")
    print(f"Purpose: {agent.purpose}")
    print(f"Derived key ID: {agent.derived_key_id}")


def cmd_rotate_key(args):
    """Rotate root key."""
    passphrase = _require_passphrase(args)
    sac = SACContainer.load(Path(args.container), passphrase)

    old_key_id = sac.root_key.key_id
    sac.rotate_key()
    sac.save(Path(args.container), passphrase)

    print(f"Rotated root key")
    print(f"Old key ID: {old_key_id}")
    print(f"New key ID: {sac.root_key.key_id}")


def cmd_export_metadata(args):
    """Export metadata without secrets."""
    sac = SACContainer.load(Path(args.container), _require_passphrase(args))

    metadata = sac.export_metadata()

    if args.output:
        output_path = Path(args.output)
        with open(output_path, 'w') as f:
            json.dump(metadata, f, indent=2)
        print(f"Exported metadata to: {output_path}")
    else:
        print(json.dumps(metadata, indent=2))


def cmd_check_permission(args):
    """Check if operation is allowed."""
    sac = SACContainer.load(Path(args.container), _require_passphrase(args))

    context = {}
    if args.amount:
        context["amount"] = args.amount
    if args.daily_total:
        context["daily_total"] = args.daily_total
    if args.confirmed:
        context["user_confirmed"] = True

    allowed, reason = sac.check_permission(args.operation, context)

    if allowed:
        print(f"✓ ALLOWED: {args.operation}")
        print(f"  Reason: {reason}")
        sys.exit(0)
    else:
        print(f"✗ DENIED: {args.operation}")
        print(f"  Reason: {reason}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="SAC Reference Implementation CLI"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # create
    create_parser = subparsers.add_parser("create", help="Create new SAC container")
    create_parser.add_argument("--memory-path", default="./memory", help="Memory root path")
    create_parser.add_argument("--financial-limit", type=float, help="Single transaction limit")
    create_parser.add_argument("--daily-limit", type=float, help="Daily transaction limit")
    create_parser.add_argument("--output", required=True, help="Output file path")
    _add_passphrase_argument(create_parser)

    # show
    show_parser = subparsers.add_parser("show", help="Show SAC container")
    show_parser.add_argument("container", help="SAC container file")
    _add_passphrase_argument(show_parser)

    # derive-agent
    derive_parser = subparsers.add_parser("derive-agent", help="Derive child agent")
    derive_parser.add_argument("container", help="SAC container file")
    derive_parser.add_argument("--purpose", required=True, help="Agent purpose")
    _add_passphrase_argument(derive_parser)

    # rotate-key
    rotate_parser = subparsers.add_parser("rotate-key", help="Rotate root key")
    rotate_parser.add_argument("container", help="SAC container file")
    _add_passphrase_argument(rotate_parser)

    # export-metadata
    export_parser = subparsers.add_parser("export-metadata", help="Export metadata")
    export_parser.add_argument("container", help="SAC container file")
    export_parser.add_argument("--output", help="Output file (default: stdout)")
    _add_passphrase_argument(export_parser)

    # check-permission
    check_parser = subparsers.add_parser("check-permission", help="Check permission")
    check_parser.add_argument("container", help="SAC container file")
    check_parser.add_argument("--operation", required=True, help="Operation to check")
    check_parser.add_argument("--amount", type=float, help="Transaction amount")
    check_parser.add_argument("--daily-total", type=float, help="Daily total so far")
    check_parser.add_argument("--confirmed", action="store_true", help="User confirmed")
    _add_passphrase_argument(check_parser)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "create": cmd_create,
        "show": cmd_show,
        "derive-agent": cmd_derive_agent,
        "rotate-key": cmd_rotate_key,
        "export-metadata": cmd_export_metadata,
        "check-permission": cmd_check_permission,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
