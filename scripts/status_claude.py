#!/usr/bin/env python3
"""scripts/status_claude.py — observes `launched -> working -> waiting_approval
-> finished` (G2) via `claude agents --json --all`. Never causes a
transition, never answers a prompt: when `waitingFor: permission prompt`,
prints the literal instruction `claude attach <id>` and stops.

Minimum tested Claude CLI version: 2.1.270 — `cwd` confirmed present on
every listed session (background and interactive) on this version; see
docs/agent-workflow.md's "Claude Code" section. Filters by `cwd` and/or
title prefix, per the handoff (not title prefix alone).

Read-only by default: never writes anything unless the optional `--state
PATH` and `--nn N` are both supplied (tooling-gaps-fix Finding 2; `--nn`
alone remains a pure, non-persisting filter — RISK 2 relaxation), in which
case exactly one matched session's observed G2 transition is persisted
into that `state.toml` (never anywhere else). Every native-manager call is
injectable (`list_sessions`, default `scripts.common.list_manager_sessions`);
no test here touches the real installed CLI or a real `state.toml` under
`.agent-state/`.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common
from scripts import state as state_module

ATTACH_INSTRUCTION = "claude attach {id}"

FINISHED_STATES = frozenset({"done", "stopped", "failed"})

# Finding 2 (tooling-gaps-fix): classifications that map to a recordable G2
# target state. "unknown" (and a `None` classification, no matching
# session) are deliberately absent — never written (Finding 3's guard
# extends to persistence too: an unresolved/transient classification must
# never itself cause a state.toml write).
G2_TARGET_BY_CLASSIFICATION: dict[str, str] = {
    "working": "working",
    "waiting_approval": "waiting_approval",
    "finished": "finished",
}


def record_observed_transition(
    state_path: str,
    nn: int,
    classification: str | None,
    *,
    at: datetime.datetime | None = None,
) -> bool:
    """Persist one observed G2 transition into `state.toml` (Finding 2).

    Maps `classification` to its G2 target state and appends the event via
    `scripts.state.append_event`/`can_transition` — transition legality is
    never reimplemented here. Returns `True` iff a write happened.

    Writes nothing (returns `False`) when: `classification` is `"unknown"`
    or `None` (no target state — Finding 3's guard); the assignment is
    already in the target state (a no-op is not a duplicate event); or the
    observed transition would be illegal for the assignment's current
    recorded state, in which case a warning is printed to stderr instead
    of raising or corrupting `state.toml` (a defensive guard, not expected
    to trigger in normal use — e.g. `launch-claude` was never run so the
    assignment is still `prepared`, but the manager reports `working` for
    an unrelated reason).
    """

    target = G2_TARGET_BY_CLASSIFICATION.get(classification)
    if target is None:
        return False

    doc = state_module.read_state(state_path)
    assignment = state_module.get_assignment(doc, nn)

    if assignment.state == target:
        return False

    if not state_module.can_transition(assignment.state, target):
        print(
            f"warning: observed classification {classification!r} would require an illegal "
            f"G2 transition for nn={nn} ({assignment.state} -> {target}); skipping state.toml write",
            file=sys.stderr,
        )
        return False

    at = at or datetime.datetime.now().astimezone()
    assignment.native.last_seen = classification
    assignment.native.last_seen_at = at
    state_module.append_event(assignment, target, by="status", at=at)
    doc.task.updated_at = at
    state_module.write_state(state_path, doc)
    return True


def classify_session(session: dict) -> str:
    """One of "working" / "waiting_approval" / "finished" / "unknown".

    "unknown" covers an interactive session that documentedly omits
    `state`/`status` — not a schema error (docs/agent-workflow.md:
    "interactive sessions may omit state/status/waitingFor").
    """

    common.validate_manager_session_schema(session)
    if session.get("status") == "waiting" and session.get("waitingFor") == "permission prompt":
        return "waiting_approval"
    state = session.get("state")
    if state == "working":
        return "working"
    if state in FINISHED_STATES:
        return "finished"
    return "unknown"


def session_nn(name: str) -> int | None:
    """Parse the `nn` segment out of a session title.

    Follows the kit's "<task> — <role> — <nn> — <type>" naming convention
    (docs/agent-workflow.md's "Claude Code" example): exactly four
    " — "-separated segments, the third being the numeric `nn`. Returns
    `None` (never raises) when `name` does not have this shape or the
    third segment is not an integer, so filtering by `--nn` on a
    differently-shaped title simply excludes it rather than erroring.
    """

    parts = name.split(" — ")
    if len(parts) != 4:
        return None
    try:
        return int(parts[2].strip())
    except ValueError:
        return None


def find_task_sessions(
    sessions: list[dict],
    *,
    cwd: str | None = None,
    title_prefix: str | None = None,
    native_id: str | None = None,
    nn: int | None = None,
) -> list[dict]:
    """Sessions matching every filter actually supplied (`cwd`, `title_prefix`,
    `native_id`, `nn` — every one given must match, not "any is sufficient").

    Real evidence this matters: the kit_root is shared by every session
    launched from it, so filtering by `cwd` alone can match an unrelated
    session (confirmed against the real installed manager on 2026-09-19 —
    see the receipt). Passing no filter at all matches nothing (never
    "everything"), so a missing filter cannot silently widen scope.

    `native_id`/`nn` (Finding 1, `02-reviewer-receipt.md`) let a caller
    holding one assignment's own `state.toml` disambiguate to that exact
    session — by its recorded `native.id`, or by the `nn` segment of its
    title — when `cwd`/`title_prefix` alone still match more than one
    session of the same task (the normal shape once a task has more than
    one assignment). `status_claude`'s own multi-match `report()`/`main()`
    behavior is unaffected when these two are left unset; `watch_claude`'s
    single-outcome `run_watch` is the caller that turns a remaining
    multi-match into a loud error rather than silently picking one.
    """

    hits: list[dict] = []
    for session in sessions:
        common.validate_manager_session_schema(session)
        if cwd is None and title_prefix is None and native_id is None and nn is None:
            continue
        if cwd is not None and session.get("cwd") != cwd:
            continue
        if title_prefix is not None and not session.get("name", "").startswith(title_prefix):
            continue
        if native_id is not None and session.get("id") != native_id:
            continue
        if nn is not None and session_nn(session.get("name", "")) != nn:
            continue
        hits.append(session)
    return hits


@dataclasses.dataclass
class StatusLine:
    name: str
    id: str | None
    classification: str
    attach_message: str | None


def report(sessions: list[dict]) -> list[StatusLine]:
    lines: list[StatusLine] = []
    for session in sessions:
        classification = classify_session(session)
        session_id = session.get("id")
        attach_message = ATTACH_INSTRUCTION.format(id=session_id) if classification == "waiting_approval" else None
        lines.append(
            StatusLine(
                name=session.get("name", "?"), id=session_id, classification=classification, attach_message=attach_message
            )
        )
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="status-claude", description="Report working/waiting_approval/finished for matching sessions."
    )
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--title-prefix", default=None)
    parser.add_argument("--id", dest="native_id", default=None, help="exact recorded native.id, to disambiguate one assignment")
    parser.add_argument("--nn", type=int, default=None, help="exact assignment nn, to disambiguate one assignment")
    parser.add_argument(
        "--state",
        default=None,
        help="state.toml path; requires --nn (to know which assignment to persist "
        "to) and persists the one matched session's observed G2 transition "
        "(Finding 2). --nn alone, without --state, remains a pure disambiguation "
        "filter with no persistence (tooling-gaps-fix RISK 2: --nn-alone usage "
        "was already reviewed and endorsed by a prior task; only --state without "
        "--nn is genuinely ambiguous and rejected)",
    )
    args = parser.parse_args(argv)

    if args.cwd is None and args.title_prefix is None and args.native_id is None and args.nn is None:
        print("error: at least one of --cwd/--title-prefix/--id/--nn is required", file=sys.stderr)
        return 2

    if args.state is not None and args.nn is None:
        print("error: --state requires --nn (to know which assignment to persist to)", file=sys.stderr)
        return 2

    try:
        sessions = common.list_manager_sessions()
    except common.ManagerUnavailable as exc:
        print(f"NOTE: native manager unavailable: {exc}")
        return 0

    matches = find_task_sessions(
        sessions, cwd=args.cwd, title_prefix=args.title_prefix, native_id=args.native_id, nn=args.nn
    )
    if not matches:
        print("no matching sessions")
        return 0

    saw_waiting_approval = False
    lines = report(matches)
    for line in lines:
        print(f"{line.name}: {line.classification}" + (f" (id={line.id})" if line.id else ""))
        if line.attach_message:
            print(f"  {line.attach_message}")
            saw_waiting_approval = True

    if args.state is not None and args.nn is not None:
        if len(matches) == 1:
            record_observed_transition(args.state, args.nn, lines[0].classification)
        else:
            print(
                f"warning: {len(matches)} sessions match nn={args.nn}; cannot unambiguously "
                f"persist to {args.state}",
                file=sys.stderr,
            )

    return 1 if saw_waiting_approval else 0


if __name__ == "__main__":
    sys.exit(main())
