"""scripts/marina/progress.py — the read-only model behind `marina watch` (F8).

`build_view` turns a task's `state.toml`, its envelope, its stage templates,
the run lock and log, the native manager listing, past tasks' events and a
session transcript into a `View`; `render` draws it as plain lines. Nothing
here writes anything.

Honest metrics (docs/plano-marina-perguntas-plano-e-tui-2026-10.md, 6.1):

- progress is counted in nodes, against the planned expansion without
  corrections (N_min) and with every correction the envelope allows
  (N_max); correction slots join N_min only once a FAIL triggers them;
- durations are p50/p80 per (role, type) over observed pairs only
  (`launched` by `launch-claude` → `finished` by `status`), with at least
  `MIN_SAMPLES` samples, otherwise "sem base"; no percentage inside a node
  and no negative estimate.

The transcript format (`~/.claude/projects/<slug>/<sessionId>.jsonl`) is
not documented; `last_activity` degrades to None on anything unexpected.
Minimum tested Claude CLI version: 2.1.311.
"""

from __future__ import annotations

import dataclasses
import datetime
import json
import math
from pathlib import Path
from typing import Callable

from scripts import common, status_claude
from scripts.marina import decide as decide_mod
from scripts.marina import envelope as env_mod
from scripts.marina import handoff_gen, runner
from scripts.state import Assignment, StateDoc, StateError, effective_edge, read_state, replaced_node
from scripts.state.model import TERMINAL_STATES

MIN_SAMPLES = 5
RUNNING_STATES = ("prepared", "launched", "uncertain", "working", "waiting_approval")
_AFTER_RUN = ("finished", "receipt_received", "receipt_validated")
_TRANSCRIPT_TAIL = 256 * 1024
_ACTIVITY_KEYS = ("command", "file_path", "pattern", "path", "url", "description")


@dataclasses.dataclass(frozen=True)
class Slot:
    stage: int
    kind: str  # "writer" | "review" | "correction" | "rereview"
    role: str
    type: str
    conditional: bool
    node: Assignment | None = None
    active: bool = True


@dataclasses.dataclass(frozen=True)
class Stats:
    n: int
    p50: float
    p80: float


@dataclasses.dataclass(frozen=True)
class Estimate:
    low: float | None
    high: float | None
    over_typical: bool
    missing: tuple[tuple[str, str], ...]


@dataclasses.dataclass(frozen=True)
class View:
    slug: str
    title: str
    envelope_note: str
    now: datetime.datetime
    run_pid: int | None
    run_alive: bool
    run_started: datetime.datetime | None
    deadline: datetime.datetime | None
    slots: list[Slot]
    extra: list[Assignment]
    counts: tuple[int, int, int]
    estimate: Estimate
    stats: dict[tuple[str, str], Stats]
    current: Slot | None
    current_is_next: bool
    manager_note: str
    activity: tuple[str, datetime.datetime] | None
    last_log: str
    io: tuple[list[str], list[str]]
    judge: str


# --------------------------------------------------------------------------
# Planned expansion
# --------------------------------------------------------------------------


def expansion_slots(env: env_mod.Envelope) -> list[Slot]:
    """Every node the envelope's expansion can open, in order (the `decide` table)."""

    slots: list[Slot] = []
    last = len(env.stages)
    for stage, spec in enumerate(env.stages, 1):
        slots.append(Slot(stage, "writer", spec.role, "implementação", False))
        if env.review == "each_stage" or stage == last:
            slots.append(Slot(stage, "review", "reviewer", "revisão", False))
            if env.max_corrections >= 1:
                slots.append(Slot(stage, "correction", spec.role, "correção", True, active=False))
                slots.append(Slot(stage, "rereview", "reviewer", "revisão", True, active=False))
    return slots


def _kind(doc: StateDoc, a: Assignment) -> str | None:
    original = replaced_node(doc, a)
    edge = original.edge
    if edge in env_mod.WRITER_STAGE_EDGES:
        return "writer"
    if edge == "corrige":
        return "correction"
    if edge == "revisa":
        reviewed = doc.get_assignment(original.predecessor)
        return "rereview" if effective_edge(doc, reviewed) == "corrige" else "review"
    return None


def fill_slots(doc: StateDoc, env: env_mod.Envelope) -> tuple[list[Slot], list[Assignment]]:
    """Slots with their (latest) node, and the nodes outside the expansion.

    A `substitui` fills the slot of the node it replaces, so a replaced node
    is never counted twice.
    """

    slots = expansion_slots(env)
    index = {(s.stage, s.kind): i for i, s in enumerate(slots)}
    extra: list[Assignment] = []
    for a in sorted(doc.assignments, key=lambda a: a.nn):
        try:
            key = (decide_mod.stage_of(doc, a.nn), _kind(doc, a))
        except (ValueError, KeyError, StateError, RecursionError):
            key = None
        if key is None or key not in index:
            extra.append(a)
            continue
        slots[index[key]] = dataclasses.replace(slots[index[key]], node=a)
    failed = {s.stage for s in slots if s.kind == "review" and s.node is not None
              and s.node.receipt_summary is not None and s.node.receipt_summary.verdict == "FAIL"}
    result = []
    for s in slots:
        if s.conditional:
            s = dataclasses.replace(s, active=s.node is not None or s.stage in failed)
        result.append(s)
    return result, extra


def counts(slots: list[Slot]) -> tuple[int, int, int]:
    """(done, N_min, N_max): accepted nodes, active slots, every slot."""

    done = sum(1 for s in slots if s.node is not None and s.node.state == "accepted")
    return done, sum(1 for s in slots if s.active), len(slots)


# --------------------------------------------------------------------------
# Durations
# --------------------------------------------------------------------------


def _first_event(a: Assignment, to: str, by: str | None = None) -> datetime.datetime | None:
    for event in a.events:
        if event.to == to and (by is None or event.by == by):
            return event.at
    return None


def node_window(a: Assignment, now: datetime.datetime) -> tuple[datetime.datetime | None,
                                                               datetime.datetime | None, float | None]:
    """(launched at, finished at, seconds between them — or until `now`)."""

    start, end = _first_event(a, "launched"), _first_event(a, "finished")
    if start is None:
        return None, end, None
    return start, end, ((end or now) - start).total_seconds()


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[max(math.ceil(q * len(ordered)) - 1, 0)]


def duration_stats(docs: list[StateDoc]) -> dict[tuple[str, str], Stats]:
    """p50/p80 per (role, type) over observed launched→finished pairs."""

    samples: dict[tuple[str, str], list[float]] = {}
    for doc in docs:
        for a in doc.assignments:
            start = _first_event(a, "launched", "launch-claude")
            end = _first_event(a, "finished", "status")
            if start is not None and end is not None and end >= start:
                samples.setdefault((a.role, a.type), []).append((end - start).total_seconds())
    return {
        key: Stats(len(values), _percentile(values, 0.5), _percentile(values, 0.8))
        for key, values in samples.items() if len(values) >= MIN_SAMPLES
    }


def estimate(slots: list[Slot], stats: dict[tuple[str, str], Stats], now: datetime.datetime) -> Estimate:
    """Remaining time of the active slots (p50..p80), or the keys with no base."""

    low = high = 0.0
    over = False
    missing: list[tuple[str, str]] = []
    for s in slots:
        if not s.active:
            continue
        node = s.node
        if node is not None and node.state not in RUNNING_STATES:
            continue
        key = (s.role, s.type)
        if key not in stats:
            if key not in missing:
                missing.append(key)
            continue
        st = stats[key]
        if node is None:
            low, high = low + st.p50, high + st.p80
            continue
        _, _, elapsed = node_window(node, now)
        elapsed = elapsed or 0.0
        over = over or elapsed > st.p80
        low, high = low + max(st.p50 - elapsed, 0.0), high + max(st.p80 - elapsed, 0.0)
    if missing:
        return Estimate(None, None, over, tuple(missing))
    return Estimate(low, high, over, ())


# --------------------------------------------------------------------------
# Expected inputs and outputs, activity
# --------------------------------------------------------------------------


def _lines(body: str) -> list[str]:
    out = []
    for line in body.splitlines():
        line = line.strip()
        if line[:2] in ("- ", "* "):
            line = line[2:].strip()
        if line:
            out.append(line)
    return out


def _mark(kit_root: Path, relative: str) -> str:
    return "✔" if (kit_root / relative).is_file() else "☐"


def stage_io(doc: StateDoc, env: env_mod.Envelope, slot: Slot, *, kit_root: Path,
             task_dir: Path) -> tuple[list[str], list[str]]:
    """Expected inputs and outputs of `slot`, from its stage template or defaults."""

    try:
        template = (task_dir / env.stages[slot.stage - 1].handoff).read_text(encoding="utf-8")
    except (OSError, IndexError):
        template = ""
    if slot.kind in ("writer", "correction"):
        declared_in = _lines(handoff_gen._body(template, "Expected inputs"))
        declared_out = _lines(handoff_gen._body(template, "Expected outputs"))
    else:
        declared_in = declared_out = []
    node = slot.node
    nn = f"{node.nn:02d}" if node is not None else "NN"
    handoff = node.handoff if node is not None else f"{nn}-{slot.role}-handoff.md"
    receipt = node.receipt if node is not None else f"{nn}-{slot.role}-receipt.md"
    pred = None
    if node is not None and node.predecessor:
        try:
            pred = doc.get_assignment(node.predecessor)
        except (KeyError, StateError):
            pred = None
    inputs = declared_in or [f"{_mark(kit_root, handoff)} handoff {Path(handoff).name}"]
    if not declared_in:
        if pred is not None:
            verdict = pred.receipt_summary.verdict if pred.receipt_summary is not None else ""
            inputs.append(f"{_mark(kit_root, pred.receipt)} receipt {Path(pred.receipt).name} {verdict}".rstrip())
        elif slot.kind != "writer" or slot.stage > 1:
            inputs.append("☐ receipt do predecessor")
        if slot.kind in ("writer", "correction"):
            inputs.append("Git gate: alvos iguais ao git-after do writer anterior")
            targets, allowlist = env_mod.node_scope(env, slot.stage, "corrige" if slot.kind == "correction"
                                                    else "inicia")
            inputs.append(f"alvos: {', '.join(targets)} · allowlist: {len(allowlist)} regra(s)")
        else:
            inputs.append("diff dos alvos do writer revisado")
    if declared_out:
        return inputs, declared_out
    outputs: list[str] = []
    if slot.kind in ("writer", "correction"):
        outputs += _lines(handoff_gen._body(template, "Write scope"))
        outputs.append(f"{_mark(kit_root, receipt)} receipt {Path(receipt).name} (receipt-lint)")
        outputs.append("checks do handoff verdes")
        outputs.append(f"☐ git-after-{nn}.txt (gerado pelo run)")
    else:
        outputs.append(f"{_mark(kit_root, receipt)} receipt {Path(receipt).name} com verdict")
    return inputs, outputs


def _parse_timestamp(text: object) -> datetime.datetime | None:
    if not isinstance(text, str):
        return None
    try:
        return datetime.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def last_activity(session_id: str, projects_root: Path) -> tuple[str, datetime.datetime] | None:
    """The last tool call in a session transcript, as ("Name summary", at); None if unknown."""

    if not session_id:
        return None
    try:
        matches = sorted(Path(projects_root).glob(f"*/{session_id}.jsonl"))
        if not matches:
            return None
        with matches[0].open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(size - _TRANSCRIPT_TAIL, 0))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get("type") != "assistant":
            continue
        content = (entry.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        uses = [c for c in content if isinstance(c, dict) and c.get("type") == "tool_use"]
        at = _parse_timestamp(entry.get("timestamp"))
        if not uses or at is None:
            continue
        use = uses[-1]
        inp = use.get("input") if isinstance(use.get("input"), dict) else {}
        summary = next((str(inp[k]) for k in _ACTIVITY_KEYS if k in inp), "")
        text = " ".join(f"{use.get('name', '?')} {summary}".split())
        return text[:200], at
    return None


# --------------------------------------------------------------------------
# View
# --------------------------------------------------------------------------


def _lock(task_dir: Path) -> tuple[int | None, datetime.datetime | None]:
    try:
        info = json.loads((task_dir / runner.LOCK_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(info, dict):
        return None, None
    pid = info.get("pid") if isinstance(info.get("pid"), int) else None
    return pid, _parse_timestamp(info.get("started_at"))


def _last_log(task_dir: Path) -> str:
    try:
        text = (task_dir / runner.LOG_NAME).read_text(encoding="utf-8")
    except OSError:
        return ""
    lines = [line for line in text.splitlines() if line and not line.startswith(" ")]
    return lines[-1] if lines else ""


def _judge(task_dir: Path, env: env_mod.Envelope | None) -> str:
    try:
        used = sum(1 for line in (task_dir / runner.JUDGE_LEDGER).read_text(encoding="utf-8").splitlines()
                   if line.strip())
    except OSError:
        used = 0
    return f"{used}/{env.judge_max_calls}" if env is not None else str(used)


def _current(slots: list[Slot], doc: StateDoc) -> tuple[Slot | None, bool]:
    live = [s for s in slots if s.node is not None and s.node.state not in TERMINAL_STATES]
    if live:
        return max(live, key=lambda s: s.node.nn), False
    upcoming = [s for s in slots if s.active and s.node is None]
    return (upcoming[0], True) if upcoming else (None, False)


def build_view(
    state_path: Path,
    *,
    kit_root: Path,
    now: datetime.datetime,
    sessions: list[dict] | None,
    pid_alive: Callable[[int], bool],
    projects_root: Path,
    history_docs: list[StateDoc],
) -> View:
    """Everything `render` shows; `sessions=None` means the manager is unavailable."""

    state_path, kit_root = Path(state_path), Path(kit_root)
    task_dir = state_path.parent
    doc = read_state(state_path)
    env: env_mod.Envelope | None = None
    try:
        env = env_mod.envelope_from_doc(doc)
    except env_mod.EnvelopeError as exc:
        envelope_note = f"inválido ({exc})"
    else:
        if env is None:
            envelope_note = "nenhum"
        elif env.approval is None:
            envelope_note = "não aprovado"
        else:
            at = env.approval.at.astimezone(now.tzinfo).strftime("%d/%m %H:%M")
            envelope_note = f"aprovado {env.approval.sha256[:4]}…{env.approval.sha256[-2:]} em {at}"
    if env is not None:
        slots, extra = fill_slots(doc, env)
    else:
        slots, extra = [], sorted(doc.assignments, key=lambda a: a.nn)
    pid, started = _lock(task_dir)
    alive = pid is not None and pid_alive(pid)
    deadline = None
    if env is not None and started is not None:
        deadline = started + datetime.timedelta(seconds=env_mod.parse_duration(env.max_duration))
    current, is_next = _current(slots, doc)
    manager_note, activity = "manager indisponível", None
    if sessions is not None:
        manager_note = "manager: sem sessão para o nó atual"
        node = current.node if current is not None else None
        if node is not None and node.native.id:
            match = [s for s in sessions if s.get("id") == node.native.id]
            if match:
                try:
                    classification = status_claude.classify_session(match[0])
                except common.ManagerSchemaError:
                    classification = "unknown"
                manager_note = f"manager: {classification} ({match[0].get('state', '?')}/{match[0].get('status', '?')})"
                activity = last_activity(str(match[0].get("sessionId", "")), projects_root)
    stats = duration_stats(history_docs)
    io: tuple[list[str], list[str]] = ([], [])
    if env is not None and current is not None:
        io = stage_io(doc, env, current, kit_root=kit_root, task_dir=task_dir)
    return View(
        slug=doc.task.slug, title=doc.task.title, envelope_note=envelope_note, now=now, run_pid=pid,
        run_alive=alive, run_started=started, deadline=deadline, slots=slots, extra=extra,
        counts=counts(slots), estimate=estimate(slots, stats, now), stats=stats, current=current,
        current_is_next=is_next, manager_note=manager_note, activity=activity, last_log=_last_log(task_dir),
        io=io, judge=_judge(task_dir, env),
    )


# --------------------------------------------------------------------------
# Render
# --------------------------------------------------------------------------


def _clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = int(seconds)
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


def _minutes(seconds: float) -> str:
    return f"{max(round(seconds / 60), 1)}m" if seconds >= 30 else f"{int(seconds)}s"


def _hm(at: datetime.datetime | None, now: datetime.datetime) -> str:
    return at.astimezone(now.tzinfo).strftime("%H:%M") if at is not None else "—"


def _fit(text: str, width: int) -> str:
    return text if len(text) <= width else text[: max(width - 1, 0)] + "…"


def _bar(done: int, total: int, size: int = 16) -> str:
    filled = round(size * done / total) if total else 0
    return "▓" * filled + "░" * (size - filled)


def _pct(done: int, total: int) -> str:
    return f"{round(100 * done / total)}%" if total else "—"


def _mark_for(s: Slot) -> str:
    if s.node is None:
        return "·" if s.active else "?"
    if s.node.state == "accepted":
        return "✔"
    if s.node.state in TERMINAL_STATES:
        return "✖"
    return "▶"


def _slot_row(s: Slot, view: View) -> str:
    stats = view.stats.get((s.role, s.type))
    typical = f"p50 {_minutes(stats.p50)}" if stats else "sem base"
    if s.node is None:
        state = "planejado" if s.active else "só se FAIL"
        return f" {_mark_for(s)} {s.stage:<3} {'—':<3} {s.role:<14} {s.type:<14} {state:<22} {'—':<6} {'—':<6} {'—':<8} {typical}"
    start, end, elapsed = node_window(s.node, view.now)
    state = s.node.state
    verdict = s.node.receipt_summary.verdict if s.node.receipt_summary is not None else ""
    if verdict:
        state = f"{state} {verdict}"
    if s.node.edge == "substitui":
        state = f"{state} (substitui)"
    return (f" {_mark_for(s)} {s.stage:<3} {s.node.nn:02d}  {s.role:<14} {s.type:<14} {state:<22} "
            f"{_hm(start, view.now):<6} {_hm(end, view.now):<6} {_clock(elapsed):<8} {typical}")


def render(view: View, width: int) -> list[str]:
    """The watch screen as lines no longer than `width`."""

    done, n_min, n_max = view.counts
    lines = [f"marina · {view.slug} — {view.title}", f"envelope: {view.envelope_note}"]
    if view.run_pid is None:
        lines.append("run: nenhuma em andamento (sem trava)")
    else:
        status = "ativa" if view.run_alive else "parada (trava órfã)"
        elapsed = (view.now - view.run_started).total_seconds() if view.run_started else None
        limit = f" · limite até {_hm(view.deadline, view.now)}" if view.deadline else ""
        lines.append(f"run: pid {view.run_pid} {status} desde {_hm(view.run_started, view.now)} · "
                     f"decorrido {_clock(elapsed)}{limit}")
    if view.slots:
        lines.append(f"progresso {_bar(done, n_max)} {done}/{n_min} nós ({_pct(done, n_min)}) · "
                     f"com todas as correções: {done}/{n_max} ({_pct(done, n_max)})")
        est = view.estimate
        if view.current is None:
            lines.append("restante: nada pendente na expansão do envelope")
        elif est.low is None:
            missing = ", ".join(f"{r}/{t}" for r, t in est.missing)
            lines.append(f"restante: sem base (menos de {MIN_SAMPLES} amostras para {missing})")
        else:
            end_low = view.now + datetime.timedelta(seconds=est.low)
            end_high = view.now + datetime.timedelta(seconds=est.high)
            over = " · nó atual acima do típico" if est.over_typical else ""
            lines.append(f"restante: {_minutes(est.low)}–{_minutes(est.high)} (p50–p80) · fim provável "
                         f"{_hm(end_low, view.now)}–{_hm(end_high, view.now)}{over}")
        lines.append("── etapas planejadas " + "─" * 40)
        lines.append(f"   {'est':<3} {'NN':<3} {'papel':<14} {'tipo':<14} {'estado':<22} {'entra':<6} {'sai':<6} "
                     f"{'duração':<8} típico")
        lines += [_slot_row(s, view) for s in view.slots]
    if view.extra:
        title = "nós fora da expansão do envelope" if view.slots else "nós da tarefa (sem envelope válido)"
        lines.append(f"── {title} " + "─" * max(56 - len(title), 4))
        lines += [f"   {a.nn:02d} {a.role} {a.edge} {a.state}" for a in view.extra]
    lines.append("── agora " + "─" * 51)
    current = view.current
    if current is None:
        lines.append("nenhuma etapa ativa ou prevista")
    elif view.current_is_next:
        lines.append(f"próxima etapa: {current.role} · {current.type} · estágio {current.stage}")
    else:
        node = current.node
        lines.append(f"{node.nn:02d} {node.role} · {node.title} · id {node.native.id or '—'}")
    activity = view.manager_note
    if view.activity is not None:
        text, at = view.activity
        activity += f" · última ação há {_clock((view.now - at).total_seconds())}: {text}"
    lines.append(activity)
    lines.append(f"runner: {view.last_log or '—'} · juíza {view.judge}")
    inputs, outputs = view.io
    if inputs or outputs:
        lines.append("── entradas esperadas " + "─" * 38)
        lines += [f"  {line}" for line in inputs]
        lines.append("── saídas e artefatos esperados " + "─" * 28)
        lines += [f"  {line}" for line in outputs]
    lines.append("q fecha o visor (a run continua) · s pede parada da run")
    return [_fit(line, width) for line in lines]
