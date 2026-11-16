"""scripts/marina/accept.py — `marina accept`: close one node the way `marina run` would.

A node launched by the manual procedure (`launch_node`) ends without a run
to record its end. `accept_node` does, for that one node, what the run's
loop does after the session ends, reusing its rules:

1. `finished` (when the node is still `launched`/`working`/`waiting_approval`);
2. for a writer without `git-after-NN.txt`, write it with `git_snapshot` of
   each target (`runner.git_after_text`, the run's own rule);
3. `receipt_received`, or `receipt_missing` when the receipt is absent;
4. `receipt_lint.lint_file`: `receipt_invalid` with the first error as the
   note, or `receipt_validated` with the `receipt_summary`;
5. the closed state from `decide.closed_state(summary.status)`.

Each step resumes from the state the node is in. Events use
`by = "marina-accept"` through `append_event` (so `G2_TRANSITIONS` is
enforced) and `write_state`.

It refuses, writing nothing, when the node does not exist or is not
launched yet, when a `marina run` holds a live lock on the task, when the
native manager is unavailable, or when it still classifies the node's
session (`native.id`) as working or waiting for approval. A node on
`native.platform = "unavailable"` (main-session fallback) is accepted
without consulting the manager. A node already in a terminal state is left
alone: no transition, no refusal, so a second run is harmless.

Every check that can fail (manager, Git snapshot, receipt lint) runs before
the first write. It never answers a native approval and writes only inside
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
from scripts.marina import runner
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


@dataclasses.dataclass
class AcceptResult:
    transitions: list[str]
    final_state: str
    refused: str | None


def deps_from_runner(deps: runner.RunnerDeps) -> AcceptDeps:
    """The subset of the run's boundaries that `accept_node` uses."""

    return AcceptDeps(list_sessions=deps.list_sessions, git_snapshot=deps.git_snapshot, now=deps.now,
                      pid_alive=deps.pid_alive)


def _session_refusal(a: Assignment, deps: AcceptDeps) -> str | None:
    if a.native.platform == "unavailable":
        return None
    try:
        sessions = deps.list_sessions()
        matches = status_claude.find_task_sessions(sessions, native_id=a.native.id) if a.native.id else []
        classes = [status_claude.classify_session(s) for s in matches]
    except (common.ManagerUnavailable, common.ManagerSchemaError) as exc:
        return f"native manager unavailable: {exc}"
    return "session still working" if any(c in _STILL_WORKING for c in classes) else None


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
    refused = _session_refusal(a, deps)
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
    lint = state == "receipt_received"
    if state in (*_SESSION_STATES, "finished"):
        lint = receipt.is_file()
        plan.append(("receipt_received" if lint else "receipt_missing", "", None))
        summary = None
    if lint:
        try:
            errors, summary = receipt_lint.lint_file(receipt, role=a.role, handoff=kit_root / a.handoff)
        except OSError as exc:
            return AcceptResult([], state, f"cannot lint the receipt: {exc}")
        if errors:
            plan.append(("receipt_invalid", errors[0], None))
            summary = None
        else:
            plan.append(("receipt_validated", "", summary))
    if summary is not None:
        plan.append((closed_state(summary.status), "", None))
    elif state == "receipt_validated":
        return AcceptResult([], state, f"nn={nn} is receipt_validated without a receipt_summary")

    # Like the run, `git-after` is written once the node is `finished` and
    # before `receipt_received`; a node already past `finished` gets it now.
    if git_after is not None and state not in _SESSION_STATES:
        path.write_text(git_after, encoding="utf-8")
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
        if to == "finished" and git_after is not None:
            path.write_text(git_after, encoding="utf-8")
    return AcceptResult(transitions, transitions[-1], None)
