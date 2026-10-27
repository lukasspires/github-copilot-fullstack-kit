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
from scripts.marina import handoff_gen, runner
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
                 on_pass_with_risks: str = "judge", judge_max_calls: int = 1, max_corrections: int = 1):
        self.kit = Path(tmp) / "kit"
        agents = self.kit / ".claude" / "agents"
        agents.mkdir(parents=True)
        for role in (ROLE, "reviewer"):
            shutil.copy(KIT_ROOT / ".claude" / "agents" / f"{role}.md", agents)
        (self.kit / "AGENTS.md").write_text("# kit\n", encoding="utf-8")
        self.target = Path(tmp) / "target"
        self.target.mkdir()
        self.task_dir = self.kit / ".agent-state" / "demo" / "tasks" / "t1"
        self.task_dir.mkdir(parents=True)
        self.state_path = self.task_dir / "state.toml"
        for n in range(1, stages + 1):
            (self.task_dir / f"stage-{n}-handoff-template.md").write_text(TEMPLATE.format(n=n), encoding="utf-8")
        doc = st.init_state(self.state_path, project="demo", slug="t1", title="Demo", kit_root=str(self.kit),
                            targets=[str(self.target)], at=AT)
        raw = {
            "targets": [str(self.target)],
            "branches": {str(self.target): "feat/x"},
            "allowlist": [f"Bash(test -d {self.target})"],
            "review": review,
            "max_corrections": max_corrections,
            "max_duration": "8h",
            "judge_max_calls": judge_max_calls,
            "on_pass_with_risks": on_pass_with_risks,
            "stages": [{"role": ROLE, "handoff": f"stage-{n}-handoff-template.md"} for n in range(1, stages + 1)],
        }
        sha = env_mod.compute_hash(env_mod.parse_envelope(raw), task_dir=self.task_dir)
        raw["approval"] = {"at": AT, "sha256": sha}
        doc.envelope = raw
        st.write_state(self.state_path, doc)

        self.sessions: dict[str, dict] = {}
        self.verdicts = verdicts or {}
        self.after_receipt: dict[int, callable] = {}
        self.snapshot = "clean\n"
        self.branch = "feat/x"
        self.clock = 0.0
        self.auto_finish = True
        self.initial_session: dict = {"state": "working", "status": "busy"}
        self.launch_calls: list[tuple[list[str], dict]] = []
        self.judge_calls: list = []
        self.judge_result: JudgeAnswer | Exception = JudgeAnswer("continue", "risks are acceptable")
        self.notified: list[str] = []
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
            git_snapshot=lambda t: self.snapshot,
            git_branch=self.git_branch,
            judge=self.judge,
            notify=self.notified.append,
            sleep=self.sleep,
            monotonic=lambda: self.clock,
            now=lambda: AT + datetime.timedelta(seconds=self.clock),
            pid_alive=lambda pid: self.alive,
            getpid=lambda: 4242,
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
