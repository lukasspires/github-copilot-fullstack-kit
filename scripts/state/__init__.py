"""scripts.state — read/write/validate schema-v0 `state.toml`, plus the
mechanical `init`/`add`/`set`/`next-nn` operations (see
docs/agent-workflow.md "Structured task state (schema v0)" for the
contract).

Library only: `python3 -c "import scripts.state"` must succeed with no
external dependency beyond the Python >= 3.11 stdlib (`tomllib`). For the
CLI, run `python3 -m scripts.state <init|add|set|next-nn> ...` (see
`scripts/state/__main__.py`).

Judgment (routing, accept/return decisions, edge choice) is never made
here — only the coordinator or another script (`preflight`, `receipt-lint`)
appends events with an explicit `by`.
"""

from __future__ import annotations

import datetime
import posixpath
import tomllib
from pathlib import Path
from typing import Iterable

from .model import (  # noqa: F401 - re-exported public API
    ACTIVE_WRITER_STATES,
    ALL_STATES,
    ASSIGNMENT_MODES,
    ASSIGNMENT_TYPES,
    EDGES,
    G2_TRANSITIONS,
    NATIVE_PLATFORMS,
    READER_ROLES,
    SUPPORTED_SCHEMA,
    TERMINAL_STATES,
    Assignment,
    Event,
    NativeMeta,
    ReceiptSummary,
    StateDoc,
    StateError,
    Task,
    can_transition,
    mode_for_role,
)
from . import toml_write

__all__ = [
    "StateDoc",
    "Task",
    "Assignment",
    "Event",
    "NativeMeta",
    "ReceiptSummary",
    "StateError",
    "mode_for_role",
    "can_transition",
    "parse_state_text",
    "read_state",
    "dumps_state",
    "write_state",
    "init_state",
    "add_assignment",
    "append_event",
    "set_state",
    "next_nn",
    "get_assignment",
]


def parse_state_text(text: str) -> StateDoc:
    """Parse `state.toml` text (already read) into a `StateDoc`."""

    raw = tomllib.loads(text)
    return StateDoc.from_raw(raw)


def read_state(path: str | Path) -> StateDoc:
    """Read and structurally validate a `state.toml` file."""

    with Path(path).open("rb") as fh:
        raw = tomllib.load(fh)
    return StateDoc.from_raw(raw)


def dumps_state(doc: StateDoc) -> str:
    """Serialize a `StateDoc` back to `state.toml` text (minimal writer)."""

    return toml_write.dumps(doc.to_raw())


def write_state(path: str | Path, doc: StateDoc) -> None:
    """Write a `StateDoc` to `path` using the minimal TOML writer."""

    Path(path).write_text(dumps_state(doc), encoding="utf-8")


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def get_assignment(doc: StateDoc, nn: int) -> Assignment:
    return doc.get_assignment(nn)


def append_event(
    assignment: Assignment,
    to_state: str,
    *,
    by: str,
    note: str = "",
    at: datetime.datetime | None = None,
    enforce: bool = True,
) -> Event:
    """Append a G2 transition event and update `assignment.state`.

    `enforce=True` (default) rejects a transition not present in
    `G2_TRANSITIONS`; every script and `state set` use this so that
    `assignments[].state` can never drift from the last event's `to`
    (state-lint invariant 5 is then a property preserved by construction,
    not just checked after the fact).
    """

    if enforce and not can_transition(assignment.state, to_state):
        raise StateError(f"illegal G2 transition for nn={assignment.nn}: {assignment.state} -> {to_state}")
    at = at or _now()
    event = Event(at=at, from_=assignment.state, to=to_state, by=by, note=note)
    assignment.events.append(event)
    assignment.state = to_state
    return event


def next_nn(doc: StateDoc) -> int:
    return doc.task.next_nn


def _task_dir(doc: StateDoc) -> str:
    return posixpath.dirname(doc.task.journal)


def init_state(
    path: str | Path,
    *,
    project: str,
    slug: str,
    title: str,
    kit_root: str,
    targets: Iterable[str],
    phase: str = "intake",
    at: datetime.datetime | None = None,
) -> StateDoc:
    """`state init` — bootstrap a brand-new task's `state.toml` `[task]`
    header (no `state add`/`set`/`next-nn` can do this: every one of them
    calls `read_state` first, so none can create the file itself).

    Refuses (raises `StateError`) if `path` already exists — never
    overwrites. Derives `journal` as the sibling `checkpoint.md` next to
    `path` (``posixpath.dirname(path) + "/checkpoint.md"``), matching the
    convention every real task in this project's history already uses
    (state.toml, checkpoint.md, handoffs and receipts all in one
    directory) — there is deliberately no separate `--journal` flag.
    `project`/`slug` are validated by routing through `Task.from_dict`'s
    own `^[a-z0-9-]+$` check rather than duplicating that regex here, so
    this raises the exact same `StateError` a hand-written invalid
    `state.toml` would on read. `next_nn` starts at 1; `created_at` and
    `updated_at` are both set to `at` (or now).
    """

    path_str = str(path)
    if Path(path_str).exists():
        raise StateError(f"refusing to overwrite existing state file: {path_str}")

    at = at or _now()
    journal = f"{posixpath.dirname(path_str)}/checkpoint.md"
    task = Task.from_dict(
        {
            "project": project,
            "slug": slug,
            "title": title,
            "phase": phase,
            "kit_root": kit_root,
            "targets": list(targets),
            "journal": journal,
            "next_nn": 1,
            "created_at": at,
            "updated_at": at,
        }
    )
    return StateDoc(schema=SUPPORTED_SCHEMA, task=task, assignments=[])


def add_assignment(
    doc: StateDoc,
    *,
    role: str,
    type_: str,
    edge: str,
    predecessor: int,
    targets: Iterable[str],
    platform: str = "claude",
    host: str = "",
    reason: str = "",
    allowlist: Iterable[str] | None = None,
    note: str = "",
    by: str = "coordinator",
    at: datetime.datetime | None = None,
) -> Assignment:
    """`state add` — reserve a new assignment node in `reserved`.

    Derives `nn` (from `task.next_nn`), `mode` (from `role`), `title`,
    `handoff` and `receipt` (by convention from `task.slug`/`task.journal`)
    exactly as docs/plano-estado-estruturado-e-grafos.md §2.4 specifies;
    the coordinator only supplies the judgment fields (`role`, `type`,
    `edge`, `predecessor`, `targets`, `allowlist`, native platform).
    """

    if type_ not in ASSIGNMENT_TYPES:
        raise StateError(f"unknown assignment type: {type_!r}")
    if edge not in EDGES:
        raise StateError(f"unknown edge: {edge!r}")
    if platform not in NATIVE_PLATFORMS:
        raise StateError(f"unknown native platform: {platform!r}")
    if platform == "unavailable" and not reason.strip():
        raise StateError("platform='unavailable' requires a non-empty reason")

    nn = doc.task.next_nn
    if predecessor != 0:
        if predecessor >= nn:
            raise StateError(f"predecessor {predecessor} must be < nn {nn}")
        if not any(a.nn == predecessor for a in doc.assignments):
            raise StateError(f"predecessor {predecessor} does not exist")

    mode = mode_for_role(role)
    task_dir = _task_dir(doc)
    handoff = f"{task_dir}/{nn:02d}-{role}-handoff.md"
    receipt = f"{task_dir}/{nn:02d}-{role}-receipt.md"
    title = f"{doc.task.slug} — {role} — {nn:02d} — {type_}"
    at = at or _now()

    assignment = Assignment(
        nn=nn,
        role=role,
        type=type_,
        mode=mode,
        edge=edge,
        predecessor=predecessor,
        targets=list(targets),
        title=title,
        state="reserved",
        handoff=handoff,
        receipt=receipt,
        git_before="",
        allowlist=list(allowlist or []),
        native=NativeMeta(platform=platform, host=host, reason=reason),
        events=[Event(at=at, from_="", to="reserved", by=by, note=note)],
    )
    doc.assignments.append(assignment)
    doc.task.next_nn = nn + 1
    doc.task.updated_at = at
    return assignment


def set_state(
    doc: StateDoc,
    nn: int,
    to_state: str,
    *,
    by: str = "coordinator",
    note: str = "",
    at: datetime.datetime | None = None,
) -> Assignment:
    """`state set` — record a coordinator judgment transition (or any
    other explicit, legal G2 transition) for an existing node."""

    assignment = doc.get_assignment(nn)
    at = at or _now()
    append_event(assignment, to_state, by=by, note=note, at=at)
    doc.task.updated_at = at
    return assignment
