"""scripts/marina/cli.py — argument parsing for `scripts/marina/__main__.py`.

Subcommands:

- `hook require-receipt` (F2): the Stop hook. Invalid arguments, invalid
  hook input and unexpected errors exit 1 (non-blocking), never 2, so a
  broken hook cannot trap a session in an endless Stop loop.
- `approve <project> <task>` (F3): records `[envelope.approval]` in that
  task's `state.toml` after the human types the slug on a TTY
  (scripts/marina/envelope.py). It writes nothing else.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
from pathlib import Path
from typing import Callable, TextIO

from scripts.marina import envelope, hooks
from scripts.state import StateError

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_DEFAULT_KIT_ROOT = Path(__file__).resolve().parents[2]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marina", description="Marina's executable.")
    commands = parser.add_subparsers(dest="command", required=True)
    hook = commands.add_parser("hook", help="Claude Code hook entry points")
    hook_commands = hook.add_subparsers(dest="hook", required=True)
    require = hook_commands.add_parser("require-receipt", help="Stop hook: block until the receipt passes receipt-lint")
    require.add_argument("--receipt", required=True)
    require.add_argument("--handoff", required=True)
    approve = commands.add_parser("approve", help="approve a task's [envelope] (interactive terminal only)")
    approve.add_argument("project")
    approve.add_argument("task")
    approve.add_argument("--kit-root", default=str(_DEFAULT_KIT_ROOT))
    return parser


def _run_hook(args: argparse.Namespace, *, stdin: TextIO, stderr: TextIO) -> int:
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


def _run_approve(
    args: argparse.Namespace, *, stdin: TextIO, stdout: TextIO, stderr: TextIO, isatty: Callable[[], bool]
) -> int:
    for label, value in (("project", args.project), ("task", args.task)):
        if not _SLUG_RE.fullmatch(value):
            print(f"marina approve: {label} must match ^[a-z0-9-]+$, got {value!r}", file=stderr)
            return 1
    kit_root = Path(args.kit_root)
    state_path = kit_root / ".agent-state" / args.project / "tasks" / args.task / "state.toml"
    if not state_path.is_file():
        print(f"marina approve: no state.toml at {state_path}", file=stderr)
        return 1
    try:
        return envelope.approve(
            state_path,
            kit_root=kit_root,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            isatty=isatty,
            now=lambda: datetime.datetime.now().astimezone(),
        )
    except (StateError, OSError) as exc:
        print(f"marina approve: {exc}", file=stderr)
        return 1


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    isatty: Callable[[], bool] | None = None,
) -> int:
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        # argparse exits 2 on bad arguments, which a Stop hook would read as "block".
        if exc.code in (0, None):
            return 0
        print(f"marina: invalid arguments: {argv if argv is not None else sys.argv[1:]}", file=stderr)
        return 1
    if args.command == "hook":
        return _run_hook(args, stdin=stdin, stderr=stderr)
    if isatty is None:
        isatty = lambda: stdin.isatty() and stdout.isatty()  # noqa: E731
    return _run_approve(args, stdin=stdin, stdout=stdout, stderr=stderr, isatty=isatty)
