"""scripts/marina/decide.py — the decision table of spec §3.3 as a pure function.

`decide(doc, env, obs)` looks at the task graph, the approved envelope and
what the caller observed outside (hash, branches, receipt, manager, judge)
and returns one `Decision`. It performs no I/O of its own: every external
fact arrives in `Observations`, so the runner (F4) owns all side effects
and records each decision before asking again.

Choices from docs/plano-f3-envelope-e-decide-2026-10.md:

- decision 6: besides `launch`, `wait`, `ask_judge` and `stop`, a decision
  can be a `transition` (record one G2 state) or `done` (chain finished);
  one action per call.
- decision 7: a graph with any node outside the envelope's expansion
  (other edges, roles or targets) stops with `graph_outside_envelope`.
- decision 9: `prossegue` follows the writer that opened the previous
  stage, because G3 requires the same role and type as its predecessor.
- decision 1: the gray zone of `gate` is not consulted; with
  `max_corrections <= 1` a second consecutive FAIL always stops first.

F7 (docs/plano-f7-envelope-multipapel-e-envio-2026-10.md): the next stage
opens with `encadeia` when its role differs from the previous stage's, and
every node carries `envelope.node_scope` for its stage and edge; a node
whose targets or allowlist differ from that scope is outside the envelope.

F6 finding A4 (part 1): a `substitui` node that Marina opens for a node in
`receipt_missing`/`receipt_invalid` stands for that node (same role, type,
targets and allowlist, once per node), so the run can resume. The runner
itself never opens one.
"""

from __future__ import annotations

import dataclasses

from scripts.gate import find_fail_review_chain
from scripts.marina.envelope import WRITER_STAGE_EDGES, Envelope, node_scope
from scripts.state import Assignment, ReceiptSummary, StateDoc, effective_edge

EDGE_TYPE = {
    "inicia": "implementação", "prossegue": "implementação", "encadeia": "implementação",
    "revisa": "revisão", "corrige": "correção",
}
_WRITER_EDGES = (*WRITER_STAGE_EDGES, "corrige")
# Edge of the predecessor each expansion edge may follow (spec 3.2, decision 9).
_PREDECESSOR_EDGES = {
    "prossegue": WRITER_STAGE_EDGES, "encadeia": WRITER_STAGE_EDGES, "revisa": _WRITER_EDGES, "corrige": ("revisa",),
}
_REPLACEABLE = ("receipt_missing", "receipt_invalid")
_RUNNING = ("launched", "working")
_CLOSED_BY_STATUS = {
    "done": "accepted",
    "pending": "closed_pending",
    "needs_input": "closed_needs_input",
    "blocked": "closed_blocked",
}


class MissingObservation(ValueError):
    """The caller did not supply an observation this state needs."""


@dataclasses.dataclass(frozen=True)
class NodeSpec:
    role: str
    type: str
    edge: str
    predecessor: int
    targets: tuple[str, ...]
    allowlist: tuple[str, ...]
    stage: int


@dataclasses.dataclass(frozen=True)
class Question:
    kind: str
    nn: int
    options: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class Observations:
    envelope_sha256: str
    branches: dict[str, str]
    envelope_errors: tuple[str, ...] = ()
    receipt_exists: bool | None = None
    receipt_lint: tuple[tuple[str, ...], ReceiptSummary] | None = None
    manager_match: str | None = None
    notified: bool = False
    judge_calls_used: int = 0
    judge_answer: tuple[Question, str] | None = None


@dataclasses.dataclass(frozen=True)
class Decision:
    kind: str
    node: NodeSpec | None = None
    nn: int | None = None
    to: str | None = None
    reason: str = ""
    notify: bool = False
    question: Question | None = None
    receipt_summary: ReceiptSummary | None = None


def _stop(reason: str) -> Decision:
    return Decision("stop", reason=reason)


# --------------------------------------------------------------------------
# Graph position
# --------------------------------------------------------------------------


def stage_of(doc: StateDoc, nn: int) -> int:
    """1-based envelope stage of node `nn`; `ValueError` outside the expansion."""

    a = doc.get_assignment(nn)
    if a.edge == "inicia":
        return 1
    if a.edge in ("prossegue", "encadeia"):
        return stage_of(doc, a.predecessor) + 1
    if a.edge in ("revisa", "corrige", "substitui"):
        return stage_of(doc, a.predecessor)
    raise ValueError(f"nn={nn}: edge {a.edge!r} is outside the envelope's expansion")


def expected_scope(doc: StateDoc, env: Envelope, a: Assignment) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(targets, allowlist) node `a` must carry; a replacement keeps its original's.

    Raises `ValueError` (from `stage_of`) for a node outside the expansion.
    """

    return node_scope(env, stage_of(doc, a.nn), effective_edge(doc, a))


def graph_errors(doc: StateDoc, env: Envelope) -> list[str]:
    """Every node that the envelope's expansion could not have created."""

    nodes = sorted(doc.assignments, key=lambda a: a.nn)
    errors: list[str] = []
    if nodes and (nodes[0].edge != "inicia" or nodes[0].predecessor != 0):
        errors.append(f"nn={nodes[0].nn}: the first node must be inicia with predecessor 0")
    if sum(a.edge == "inicia" for a in nodes) > 1:
        errors.append("more than one inicia node")
    by_nn = {a.nn: a for a in nodes}
    # Replaced node -> its first replacement, known before the walk: any other
    # node must follow the replacement, or the second-FAIL chain gets shorter.
    replacements: dict[int, int] = {}
    for a in nodes:
        if a.edge == "substitui":
            replacements.setdefault(a.predecessor, a.nn)
    seen: set[int] = set()
    for a in nodes:
        shape = _shape_error(doc, a, by_nn)
        if shape:
            errors.append(shape)
            continue
        if a.edge != "substitui" and a.predecessor in replacements:
            errors.append(f"nn={a.nn}: predecessor nn={a.predecessor} was replaced by "
                          f"nn={replacements[a.predecessor]}; follow the replacement")
        if a.edge == "substitui":
            if a.predecessor in seen:
                errors.append(f"nn={a.nn}: nn={a.predecessor} was already replaced")
            seen.add(a.predecessor)
        edge = effective_edge(doc, a)
        stage = stage_of(doc, a.nn)
        if stage > len(env.stages):
            errors.append(f"nn={a.nn}: stage {stage} is beyond the envelope's {len(env.stages)} stage(s)")
            continue
        targets, allowlist = node_scope(env, stage, edge)
        if tuple(a.targets) != targets:
            errors.append(f"nn={a.nn}: targets {a.targets} differ from stage {stage}'s {list(targets)}")
        if a.edge == "substitui" and tuple(a.allowlist) != allowlist:
            errors.append(f"nn={a.nn}: substitui allowlist differs from the replaced node's scope")
        if edge in _WRITER_EDGES and a.role != env.stages[stage - 1].role:
            errors.append(f"nn={a.nn}: role {a.role!r} differs from stage {stage}'s {env.stages[stage - 1].role!r}")
        elif edge == "encadeia" and a.role == env.stages[stage - 2].role:
            errors.append(f"nn={a.nn}: encadeia needs a role different from stage {stage - 1}'s; use prossegue")
        elif edge == "prossegue" and a.role != env.stages[stage - 2].role:
            errors.append(f"nn={a.nn}: prossegue needs stage {stage - 1}'s role; use encadeia")
        if edge == "revisa" and a.role != "reviewer":
            errors.append(f"nn={a.nn}: revisa must use the reviewer role, got {a.role!r}")
    return errors


def _shape_error(doc: StateDoc, a: Assignment, by_nn: dict[int, Assignment]) -> str:
    """Edge, type and predecessor shape the expansion produces; "" when it fits.

    Predecessors must point to an earlier node, so `stage_of` always terminates.
    A predecessor's edge is its effective one, so a replacement is followed
    like the node it replaces.
    """

    if a.edge not in EDGE_TYPE and a.edge != "substitui":
        return f"nn={a.nn}: edge {a.edge!r} is outside the envelope's expansion"
    if a.edge in EDGE_TYPE and a.type != EDGE_TYPE[a.edge]:
        return f"nn={a.nn}: type {a.type!r} does not match edge {a.edge!r}"
    if a.edge == "inicia":
        return "" if a.predecessor == 0 else f"nn={a.nn}: inicia must have predecessor 0"
    pred = by_nn.get(a.predecessor)
    if pred is None or a.predecessor >= a.nn:
        return f"nn={a.nn}: predecessor {a.predecessor} is not an earlier node"
    if a.edge == "substitui":
        return _replacement_error(a, pred)
    pred_edge = effective_edge(doc, pred)
    if pred_edge not in _PREDECESSOR_EDGES[a.edge]:
        return f"nn={a.nn}: {a.edge} cannot follow a {pred_edge} node (nn={pred.nn})"
    return ""


def _replacement_error(a: Assignment, pred: Assignment) -> str:
    """A `substitui` replaces one expansion node that ended without a usable receipt."""

    if pred.edge not in EDGE_TYPE:
        return f"nn={a.nn}: substitui cannot replace a {pred.edge} node (nn={pred.nn})"
    if pred.state not in _REPLACEABLE:
        return f"nn={a.nn}: substitui requires nn={pred.nn} in receipt_missing/receipt_invalid, got {pred.state!r}"
    if (a.role, a.type) != (pred.role, pred.type):
        return f"nn={a.nn}: substitui must keep nn={pred.nn}'s role and type ({pred.role!r}, {pred.type!r})"
    return ""


def _stage_opener(doc: StateDoc, stage: int) -> Assignment:
    """The stage's opening writer; a replacement comes after the node it replaces."""

    openers = [a for a in doc.assignments
               if effective_edge(doc, a) in WRITER_STAGE_EDGES and stage_of(doc, a.nn) == stage]
    return max(openers, key=lambda a: a.nn)


def _launch(env: Envelope, *, role: str, edge: str, predecessor: int, stage: int) -> Decision:
    targets, allowlist = node_scope(env, stage, edge)
    node = NodeSpec(role, EDGE_TYPE[edge], edge, predecessor, targets, allowlist, stage)
    return Decision("launch", node=node)


def _next_stage(env: Envelope, *, predecessor: int, stage: int) -> Decision:
    """Open stage `stage + 1`: `prossegue` for the same role, `encadeia` for another (F7)."""

    role = env.stages[stage].role
    edge = "prossegue" if role == env.stages[stage - 1].role else "encadeia"
    return _launch(env, role=role, edge=edge, predecessor=predecessor, stage=stage + 1)


# --------------------------------------------------------------------------
# After acceptance
# --------------------------------------------------------------------------


def _after_writer(doc: StateDoc, env: Envelope, writer: Assignment) -> Decision:
    stage = stage_of(doc, writer.nn)
    if effective_edge(doc, writer) == "corrige" or env.review == "each_stage" or stage == len(env.stages):
        return _launch(env, role="reviewer", edge="revisa", predecessor=writer.nn, stage=stage)
    return _next_stage(env, predecessor=writer.nn, stage=stage)


def _after_pass(doc: StateDoc, env: Envelope, reviewer: Assignment) -> Decision:
    stage = stage_of(doc, reviewer.nn)
    if env.review == "each_stage" and stage < len(env.stages):
        return _next_stage(env, predecessor=_stage_opener(doc, stage).nn, stage=stage)
    return Decision("done")


def _after_pass_with_risks(doc: StateDoc, env: Envelope, reviewer: Assignment, obs: Observations) -> Decision:
    if env.on_pass_with_risks == "accept":
        return _after_pass(doc, env, reviewer)
    if env.on_pass_with_risks == "stop":
        return _stop("pass_with_risks")
    question = Question("pass_with_risks", reviewer.nn, ("continue", "stop"))
    if obs.judge_answer is not None and obs.judge_answer[0] == question:
        answer = obs.judge_answer[1]
        if answer == "continue":
            return _after_pass(doc, env, reviewer)
        if answer == "stop":
            return _stop("judge_stop")
        return _stop("judge_failed")
    if obs.judge_calls_used >= env.judge_max_calls:
        return _stop("judge_failed")
    return Decision("ask_judge", question=question)


def _after_fail(doc: StateDoc, env: Envelope, reviewer: Assignment) -> Decision:
    if len(find_fail_review_chain(doc, reviewer.nn)) >= 2:
        return _stop("second_fail")
    stage = stage_of(doc, reviewer.nn)
    # A replaced `corrige` counts once: by its original, never by its `substitui`.
    corrections = sum(1 for a in doc.assignments if a.edge == "corrige" and stage_of(doc, a.nn) == stage)
    if corrections >= env.max_corrections:
        return _stop("max_corrections")
    return _launch(env, role=env.stages[stage - 1].role, edge="corrige", predecessor=reviewer.nn, stage=stage)


def _after_reviewer(doc: StateDoc, env: Envelope, reviewer: Assignment, obs: Observations) -> Decision:
    verdict = reviewer.receipt_summary.verdict if reviewer.receipt_summary is not None else ""
    if verdict == "PASS":
        return _after_pass(doc, env, reviewer)
    if verdict == "PASS_WITH_RISKS":
        return _after_pass_with_risks(doc, env, reviewer, obs)
    if verdict == "FAIL":
        return _after_fail(doc, env, reviewer)
    return _stop("verdict_missing")


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def _decide_for_state(doc: StateDoc, env: Envelope, current: Assignment, obs: Observations) -> Decision:
    state, nn = current.state, current.nn
    if state in ("reserved", "prepared"):
        return _stop("node_not_launched")
    if state in _RUNNING:
        return Decision("wait")
    if state == "waiting_approval":
        return Decision("wait", notify=not obs.notified)
    if state == "uncertain":
        if obs.manager_match == "found":
            return Decision("transition", nn=nn, to="launched")
        if obs.manager_match == "absent":
            return Decision("transition", nn=nn, to="abandoned")
        return Decision("wait")
    if state == "finished":
        if obs.receipt_exists is None:
            raise MissingObservation(f"nn={nn} finished: receipt_exists is required")
        return Decision("transition", nn=nn, to="receipt_received" if obs.receipt_exists else "receipt_missing")
    if state == "receipt_received":
        if obs.receipt_lint is None:
            raise MissingObservation(f"nn={nn} receipt_received: receipt_lint is required")
        errors, summary = obs.receipt_lint
        if errors:
            return Decision("transition", nn=nn, to="receipt_invalid", reason=errors[0])
        return Decision("transition", nn=nn, to="receipt_validated", receipt_summary=summary)
    if state == "receipt_validated":
        if current.receipt_summary is None:
            return _stop("receipt_summary_missing")
        return Decision("transition", nn=nn, to=_CLOSED_BY_STATUS[current.receipt_summary.status])
    if state == "accepted":
        if effective_edge(doc, current) == "revisa":
            return _after_reviewer(doc, env, current, obs)
        return _after_writer(doc, env, current)
    return _stop(state)


def decide(doc: StateDoc, env: Envelope | None, obs: Observations) -> Decision:
    """One next step for the task, per spec §3.3; never performs I/O."""

    if env is None:
        return _stop("no_envelope")
    if env.approval is None:
        return _stop("not_approved")
    if obs.envelope_errors:
        return _stop("envelope_invalid")
    current = max(doc.assignments, key=lambda a: a.nn, default=None)
    if (
        obs.envelope_sha256 != env.approval.sha256
        or any(obs.branches.get(t) != env.branches[t] for t in env.targets)
    ):
        return _stop("envelope_changed")
    errors = graph_errors(doc, env)
    if errors:
        return _stop(f"graph_outside_envelope: {errors[0]}")
    # The graph is valid here, so `stage_of` terminates for every node.
    if current is not None and tuple(current.allowlist) != expected_scope(doc, env, current)[1]:
        return _stop("envelope_changed")
    if current is None:
        return _launch(env, role=env.stages[0].role, edge="inicia", predecessor=0, stage=1)
    return _decide_for_state(doc, env, current, obs)
