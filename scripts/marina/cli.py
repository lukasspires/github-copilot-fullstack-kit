"""scripts/marina/cli.py — argument parsing for `scripts/marina/__main__.py`.

Only `hook require-receipt` exists in F2. Invalid arguments, invalid hook
input and unexpected errors exit 1 (non-blocking), never 2, so a broken
hook cannot trap a session in an endless Stop loop.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from scripts.marina import hooks


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marina", description="Marina's executable (F2: session hooks only).")
    commands = parser.add_subparsers(dest="command", required=True)
    hook = commands.add_parser("hook", help="Claude Code hook entry points")
    hook_commands = hook.add_subparsers(dest="hook", required=True)
    require = hook_commands.add_parser("require-receipt", help="Stop hook: block until the receipt passes receipt-lint")
    require.add_argument("--receipt", required=True)
    require.add_argument("--handoff", required=True)
    return parser


def main(argv: list[str] | None = None, *, stdin: TextIO = sys.stdin, stderr: TextIO = sys.stderr) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on bad arguments, which a Stop hook would read as "block".
        if exc.code in (0, None):
            return 0
        print(f"marina hook: invalid arguments: {argv if argv is not None else sys.argv[1:]}", file=stderr)
        return 1
    try:
        hook_input = json.loads(stdin.read())
    except json.JSONDecodeError as exc:
        print(f"marina hook: invalid hook input on stdin: {exc}", file=stderr)
        return 1
    if not isinstance(hook_input, dict):
        print("marina hook: hook input on stdin is not a JSON object", file=stderr)
        return 1
    try:
        code, message = hooks.require_receipt(hook_input, receipt=Path(args.receipt), handoff=Path(args.handoff))
    except Exception as exc:  # noqa: BLE001 — any failure must stay non-blocking
        print(f"marina hook: unexpected error: {exc}", file=stderr)
        return 1
    if message:
        print(message, file=stderr)
    return code
