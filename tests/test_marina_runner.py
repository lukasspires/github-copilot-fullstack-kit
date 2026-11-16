"""Tests for scripts/marina/runner.py — the `marina run` loop.

A `World` fakes everything outside the task directory: the native manager
(a dict of sessions), `claude --bg` (prints an 8-hex id and registers a
working session), Git (a snapshot string and a branch), the clock and
`sleep` (which advances time and finishes working sessions, writing their
receipts), the judge and the notifier. Preflight, launch_claude, gate,
handoff_sync and receipt_lint run for real against a temporary kit root.
"""

from __future__ import annotations

import datetime
import functools
import json
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import scripts.state as st
from scripts import preflight, status_claude
from scripts.marina import envelope as env_mod
from scripts.marina import handoff_gen, runner, usage_limit
from scripts.marina.judge import JudgeAnswer, JudgeFailed

KIT_ROOT = Path(__file__).resolve().parent.parent
AT = datetime.datetime(2026, 10, 26, 21, 0, 0, tzinfo=datetime.timezone.utc)
ROLE = "node-backend"
TEMPLATE = (
    "## Objective\n\nImplement stage {n}.\n\n## Write scope\n\n`src/`\n\n"
    "## Acceptance criteria\n\n1. Stage {n} works.\n\n## Checks and workdir\n\nRun `true`.\n"
)


class World:
    def __init__(self, tmp: str, *, stages: int = 1, review: str = "each_stage", verdicts: dict | None = None,
                 on_pass_with_risks: str = "judge", judge_max_calls: int = 1, max_corrections: int = 1,
                 second_target: bool = False, on_usage_limit: str | None = None):
        self.kit = Path(tmp) / "kit"
        agents = self.kit / ".claude" / "agents"
        agents.mkdir(parents=True)
        for role in (ROLE, "reviewer"):
            shutil.copy(KIT_ROOT / ".claude" / "agents" / f"{role}.md", agents)
        (self.kit / "AGENTS.md").write_text("# kit\n", encoding="utf-8")
        self.target = Path(tmp) / "target"
        self.target.mkdir()
        # F7: with `second_target`, stage 1 works in `target` and every later stage in `target2`.
        self.target2 = Path(tmp) / "target2"
        self.target2.mkdir()
        targets = [str(self.target), str(self.target2)] if second_target else [str(self.target)]
        self.task_dir = self.kit / ".agent-state" / "demo" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)
        self.state_path = self.task_dir / "state.toml"
        for n in range(1, stages + 1):
            (self.task_dir / f"stage-{n}-handoff-template.md").write_text(TEMPLATE.format(n=n), encoding="utf-8")
        doc = st.init_state(self.state_path, project="demo", slug="t1", title="Demo", kit_root=str(self.kit),
                            targets=targets, at=AT)
        raw = {
            "targets": targets,
            "branches": {t: "feat/x" for t in targets},
            "allowlist": [f"Bash(test -d {t})" for t in targets],
            "review": review,
            "max_corrections": max_corrections,
            "max_duration": "8h",
            "judge_max_calls": judge_max_calls,
            "on_pass_with_risks": on_pass_with_risks,
            "stages": [{"role": ROLE, "handoff": f"stage-{n}-handoff-template.md"} for n in range(1, stages + 1)],
        }
        if second_target:
            for n, stage in enumerate(raw["stages"], 1):
                stage_target = targets[0] if n == 1 else targets[1]
                stage.update(targets=[stage_target], allowlist=[f"Bash(test -d {stage_target})"])
        if on_usage_limit is not None:
            raw["on_usage_limit"] = on_usage_limit
        sha = env_mod.compute_hash(env_mod.parse_envelope(raw), task_dir=self.task_dir)
        raw["approval"] = {"at": AT, "sha256": sha}
        doc.envelope = raw
        st.write_state(self.state_path, doc)

        self.sessions: dict[str, dict] = {}
        self.verdicts = verdicts or {}
        self.after_receipt: dict[int, callable] = {}
        self.snapshot = "clean\n"
        self.per_target: dict[str, str] = {}
        self.branch = "feat/x"
        self.clock = 0.0
        self.wall = AT  # wall clock at clock 0; `now()` is wall + clock
        self.auto_finish = True
        self.initial_session: dict = {"state": "working", "status": "busy"}
        self.launch_calls: list[tuple[list[str], dict]] = []
        self.judge_calls: list = []
        self.judge_result: JudgeAnswer | Exception = JudgeAnswer("continue", "risks are acceptable")
        self.notified: list[str] = []
        self.notify_events: list[dict] = []
        self.notify_error: Exception | None = None
        self.projects_root = Path(tmp) / "projects"
        self.alive = False
        self.git_branch_error: Exception | None = None

    # -- fakes ---------------------------------------------------------------

    def list_sessions(self) -> list[dict]:
        return [dict(s) for s in self.sessions.values()]

    def launch(self, argv, **kwargs):
        self.launch_calls.append((list(argv), kwargs))
        name = argv[argv.index("--name") + 1]
        nn = int(name.split(" — ")[2])
        sid = f"{nn:08x}"
        self.sessions[sid] = {"id": sid, "name": name, "cwd": str(self.kit), "kind": "background",
                              **self.initial_session}
        return subprocess.CompletedProcess(argv, 0, f"started {sid}\n", "")

    def sleep(self, seconds: float) -> None:
        self.clock += seconds
        if not self.auto_finish:
            return
        for session in self.sessions.values():
            if session.get("state") == "working":
                session.update(state="done", status="idle")
                nn = int(session["name"].split(" — ")[2])
                self.write_receipt(nn)
                hook = self.after_receipt.get(nn)
                if hook:
                    hook()

    def write_receipt(self, nn: int) -> None:
        a = st.read_state(self.state_path).get_assignment(nn)
        verdict = self.verdicts.get(nn)
        text = (
            f"# {a.title}\n\n## Status\n\ndone\n\n## Changed\n\nSomething.\n\n"
            "## Profile and Instructions Read\n\n"
            f"- **profile_read:** `{self.kit}/.claude/agents/{a.role}.md`\n"
            f"- **instructions_read:**\n  - `{self.kit}/AGENTS.md`\n\n"
            f"## Risks\n\n### RISK 1: finding of nn {nn} (Severity: Low)\n\nBody.\n\n## Next\n\nNone.\n"
        )
        if verdict:
            text += f"\n## Verdict\n\n{verdict}\n"
        (self.kit / a.receipt).write_text(text, encoding="utf-8")

    def notify(self, command: str, event: dict) -> None:
        self.notified.append(command)
        self.notify_events.append(dict(event))
        if self.notify_error is not None:
            raise self.notify_error

    def judge(self, question, paths):
        self.judge_calls.append((question, [str(p) for p in paths]))
        if isinstance(self.judge_result, Exception):
            raise self.judge_result
        return self.judge_result

    def git_branch(self, target: str) -> str:
        if self.git_branch_error is not None:
            raise self.git_branch_error
        return self.branch

    def deps(self) -> runner.RunnerDeps:
        return runner.RunnerDeps(
            list_sessions=self.list_sessions,
            run_subprocess=self.launch,
            run_preflight=functools.partial(
                preflight.run_preflight, which=lambda c: f"/usr/bin/{c}", list_sessions=self.list_sessions,
                git_status_diff=lambda t: "clean\n",
            ),
            git_snapshot=lambda t: self.per_target.get(t, self.snapshot),
            git_branch=self.git_branch,
            judge=self.judge,
            notify=self.notify,
            sleep=self.sleep,
            monotonic=lambda: self.clock,
            now=lambda: self.wall + datetime.timedelta(seconds=self.clock),
            pid_alive=lambda pid: self.alive,
            getpid=lambda: 4242,
            projects_root=self.projects_root,
        )

    def run(self, **kwargs) -> runner.RunResult:
        options = {"interval": 10, "max_duration": 3600}
        options.update(kwargs)
        return runner.run(self.state_path, kit_root=self.kit, deps=self.deps(), **options)

    # -- reading ---------------------------------------------------------------

    def doc(self) -> st.StateDoc:
        return st.read_state(self.state_path)

    def states(self) -> dict[int, str]:
        return {a.nn: a.state for a in self.doc().assignments}

    def checkpoint(self) -> str:
        path = self.task_dir / "checkpoint.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def ledger(self) -> list[dict]:
        path = self.task_dir / runner.JUDGE_LEDGER
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class ChainTests(unittest.TestCase):
    def test_happy_chain_writer_review_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            result = w.run()
            self.assertEqual((result.outcome, result.reason), ("done", ""))
            self.assertEqual(result.created, [1, 2])
            doc = w.doc()
            self.assertEqual([(a.edge, a.state) for a in doc.assignments], [("inicia", "accepted"), ("revisa", "accepted")])
            for a in doc.assignments:
                self.assertEqual(a.events[0].by, "marina-run")
                self.assertEqual(a.allowlist, [f"Bash(test -d {w.target})"])
            self.assertTrue((w.task_dir / "git-after-01.txt").exists())
            self.assertFalse((w.task_dir / "git-after-02.txt").exists())
            checkpoint = w.checkpoint()
            self.assertIn("## Execução marina-run", checkpoint)
            self.assertIn("Motivo de parada: done.", checkpoint)
            self.assertIn("nn=01 node-backend inicia", checkpoint)
            self.assertFalse((w.task_dir / runner.LOCK_NAME).exists())

    def test_turn_ended_as_working_idle_is_finished(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            original = w.sleep

            def end_as_working_idle(seconds):
                original(seconds)
                for session in w.sessions.values():
                    if session.get("state") == "done":
                        session.update(state="working", status="idle")

            w.sleep = end_as_working_idle
            result = w.run(max_duration=300)
            self.assertEqual((result.outcome, result.created), ("done", [1, 2]))

    def test_idle_right_after_launch_is_not_finished(self):
        # F6 acceptance A3: a session listed as working/idle 0.3 s after launch
        # was recorded as finished and stopped the chain with receipt_missing.
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            w.initial_session = {"state": "working", "status": "idle"}
            original = w.sleep

            def start_then_finish(seconds):
                for session in w.sessions.values():
                    if session.get("status") == "idle" and session.get("state") == "working":
                        session.update(status="busy")
                original(seconds)

            w.sleep = start_then_finish
            result = w.run(max_duration=300)
            self.assertEqual((result.outcome, result.created), ("done", [1, 2]))

    def test_session_idle_since_launch_stops_after_grace(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.initial_session = {"state": "blocked", "status": "idle"}
            w.auto_finish = False
            result = w.run(max_duration=3600)
            self.assertEqual((result.outcome, result.reason), ("stop", "receipt_missing"))
            self.assertGreaterEqual(w.clock, status_claude.LAUNCH_IDLE_GRACE.total_seconds())
            self.assertLess(w.clock, 3600)

    def test_children_stdin_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            w.run()
            self.assertEqual(len(w.launch_calls), 2)
            for _, kwargs in w.launch_calls:
                self.assertIs(kwargs["stdin"], subprocess.DEVNULL)

    def test_fail_then_correction_then_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "FAIL", 4: "PASS"})
            result = w.run()
            self.assertEqual((result.outcome, result.created), ("done", [1, 2, 3, 4]))
            self.assertEqual([a.edge for a in w.doc().assignments], ["inicia", "revisa", "corrige", "revisa"])
            handoff = (w.task_dir / "03-node-backend-handoff.md").read_text(encoding="utf-8")
            self.assertIn(str(w.task_dir / "02-reviewer-receipt.md"), handoff)

    def test_second_fail_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "FAIL", 4: "FAIL"})
            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "second_fail", [1, 2, 3, 4]))
            self.assertIn("Motivo de parada: stop(second_fail).", w.checkpoint())

    def test_two_stage_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={2: "PASS", 4: "PASS"})
            result = w.run()
            self.assertEqual((result.outcome, result.created), ("done", [1, 2, 3, 4]))
            self.assertEqual(w.doc().get_assignment(3).edge, "prossegue")
            self.assertIn("Implement stage 2.", (w.task_dir / "03-node-backend-handoff.md").read_text(encoding="utf-8"))


class JudgeTests(unittest.TestCase):
    def test_pass_with_risks_judge_continue_opens_next_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={2: "PASS_WITH_RISKS", 4: "PASS"})
            result = w.run()
            self.assertEqual((result.outcome, result.created), ("done", [1, 2, 3, 4]))
            reserved = w.doc().get_assignment(3).events[0]
            self.assertEqual(reserved.by, "marina-judge")
            self.assertIn("continue", reserved.note)
            self.assertEqual(len(w.ledger()), 1)
            self.assertTrue(w.ledger()[0]["ok"])
            question, paths = w.judge_calls[0]
            self.assertEqual((question.kind, question.nn), ("pass_with_risks", 2))
            self.assertIn(str(w.task_dir / "02-reviewer-receipt.md"), paths)
            self.assertIn("pass_with_risks → continue", w.checkpoint())

    def test_judge_failure_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={2: "PASS_WITH_RISKS"})
            w.judge_result = JudgeFailed("no structured_output")
            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "judge_failed", [1, 2]))
            self.assertEqual([entry["ok"] for entry in w.ledger()], [False])

    def test_judge_stop_answer_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={2: "PASS_WITH_RISKS"})
            w.judge_result = JudgeAnswer("stop", "needs a human")
            self.assertEqual(w.run().reason, "judge_stop")

    def test_judge_quota_counts_previous_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={2: "PASS_WITH_RISKS"}, judge_max_calls=1)
            (w.task_dir / runner.JUDGE_LEDGER).write_text(
                json.dumps({"nn": 99, "kind": "pass_with_risks", "options": ["continue", "stop"],
                            "decision": "stop", "reason": "older run", "ok": True}) + "\n",
                encoding="utf-8",
            )
            result = w.run()
            self.assertEqual((result.outcome, result.reason), ("stop", "judge_failed"))
            self.assertEqual(w.judge_calls, [])

    def test_ledger_answer_is_reused_on_resume(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={2: "PASS_WITH_RISKS", 4: "PASS"}, judge_max_calls=1)
            w.judge_result = JudgeFailed("must not be called twice")
            # First run stops right after the judge would be asked: simulate by a prior ledger answer.
            (w.task_dir / runner.JUDGE_LEDGER).write_text(
                json.dumps({"nn": 2, "kind": "pass_with_risks", "options": ["continue", "stop"],
                            "decision": "continue", "reason": "earlier run", "ok": True}) + "\n",
                encoding="utf-8",
            )
            result = w.run()
            self.assertEqual((result.outcome, result.created), ("done", [1, 2, 3, 4]))
            self.assertEqual(w.judge_calls, [])
            self.assertEqual(w.doc().get_assignment(3).events[0].by, "marina-judge")


class SafetyTests(unittest.TestCase):
    def test_restart_with_reserved_node_stops_without_new_node(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            doc = w.doc()
            st.add_assignment(doc, role=ROLE, type_="implementação", edge="inicia", predecessor=0,
                              targets=[str(w.target)], allowlist=[f"Bash(test -d {w.target})"], by="marina-run", at=AT)
            st.write_state(w.state_path, doc)
            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "node_not_launched", []))
            self.assertEqual(list(w.states()), [1])
            self.assertEqual(w.launch_calls, [])

    def test_live_lock_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            (w.task_dir / runner.LOCK_NAME).write_text(json.dumps({"pid": 777, "started_at": "x"}), encoding="utf-8")
            w.alive = True
            with self.assertRaises(runner.RunRefused):
                w.run()
            with self.assertRaises(runner.RunRefused):
                w.run(recover=True)
            self.assertTrue((w.task_dir / runner.LOCK_NAME).exists())
            self.assertEqual(w.states(), {})

    def test_recover_dead_lock_with_working_session_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            (w.task_dir / runner.LOCK_NAME).write_text(json.dumps({"pid": 777, "started_at": "x"}), encoding="utf-8")
            w.sessions["abcdef01"] = {"id": "abcdef01", "name": "t1 — node-backend — 01 — implementação",
                                      "cwd": str(w.kit), "kind": "background", "state": "working", "status": "busy"}
            with self.assertRaisesRegex(runner.RunRefused, "working"):
                w.run(recover=True)

    def test_recover_dead_lock_takes_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            (w.task_dir / runner.LOCK_NAME).write_text(json.dumps({"pid": 777, "started_at": "x"}), encoding="utf-8")
            self.assertEqual(w.run(recover=True).outcome, "done")
            self.assertFalse((w.task_dir / runner.LOCK_NAME).exists())

    def test_foreign_change_before_next_writer_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "FAIL"})
            w.after_receipt[2] = lambda: setattr(w, "snapshot", "dirty\n")
            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "foreign_change", [1, 2]))

    def test_git_after_covers_every_envelope_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, second_target=True, verdicts={2: "PASS"})
            w.per_target = {str(w.target): "a\n", str(w.target2): "b\n"}
            result = w.run()
            self.assertEqual(result.outcome, "done", result.reason)
            self.assertEqual(w.doc().get_assignment(1).targets, [str(w.target)])
            self.assertEqual((w.task_dir / "git-after-01.txt").read_text(encoding="utf-8"), "a\nb\n")

    def test_foreign_change_in_other_stage_target_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, second_target=True, verdicts={2: "PASS"})
            w.after_receipt[2] = lambda: w.per_target.__setitem__(str(w.target2), "dirty\n")
            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "foreign_change", [1, 2]))

    def test_second_stage_opens_with_its_own_scope(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, second_target=True, verdicts={2: "PASS", 4: "PASS"})
            self.assertEqual(w.run().outcome, "done")
            third = w.doc().get_assignment(3)
            self.assertEqual((third.edge, third.targets, third.allowlist),
                             ("prossegue", [str(w.target2)], [f"Bash(test -d {w.target2})"]))

    def test_template_edited_mid_run_stops_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            w.after_receipt[1] = lambda: (w.task_dir / "stage-1-handoff-template.md").write_text(
                TEMPLATE.format(n="edited"), encoding="utf-8")
            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "envelope_changed", [1]))
            self.assertEqual(len(w.launch_calls), 1)

    def test_branch_changed_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            w.after_receipt[1] = lambda: setattr(w, "branch", "main")
            self.assertEqual(w.run().reason, "envelope_changed")

    def test_stop_file_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            w.after_receipt[1] = lambda: self.assertTrue(runner.request_stop(w.state_path))
            result = w.run()
            self.assertEqual((result.outcome, result.reason), ("stop", "stop_requested"))
            self.assertFalse((w.task_dir / runner.STOP_NAME).exists())

    def test_max_duration_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.auto_finish = False
            result = w.run(max_duration=25)
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "max_duration", [1]))

    def test_waiting_approval_notifies_once_and_never_answers(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.auto_finish = False
            w.initial_session = {"state": "working", "status": "waiting", "waitingFor": "permission prompt"}
            result = w.run(max_duration=45, notify_cmd="notify-send marina")
            self.assertEqual(result.reason, "max_duration")
            self.assertEqual(w.notified, ["notify-send marina"])
            self.assertEqual(w.doc().get_assignment(1).state, "waiting_approval")
            for argv, _ in w.launch_calls:
                self.assertNotIn("attach", argv)

    def test_internal_error_stops_and_logs_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.git_branch_error = RuntimeError("git exploded")
            result = w.run()
            self.assertEqual((result.outcome, result.reason), ("stop", "internal_error"))
            log = (w.task_dir / runner.LOG_NAME).read_text(encoding="utf-8")
            self.assertIn("Traceback", log)
            self.assertIn("git exploded", log)
            self.assertIn("stop(internal_error)", w.checkpoint())
            self.assertFalse((w.task_dir / runner.LOCK_NAME).exists())

    def test_keyboard_interrupt_records_stop_and_releases_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.auto_finish = False

            def interrupted(seconds):
                raise KeyboardInterrupt

            w.sleep = interrupted
            result = w.run()
            self.assertEqual((result.outcome, result.reason), ("stop", "interrupted"))
            self.assertIn("stop(interrupted)", w.checkpoint())
            self.assertFalse((w.task_dir / runner.LOCK_NAME).exists())

    def test_default_deps_run_children_from_kit_root(self):
        deps = runner.default_deps(Path("/kit/root"))
        self.assertEqual(deps.run_subprocess.keywords.get("cwd"), "/kit/root")
        calls = []
        with unittest.mock.patch.object(runner.judge, "ask", lambda q, p, **kw: calls.append(kw)):
            deps.judge(None, ["/a"])
        self.assertEqual(calls[0]["cwd"], "/kit/root")

    def test_invalid_interval_or_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            for kwargs in ({"interval": 0}, {"max_duration": 0}):
                with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                    w.run(**kwargs)
            self.assertFalse((w.task_dir / runner.LOCK_NAME).exists())


class ReplacementTests(unittest.TestCase):
    """F6 A4 part 1: `marina run` resumes after Marina opens a `substitui` by hand."""

    @staticmethod
    def _lose_receipt(w: World, nn: int) -> None:
        w.after_receipt[nn] = lambda: (w.kit / w.doc().get_assignment(nn).receipt).unlink()

    @staticmethod
    def _replace(w: World, nn: int, *, verdict: str = "") -> int:
        """Marina opens and launches a `substitui` by hand; the run observes it from `launched`."""

        doc = w.doc()
        original = doc.get_assignment(nn)
        at = AT + datetime.timedelta(seconds=w.clock)
        a = st.add_assignment(doc, role=original.role, type_=original.type, edge="substitui", predecessor=nn,
                              targets=original.targets, allowlist=original.allowlist, by="marina", at=at)
        for to in ("prepared", "launched"):
            st.set_state(doc, a.nn, to, by="marina", at=at)
        a.native.id = f"{a.nn:08x}"
        st.write_state(w.state_path, doc)
        if a.role == "reviewer":
            writer_text = (w.kit / st.reviewed_writer(doc, a).handoff).read_text(encoding="utf-8")
            text = handoff_gen.render_review_handoff(doc, a, kit_root=w.kit, writer_handoff_text=writer_text)
        else:
            template = (w.task_dir / "stage-1-handoff-template.md").read_text(encoding="utf-8")
            text = handoff_gen.render_stage_handoff(doc, a, kit_root=w.kit, template_text=template)
        (w.kit / a.handoff).write_text(text, encoding="utf-8")
        w.sessions[a.native.id] = {"id": a.native.id, "name": a.title, "cwd": str(w.kit), "kind": "background",
                                   "state": "working", "status": "busy"}
        if verdict:
            w.verdicts[a.nn] = verdict
        return a.nn

    def test_replaced_reviewer_is_judged_against_the_reviewed_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={5: "PASS"})
            self._lose_receipt(w, 2)
            first = w.run()
            self.assertEqual((first.outcome, first.reason, first.created), ("stop", "receipt_missing", [1, 2]))
            self.assertEqual(self._replace(w, 2, verdict="PASS_WITH_RISKS"), 3)
            second = w.run()
            self.assertEqual((second.outcome, second.created), ("done", [4, 5]))
            question, paths = w.judge_calls[0]
            self.assertEqual(question.nn, 3)
            self.assertIn(str(w.task_dir / f"01-{ROLE}-receipt.md"), paths)
            self.assertNotIn(str(w.task_dir / "02-reviewer-receipt.md"), paths)
            self.assertEqual(w.doc().get_assignment(4).predecessor, 1)

    def test_replaced_writer_is_the_stage_writer_for_the_git_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={3: "PASS", 5: "PASS"})
            self._lose_receipt(w, 1)
            first = w.run()
            self.assertEqual((first.outcome, first.reason, first.created), ("stop", "receipt_missing", [1]))
            self.assertEqual(self._replace(w, 1), 2)
            second = w.run()
            self.assertEqual((second.outcome, second.created), ("done", [3, 4, 5]))
            self.assertTrue((w.task_dir / "git-after-02.txt").exists())
            self.assertEqual([w.doc().get_assignment(n).predecessor for n in (3, 4)], [2, 2])

    def test_foreign_change_after_a_replaced_writer_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={3: "PASS"})
            self._lose_receipt(w, 1)
            w.run()
            self._replace(w, 1)
            w.after_receipt[3] = lambda: setattr(w, "snapshot", "dirty\n")
            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", "foreign_change", [3]))


class PreEnvelopePrefixTests(unittest.TestCase):
    """F2 (analisa-pre-envelope review): the agenda/task-8528 shape, an accepted
    `architect analisa` (predecessor 0) run by hand before the envelope."""

    def test_accepted_analisa_prefix_then_run_opens_stage_one_inicia(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={3: "PASS"})
            doc = w.doc()
            a = st.add_assignment(doc, role="architect", type_="análise", edge="analisa", predecessor=0,
                                  targets=[str(w.target)], allowlist=[f"Bash(test -d {w.target})"],
                                  by="marina", at=AT)
            for to in ("prepared", "launched", "working", "finished", "receipt_received", "receipt_validated"):
                st.set_state(doc, a.nn, to, by="marina", at=AT)
                if to == "receipt_validated":
                    a.receipt_summary = st.ReceiptSummary(status="done", verdict="", profile_ok=True)
            st.set_state(doc, a.nn, "accepted", by="marina", at=AT)
            st.write_state(w.state_path, doc)

            result = w.run()
            self.assertEqual((result.outcome, result.reason, result.created), ("done", "", [2, 3]))
            first_launch = w.launch_calls[0][0]
            self.assertIn(f"t1 — {ROLE} — 02 — implementação", first_launch[first_launch.index("--name") + 1])
            opened = w.doc().get_assignment(2)
            self.assertEqual((opened.role, opened.edge, opened.predecessor), (ROLE, "inicia", 0))
            self.assertEqual(w.doc().get_assignment(1).state, "accepted")
            self.assertIn("Implement stage 1.", (w.kit / opened.handoff).read_text(encoding="utf-8"))


class PreviewTests(unittest.TestCase):
    def _files(self, w: World) -> dict[str, bytes]:
        return {p.name: p.read_bytes() for p in w.task_dir.iterdir()}

    def test_preview_empty_graph_is_launch_stage_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            d = runner.preview_decision(w.state_path, kit_root=w.kit, deps=w.deps())
            self.assertEqual((d.kind, d.node.edge, d.node.stage), ("launch", "inicia", 1))

    def test_preview_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.auto_finish = False
            w.run(max_duration=15)
            w.sessions[next(iter(w.sessions))].update(state="done", status="idle")
            before = self._files(w)
            d = runner.preview_decision(w.state_path, kit_root=w.kit, deps=w.deps())
            self.assertEqual(d.kind, "wait")
            self.assertEqual(self._files(w), before)
            self.assertFalse((w.task_dir / "git-after-01.txt").exists())

    def test_preview_returns_ask_judge_without_calling_judge(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, stages=2, verdicts={2: "PASS_WITH_RISKS"})
            w.judge_result = JudgeFailed("stop here")
            w.run()
            (w.task_dir / runner.JUDGE_LEDGER).unlink()
            calls_before = len(w.judge_calls)
            d = runner.preview_decision(w.state_path, kit_root=w.kit, deps=w.deps())
            self.assertEqual((d.kind, d.question.kind, d.question.nn), ("ask_judge", "pass_with_risks", 2))
            self.assertEqual(len(w.judge_calls), calls_before)

    def test_decision_to_dict_is_json_serializable(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            launch = runner.decision_to_dict(runner.preview_decision(w.state_path, kit_root=w.kit, deps=w.deps()))
            self.assertEqual(launch["node"]["role"], ROLE)
            json.dumps(launch)
            ask = runner.decision_to_dict(runner.Decision(
                "ask_judge", question=runner.Question("pass_with_risks", 2, ("continue", "stop"))))
            self.assertEqual(json.loads(json.dumps(ask))["question"]["options"], ["continue", "stop"])


class HelperTests(unittest.TestCase):
    def test_request_stop_without_lock_returns_false(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            self.assertFalse(runner.request_stop(w.state_path))
            self.assertFalse((w.task_dir / runner.STOP_NAME).exists())

    def test_status_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp, verdicts={2: "PASS"})
            w.run()
            lines = "\n".join(runner.status_lines(w.state_path, pid_alive=lambda pid: False))
            for fragment in ("task: t1", "lock: none", "envelope: approved", "01 node-backend inicia accepted",
                             "02 reviewer revisa accepted", "done"):
                self.assertIn(fragment, lines)


if __name__ == "__main__":
    unittest.main()


class LockHelperTests(unittest.TestCase):
    def test_live_lock_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            task_dir = Path(tmp)
            self.assertIsNone(runner.live_lock_pid(task_dir, pid_alive=lambda pid: True))
            (task_dir / runner.LOCK_NAME).write_text(json.dumps({"pid": 77, "started_at": "x"}), encoding="utf-8")
            self.assertEqual(runner.live_lock_pid(task_dir, pid_alive=lambda pid: True), 77)
            self.assertIsNone(runner.live_lock_pid(task_dir, pid_alive=lambda pid: False))
            (task_dir / runner.LOCK_NAME).write_text("garbage", encoding="utf-8")
            self.assertIsNone(runner.live_lock_pid(task_dir, pid_alive=lambda pid: True))

    def test_run_argv(self):
        argv = runner.run_argv(Path("/kit"), "demo", "t1", interval=30, max_duration="2h", notify_cmd=None)
        self.assertEqual(argv[1:], ["/kit/scripts/marina/__main__.py", "run", "demo", "t1", "--interval", "30",
                                    "--max-duration", "2h", "--kit-root", "/kit"])


SID = "0123abcd-0123-4567-89ab-0123456789ab"
TRANSCRIPTS = Path(__file__).resolve().parent / "fixtures" / "transcripts"
LIMIT_REASON = "usage_limit: nn=01 resets 7:50pm (America/Sao_Paulo)"


class UsageLimitRunTests(unittest.TestCase):
    """limite-uso stage 1: a session that ends on the usage limit stops the run with the reason."""

    def _world(self, tmp: str, *, transcript: str | None = "limit-then-system.jsonl", receipt: str | None = None,
               with_session_id: bool = True) -> World:
        w = World(tmp)
        w.auto_finish = False
        w.initial_session = {"state": "working", "status": "busy"}
        if with_session_id:
            w.initial_session["sessionId"] = SID

        def end_on_limit(seconds):
            w.clock += seconds
            for session in w.sessions.values():
                if session.get("state") == "working":
                    session.update(state="done", status="idle")
                    if transcript:
                        folder = w.projects_root / "-kit"
                        folder.mkdir(parents=True, exist_ok=True)
                        shutil.copy(TRANSCRIPTS / transcript, folder / f"{SID}.jsonl")
                    if receipt is not None:
                        a = w.doc().get_assignment(int(session["name"].split(" — ")[2]))
                        (w.kit / a.receipt).write_text(receipt, encoding="utf-8")

        w.sleep = end_on_limit
        return w

    def _assert_sanitized(self, w: World) -> None:
        for text in (w.state_path.read_text(encoding="utf-8"), w.checkpoint(),
                     (w.task_dir / runner.LOG_NAME).read_text(encoding="utf-8"), json.dumps(w.notify_events)):
            self.assertNotIn("You've hit", text)
            self.assertNotIn("isApiErrorMessage", text)

    def test_receipt_missing_with_limit_stops_with_usage_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            result = w.run(notify_cmd="notify-send marina")
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", LIMIT_REASON, [1]))
            a = w.doc().get_assignment(1)
            self.assertEqual(a.state, "receipt_missing")
            self.assertEqual(a.events[-1].note,
                             'usage_limit resets_at=2026-11-12T22:50:00+00:00 text="7:50pm (America/Sao_Paulo)"')
            self.assertEqual(a.events[-1].by, "marina-run")
            self.assertIn(f"Motivo de parada: stop({LIMIT_REASON}).", w.checkpoint())
            self.assertEqual(w.notify_events, [{"event": "usage_limit_stop", "task": "t1", "nn": 1,
                                                "reason": LIMIT_REASON}])
            self._assert_sanitized(w)

    def test_manual_replacement_after_the_limit_is_in_the_envelope(self):
        from scripts.marina import decide as decide_mod

        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            w.run()
            doc = w.doc()
            st.add_assignment(doc, role=ROLE, type_="implementação", edge="substitui", predecessor=1,
                              targets=[str(w.target)], allowlist=[f"Bash(test -d {w.target})"], by="marina", at=AT)
            self.assertEqual(decide_mod.graph_errors(doc, env_mod.envelope_from_doc(doc)), [])

    def test_receipt_invalid_cites_the_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp, receipt="# partial receipt\n")
            result = w.run()
            self.assertEqual((result.outcome, result.reason), ("stop", LIMIT_REASON))
            a = w.doc().get_assignment(1)
            self.assertEqual(a.state, "receipt_invalid")
            first_error, _, note = a.events[-1].note.partition("; ")
            self.assertTrue(first_error)
            self.assertTrue(note.startswith("usage_limit resets_at=2026-11-12T22:50:00+00:00"), note)
            self._assert_sanitized(w)

    def test_without_transcript_the_reason_is_unchanged(self):
        for transcript, with_sid in ((None, True), ("limit-then-normal.jsonl", True),
                                     ("other-api-error.jsonl", True), ("limit-then-system.jsonl", False)):
            with self.subTest(transcript=transcript, with_sid=with_sid), tempfile.TemporaryDirectory() as tmp:
                w = self._world(tmp, transcript=transcript, with_session_id=with_sid)
                result = w.run(notify_cmd="notify-send marina")
                self.assertEqual((result.outcome, result.reason), ("stop", "receipt_missing"))
                self.assertEqual(w.doc().get_assignment(1).events[-1].note, "")
                self.assertEqual(w.notify_events, [])

    def test_unavailable_manager_after_restart_keeps_the_reason(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            doc = w.doc()
            a = st.add_assignment(doc, role=ROLE, type_="implementação", edge="inicia", predecessor=0,
                                  targets=[str(w.target)], allowlist=[f"Bash(test -d {w.target})"],
                                  by="marina-run", at=AT)
            a.native.id = "00000001"
            for to in ("prepared", "launched", "working", "finished"):
                st.append_event(a, to, by="test", at=AT)
            st.write_state(w.state_path, doc)

            def unavailable():
                raise runner.common.ManagerUnavailable("down")

            deps = w.deps()
            deps.list_sessions = unavailable
            result = runner.run(w.state_path, kit_root=w.kit, deps=deps, interval=10, max_duration=3600)
            self.assertEqual(result.reason, "receipt_missing")

    def test_notifier_failure_does_not_prevent_the_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            w.notify_error = RuntimeError("no notifier")
            result = w.run(notify_cmd="notify-send marina")
            self.assertEqual(result.reason, LIMIT_REASON)
            self.assertIn("notify failed: no notifier", (w.task_dir / runner.LOG_NAME).read_text(encoding="utf-8"))

    def test_waiting_approval_notifies_with_its_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.auto_finish = False
            w.initial_session = {"state": "working", "status": "waiting", "waitingFor": "permission prompt"}
            w.run(max_duration=45, notify_cmd="notify-send marina")
            self.assertEqual(w.notify_events, [{"event": "waiting_approval", "task": "t1", "nn": 1,
                                                "reason": "waiting_approval"}])

    def test_waiting_approval_notifier_failure_keeps_running(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = World(tmp)
            w.auto_finish = False
            w.notify_error = RuntimeError("no notifier")
            w.initial_session = {"state": "working", "status": "waiting", "waitingFor": "permission prompt"}
            self.assertEqual(w.run(max_duration=45, notify_cmd="notify-send marina").reason, "max_duration")


class NotifyEnvTests(unittest.TestCase):
    def test_enumerated_and_sanitized(self):
        env = runner.notify_env({"event": "usage_limit_stop", "task": "t1", "nn": 9,
                                 "reason": "usage_limit: nn=09\x1b[31m resets\n" + "x" * 300, "secret": "no"})
        self.assertEqual(set(env), {"MARINA_EVENT", "MARINA_TASK", "MARINA_NN", "MARINA_REASON"})
        self.assertEqual((env["MARINA_EVENT"], env["MARINA_TASK"], env["MARINA_NN"]), ("usage_limit_stop", "t1", "09"))
        self.assertEqual(len(env["MARINA_REASON"]), runner.NOTIFY_REASON_MAX)
        self.assertTrue(all(ch.isprintable() for ch in env["MARINA_REASON"]))
        self.assertEqual(runner.notify_env({"event": "waiting_approval", "nn": None})["MARINA_NN"], "")

    def test_child_gets_the_variables_and_closed_stdin(self):
        with unittest.mock.patch.object(runner.subprocess, "run") as run:
            runner._run_notify("notify-send 'marina run'", {"event": "waiting_approval", "task": "t1", "nn": 2,
                                                             "reason": "waiting_approval"})
        argv, kwargs = run.call_args.args[0], run.call_args.kwargs
        self.assertEqual(argv, ["notify-send", "marina run"])
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertEqual((kwargs["env"]["MARINA_EVENT"], kwargs["env"]["MARINA_NN"]), ("waiting_approval", "02"))


RESETS = datetime.datetime(2026, 11, 12, 22, 50, tzinfo=datetime.timezone.utc)
READY = RESETS + datetime.timedelta(seconds=300)
WAIT_LINE = "usage_limit wait nn=01 until 2026-11-12T22:55:00+00:00"


class UsageLimitWaitRunTests(unittest.TestCase):
    """limite-uso stage 2: with `on_usage_limit = "wait"` the run waits for the reset and reopens the node once."""

    def _world(self, tmp: str, *, limited=(1,), stages: int = 1, verdicts: dict | None = None,
               on_usage_limit: str | None = "wait") -> World:
        w = World(tmp, stages=stages, verdicts=verdicts if verdicts is not None else {3: "PASS"},
                  on_usage_limit=on_usage_limit)
        w.wall = RESETS - datetime.timedelta(hours=1)
        w.initial_session = {"state": "working", "status": "busy", "sessionId": SID}
        w.launched_at = {}
        w.on_sleep = []
        launch = w.launch

        def timed_launch(argv, **kwargs):
            nn = int(argv[argv.index("--name") + 1].split(" — ")[2])
            w.launched_at[nn] = w.wall + datetime.timedelta(seconds=w.clock)
            return launch(argv, **kwargs)

        def sleep(seconds):
            w.clock += seconds
            for session in w.sessions.values():
                if session.get("state") != "working":
                    continue
                session.update(state="done", status="idle")
                nn = int(session["name"].split(" — ")[2])
                if nn in limited:
                    folder = w.projects_root / "-kit"
                    folder.mkdir(parents=True, exist_ok=True)
                    shutil.copy(TRANSCRIPTS / "limit-then-system.jsonl", folder / f"{SID}.jsonl")
                else:
                    w.write_receipt(nn)
                hook = w.after_receipt.get(nn)
                if hook:
                    hook()
            for hook in w.on_sleep:
                hook()

        w.launch = timed_launch
        w.sleep = sleep
        return w

    @staticmethod
    def _log(w: World) -> list[str]:
        return (w.task_dir / runner.LOG_NAME).read_text(encoding="utf-8").splitlines()

    def _count(self, w: World, fragment: str) -> int:
        return sum(1 for line in self._log(w) if fragment in line)

    def test_waits_for_the_reset_then_opens_exactly_one_substitui(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            result = w.run(interval=60, max_duration=4 * 3600, notify_cmd="notify-send marina")
            self.assertEqual((result.outcome, result.reason, result.created), ("done", "", [1, 2, 3]))
            doc = w.doc()
            original, sub = doc.get_assignment(1), doc.get_assignment(2)
            self.assertEqual(original.state, "receipt_missing")
            self.assertEqual((sub.role, sub.type, sub.edge, sub.predecessor, sub.targets, sub.allowlist),
                             (original.role, original.type, "substitui", 1, original.targets, original.allowlist))
            self.assertEqual(sub.state, "accepted")
            reserved = sub.events[0]
            self.assertEqual(reserved.by, "marina-run")
            self.assertTrue(reserved.note.startswith(
                "usage_limit: substitui nn=01; resets_at=2026-11-12T22:50:00+00:00; esperou "), reserved.note)
            # Nothing opens before resets_at + 300 s, and the reopening comes at the first iteration after it.
            self.assertGreaterEqual(w.launched_at[2], READY)
            self.assertLess(w.launched_at[2], READY + datetime.timedelta(seconds=60))
            self.assertEqual(len(w.launch_calls), 3)
            # The generated handoff, preflight and launch ran for the replacement.
            handoff = (w.kit / sub.handoff).read_text(encoding="utf-8")
            self.assertIn("Substitui o nn=01 (node-backend, inicia)", handoff)
            self.assertIn(str(w.task_dir / "git-after-01.txt"), handoff)
            self.assertTrue((w.task_dir / "git-before-02.txt").exists())
            self.assertEqual(sub.native.id, f"{2:08x}")
            review = (w.kit / doc.get_assignment(3).handoff).read_text(encoding="utf-8")
            self.assertIn(f"Target state before the writer: `{w.task_dir / 'git-before-01.txt'}`", review)
            # Audit: log (one line each), checkpoint and notify.
            self.assertEqual(self._count(w, WAIT_LINE), 1)
            self.assertEqual(self._count(w, "usage_limit resume nn=01 → nn=02"), 1)
            self.assertIn("- Reaberturas por limite de uso: nn=01→nn=02 (resets_at 2026-11-12T22:50:00+00:00).",
                          w.checkpoint())
            self.assertEqual(w.notify_events, [
                {"event": "usage_limit_wait", "task": "t1", "nn": 1,
                 "reason": "usage_limit until 2026-11-12T22:55:00+00:00"},
                {"event": "usage_limit_resume", "task": "t1", "nn": 2, "reason": "usage_limit resume nn=01 → nn=02"},
            ])

    def test_without_the_key_the_run_still_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp, on_usage_limit=None)
            result = w.run(interval=60, max_duration=4 * 3600)
            self.assertEqual((result.outcome, result.reason, result.created), ("stop", LIMIT_REASON, [1]))
            self.assertNotIn("Reaberturas", w.checkpoint())

    def test_reset_after_the_deadline_stops_at_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            result = w.run(interval=60, max_duration=1800, notify_cmd="notify-send marina")
            self.assertEqual((result.outcome, result.reason, result.created),
                             ("stop", f"{LIMIT_REASON} (after max_duration)", [1]))
            self.assertLess(w.clock, 300)
            self.assertEqual([e["event"] for e in w.notify_events], ["usage_limit_stop"])

    def test_replacement_on_the_limit_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp, limited=(1, 2))
            result = w.run(interval=60, max_duration=4 * 3600)
            self.assertEqual((result.outcome, result.reason, result.created),
                             ("stop", "usage_limit: nn=02 resets 7:50pm (America/Sao_Paulo) (replacement)", [1, 2]))

    def test_max_reopens_is_counted_from_the_state_after_a_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp, limited=(1, 3, 5), stages=2, verdicts={4: "PASS"})
            w.after_receipt[5] = lambda: runner.request_stop(w.state_path)
            first = w.run(interval=60, max_duration=4 * 3600)
            self.assertEqual((first.reason, first.created), ("stop_requested", [1, 2, 3, 4, 5]))
            doc = w.doc()
            self.assertEqual([(a.edge, a.role) for a in doc.assignments],
                             [("inicia", ROLE), ("substitui", ROLE), ("revisa", "reviewer"),
                              ("substitui", "reviewer"), ("prossegue", ROLE)])
            self.assertEqual(doc.get_assignment(4).events[0].by, "marina-run")
            second = w.run(interval=60, max_duration=4 * 3600)
            self.assertEqual((second.outcome, second.reason, second.created),
                             ("stop", "usage_limit: nn=05 resets 7:50pm (America/Sao_Paulo) (max reopens)", []))

    def test_unparsed_reset_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            doc = w.doc()
            a = st.add_assignment(doc, role=ROLE, type_="implementação", edge="inicia", predecessor=0,
                                  targets=[str(w.target)], allowlist=[f"Bash(test -d {w.target})"],
                                  by="marina-run", at=w.wall)
            for to in ("prepared", "launched", "working", "finished", "receipt_missing"):
                note = usage_limit.note_for(usage_limit.UsageLimit("soon", None)) if to == "receipt_missing" else ""
                st.append_event(a, to, by="marina-run", note=note, at=w.wall)
            st.write_state(w.state_path, doc)
            result = w.run(interval=60, max_duration=4 * 3600)
            self.assertEqual((result.reason, result.created), ("usage_limit: nn=01 resets soon (unparsed)", []))

    def _during_wait(self, w: World, action) -> None:
        """Run `action` once, at the first sleep after the wait began."""

        done = []

        def hook():
            if not done and any(WAIT_LINE in line for line in self._log(w)):
                done.append(True)
                action()

        w.on_sleep.append(hook)

    def test_git_gate_compares_with_the_replaced_writers_git_after(self):
        def dirty(w):
            w.snapshot = "dirty\n"

        def missing(w):
            (w.task_dir / "git-after-01.txt").unlink()

        for action, reason in ((dirty, "foreign_change"), (missing, "git_after_missing")):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                w = self._world(tmp)
                self._during_wait(w, functools.partial(action, w))
                result = w.run(interval=60, max_duration=4 * 3600)
                self.assertEqual((result.outcome, result.reason, result.created), ("stop", reason, [1]))
                self.assertEqual(len(w.launch_calls), 1)

    def test_partial_work_left_by_the_writer_is_its_git_after(self):
        # The interrupted writer changed the target; that state is git-after-01, so the gate opens.
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            w.after_receipt[1] = lambda: setattr(w, "snapshot", "partial\n")
            result = w.run(interval=60, max_duration=4 * 3600)
            self.assertEqual((result.outcome, result.created), ("done", [1, 2, 3]))
            self.assertEqual((w.task_dir / "git-after-01.txt").read_text(encoding="utf-8"), "partial\n")

    def test_stop_during_the_wait_then_recover_from_the_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = self._world(tmp)
            self._during_wait(w, lambda: runner.request_stop(w.state_path))
            first = w.run(interval=60, max_duration=4 * 3600)
            self.assertEqual((first.outcome, first.reason, first.created), ("stop", "stop_requested", [1]))
            self.assertEqual(len(w.launch_calls), 1)
            # The process dies during a later wait: an orphan lock is left behind.
            w.on_sleep.clear()
            (w.task_dir / runner.LOCK_NAME).write_text(json.dumps({"pid": 777, "started_at": "x"}), encoding="utf-8")
            with self.assertRaises(runner.RunRefused):
                w.run(interval=60, max_duration=4 * 3600)
            second = w.run(interval=60, max_duration=4 * 3600, recover=True)
            self.assertEqual((second.outcome, second.created), ("done", [2, 3]))
            self.assertEqual(self._count(w, WAIT_LINE), 2)
            self.assertEqual(self._count(w, "usage_limit resume nn=01 → nn=02"), 1)
            self.assertGreaterEqual(w.launched_at[2], READY)
