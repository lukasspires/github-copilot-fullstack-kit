#!/usr/bin/env python3
"""scripts/state/__main__.py — `state init` / `state add` / `state set` /
`state next-nn`.

Run as `python3 -m scripts.state <command> ...` from kit_root.

Minimum tested Claude CLI version: none (neutral script; no native CLI
invoked — this only reads/writes `state.toml`).

Writes only the `state.toml` file passed via `--state` (runtime write
scope: `.agent-state/<project>/tasks/<task>/`, never `scripts/`, `tests/`
or a target repository).
"""

from __future__ import annotations

import argparse
import datetime
import sys

from . import StateError, add_assignment, init_state, next_nn, read_state, set_state, write_state


def _parse_at(value: str | None) -> datetime.datetime | None:
    if value is None:
        return None
    return datetime.datetime.fromisoformat(value)


def cmd_init(args: argparse.Namespace) -> int:
    doc = init_state(
        args.state,
        project=args.project,
        slug=args.slug,
        title=args.title,
        kit_root=args.kit_root,
        targets=args.target,
        phase=args.phase,
        at=_parse_at(args.at),
    )
    write_state(args.state, doc)
    print(f"initialized {args.state} (project={args.project}, slug={args.slug})")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    doc = read_state(args.state)
    assignment = add_assignment(
        doc,
        role=args.role,
        type_=args.type,
        edge=args.edge,
        predecessor=args.predecessor,
        targets=args.target,
        platform=args.platform,
        host=args.host,
        reason=args.reason,
        allowlist=args.allowlist,
        note=args.note,
        at=_parse_at(args.at),
    )
    write_state(args.state, doc)
    print(assignment.nn)
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    doc = read_state(args.state)
    set_state(doc, args.nn, args.to, by=args.by, note=args.note, at=_parse_at(args.at))
    write_state(args.state, doc)
    print(f"nn={args.nn} -> {args.to}")
    return 0


def cmd_next_nn(args: argparse.Namespace) -> int:
    doc = read_state(args.state)
    print(next_nn(doc))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python3 -m scripts.state",
        description="schema-v0 state.toml operations (stdlib only; no target-repository writes).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init_p = sub.add_parser("init", help="bootstrap a brand-new task's state.toml [task] header")
    init_p.add_argument("--state", required=True, help="path to the new state.toml (must not already exist)")
    init_p.add_argument("--project", required=True)
    init_p.add_argument("--slug", required=True)
    init_p.add_argument("--title", required=True)
    init_p.add_argument("--kit-root", required=True, dest="kit_root")
    init_p.add_argument("--target", action="append", required=True, help="repeat per target_root")
    init_p.add_argument("--phase", default="intake")
    init_p.add_argument("--at", default=None, help="ISO 8601 timestamp override (tests only)")
    init_p.set_defaults(func=cmd_init)

    add_p = sub.add_parser("add", help="reserve a new assignment node (G3, judgment fields)")
    add_p.add_argument("--state", required=True, help="path to state.toml")
    add_p.add_argument("--role", required=True)
    add_p.add_argument("--type", required=True, dest="type")
    add_p.add_argument("--edge", required=True)
    add_p.add_argument("--predecessor", required=True, type=int)
    add_p.add_argument("--target", action="append", required=True, help="repeat per target_root")
    add_p.add_argument("--platform", default="claude", choices=("claude", "codex", "unavailable"))
    add_p.add_argument("--host", default="", help="Codex hostId, when platform=codex")
    add_p.add_argument("--reason", default="", help="required when platform=unavailable")
    add_p.add_argument("--allowlist", action="append", default=None, help="repeat per granted Bash(...) rule")
    add_p.add_argument("--note", default="")
    add_p.add_argument("--at", default=None, help="ISO 8601 timestamp override (tests only)")
    add_p.set_defaults(func=cmd_add)

    set_p = sub.add_parser("set", help="record a coordinator judgment (or observed) G2 transition")
    set_p.add_argument("--state", required=True)
    set_p.add_argument("--nn", required=True, type=int)
    set_p.add_argument("--to", required=True)
    set_p.add_argument("--by", default="coordinator")
    set_p.add_argument("--note", default="")
    set_p.add_argument("--at", default=None)
    set_p.set_defaults(func=cmd_set)

    nn_p = sub.add_parser("next-nn", help="print the next free nn for a task")
    nn_p.add_argument("--state", required=True)
    nn_p.set_defaults(func=cmd_next_nn)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (StateError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
