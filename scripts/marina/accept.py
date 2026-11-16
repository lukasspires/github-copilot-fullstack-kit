"""scripts/marina/accept.py — `marina accept`: close one node the way `marina run` would.

A node launched by the manual procedure (`launch_node`) ends without a run
to record its end. `accept_node` does, for that one node, what the run's
loop does after the session ends, reusing its rules:

1. for a writer without `git-after-NN.txt`, write it with `git_snapshot` of
   each target (`runner.git_after_text`, the run's own rule), before any
   transition;
2. `finished` (when the node is still `launched`/`working`/`waiting_approval`);
3. `receipt_received`, or `receipt_missing` when the receipt is absent;
4. `receipt_lint.lint_file`: `receipt_invalid` with the first error as the
   note, or `receipt_validated` with the `receipt_summary`;
5. the closed state from `decide.closed_state(summary.status)`.

Each step resumes from the state the node is in. Events use
`by = "marina-accept"` through `append_event` (so `G2_TRANSITIONS` is
enforced) and `write_state`.

It refuses, writing nothing, when the node does not exist or is not
launched yet, when a `marina run` holds a live lock on the task, or, for a
node still in a session state, unless the native manager shows exactly one
session for its `native.id` and classifies it `finished` (like the run's
own observation): an empty `native.id`, no match, more than one match, a
session still working or waiting for approval, an `unknown` session or an
unavailable manager all refuse. A node already past `finished` is not
re-checked against the manager. A node on `native.platform = "unavailable"`
(main-session fallback) is accepted without consulting the manager. A node
already in a terminal state is left alone: no transition, no refusal, so a
second run is harmless.

It holds no lock of its own: it refuses a live run lock, but must not run
while a `marina run` of the same task may start.

When the node ends `receipt_missing` or `receipt_invalid`, it looks for a
usage limit in the session transcript like the run does (`usage_limit.detect`,
through the manager item for `native.id`; best effort, never a refusal),
records the same note (`usage_limit.with_note`) and returns it in
`AcceptResult.usage_limit` for the CLI to show.

Every check that can fail (manager, Git snapshot, receipt lint, the
`git-after` write) runs before the first `state.toml` write. It never answers a native approval and writes only inside
the task directory.

Minimum tested Claude CLI version: 2.1.306 — through the manager listing
(`common.list_manager_sessions`, `status_claude.classify_session`).
"""

from __future__ import annotations

import dataclasses
import datetime
from pathlib import Path
from typing import Callable

from scripts import common, receipt_lint, status_claude
from scripts.marina import envelope as env_mod
from scripts.marina import runner, usage_limit
from scripts.marina.decide import closed_state
from scripts.state import TERMINAL_STATES, Assignment, ReceiptSummary, StateError, append_event, read_state, write_state
from scripts.state.model import mode_for_role

BY = "marina-accept"
_SESSION_STATES = ("launched", "working", "waiting_approval")
_ACCEPTABLE = (*_SESSION_STATES, "finished", "receipt_received", "receipt_validated")
_STILL_WORKING = ("working", "waiting_approval")


@dataclasses.dataclass
class AcceptDeps:
    list_sessions: Callable[[], list[dict]]
    git_snapshot: Callable[[str], str]
    now: Callable[[], datetime.datetime]
    pid_alive: Callable[[int], bool]
    projects_root: Path = dataclasses.field(default_factory=usage_limit.default_projects_root)


@dataclasses.dataclass
class AcceptResult:
    transitions: list[str]
    final_state: str
    refused: str | None
    usage_limit: usage_limit.UsageLimit | None = None


def deps_from_runner(deps: runner.RunnerDeps) -> AcceptDeps:
    """The subset of the run's boundaries that `accept_node` uses."""

    return AcceptDeps(list_sessions=deps.list_sessions, git_snapshot=deps.git_snapshot, now=deps.now,
                      pid_alive=deps.pid_alive, projects_root=deps.projects_root)


def _session_refusal(a: Assignment, deps: AcceptDeps) -> tuple[str | None, dict | None]:
    """(None, session) only when the manager shows exactly one session for `native.id`, finished.

    Mirrors `runner._observe`, which records `finished` only on a single match.
    """

    if a.native.platform == "unavailable":
        return None, None
    if not a.native.id:
        return "native id is empty", None
    try:
        sessions = deps.list_sessions()
        matches = status_claude.find_task_sessions(sessions, native_id=a.native.id)
        classes = [status_claude.classify_session(s) for s in matches]
    except (common.ManagerUnavailable, common.ManagerSchemaError) as exc:
        return f"native manager unavailable: {exc}", None
    if not classes:
        return "session not found in manager", None
    if len(classes) > 1:
        return "more than one session matches", None
    if classes[0] in _STILL_WORKING:
        return "session still working", None
    if classes[0] != "finished":
        return "session state unknown", None
    return None, matches[0]


def _detect_usage_limit(a: Assignment, session: dict | None, deps: AcceptDeps) -> usage_limit.UsageLimit | None:
    """The usage limit in `a`'s transcript, like the run's; None when unknown (never raises)."""

    if session is None:
        if a.native.platform == "unavailable" or not a.native.id:
            return None
        try:
            matches = status_claude.find_task_sessions(deps.list_sessions(), native_id=a.native.id)
        except Exception:  # noqa: BLE001 — best effort: the limit is an annotation, not a check
            return None
        if len(matches) != 1:
            return None
        session = matches[0]
    sid = session.get("sessionId")
    if not isinstance(sid, str):
        return None
    try:
        local_tz = deps.now().tzinfo
    except Exception:  # noqa: BLE001
        local_tz = None
    return usage_limit.detect(sid, deps.projects_root, local_tz=local_tz)


def accept_node(state_path: Path, nn: int, *, kit_root: Path, deps: AcceptDeps) -> AcceptResult:
    """Close node `nn` of the task at `state_path`, as `marina run` would."""

    state_path, kit_root = Path(state_path), Path(kit_root)
    doc = read_state(state_path)
    try:
        a = doc.get_assignment(nn)
    except StateError:
        return AcceptResult([], "", f"nn={nn} does not exist")
    state = a.state
    if state in TERMINAL_STATES:
        return AcceptResult([], state, None)
    if state not in _ACCEPTABLE:
        return AcceptResult([], state, f"nn={nn} is {state}; nothing to accept before launch")
    pid = runner.live_lock_pid(state_path.parent, pid_alive=deps.pid_alive)
    if pid is not None:
        return AcceptResult([], state, f"marina run is active (pid {pid})")
    # A node past `finished` already had its session observed; only a node
    # still in a session state needs the manager to confirm it ended.
    refused, session = _session_refusal(a, deps) if state in _SESSION_STATES else (None, None)
    if refused:
        return AcceptResult([], state, refused)

    # Everything that can fail runs before the first write.
    git_after: str | None = None
    path = runner.git_after_path(state_path.parent, nn)
    if mode_for_role(a.role) == "writer" and not path.exists():
        try:
            git_after = runner.git_after_text(a, env_mod.envelope_from_doc(doc), deps.git_snapshot)
        except Exception as exc:  # noqa: BLE001 — any snapshot failure refuses before writing
            return AcceptResult([], state, f"git-after not written: {exc}")
    receipt = kit_root / a.receipt
    # (state, note, receipt_summary to record with it)
    plan: list[tuple[str, str, ReceiptSummary | None]] = []
    if state in _SESSION_STATES:
        plan.append(("finished", "", None))
    summary = a.receipt_summary
    limit: usage_limit.UsageLimit | None = None
    lint = state == "receipt_received"
    if state in (*_SESSION_STATES, "finished"):
        lint = receipt.is_file()
        if not lint:
            limit = _detect_usage_limit(a, session, deps)
        plan.append(("receipt_received" if lint else "receipt_missing", usage_limit.with_note("", limit), None))
        summary = None
    if lint:
        try:
            errors, summary = receipt_lint.lint_file(receipt, role=a.role, handoff=kit_root / a.handoff)
        except OSError as exc:
            return AcceptResult([], state, f"cannot lint the receipt: {exc}")
        if errors:
            limit = _detect_usage_limit(a, session, deps)
            plan.append(("receipt_invalid", usage_limit.with_note(errors[0], limit), None))
            summary = None
        else:
            plan.append(("receipt_validated", "", summary))
    if summary is not None:
        plan.append((closed_state(summary.status), "", None))
    elif state == "receipt_validated":
        return AcceptResult([], state, f"nn={nn} is receipt_validated without a receipt_summary")

    # `git-after` is written before the first transition (`finished`, or the
    # first one past it), so a failed write leaves `state.toml` untouched.
    if git_after is not None:
        try:
            path.write_text(git_after, encoding="utf-8")
        except OSError as exc:
            return AcceptResult([], state, f"git-after not written: {exc}")
    transitions: list[str] = []
    for to, note, validated in plan:
        doc = read_state(state_path)
        current = doc.get_assignment(nn)
        if validated is not None:
            current.receipt_summary = validated
        at = deps.now()
        append_event(current, to, by=BY, note=note, at=at)
        doc.task.updated_at = at
        write_state(state_path, doc)
        transitions.append(to)
    return AcceptResult(transitions, transitions[-1], None, limit)
