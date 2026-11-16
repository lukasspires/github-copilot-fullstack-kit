"""scripts/marina/runner.py — the `marina run` loop (spec §3.3 and §3.6).

One iteration: honor a stop request and the time limit, re-read
`state.toml`, observe the current node in the native manager, gather the
`Observations` `decide` needs (envelope hash and validity, branches,
receipt, judge ledger), call `decide` and execute exactly one action.
Nodes are opened through the existing path only — Git gate (writers) →
`gate.evaluate_gate` → `state add` → `handoff_gen` → `launch_claude.run_launch`
(which runs preflight) — and never outside the envelope's expansion.

Choices from docs/plano-f4-runner-e-juiza-2026-10.md:

- decision 2: the gate runs before `state add`, because it evaluates a
  proposed node that does not exist yet;
- decision 3: the first writer needs no Git acknowledgement (the approved
  envelope is it); later writers need the targets' `git_snapshot` to equal
  the previous writer's `git-after-NN.txt`, otherwise `stop(foreign_change)`;
- decision 4: `git-after-NN.txt` uses `common.git_snapshot`;
- decision 5: judge calls go to `judge-calls.jsonl` (count survives restarts;
  the last valid answer to the same question is reused) and the node a
  judge answer opens is reserved with `by = "marina-judge"`;
- decision 6: the runner's own `state add`/`state set` use `by = "marina-run"`;
- decision 7: only a `wait` sleeps;
- decision 8: `marina stop` writes `.marina-run.stop`, checked each iteration.
- F7: `git-after-NN.txt` and the Git gate cover every envelope target, in
  envelope order, so a foreign change in another stage's target also stops
  the run; `run_argv`/`spawn_detached` are shared by `run_start` and `go`.
- limite-uso, stage 1: when the current node ends without a usable receipt,
  its manager item (`native.id` → `sessionId`) locates the transcript under
  `RunnerDeps.projects_root` and `usage_limit.detect` feeds
  `Observations.usage_limit`; a `usage_limit:` stop runs `--notify-cmd`
  with `MARINA_EVENT=usage_limit_stop`. Every notification carries
  `MARINA_EVENT`, `MARINA_TASK`, `MARINA_NN` and `MARINA_REASON`
  (sanitized, at most 200 characters) in the child's environment.
- limite-uso, stage 2 (architect decisions 3–6): `Observations` carry the
  wall clock (`deps.now()`) and the run's wall-clock deadline; under
  `on_usage_limit = "wait"` the run waits in its own process, holding the
  lock (`marina stop` and `--recover` work as usual), logging and notifying
  (`usage_limit_wait`) only on entering the wait, then opens the
  `substitui` through the same path as any node: its Git gate compares with
  the replaced writer's `git-after-NN.txt`, its handoff comes from
  `handoff_gen.render_replacement_handoff`, its `reserved` event carries
  the audit note, and the reopening is logged, notified
  (`usage_limit_resume`) and listed in the checkpoint section.

It never answers a native approval (it may run `--notify-cmd`), never
retries an `uncertain` launch, never archives or deletes sessions, and
writes only inside the task directory.

Minimum tested Claude CLI version: 2.1.306 — through `launch_claude`,
`status_claude` and `judge` (docs/achados-f1-spike-hooks-e-juiza-2026-10.md).
Every injected boundary lives in `RunnerDeps`; `default_deps` binds the
real ones, and every `claude`/notify child gets `stdin=subprocess.DEVNULL`.
"""

from __future__ import annotations

import dataclasses
import datetime
import functools
import json
import os
import shlex
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Callable

from scripts import common, gate, handoff_sync, launch_claude, preflight, receipt_lint, status_claude
from scripts.marina import envelope as env_mod
from scripts.marina import handoff_gen, judge, usage_limit
from scripts.marina.decide import Decision, NodeSpec, Observations, Question, decide
from scripts.state import (
    Assignment, StateDoc, add_assignment, append_event, effective_edge, read_state, reviewed_writer, write_state,
)
from scripts.state.model import mode_for_role

LOCK_NAME = ".marina-run.lock"
STOP_NAME = ".marina-run.stop"
LOG_NAME = "marina-run.log"
JUDGE_LEDGER = "judge-calls.jsonl"
_WRITER_EDGES = (*env_mod.WRITER_STAGE_EDGES, "corrige")
_OBSERVED_STATES = ("launched", "working", "waiting_approval")
_BEFORE_ACCEPTANCE = ("finished", "receipt_received", "receipt_validated")
USAGE_WAIT_PREFIX = "usage_limit until "


class RunRefused(RuntimeError):
    """The run cannot start (lock held, or recovery not confirmed)."""


@dataclasses.dataclass
class RunnerDeps:
    list_sessions: Callable[[], list[dict]]
    run_subprocess: Callable[..., subprocess.CompletedProcess]
    run_preflight: Callable[..., preflight.PreflightResult]
    git_snapshot: Callable[[str], str]
    git_branch: Callable[[str], str]
    judge: Callable[[Question, list[str]], judge.JudgeAnswer]
    notify: Callable[[str, dict], None]
    sleep: Callable[[float], None]
    monotonic: Callable[[], float]
    now: Callable[[], datetime.datetime]
    pid_alive: Callable[[int], bool]
    getpid: Callable[[], int]
    projects_root: Path = dataclasses.field(default_factory=usage_limit.default_projects_root)


@dataclasses.dataclass
class RunResult:
    outcome: str
    reason: str
    created: list[int]
    judge_decisions: list[str]


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


NOTIFY_REASON_MAX = 200


def _sanitize(value: object, limit: int) -> str:
    return "".join(ch for ch in str(value) if ch.isprintable())[:limit]


def notify_env(event: dict) -> dict[str, str]:
    """The `MARINA_*` variables a `--notify-cmd` child receives for `event` — enumerated fields only."""

    nn = event.get("nn")
    return {
        "MARINA_EVENT": _sanitize(event.get("event", ""), 40),
        "MARINA_TASK": _sanitize(event.get("task", ""), 80),
        "MARINA_NN": f"{nn:02d}" if isinstance(nn, int) else "",
        "MARINA_REASON": _sanitize(event.get("reason", ""), NOTIFY_REASON_MAX),
    }


def _run_notify(command: str, event: dict) -> None:
    subprocess.run(shlex.split(command), stdin=subprocess.DEVNULL, capture_output=True, timeout=30, check=False,
                   env={**os.environ, **notify_env(event)})


def default_deps(kit_root: Path) -> RunnerDeps:
    """Real boundaries; every `claude` child runs from `kit_root`, where the
    kit's agents resolve and `--bg` sessions get the cwd reconciliation expects."""

    cwd = str(kit_root)
    return RunnerDeps(
        list_sessions=common.list_manager_sessions,
        run_subprocess=functools.partial(subprocess.run, cwd=cwd),
        run_preflight=preflight.run_preflight,
        git_snapshot=common.git_snapshot,
        git_branch=common.git_current_branch,
        judge=lambda question, paths: judge.ask(question, [str(p) for p in paths], cwd=cwd),
        notify=_run_notify,
        sleep=time.sleep,
        monotonic=time.monotonic,
        now=lambda: datetime.datetime.now().astimezone(),
        pid_alive=_pid_alive,
        getpid=os.getpid,
    )


# --------------------------------------------------------------------------
# Lock, stop request, status
# --------------------------------------------------------------------------


def _busy_sessions(doc: StateDoc, sessions: list[dict]) -> list[str]:
    prefix = f"{doc.task.slug} —"
    return [
        s.get("name", "?")
        for s in sessions
        if s.get("name", "").startswith(prefix)
        and status_claude.classify_session(s) in ("working", "waiting_approval")
    ]


def _acquire_lock(task_dir: Path, doc: StateDoc, *, recover: bool, deps: RunnerDeps) -> Path:
    path = task_dir / LOCK_NAME
    payload = json.dumps({"pid": deps.getpid(), "started_at": deps.now().isoformat()})
    for attempt in (1, 2):
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            if not recover or attempt == 2:
                raise RunRefused(f"another marina run holds {path}; use `marina status`, or --recover if it died")
            try:
                pid = json.loads(path.read_text(encoding="utf-8")).get("pid")
            except (OSError, ValueError, AttributeError):
                pid = None
            if isinstance(pid, int) and deps.pid_alive(pid):
                raise RunRefused(f"lock {path} is held by live pid {pid}")
            try:
                busy = _busy_sessions(doc, deps.list_sessions())
            except common.ManagerUnavailable as exc:
                raise RunRefused(f"cannot confirm recovery, native manager unavailable: {exc}") from exc
            if busy:
                raise RunRefused(f"cannot recover: task sessions still working or waiting: {busy}")
            path.unlink()
            continue
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
        return path
    raise RunRefused(f"could not acquire {path}")  # pragma: no cover - loop always returns or raises


def live_lock_pid(task_dir: Path, *, pid_alive: Callable[[int], bool] | None = None) -> int | None:
    """The pid of a live `marina run` holding the task's lock, else None."""

    pid_alive = pid_alive or _pid_alive
    try:
        pid = json.loads((Path(task_dir) / LOCK_NAME).read_text(encoding="utf-8")).get("pid")
    except (OSError, ValueError, AttributeError):
        return None
    return pid if isinstance(pid, int) and pid_alive(pid) else None


def git_after_path(task_dir: Path, nn: int) -> Path:
    """Where a writer's `git-after-NN.txt` lives."""

    return Path(task_dir) / f"git-after-{nn:02d}.txt"


def git_after_text(a: Assignment, env: env_mod.Envelope | None, git_snapshot: Callable[[str], str]) -> str:
    """`git-after` content for writer `a`: one `git_snapshot` per target, concatenated.

    The targets are the envelope's, in envelope order (F7), or the node's own
    when the task has no envelope (manual procedure).
    """

    targets = env.targets if env is not None else a.targets
    return "".join(git_snapshot(t) for t in targets)


def run_argv(kit_root: Path, project: str, task: str, *, interval: float, max_duration: str,
             notify_cmd: str | None) -> list[str]:
    """The detached `marina run` command line, as `run_start` and `marina go` spawn it."""

    argv = [sys.executable, str(Path(kit_root) / "scripts" / "marina" / "__main__.py"), "run", project, task,
            "--interval", f"{interval:g}", "--max-duration", max_duration]
    if notify_cmd:
        argv += ["--notify-cmd", notify_cmd]
    return argv + ["--kit-root", str(kit_root)]


def spawn_detached(argv: list[str], cwd: Path, log_path: Path) -> int:
    """Start `argv` in its own session, stdin closed, output appended to `log_path`."""

    with Path(log_path).open("a", encoding="utf-8") as log:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return proc.pid


def request_stop(state_path: Path) -> bool:
    """Ask a running `marina run` to stop at its next iteration."""

    task_dir = Path(state_path).parent
    if not (task_dir / LOCK_NAME).exists():
        return False
    (task_dir / STOP_NAME).write_text("stop requested\n", encoding="utf-8")
    return True


def status_lines(state_path: Path, *, pid_alive: Callable[[int], bool] = _pid_alive) -> list[str]:
    """Read-only summary for `marina status`."""

    state_path = Path(state_path)
    task_dir = state_path.parent
    doc = read_state(state_path)
    lines = [f"task: {doc.task.slug} — {doc.task.title}"]
    lock = task_dir / LOCK_NAME
    if lock.exists():
        try:
            info = json.loads(lock.read_text(encoding="utf-8"))
            pid = info.get("pid")
            alive = "alive" if isinstance(pid, int) and pid_alive(pid) else "not running (orphan lock)"
            lines.append(f"lock: pid {pid} since {info.get('started_at')} — {alive}")
        except (OSError, ValueError, AttributeError):
            lines.append("lock: present but unreadable")
    else:
        lines.append("lock: none")
    try:
        env = env_mod.envelope_from_doc(doc)
    except env_mod.EnvelopeError as exc:
        lines.append(f"envelope: invalid ({exc})")
    else:
        if env is None:
            lines.append("envelope: none")
        elif env.approval is None:
            lines.append("envelope: not approved")
        else:
            lines.append(f"envelope: approved sha256={env.approval.sha256}")
    lines += [f"  {a.nn:02d} {a.role} {a.edge} {a.state}" for a in sorted(doc.assignments, key=lambda a: a.nn)]
    log = task_dir / LOG_NAME
    if log.exists():
        tail = [line for line in log.read_text(encoding="utf-8").splitlines() if line and not line.startswith(" ")][-5:]
        lines.append("last log lines:")
        lines += [f"  {line}" for line in tail]
    return lines


# --------------------------------------------------------------------------
# The loop
# --------------------------------------------------------------------------


class _Run:
    def __init__(self, state_path: Path, kit_root: Path, interval: float, notify_cmd: str | None, deps: RunnerDeps):
        self.state_path = state_path
        self.task_dir = state_path.parent
        self.kit_root = kit_root
        self.interval = interval
        self.notify_cmd = notify_cmd
        self.deps = deps
        self.created: list[int] = []
        self.judge_decisions: list[str] = []
        self.notified: set[tuple[int, int]] = set()
        self.judge_note = ""
        self.reconciled_id: str | None = None
        self.envelope_sha = ""
        # native.id -> transcript sessionId, from the manager items `_observe` reads.
        self.session_ids: dict[str, str] = {}
        # Wall-clock end of the run (None for a preview), and usage-limit waits already logged.
        self.deadline: datetime.datetime | None = None
        self.usage_waits: set[int] = set()
        self.reopenings: list[str] = []

    # -- records ---------------------------------------------------------------

    def log(self, line: str) -> None:
        with (self.task_dir / LOG_NAME).open("a", encoding="utf-8") as stream:
            stream.write(f"{self.deps.now().isoformat()} {line}\n")

    def _ledger(self) -> list[dict]:
        path = self.task_dir / JUDGE_LEDGER
        if not path.exists():
            return []
        entries = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    entries.append({"ok": False})
        return entries

    def _record_judge(self, question: Question, *, decision: str, reason: str, ok: bool) -> None:
        entry = {
            "at": self.deps.now().isoformat(), "nn": question.nn, "kind": question.kind,
            "options": list(question.options), "decision": decision, "reason": reason, "ok": ok,
        }
        with (self.task_dir / JUDGE_LEDGER).open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # -- observation -------------------------------------------------------------

    def _observe(self, doc: StateDoc) -> str | None:
        """Record what the manager shows for the current node; manager_match for `uncertain`."""

        current = max(doc.assignments, key=lambda a: a.nn, default=None)
        if current is None:
            return None
        if current.state in _OBSERVED_STATES and current.native.id:
            try:
                sessions = self.deps.list_sessions()
            except common.ManagerUnavailable:
                return None
            matches = status_claude.find_task_sessions(sessions, native_id=current.native.id)
            if len(matches) == 1:
                self._remember_session(current.native.id, matches[0])
                status_claude.record_observed_transition(
                    str(self.state_path), current.nn, status_claude.classify_session(matches[0]),
                    at=self.deps.now(), session=matches[0],
                )
            return None
        if current.state == "uncertain":
            try:
                sessions = self.deps.list_sessions()
            except common.ManagerUnavailable:
                return None
            matches = [s for s in sessions if s.get("name") == current.title and s.get("cwd") == str(self.kit_root)]
            if len(matches) == 1:
                self.reconciled_id = matches[0].get("id")
                return "found"
            return "absent" if not matches else None
        return None

    def _remember_session(self, native_id: str, session: dict) -> None:
        sid = session.get("sessionId")
        if isinstance(sid, str) and sid:
            self.session_ids[native_id] = sid

    def _usage_limit(self, a: Assignment) -> usage_limit.UsageLimit | None:
        """The usage limit in `a`'s transcript; None when unknown (never raises)."""

        native_id = a.native.id
        if not native_id:
            return None
        if native_id not in self.session_ids:
            try:
                matches = status_claude.find_task_sessions(self.deps.list_sessions(), native_id=native_id)
            except Exception:  # noqa: BLE001 — an unavailable manager only means "no observation"
                return None
            if len(matches) != 1:
                return None
            self._remember_session(native_id, matches[0])
        sid = self.session_ids.get(native_id)
        if sid is None:
            return None
        return usage_limit.detect(sid, self.deps.projects_root, local_tz=self.deps.now().tzinfo)

    def _write_git_after(self, doc: StateDoc, env: env_mod.Envelope | None) -> None:
        current = max(doc.assignments, key=lambda a: a.nn, default=None)
        if current is None or mode_for_role(current.role) != "writer" or current.state not in _BEFORE_ACCEPTANCE:
            return
        path = git_after_path(self.task_dir, current.nn)
        if not path.exists():
            path.write_text(git_after_text(current, env, self.deps.git_snapshot), encoding="utf-8")

    def _observations(self, doc: StateDoc, env: env_mod.Envelope | None, manager_match: str | None) -> Observations:
        if env is None:
            return Observations(envelope_sha256="", branches={})
        errors = list(env_mod.validate_envelope(env, doc=doc, kit_root=self.kit_root, task_dir=self.task_dir))
        try:
            sha = env_mod.compute_hash(env, task_dir=self.task_dir)
        except OSError as exc:
            sha = ""
            errors.append(f"cannot hash the envelope: {exc}")
        self.envelope_sha = sha
        branches = {t: self.deps.git_branch(t) for t in env.targets}
        current = max(doc.assignments, key=lambda a: a.nn, default=None)
        receipt_exists = receipt_lint_result = limit = None
        notified = False
        if current is not None:
            receipt = self.kit_root / current.receipt
            if current.state == "finished":
                receipt_exists = receipt.is_file()
                if not receipt_exists:
                    limit = self._usage_limit(current)
            elif current.state == "receipt_received":
                lint_errors, summary = receipt_lint.lint_file(receipt, handoff=self.kit_root / current.handoff)
                receipt_lint_result = (tuple(lint_errors), summary)
                if lint_errors:
                    limit = self._usage_limit(current)
            elif current.state == "waiting_approval":
                notified = self._waiting_key(current) in self.notified
        ledger = self._ledger()
        judge_answer = None
        for entry in reversed(ledger):
            if entry.get("ok"):
                question = Question(entry.get("kind", ""), entry.get("nn", 0), tuple(entry.get("options", ())))
                judge_answer = (question, entry.get("decision", ""))
                if current is not None and question.nn == current.nn:
                    self.judge_note = (
                        f"nn={question.nn:02d} {question.kind} → {entry.get('decision')}: {entry.get('reason', '')}"
                    )
                break
        return Observations(
            envelope_sha256=sha,
            branches=branches,
            envelope_errors=tuple(errors),
            receipt_exists=receipt_exists,
            receipt_lint=receipt_lint_result,
            manager_match=manager_match,
            notified=notified,
            judge_calls_used=len(ledger),
            judge_answer=judge_answer,
            usage_limit=limit,
            now=self.deps.now(),
            deadline=self.deadline,
        )

    @staticmethod
    def _waiting_key(a: Assignment) -> tuple[int, int]:
        return a.nn, sum(1 for e in a.events if e.to == "waiting_approval")

    # -- actions ---------------------------------------------------------------

    def _transition(self, decision: Decision) -> None:
        doc = read_state(self.state_path)
        a = doc.get_assignment(decision.nn)
        if decision.to == "receipt_validated":
            a.receipt_summary = decision.receipt_summary
        if decision.to == "launched" and self.reconciled_id:
            a.native.id = self.reconciled_id
            self.reconciled_id = None
        at = self.deps.now()
        append_event(a, decision.to, by="marina-run", note=decision.reason, at=at)
        doc.task.updated_at = at
        write_state(self.state_path, doc)

    def _ask_judge(self, doc: StateDoc, env: env_mod.Envelope, obs: Observations, question: Question) -> Decision:
        reviewer = doc.get_assignment(question.nn)
        writer = reviewed_writer(doc, reviewer)
        paths = [str(self.kit_root / p) for p in (reviewer.receipt, reviewer.handoff, writer.receipt)]
        try:
            answer = self.deps.judge(question, paths)
        except judge.JudgeFailed as exc:
            self._record_judge(question, decision="", reason=str(exc)[:200], ok=False)
            return Decision("stop", reason="judge_failed")
        self._record_judge(question, decision=answer.decision, reason=answer.reason, ok=True)
        summary = f"nn={question.nn:02d} {question.kind} → {answer.decision}: {answer.reason}"
        self.judge_decisions.append(summary)
        self.judge_note = summary
        follow = dataclasses.replace(obs, judge_calls_used=obs.judge_calls_used + 1,
                                     judge_answer=(question, answer.decision))
        return decide(doc, env, follow)

    def _git_gate(self, doc: StateDoc, env: env_mod.Envelope, node: NodeSpec) -> str:
        if node.edge == "substitui":
            # The replaced writer's partial work is its git-after; anything else
            # changed the targets meanwhile (architect decision 5), also for `inicia`.
            path = git_after_path(self.task_dir, node.predecessor)
        else:
            writers = [a for a in doc.assignments if effective_edge(doc, a) in _WRITER_EDGES and a.state == "accepted"]
            if not writers:
                return ""
            path = git_after_path(self.task_dir, max(writers, key=lambda a: a.nn).nn)
        if not path.exists():
            return "git_after_missing"
        current = "".join(self.deps.git_snapshot(t) for t in env.targets)
        return "" if current == path.read_text(encoding="utf-8") else "foreign_change"

    def _render(self, doc: StateDoc, env: env_mod.Envelope, a: Assignment, node: NodeSpec) -> str:
        if node.edge == "substitui":
            replaced = doc.get_assignment(a.predecessor)
            replaced_text = (self.kit_root / replaced.handoff).read_text(encoding="utf-8")
            return handoff_gen.render_replacement_handoff(doc, a, kit_root=self.kit_root,
                                                          replaced_handoff_text=replaced_text)
        if node.edge == "revisa":
            writer = doc.get_assignment(a.predecessor)
            writer_text = (self.kit_root / writer.handoff).read_text(encoding="utf-8")
            return handoff_gen.render_review_handoff(doc, a, kit_root=self.kit_root, writer_handoff_text=writer_text)
        template = (self.task_dir / env.stages[node.stage - 1].handoff).read_text(encoding="utf-8")
        if node.edge == "corrige":
            return handoff_gen.render_correction_handoff(doc, a, kit_root=self.kit_root, template_text=template)
        return handoff_gen.render_stage_handoff(doc, a, kit_root=self.kit_root, template_text=template)

    def _open(self, doc: StateDoc, env: env_mod.Envelope, node: NodeSpec, reopen_note: str = "") -> str:
        """Open one node; returns a stop reason, or "" once launch_claude ran.

        `reopen_note` (a usage-limit `substitui`) is the `reserved` event's audit note.
        """

        if mode_for_role(node.role) == "writer":
            refused = self._git_gate(doc, env, node)
            if refused:
                return refused
        result = gate.evaluate_gate(
            doc, role=node.role, type_=node.type, edge=node.edge, predecessor=node.predecessor,
            targets=list(node.targets),
            sibling_docs=gate.load_task_docs(self.task_dir.parent, exclude_slug=doc.task.slug),
            git_diff_acknowledged=True, user_decided=False, list_sessions=self.deps.list_sessions,
        )
        if not result.allowed:
            return f"gate_refused: {result.reasons[0]}"
        if reopen_note:
            by, note = "marina-run", reopen_note
        elif self.judge_note:
            by, note = "marina-judge", self.judge_note
        else:
            by, note = "marina-run", f"stage {node.stage}"
        self.judge_note = ""
        a = add_assignment(
            doc, role=node.role, type_=node.type, edge=node.edge, predecessor=node.predecessor,
            targets=list(node.targets), platform="claude", allowlist=list(node.allowlist),
            note=note, by=by, at=self.deps.now(),
        )
        write_state(self.state_path, doc)
        handoff_sync.write_atomic(self.kit_root / a.handoff, self._render(doc, env, a, node), self.task_dir)
        self.created.append(a.nn)
        launch = launch_claude.run_launch(
            self.state_path, a.nn, kit_root=self.kit_root,
            run_preflight=self.deps.run_preflight, run_subprocess=self.deps.run_subprocess, now=self.deps.now,
        )
        self.log(f"opened nn={a.nn:02d} {a.role} {a.edge}: " + (f"id={launch.session_id}" if launch.ok else
                                                              "; ".join(launch.reasons)[:300]))
        if reopen_note:
            resume = f"usage_limit resume nn={node.predecessor:02d} → nn={a.nn:02d}"
            self.log(resume)
            resets_at = reopen_note.split("resets_at=", 1)[-1].split(";", 1)[0]
            self.reopenings.append(f"nn={node.predecessor:02d}→nn={a.nn:02d} (resets_at {resets_at})")
            self._notify("usage_limit_resume", doc, a.nn, resume)
        return ""

    # -- loop ------------------------------------------------------------------

    def iterate(self) -> Decision | None:
        """One iteration; returns the final decision (stop/done) or None to continue."""

        stop_file = self.task_dir / STOP_NAME
        if stop_file.exists():
            stop_file.unlink()
            return Decision("stop", reason="stop_requested")
        doc = read_state(self.state_path)
        try:
            env = env_mod.envelope_from_doc(doc)
        except env_mod.EnvelopeError:
            return Decision("stop", reason="envelope_invalid")
        manager_match = self._observe(doc)
        doc = read_state(self.state_path)
        self._write_git_after(doc, env)
        obs = self._observations(doc, env, manager_match)
        decision = decide(doc, env, obs)
        if decision.kind == "ask_judge":
            decision = self._ask_judge(doc, env, obs, decision.question)
        usage_wait = decision.kind == "wait" and decision.reason.startswith(USAGE_WAIT_PREFIX)
        if usage_wait:
            # Logged and notified once per entry into the wait, not every interval.
            if decision.nn not in self.usage_waits:
                self.usage_waits.add(decision.nn)
                self.log(f"usage_limit wait nn={decision.nn:02d} until {decision.reason[len(USAGE_WAIT_PREFIX):]}")
                self._notify("usage_limit_wait", doc, decision.nn, decision.reason)
        else:
            self.log(f"{decision.kind} nn={decision.nn or '-'} {decision.to or decision.reason}".rstrip())
        if decision.kind == "wait":
            if decision.notify:
                current = max(doc.assignments, key=lambda a: a.nn)
                self.notified.add(self._waiting_key(current))
                self._notify("waiting_approval", doc, current.nn, "waiting_approval")
            self.deps.sleep(self.interval)
            return None
        if decision.kind == "transition":
            self._transition(decision)
            return None
        if decision.kind == "launch":
            reopen_note = decision.reason if decision.node.edge == "substitui" else ""
            refused = self._open(doc, env, decision.node, reopen_note)
            return Decision("stop", reason=refused) if refused else None
        if decision.kind == "stop" and decision.reason.startswith("usage_limit:"):
            current = max(doc.assignments, key=lambda a: a.nn, default=None)
            self._notify("usage_limit_stop", doc, current.nn if current is not None else None, decision.reason)
        return decision

    def _notify(self, event: str, doc: StateDoc, nn: int | None, reason: str) -> None:
        """Run `--notify-cmd` with the event in its environment; a failure is only logged."""

        if not self.notify_cmd:
            return
        try:
            self.deps.notify(self.notify_cmd, {"event": event, "task": doc.task.slug, "nn": nn, "reason": reason})
        except Exception as exc:  # noqa: BLE001 — a notifier failure never stops the run
            self.log(f"notify failed: {exc}")


def preview_decision(state_path: Path, *, kit_root: Path, deps: RunnerDeps) -> Decision:
    """The decision `marina run` would take now, without any side effect.

    Same observations as the loop, except that the manager is not observed
    (no `record_observed_transition`, so an `uncertain` node shows `wait`),
    no `git-after` is written and the judge is never called: an `ask_judge`
    is returned as is (F5 plan, decision 3).
    """

    state_path = Path(state_path)
    doc = read_state(state_path)
    try:
        env = env_mod.envelope_from_doc(doc)
    except env_mod.EnvelopeError:
        return Decision("stop", reason="envelope_invalid")
    preview = _Run(state_path, Path(kit_root), 1.0, None, deps)
    return decide(doc, env, preview._observations(doc, env, None))


def decision_to_dict(decision: Decision) -> dict:
    """JSON-serializable view of a `Decision` (for `marina mcp`)."""

    return {
        "kind": decision.kind,
        "nn": decision.nn,
        "to": decision.to,
        "reason": decision.reason,
        "notify": decision.notify,
        "node": dataclasses.asdict(decision.node) if decision.node is not None else None,
        "question": (
            {"kind": decision.question.kind, "nn": decision.question.nn, "options": list(decision.question.options)}
            if decision.question is not None else None
        ),
    }


def _append_checkpoint(run: _Run, doc: StateDoc, *, started: datetime.datetime, interval: float,
                       effective: float, final: Decision) -> None:
    journal = run.kit_root / doc.task.journal
    created = [doc.get_assignment(nn) for nn in run.created if any(a.nn == nn for a in doc.assignments)]
    nodes = ", ".join(f"nn={a.nn:02d} {a.role} {a.edge} (id {a.native.id or '—'})" for a in created) or "nenhum"
    judged = ", ".join(run.judge_decisions) or "nenhuma"
    stop = "done" if final.kind == "done" else f"stop({final.reason})"
    action = (
        "Marina — revisar o resultado e decidir commit." if final.kind == "done"
        else f"Marina — decidir sobre {final.reason}."
    )
    section = (
        f"\n## Execução marina-run {started.isoformat()}\n\n"
        f"- Envelope: sha256 `{run.envelope_sha or '—'}`; intervalo {interval:g}s; duração efetiva {effective:g}s.\n"
        f"- Nós criados: {nodes}.\n"
        f"- Decisões da juíza: {judged}.\n"
        + (f"- Reaberturas por limite de uso: {', '.join(run.reopenings)}.\n" if run.reopenings else "")
        + f"- Motivo de parada: {stop}.\n"
        f"- Próxima ação: {action}\n"
    )
    with journal.open("a", encoding="utf-8") as stream:
        stream.write(section)


def run(
    state_path: Path,
    *,
    kit_root: Path,
    interval: float,
    max_duration: float,
    notify_cmd: str | None = None,
    recover: bool = False,
    deps: RunnerDeps,
) -> RunResult:
    """Run the approved envelope of one task until `done` or a stop reason."""

    if interval <= 0:
        raise ValueError("interval must be > 0")
    if max_duration <= 0:
        raise ValueError("max_duration must be > 0")
    state_path = Path(state_path)
    kit_root = Path(kit_root)
    doc = read_state(state_path)
    lock = _acquire_lock(state_path.parent, doc, recover=recover, deps=deps)
    current = _Run(state_path, kit_root, interval, notify_cmd, deps)
    started, t0 = deps.now(), deps.monotonic()
    effective = max_duration
    try:
        env = env_mod.envelope_from_doc(doc)
        if env is not None:
            effective = min(max_duration, env_mod.parse_duration(env.max_duration))
    except env_mod.EnvelopeError:
        pass
    # Wall clock, for the usage-limit wait (architect E11): the monotonic one stops during suspend.
    current.deadline = started + datetime.timedelta(seconds=effective)
    final: Decision | None = None
    try:
        while final is None:
            if deps.monotonic() - t0 >= effective:
                final = Decision("stop", reason="max_duration")
                break
            try:
                final = current.iterate()
            except KeyboardInterrupt:
                final = Decision("stop", reason="interrupted")
            except Exception:  # noqa: BLE001 — spec 3.6: any unforeseen error stops the run
                current.log("internal_error\n" + "".join(f"  {line}\n" for line in traceback.format_exc().splitlines()))
                final = Decision("stop", reason="internal_error")
        current.log(f"end {'done' if final.kind == 'done' else 'stop(' + final.reason + ')'}")
        _append_checkpoint(current, read_state(state_path), started=started, interval=interval,
                           effective=effective, final=final)
    finally:
        lock.unlink(missing_ok=True)
    return RunResult(
        outcome="done" if final.kind == "done" else "stop",
        reason="" if final.kind == "done" else final.reason,
        created=current.created,
        judge_decisions=current.judge_decisions,
    )
