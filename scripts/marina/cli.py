"""scripts/marina/cli.py — argument parsing for `scripts/marina/__main__.py`.

Subcommands:

- `hook require-receipt` (F2): the Stop hook. Invalid arguments, invalid
  hook input and unexpected errors exit 1 (non-blocking), never 2, so a
  broken hook cannot trap a session in an endless Stop loop.
- `approve <project> <task>` (F3): records `[envelope.approval]` in that
  task's `state.toml` after the human types the slug on a TTY
  (scripts/marina/envelope.py). It writes nothing else.
- `run <project> <task> --interval S --max-duration D` (F4): runs the
  approved envelope (scripts/marina/runner.py); exit 0 on `done`, 1 on a
  stop or a refusal. `status` prints the task, lock, envelope and nodes;
  `stop` asks a running `run` to stop at its next iteration.
- `go <project> <task>` (F7): running it on a TTY approves the whole plan
  (`envelope.approve_on_dispatch`, with a Ctrl-C grace period) and starts
  `marina run` detached; with a live run it only reports it, and never
  re-approves under a running run.
- `watch <project> <task> [--once]` (F8): the read-only terminal view of
  the task (scripts/marina/watch.py); `go` opens it after dispatching
  unless `--no-watch`.
- `mcp` (F5): the stdio MCP server for interactive Marina
  (scripts/marina/mcp_server.py); stdout carries only JSON-RPC.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path
from typing import Callable, TextIO

from scripts.marina import envelope, hooks, mcp_server, runner, watch
from scripts.state import StateError, read_state

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
    run = commands.add_parser("run", help="run a task's approved envelope until done or a stop reason")
    run.add_argument("--interval", required=True, type=float, help="seconds between manager polls (> 0)")
    run.add_argument("--max-duration", required=True, help="like the envelope: 30s, 90m or 8h")
    run.add_argument("--notify-cmd", default=None, help="command run once per entry into waiting_approval")
    run.add_argument("--recover", action="store_true", help="take over an orphan lock if no task session works")
    go = commands.add_parser("go", help="approve the whole plan by dispatching it, then start marina run (TTY only)")
    go.add_argument("--interval", type=float, default=30.0, help="seconds between manager polls (> 0)")
    go.add_argument("--max-duration", default=None, help="defaults to the envelope's max_duration")
    go.add_argument("--notify-cmd", default=None, help="command run once per entry into waiting_approval")
    go.add_argument("--grace", type=float, default=10.0, help="seconds to cancel with Ctrl-C before approving")
    go.add_argument("--no-watch", action="store_true", help="do not open `marina watch` afterwards")
    watch_cmd = commands.add_parser("watch", help="read-only terminal view of a task's run")
    watch_cmd.add_argument("--once", action="store_true", help="print one snapshot and exit")
    watch_cmd.add_argument("--manager-interval", type=float, default=10.0, help="seconds between manager polls")
    status = commands.add_parser("status", help="show a task's lock, envelope and nodes")
    stop = commands.add_parser("stop", help="ask a running `marina run` to stop at its next iteration")
    mcp = commands.add_parser("mcp", help="serve the MCP stdio server for interactive Marina")
    mcp.add_argument("--kit-root", default=str(_DEFAULT_KIT_ROOT))
    for sub in (approve, go, watch_cmd, run, status, stop):
        sub.add_argument("project")
        sub.add_argument("task")
        sub.add_argument("--kit-root", default=str(_DEFAULT_KIT_ROOT))
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


def _state_path(args: argparse.Namespace, stderr: TextIO) -> Path | None:
    for label, value in (("project", args.project), ("task", args.task)):
        if not _SLUG_RE.fullmatch(value):
            print(f"marina {args.command}: {label} must match ^[a-z0-9-]+$, got {value!r}", file=stderr)
            return None
    state_path = Path(args.kit_root) / ".agent-state" / args.project / "tasks" / args.task / "state.toml"
    if not state_path.is_file():
        print(f"marina {args.command}: no state.toml at {state_path}", file=stderr)
        return None
    return state_path


def _run_approve(
    args: argparse.Namespace, *, stdin: TextIO, stdout: TextIO, stderr: TextIO, isatty: Callable[[], bool]
) -> int:
    kit_root = Path(args.kit_root)
    state_path = _state_path(args, stderr)
    if state_path is None:
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


def _run_run(args: argparse.Namespace, *, stdout: TextIO, stderr: TextIO, deps: runner.RunnerDeps | None) -> int:
    state_path = _state_path(args, stderr)
    if state_path is None:
        return 1
    if not args.interval > 0:
        print("marina run: --interval must be > 0", file=stderr)
        return 1
    try:
        max_duration = envelope.parse_duration(args.max_duration)
    except envelope.EnvelopeError as exc:
        print(f"marina run: --{exc}", file=stderr)
        return 1
    try:
        result = runner.run(
            state_path, kit_root=Path(args.kit_root), interval=args.interval, max_duration=max_duration,
            notify_cmd=args.notify_cmd, recover=args.recover, deps=deps or runner.default_deps(Path(args.kit_root)),
        )
    except (runner.RunRefused, StateError, OSError) as exc:
        print(f"marina run: {exc}", file=stderr)
        return 1
    print(f"marina run: {result.outcome} {result.reason}".rstrip(), file=stdout)
    return 0 if result.outcome == "done" else 1


def _run_go(
    args: argparse.Namespace, *, stdout: TextIO, stderr: TextIO, isatty: Callable[[], bool],
    spawn: Callable[[list[str], Path, Path], int], sleep: Callable[[float], None],
    open_watch: Callable[[Path, Path], int],
) -> int:
    state_path = _state_path(args, stderr)
    if state_path is None:
        return 1
    if not args.interval > 0 or not args.grace >= 0:
        print("marina go: --interval must be > 0 and --grace >= 0", file=stderr)
        return 1
    if args.max_duration is not None:
        try:
            envelope.parse_duration(args.max_duration)
        except envelope.EnvelopeError as exc:
            print(f"marina go: --{exc}", file=stderr)
            return 1
    kit_root, task_dir = Path(args.kit_root), state_path.parent
    # Never approve under a running run: it would start obeying the new hash.
    pid = runner.live_lock_pid(task_dir)
    if pid is not None:
        print(f"marina go: run already in progress (pid {pid}); `marina status {args.project} {args.task}`",
              file=stdout)
        return 0 if args.no_watch else open_watch(state_path, kit_root)
    try:
        code = envelope.approve_on_dispatch(
            state_path, kit_root=kit_root, stdout=stdout, stderr=stderr, isatty=isatty,
            now=lambda: datetime.datetime.now().astimezone(), sleep=sleep, grace=args.grace,
        )
        if code:
            return 1
        env = envelope.envelope_from_doc(read_state(state_path))
    except (StateError, OSError) as exc:
        print(f"marina go: {exc}", file=stderr)
        return 1
    argv = runner.run_argv(kit_root, args.project, args.task, interval=args.interval,
                           max_duration=args.max_duration or env.max_duration, notify_cmd=args.notify_cmd)
    log = task_dir / runner.LOG_NAME
    pid = spawn(argv, kit_root, log)
    print(f"marina go: marina run started, pid {pid}; log {log}", file=stdout)
    print(f"follow it with `marina status {args.project} {args.task}` or `marina watch {args.project} "
          f"{args.task}`; stop it with `marina stop {args.project} {args.task}`", file=stdout)
    return 0 if args.no_watch else open_watch(state_path, kit_root)


def _run_watch(args: argparse.Namespace, *, stdout: TextIO, stderr: TextIO, isatty: Callable[[], bool]) -> int:
    state_path = _state_path(args, stderr)
    if state_path is None:
        return 1
    if not args.manager_interval > 0:
        print("marina watch: --manager-interval must be > 0", file=stderr)
        return 1
    try:
        return watch.run_watch(state_path, kit_root=Path(args.kit_root), once=args.once, stdout=stdout,
                               isatty=isatty, manager_interval=args.manager_interval,
                               deps=watch.default_watch_deps())
    except (StateError, OSError) as exc:
        print(f"marina watch: {exc}", file=stderr)
        return 1


def _run_status(args: argparse.Namespace, *, stdout: TextIO, stderr: TextIO) -> int:
    state_path = _state_path(args, stderr)
    if state_path is None:
        return 1
    try:
        lines = runner.status_lines(state_path)
    except (StateError, OSError) as exc:
        print(f"marina status: {exc}", file=stderr)
        return 1
    print("\n".join(lines), file=stdout)
    return 0


def _run_stop(args: argparse.Namespace, *, stdout: TextIO, stderr: TextIO) -> int:
    state_path = _state_path(args, stderr)
    if state_path is None:
        return 1
    if not runner.request_stop(state_path):
        print(f"marina stop: no marina run in progress for {args.project}/{args.task}", file=stderr)
        return 1
    print(f"marina stop: stop requested for {args.project}/{args.task}", file=stdout)
    return 0


def main(
    argv: list[str] | None = None,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
    isatty: Callable[[], bool] | None = None,
    deps: runner.RunnerDeps | None = None,
    spawn: Callable[[list[str], Path, Path], int] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    open_watch: Callable[[Path, Path], int] | None = None,
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
    if args.command == "mcp":
        return mcp_server.serve(stdin, stdout, kit_root=Path(args.kit_root), deps=mcp_server.default_mcp_deps())
    if args.command == "run":
        return _run_run(args, stdout=stdout, stderr=stderr, deps=deps)
    if isatty is None:
        isatty = lambda: stdin.isatty() and stdout.isatty()  # noqa: E731
    if args.command == "go":
        if open_watch is None:
            def open_watch(state_path: Path, kit_root: Path) -> int:
                return watch.run_watch(state_path, kit_root=kit_root, once=False, stdout=stdout, isatty=isatty,
                                       manager_interval=10.0, deps=watch.default_watch_deps())
        return _run_go(args, stdout=stdout, stderr=stderr, isatty=isatty, spawn=spawn or runner.spawn_detached,
                       sleep=sleep, open_watch=open_watch)
    if args.command == "watch":
        return _run_watch(args, stdout=stdout, stderr=stderr, isatty=isatty)
    if args.command == "status":
        return _run_status(args, stdout=stdout, stderr=stderr)
    if args.command == "stop":
        return _run_stop(args, stdout=stdout, stderr=stderr)
    return _run_approve(args, stdin=stdin, stdout=stdout, stderr=stderr, isatty=isatty)
