#!/usr/bin/env python3
"""scripts/watch_claude.py — bounded polling loop (plan §6.2) around
status_claude's classification. Exits the instant it *observes* a state
change or a pending approval; never causes either. `--interval` and
`--max-duration` are mandatory — there is no infinite default.

Minimum tested Claude CLI version: 2.1.270 (same manager JSON contract as
scripts/status_claude.py; see that module's header).

Read-only by default: never writes anything unless the optional `--state
PATH` and `--nn N` are both supplied (tooling-gaps-fix Finding 2; `--nn`
alone remains a pure, non-persisting filter — RISK 2 relaxation), in which
case an observed `state_changed` exit persists that transition into
`state.toml` via `status_claude.record_observed_transition` (never
anywhere else). Every test injects a fake clock and a fixed sequence of
manager snapshots (never real `time.sleep`/wall clock, never the real
installed CLI or a real `state.toml` under `.agent-state/`).
"""

from __future__ import annotations

import argparse
import dataclasses
import sys
import time
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common, status_claude

REASON_STATE_CHANGED = "state_changed"
REASON_WAITING_APPROVAL = "waiting_approval"
REASON_TIMED_OUT = "timed_out"


class AmbiguousSessionError(RuntimeError):
    """More than one session still matches after every supplied filter.

    Finding 1 (`02-reviewer-receipt.md`): `run_watch` is a single-outcome
    polling loop and has no way to decide which of several matches is the
    one it should be watching — silently picking `matches[0]` (the old
    behavior) can report the wrong session's classification. Raised
    instead of guessing; the caller must supply `--id`/`--nn` (or a
    narrower `--cwd`/`--title-prefix`) to disambiguate to exactly one
    assignment. Does not apply to `status_claude.report()`/`main()`,
    which lists every match for a human reader rather than picking one.
    """


def _describe_filters(cwd: str | None, title_prefix: str | None, native_id: str | None, nn: int | None) -> str:
    return f"cwd={cwd!r}, title_prefix={title_prefix!r}, id={native_id!r}, nn={nn!r}"


@dataclasses.dataclass
class WatchOutcome:
    reason: str
    classification: str | None
    session: dict | None
    elapsed: float


def run_watch(
    get_sessions: Callable[[], list[dict]],
    *,
    interval: float,
    max_duration: float,
    cwd: str | None = None,
    title_prefix: str | None = None,
    native_id: str | None = None,
    nn: int | None = None,
    state_path: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WatchOutcome:
    """Poll `get_sessions()` every `interval` seconds, up to `max_duration`.

    `interval`/`max_duration` have no default and must both be > 0 — a
    caller cannot accidentally get an unbounded loop. Returns the instant
    a state change or `waiting_approval` is *observed*; a full timeout
    returns the last observed classification, not a special value.

    `native_id`/`nn` (Finding 1) disambiguate to one specific assignment
    when `cwd`/`title_prefix` alone still match more than one session of
    the same task. If, after every supplied filter, more than one session
    still matches, raises `AmbiguousSessionError` — this single-outcome
    loop never silently picks `matches[0]`.

    Finding 3 (tooling-gaps-fix): a poll whose classification is
    `"unknown"`, observed right after a poll with a real (non-`"unknown"`)
    classification, is treated as **inconclusive** rather than a
    reportable change — real evidence: a session caught mid-shutdown by
    one poll classifies as `"unknown"` for that single transient
    snapshot, even though the very next poll, moments later, correctly
    resolves to the real terminal classification. Such a poll does not
    update the "last known classification" this loop compares against and
    does not exit; polling continues, still bounded by `max_duration`. A
    genuine `"unknown"` still standing at `max_duration` is reported as
    such (unchanged timeout behavior) — this only guards the transient,
    mid-transition case. `waiting_approval` keeps exiting immediately
    regardless, exactly as before.

    Finding 2 (tooling-gaps-fix): when `state_path` and `nn` are both
    supplied, the observed transition is persisted into that `state.toml`
    (`scripts.status_claude.record_observed_transition`) at the same
    point this loop would otherwise exit reporting `state_changed` — the
    one point a *genuinely new*, non-`"unknown"` classification is
    observed. Not attempted for `waiting_approval`/timeout exits (out of
    this finding's scope) or for the inconclusive `"unknown"` polls above.
    """

    if interval <= 0:
        raise ValueError("interval must be > 0 (no infinite/instant default)")
    if max_duration <= 0:
        raise ValueError("max_duration must be > 0 (no infinite default)")

    start = clock()
    last: str | None = None
    first_pass = True

    while True:
        sessions = get_sessions()
        matches = status_claude.find_task_sessions(
            sessions, cwd=cwd, title_prefix=title_prefix, native_id=native_id, nn=nn
        )
        if len(matches) > 1:
            raise AmbiguousSessionError(
                f"{len(matches)} sessions still match after every supplied filter "
                f"({_describe_filters(cwd, title_prefix, native_id, nn)}); "
                "supply --id or --nn to disambiguate to exactly one assignment"
            )
        session = matches[0] if matches else None
        classification = status_claude.classify_session(session) if session is not None else None
        elapsed = clock() - start

        # A transient "unknown" observed right after a real prior
        # classification is inconclusive (Finding 3): never a reportable
        # change on its own, and it must not overwrite `last`.
        transient_unknown = classification == "unknown" and last is not None and last != "unknown"

        if classification == "waiting_approval":
            return WatchOutcome(REASON_WAITING_APPROVAL, classification, session, elapsed)
        if not transient_unknown and not first_pass and classification != last:
            if state_path is not None and nn is not None:
                status_claude.record_observed_transition(state_path, nn, classification)
            return WatchOutcome(REASON_STATE_CHANGED, classification, session, elapsed)
        if elapsed >= max_duration:
            return WatchOutcome(REASON_TIMED_OUT, classification, session, elapsed)

        if not transient_unknown:
            last, first_pass = classification, False
        sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="watch-claude", description="Bounded polling loop around status-claude; never infinite."
    )
    parser.add_argument("--interval", required=True, type=float, help="seconds between polls (mandatory)")
    parser.add_argument("--max-duration", required=True, type=float, help="seconds before giving up (mandatory)")
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--title-prefix", default=None)
    parser.add_argument("--id", dest="native_id", default=None, help="exact recorded native.id, to disambiguate one assignment")
    parser.add_argument("--nn", type=int, default=None, help="exact assignment nn, to disambiguate one assignment")
    parser.add_argument(
        "--state",
        default=None,
        help="state.toml path; requires --nn (to know which assignment to persist "
        "to) and persists the observed G2 transition (Finding 2) at the point "
        "this loop exits reporting state_changed. --nn alone, without --state, "
        "remains a pure disambiguation filter with no persistence (tooling-gaps-fix "
        "RISK 2: --nn-alone usage was already reviewed and endorsed by a prior "
        "task; only --state without --nn is genuinely ambiguous and rejected)",
    )
    args = parser.parse_args(argv)

    if args.cwd is None and args.title_prefix is None and args.native_id is None and args.nn is None:
        print("error: at least one of --cwd/--title-prefix/--id/--nn is required", file=sys.stderr)
        return 2

    if args.state is not None and args.nn is None:
        print("error: --state requires --nn (to know which assignment to persist to)", file=sys.stderr)
        return 2

    def get_sessions() -> list[dict]:
        try:
            return common.list_manager_sessions()
        except common.ManagerUnavailable:
            return []

    try:
        outcome = run_watch(
            get_sessions,
            interval=args.interval,
            max_duration=args.max_duration,
            cwd=args.cwd,
            title_prefix=args.title_prefix,
            native_id=args.native_id,
            nn=args.nn,
            state_path=args.state,
        )
    except AmbiguousSessionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"{outcome.reason} classification={outcome.classification!r} elapsed={outcome.elapsed:.1f}s")
    if outcome.reason == REASON_WAITING_APPROVAL and outcome.session is not None:
        print(f"  claude attach {outcome.session.get('id')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
