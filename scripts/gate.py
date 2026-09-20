#!/usr/bin/env python3
"""scripts/gate.py — G3 predicate evaluator: P_writer, P_reader, P_progresso.

Implements docs/agent-workflow.md's "Dependency graph between assignments
(G3)" table and docs/plano-estado-estruturado-e-grafos.md §5/§6.1 for a
*proposed* new node (role, edge, predecessor, targets) that does not exist
in `state.toml` yet. Answers yes/no with reasons only — never creates a
node, never transitions anything, never launches a session. `state add`
(scripts/state) is the only thing that actually reserves a node, and only
after `gate` (or the coordinator's own judgment) says yes.

Minimum tested Claude CLI version: 2.1.270 (only used, optionally and
non-fatally, to list `claude agents --json --all` for the unknown-working
-session check of P_writer — read-only; skipped, with a note, when the
CLI is unavailable, exactly like scripts/preflight.py).

Read-only: never writes anything, never invokes `subprocess` directly
(the only process invocation anywhere in this module's own import chain is
inside scripts.common.list_manager_sessions, itself read-only:
`claude agents --json --all`). See tests/test_gate.py::NeverWritesTest for
a source-grep demonstration.

Cross-task scope (P_writer, plan §5, D2): "any task whose targets
intersect the new node's" means every `state.toml` under
`.agent-state/<project>/tasks/*/state.toml` for the project the caller
supplies, not just the task the proposed node belongs to. `load_task_docs`
discovers and reads those; callers are responsible for pointing it at the
real `.agent-state/<project>/tasks/` directory (or, in tests, a fixture
tree shaped the same way).
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import sys
from pathlib import Path
from typing import Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common
from scripts.state import Assignment, Event, NativeMeta, StateDoc, StateError, read_state
from scripts.state.model import (
    ACTIVE_WRITER_STATES,
    ASSIGNMENT_TYPES,
    EDGES,
    TERMINAL_STATES,
    mode_for_role,
)
from scripts.state_lint import check_edge_compatibility

# Overlap ratio (|intersection| / |union| of normalized risk titles) at or
# above which two rounds' risks_digest are considered "the same findings,
# no new evidence" (plan §6.1). Not specified numerically by the plan;
# documented here as the one tunable constant of the whole predicate.
RISKS_OVERLAP_THRESHOLD = 0.5


@dataclasses.dataclass
class GateResult:
    allowed: bool
    reasons: list[str]
    notes: list[str] = dataclasses.field(default_factory=list)

    def __bool__(self) -> bool:  # pragma: no cover - convenience only
        return self.allowed


# --------------------------------------------------------------------------
# Cross-task discovery (P_writer/P_reader scope, plan §5 D2).
# --------------------------------------------------------------------------


def load_task_docs(tasks_root: str | Path, *, exclude_slug: str | None = None) -> list[StateDoc]:
    """Read every `<tasks_root>/*/state.toml`, skipping `exclude_slug`.

    Never raises on a missing `tasks_root` (returns an empty list); a
    malformed `state.toml` under it still raises `StateError` — a broken
    sibling task's state must not be silently ignored by a writer gate.
    """

    root = Path(tasks_root)
    if not root.is_dir():
        return []
    docs: list[StateDoc] = []
    for state_path in sorted(root.glob("*/state.toml")):
        doc = read_state(state_path)
        if exclude_slug is not None and doc.task.slug == exclude_slug:
            continue
        docs.append(doc)
    return docs


def active_writer_hits(docs: Iterable[StateDoc], targets: Iterable[str]) -> list[str]:
    """Active `writer` nodes (any task) whose `targets` intersect `targets`."""

    target_set = set(targets)
    hits: list[str] = []
    for doc in docs:
        for a in doc.assignments:
            if a.mode == "writer" and a.state in ACTIVE_WRITER_STATES and set(a.targets) & target_set:
                overlap = sorted(set(a.targets) & target_set)
                hits.append(
                    f"active writer nn={a.nn} (state={a.state!r}) in task {doc.task.slug!r} "
                    f"on overlapping targets {overlap}"
                )
    return hits


# --------------------------------------------------------------------------
# P0 (always): edge/predecessor legality — reuses state_lint's own
# edge_compatibility check by staging the candidate node in a throwaway
# copy of the document, rather than re-deriving the G3 table a second time.
# --------------------------------------------------------------------------


def _now() -> datetime.datetime:
    return datetime.datetime.now().astimezone()


def stage_candidate(
    doc: StateDoc, *, role: str, type_: str, edge: str, predecessor: int, targets: Iterable[str]
) -> Assignment:
    """Build a throwaway `reserved` Assignment for `nn = doc.task.next_nn`.

    Never appended to `doc` itself, never written anywhere; only used to
    let `state_lint.check_edge_compatibility` evaluate the proposed edge
    without duplicating that table here.
    """

    return Assignment(
        nn=doc.task.next_nn,
        role=role,
        type=type_,
        mode=mode_for_role(role),
        edge=edge,
        predecessor=predecessor,
        targets=list(targets),
        title="",
        state="reserved",
        handoff="",
        receipt="",
        git_before="",
        allowlist=[],
        native=NativeMeta(platform="claude"),
        events=[Event(at=_now(), from_="", to="reserved", by="gate")],
    )


def check_p0(
    doc: StateDoc, *, role: str, type_: str, edge: str, predecessor: int, targets: Iterable[str]
) -> tuple[list[str], Assignment | None]:
    """P0's graph-legality half: edge known, type known, predecessor exists
    (or 0), G3 table respected for the proposed edge.

    Deliberately narrower than plan §5's full P0 text ("handoff do novo nó
    completo e legível; perfil e instruções do alvo existem; diretório de
    receipt existe; receipt do novo NN não existe; executáveis dos checks
    resolvem"): `gate` is evaluated *before* the node exists (it decides
    whether `state add` should even create it), and every one of those
    remaining P0 items is only meaningful for a node that already has an
    `nn` and a handoff written against it — which is exactly why the plan
    says "(= preflight; gate apenas confirma que rodará)". Re-checking
    them here would either duplicate `preflight` on a node that does not
    exist yet, or require guessing a handoff that has not been written.
    `preflight` (already implemented, Etapa 1) is what actually enforces
    that half of P0, immediately after `state add` reserves the node this
    function said `yes` to.
    """

    if edge not in EDGES:
        return [f"unknown edge: {edge!r}"], None
    if type_ not in ASSIGNMENT_TYPES:
        return [f"unknown type: {type_!r}"], None
    if predecessor != 0 and not any(a.nn == predecessor for a in doc.assignments):
        return [f"predecessor nn={predecessor} does not exist in task {doc.task.slug!r}"], None

    candidate = stage_candidate(doc, role=role, type_=type_, edge=edge, predecessor=predecessor, targets=targets)
    staged = StateDoc(schema=doc.schema, task=doc.task, assignments=[*doc.assignments, candidate])
    errors = check_edge_compatibility(staged)
    prefix = f"nn={candidate.nn}:"
    return [e for e in errors if e.startswith(prefix)], candidate


# --------------------------------------------------------------------------
# P_progresso (plan §6.1) — only relevant for edge == "corrige".
# --------------------------------------------------------------------------


def risks_overlap_substantially(previous: list[str], new: list[str]) -> bool:
    """True iff `previous`/`new` (already-normalized risk titles) share
    "the same findings" per plan §6.1 — no new evidence between rounds."""

    prev_set, new_set = set(previous), set(new)
    if not prev_set or not new_set:
        return False
    ratio = len(prev_set & new_set) / len(prev_set | new_set)
    return ratio >= RISKS_OVERLAP_THRESHOLD


def find_fail_review_chain(doc: StateDoc, reviewer_nn: int) -> list[Assignment]:
    """Walk the correction loop backward from a `reviewer` FAIL node.

    Returns the chain of consecutive `reviewer`-FAIL nodes, most-recent
    first (`chain[0]` is `reviewer_nn` itself), stopping as soon as the
    predecessor writer's own `edge` is not `corrige` (i.e. the chain's
    first round). Empty if `reviewer_nn` is not itself an `accepted`
    `reviewer` node with `verdict == "FAIL"`.
    """

    chain: list[Assignment] = []
    current = doc.get_assignment(reviewer_nn)
    while (
        current.role == "reviewer"
        and current.receipt_summary is not None
        and current.receipt_summary.verdict == "FAIL"
    ):
        chain.append(current)
        if current.predecessor == 0:
            break
        writer = doc.get_assignment(current.predecessor)
        if writer.edge != "corrige" or writer.predecessor == 0:
            break
        current = doc.get_assignment(writer.predecessor)
    return chain


def evaluate_p_progresso(doc: StateDoc, *, reviewer_nn: int, user_decided: bool) -> GateResult:
    """P_progresso for a proposed `corrige` whose predecessor is `reviewer_nn`."""

    chain = find_fail_review_chain(doc, reviewer_nn)
    if not chain:
        return GateResult(
            False, [f"nn={reviewer_nn} is not an accepted reviewer node with verdict='FAIL'; corrige does not apply"]
        )
    if len(chain) < 2:
        return GateResult(True, [])

    latest, previous = chain[0], chain[1]
    if risks_overlap_substantially(previous.receipt_summary.risks_digest, latest.receipt_summary.risks_digest):
        return GateResult(
            False,
            [
                f"no progress: risks_digest of nn={latest.nn} substantially overlaps nn={previous.nn}'s "
                "(same findings, no new evidence) — offer `analisa` instead of `corrige`"
            ],
        )
    if not user_decided:
        return GateResult(
            False,
            [
                f"second consecutive FAIL in this chain (nn={latest.nn}); an explicit user decision "
                "must be recorded in the journal before `corrige` is allowed again"
            ],
        )
    return GateResult(True, [])


# --------------------------------------------------------------------------
# P_writer / P_reader (plan §5).
# --------------------------------------------------------------------------


def evaluate_gate(
    doc: StateDoc,
    *,
    role: str,
    type_: str,
    edge: str,
    predecessor: int,
    targets: Iterable[str],
    sibling_docs: Iterable[StateDoc] = (),
    git_diff_acknowledged: bool = False,
    user_decided: bool = False,
    list_sessions: Callable[[], list[dict]] = common.list_manager_sessions,
) -> GateResult:
    """Evaluate P0 + the relevant predicate(s) for a proposed new node.

    Never creates, transitions or launches anything; `state add` is the
    only thing that actually reserves the node once this returns
    `allowed=True`.
    """

    targets = list(targets)
    reasons, candidate = check_p0(doc, role=role, type_=type_, edge=edge, predecessor=predecessor, targets=targets)
    notes: list[str] = []
    mode = mode_for_role(role)

    all_docs = [doc, *sibling_docs]
    reasons += active_writer_hits(all_docs, targets)

    if mode == "writer":
        if predecessor != 0:
            pred = doc.get_assignment(predecessor)
            if pred.state not in TERMINAL_STATES:
                reasons.append(f"predecessor nn={predecessor} is not closed (state={pred.state!r})")
        if not git_diff_acknowledged:
            reasons.append(
                "git status/diff since the last writer's git_before has not been acknowledged by the caller"
            )
        try:
            sessions = list_sessions()
        except common.ManagerUnavailable as exc:
            notes.append(f"native manager unavailable, skipped: {exc}")
        else:
            known_titles = {
                a.title for d in all_docs for a in d.assignments if a.state in ACTIVE_WRITER_STATES
            }
            for session in sessions:
                common.validate_manager_session_schema(session)
                cwd = session.get("cwd")
                if session.get("state") != "working" or cwd is None:
                    continue
                if cwd in targets and session.get("name") not in known_titles:
                    reasons.append(
                        f"unknown working session with cwd in the new node's targets: {session.get('name')!r}"
                    )

    if edge == "corrige":
        progresso = evaluate_p_progresso(doc, reviewer_nn=predecessor, user_decided=user_decided)
        reasons += progresso.reasons

    return GateResult(allowed=not reasons, reasons=reasons, notes=notes)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="gate", description="Answer yes/no (with reasons) for a proposed new G3 node. Never writes anything."
    )
    parser.add_argument("--state", required=True, help="path to the task's own state.toml")
    parser.add_argument("--tasks-root", default=None, help=".agent-state/<project>/tasks/ (for cross-task P_writer)")
    parser.add_argument("--role", required=True)
    parser.add_argument("--type", required=True, dest="type_")
    parser.add_argument("--edge", required=True)
    parser.add_argument("--predecessor", required=True, type=int)
    parser.add_argument("--target", action="append", required=True, dest="targets")
    parser.add_argument("--git-diff-acknowledged", action="store_true")
    parser.add_argument("--user-decided", action="store_true")
    args = parser.parse_args(argv)

    try:
        doc = read_state(args.state)
    except (StateError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    sibling_docs = load_task_docs(args.tasks_root, exclude_slug=doc.task.slug) if args.tasks_root else []

    result = evaluate_gate(
        doc,
        role=args.role,
        type_=args.type_,
        edge=args.edge,
        predecessor=args.predecessor,
        targets=args.targets,
        sibling_docs=sibling_docs,
        git_diff_acknowledged=args.git_diff_acknowledged,
        user_decided=args.user_decided,
    )
    for note in result.notes:
        print(f"NOTE: {note}")
    if result.allowed:
        print("ALLOW")
        return 0
    print("REFUSE")
    for reason in result.reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
