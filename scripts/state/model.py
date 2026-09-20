"""scripts/state/model.py — schema-v0 data model.

Implements exactly the "Structured task state (schema v0)" contract in
docs/agent-workflow.md and the field table in
docs/plano-estado-estruturado-e-grafos.md §2.3/§2.4. Stdlib only.

This module only performs *structural* validation (required fields
present, enums well-formed, basic shape). The eight cross-node graph
invariants of docs/plano-estado-estruturado-e-grafos.md §5 are
`state-lint`'s job (scripts/state_lint.py), not this module's — keeping
the two layers separate makes each independently testable per the
handoff's acceptance criteria.
"""

from __future__ import annotations

import dataclasses
import datetime
import re
from typing import Any, Optional


class StateError(ValueError):
    """A state.toml document (or a requested operation on one) is invalid."""


# Roles whose `mode` is "reader"; every other role is a "writer" (plan §2.4).
READER_ROLES = frozenset({"reviewer", "architect", "analista-redmine"})

NATIVE_PLATFORMS = frozenset({"claude", "codex", "unavailable"})
ASSIGNMENT_TYPES = frozenset({"implementação", "revisão", "correção", "análise"})
ASSIGNMENT_MODES = frozenset({"writer", "reader"})
EDGES = frozenset({"inicia", "revisa", "revisa_direta", "analisa", "corrige", "continua", "substitui"})

# G2 states (docs/agent-workflow.md "Assignment state machine (G2)").
ACTIVE_WRITER_STATES = frozenset({"prepared", "launched", "uncertain", "working", "waiting_approval"})
TERMINAL_STATES = frozenset(
    {
        "preparation_failed",
        "abandoned",
        "receipt_missing",
        "receipt_invalid",
        "accepted",
        "returned",
        "closed_needs_input",
        "closed_blocked",
        "closed_pending",
    }
)
ALL_STATES = frozenset({"reserved", "finished", "receipt_received", "receipt_validated"}) | ACTIVE_WRITER_STATES | TERMINAL_STATES

# G2 transition table: from -> allowed set of "to" states. Only the
# transitions a script or the coordinator may record; `waiting_approval ->
# working` is observed (by `status`), never caused, but is still a valid
# recorded transition.
G2_TRANSITIONS: dict[str, frozenset[str]] = {
    "reserved": frozenset({"prepared", "preparation_failed"}),
    "prepared": frozenset({"launched", "uncertain"}),
    "uncertain": frozenset({"launched", "abandoned"}),
    "launched": frozenset({"working", "waiting_approval", "finished"}),
    "working": frozenset({"waiting_approval", "finished"}),
    "waiting_approval": frozenset({"working", "finished"}),
    "finished": frozenset({"receipt_received", "receipt_missing"}),
    "receipt_received": frozenset({"receipt_validated", "receipt_invalid"}),
    "receipt_validated": frozenset(
        {"accepted", "returned", "closed_needs_input", "closed_blocked", "closed_pending"}
    ),
}

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


def mode_for_role(role: str) -> str:
    """Derive `assignments[].mode` from `role` (plan §2.4: reader roles are fixed)."""

    return "reader" if role in READER_ROLES else "writer"


def can_transition(from_state: str, to_state: str) -> bool:
    return to_state in G2_TRANSITIONS.get(from_state, frozenset())


def _require(d: dict, fields: tuple[str, ...], what: str) -> list[str]:
    return [f for f in fields if f not in d]


# --------------------------------------------------------------------------
# Event
# --------------------------------------------------------------------------


@dataclasses.dataclass
class Event:
    at: datetime.datetime
    from_: str
    to: str
    by: str
    note: str = ""

    @staticmethod
    def from_dict(d: dict) -> "Event":
        missing = _require(d, ("at", "to", "by"), "event")
        if missing:
            raise StateError(f"event missing required field(s): {missing}")
        return Event(at=d["at"], from_=d.get("from", ""), to=d["to"], by=d["by"], note=d.get("note", ""))

    def to_dict(self) -> dict:
        return {"at": self.at, "from": self.from_, "to": self.to, "by": self.by, "note": self.note}


# --------------------------------------------------------------------------
# NativeMeta
# --------------------------------------------------------------------------


@dataclasses.dataclass
class NativeMeta:
    platform: str
    id: str = ""
    host: str = ""
    reason: str = ""
    last_seen: str = ""
    last_seen_at: Optional[datetime.datetime] = None

    @staticmethod
    def from_dict(d: dict) -> "NativeMeta":
        if "platform" not in d:
            raise StateError("[assignments.native] missing required field 'platform'")
        platform = d["platform"]
        if platform not in NATIVE_PLATFORMS:
            raise StateError(f"[assignments.native] unknown platform: {platform!r}")
        return NativeMeta(
            platform=platform,
            id=d.get("id", ""),
            host=d.get("host", ""),
            reason=d.get("reason", ""),
            last_seen=d.get("last_seen", ""),
            last_seen_at=d.get("last_seen_at"),
        )

    def to_dict(self) -> dict:
        out = {
            "platform": self.platform,
            "id": self.id,
            "host": self.host,
            "reason": self.reason,
            "last_seen": self.last_seen,
        }
        if self.last_seen_at is not None:
            out["last_seen_at"] = self.last_seen_at
        return out


# --------------------------------------------------------------------------
# ReceiptSummary
# --------------------------------------------------------------------------

RECEIPT_STATUS_ENUM = frozenset({"done", "pending", "needs_input", "blocked"})
VERDICT_ENUM = frozenset({"PASS", "PASS_WITH_RISKS", "FAIL", ""})


@dataclasses.dataclass
class ReceiptSummary:
    status: str
    verdict: str = ""
    profile_ok: bool = False
    risks_digest: list[str] = dataclasses.field(default_factory=list)

    @staticmethod
    def from_dict(d: dict) -> "ReceiptSummary":
        if "status" not in d:
            raise StateError("[assignments.receipt_summary] missing required field 'status'")
        status = d["status"]
        if status not in RECEIPT_STATUS_ENUM:
            raise StateError(f"[assignments.receipt_summary] unknown status: {status!r}")
        verdict = d.get("verdict", "")
        if verdict not in VERDICT_ENUM:
            raise StateError(f"[assignments.receipt_summary] unknown verdict: {verdict!r}")
        return ReceiptSummary(
            status=status,
            verdict=verdict,
            profile_ok=bool(d.get("profile_ok", False)),
            risks_digest=list(d.get("risks_digest", [])),
        )

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "verdict": self.verdict,
            "profile_ok": self.profile_ok,
            "risks_digest": list(self.risks_digest),
        }


# --------------------------------------------------------------------------
# Assignment
# --------------------------------------------------------------------------

_ASSIGNMENT_REQUIRED = (
    "nn",
    "role",
    "type",
    "mode",
    "edge",
    "predecessor",
    "targets",
    "title",
    "state",
    "handoff",
    "receipt",
    "git_before",
    "allowlist",
)


@dataclasses.dataclass
class Assignment:
    nn: int
    role: str
    type: str
    mode: str
    edge: str
    predecessor: int
    targets: list[str]
    title: str
    state: str
    handoff: str
    receipt: str
    git_before: str
    allowlist: list[str]
    native: NativeMeta
    events: list[Event]
    receipt_summary: Optional[ReceiptSummary] = None

    @staticmethod
    def from_dict(d: dict) -> "Assignment":
        missing = _require(d, _ASSIGNMENT_REQUIRED, "assignment")
        if missing:
            raise StateError(f"assignment nn={d.get('nn', '?')} missing required field(s): {missing}")
        if "native" not in d:
            raise StateError(f"assignment nn={d['nn']} missing [assignments.native] table")
        events_raw = d.get("events") or []
        if not events_raw:
            raise StateError(f"assignment nn={d['nn']} has no events")
        if d["type"] not in ASSIGNMENT_TYPES:
            raise StateError(f"assignment nn={d['nn']}: unknown type {d['type']!r}")
        if d["mode"] not in ASSIGNMENT_MODES:
            raise StateError(f"assignment nn={d['nn']}: unknown mode {d['mode']!r}")
        if d["edge"] not in EDGES:
            raise StateError(f"assignment nn={d['nn']}: unknown edge {d['edge']!r}")
        if d["state"] not in ALL_STATES:
            raise StateError(f"assignment nn={d['nn']}: unknown state {d['state']!r}")
        return Assignment(
            nn=int(d["nn"]),
            role=d["role"],
            type=d["type"],
            mode=d["mode"],
            edge=d["edge"],
            predecessor=int(d["predecessor"]),
            targets=list(d["targets"]),
            title=d["title"],
            state=d["state"],
            handoff=d["handoff"],
            receipt=d["receipt"],
            git_before=d["git_before"],
            allowlist=list(d["allowlist"]),
            native=NativeMeta.from_dict(d["native"]),
            receipt_summary=ReceiptSummary.from_dict(d["receipt_summary"])
            if "receipt_summary" in d
            else None,
            events=[Event.from_dict(e) for e in events_raw],
        )

    def to_dict(self) -> dict:
        out = {
            "nn": self.nn,
            "role": self.role,
            "type": self.type,
            "mode": self.mode,
            "edge": self.edge,
            "predecessor": self.predecessor,
            "targets": list(self.targets),
            "title": self.title,
            "state": self.state,
            "handoff": self.handoff,
            "receipt": self.receipt,
            "git_before": self.git_before,
            "allowlist": list(self.allowlist),
            "native": self.native.to_dict(),
        }
        if self.receipt_summary is not None:
            out["receipt_summary"] = self.receipt_summary.to_dict()
        out["events"] = [e.to_dict() for e in self.events]
        return out


# --------------------------------------------------------------------------
# Task
# --------------------------------------------------------------------------

_TASK_REQUIRED = (
    "project",
    "slug",
    "title",
    "phase",
    "kit_root",
    "targets",
    "journal",
    "next_nn",
    "created_at",
    "updated_at",
)


@dataclasses.dataclass
class Task:
    project: str
    slug: str
    title: str
    phase: str
    kit_root: str
    targets: list[str]
    journal: str
    next_nn: int
    created_at: datetime.datetime
    updated_at: datetime.datetime

    @staticmethod
    def from_dict(d: dict) -> "Task":
        missing = _require(d, _TASK_REQUIRED, "task")
        if missing:
            raise StateError(f"[task] missing required field(s): {missing}")
        if not _SLUG_RE.match(d["project"]):
            raise StateError(f"task.project must match ^[a-z0-9-]+$: {d['project']!r}")
        if not _SLUG_RE.match(d["slug"]):
            raise StateError(f"task.slug must match ^[a-z0-9-]+$: {d['slug']!r}")
        return Task(
            project=d["project"],
            slug=d["slug"],
            title=d["title"],
            phase=d["phase"],
            kit_root=d["kit_root"],
            targets=list(d["targets"]),
            journal=d["journal"],
            next_nn=int(d["next_nn"]),
            created_at=d["created_at"],
            updated_at=d["updated_at"],
        )

    def to_dict(self) -> dict:
        return {
            "project": self.project,
            "slug": self.slug,
            "title": self.title,
            "phase": self.phase,
            "kit_root": self.kit_root,
            "targets": list(self.targets),
            "journal": self.journal,
            "next_nn": self.next_nn,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


# --------------------------------------------------------------------------
# StateDoc — the whole state.toml document.
# --------------------------------------------------------------------------

SUPPORTED_SCHEMA = 1


@dataclasses.dataclass
class StateDoc:
    schema: int
    task: Task
    assignments: list[Assignment]

    @staticmethod
    def from_raw(raw: dict) -> "StateDoc":
        if "schema" not in raw:
            raise StateError("state.toml missing top-level 'schema'")
        if raw["schema"] != SUPPORTED_SCHEMA:
            raise StateError(f"unsupported schema version: {raw['schema']!r}")
        if "task" not in raw:
            raise StateError("state.toml missing [task] table")
        task = Task.from_dict(raw["task"])
        assignments = [Assignment.from_dict(a) for a in raw.get("assignments", [])]
        return StateDoc(schema=raw["schema"], task=task, assignments=assignments)

    def to_raw(self) -> dict:
        return {
            "schema": self.schema,
            "task": self.task.to_dict(),
            "assignments": [a.to_dict() for a in self.assignments],
        }

    def get_assignment(self, nn: int) -> Assignment:
        for a in self.assignments:
            if a.nn == nn:
                return a
        raise StateError(f"no assignment with nn={nn}")
