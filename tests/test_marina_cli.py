"""Tests for `marina approve` through scripts/marina/cli.py and bin/marina.

A temporary directory stands in for the kit root (with one copied agent
profile) and holds `.agent-state/demo/tasks/t1/`; the hook subcommand is
checked only for not regressing (tests/test_marina_hooks.py covers it).
"""

from __future__ import annotations

import contextlib
import datetime
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import state
from scripts.marina import cli, runner
from scripts.marina import envelope as env_mod

KIT_ROOT = Path(__file__).resolve().parent.parent
BIN = KIT_ROOT / "bin" / "marina"
NOW = datetime.datetime(2026, 10, 26, 21, 0, 0, tzinfo=datetime.timezone.utc)
HANDOFF = "stage-1-handoff-template.md"
TEMPLATE = "## Objective\n\nDo it.\n\n## Write scope\n\n`src/`\n\n## Acceptance criteria\n\n1. Works.\n"


def _fake_kit(tmp: str) -> Path:
    kit = Path(tmp) / "kit"
    (kit / ".claude" / "agents").mkdir(parents=True)
    shutil.copy(KIT_ROOT / ".claude" / "agents" / "java-backend.md", kit / ".claude" / "agents")
    task_dir = kit / ".agent-state" / "demo" / "tasks" / "t1"
    task_dir.mkdir(parents=True)
    (task_dir / HANDOFF).write_text(TEMPLATE, encoding="utf-8")
    doc = state.init_state(
        task_dir / "state.toml", project="demo", slug="t1", title="Demo", kit_root=str(kit),
        targets=["/abs/api"], at=NOW,
    )
    doc.envelope = {
        "targets": ["/abs/api"],
        "branches": {"/abs/api": "feat/x"},
        "allowlist": ["Bash(mvn -f /abs/api/pom.xml test)"],
        "review": "each_stage",
        "max_corrections": 1,
        "max_duration": "8h",
        "judge_max_calls": 1,
        "on_pass_with_risks": "stop",
        "stages": [{"role": "java-backend", "handoff": HANDOFF}],
    }
    state.write_state(task_dir / "state.toml", doc)
    return kit


def _state_path(kit: Path) -> Path:
    return kit / ".agent-state" / "demo" / "tasks" / "t1" / "state.toml"


class ApproveCliTests(unittest.TestCase):
    def _run(self, argv: list[str], stdin_text: str = "", *, tty: bool = True) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(argv, stdin=io.StringIO(stdin_text), stdout=out, stderr=err, isatty=lambda: tty)
        return code, out.getvalue(), err.getvalue()

    def test_approve_via_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            code, out, err = self._run(["approve", "demo", "t1", "--kit-root", str(kit)], "t1\n")
            self.assertEqual(code, 0, err)
            self.assertIsNotNone(env_mod.envelope_from_doc(state.read_state(_state_path(kit))).approval)

    def test_bad_slug_args_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            for project, task in (("../x", "t1"), ("demo", "T1"), ("demo", "t1/../t1"), ("", "t1"), ("demo", "t1\n")):
                with self.subTest(project=project, task=task):
                    code, _, err = self._run(["approve", project, task, "--kit-root", str(kit)], "t1\n")
                    self.assertEqual(code, 1)
                    self.assertTrue(err)

    def test_missing_state_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            code, _, err = self._run(["approve", "demo", "t2", "--kit-root", str(kit)], "t2\n")
            self.assertEqual(code, 1)
            self.assertIn("state.toml", err)

    def test_missing_arguments_exit_1(self):
        with contextlib.redirect_stderr(io.StringIO()):
            code, _, err = self._run(["approve", "demo"])
        self.assertEqual(code, 1)
        self.assertIn("invalid arguments", err)

    def test_hook_still_works(self):
        code, _, _ = self._run(
            ["hook", "require-receipt", "--receipt", "/r", "--handoff", "/h"], '{"stop_hook_active": true}'
        )
        self.assertEqual(code, 0)


class FakeRunnerDeps:
    """Stand-in for runner.default_deps: tests replace runner.run itself."""


class RunStatusStopCliTests(unittest.TestCase):
    def _run(self, argv: list[str], **kwargs) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        code = cli.main(argv, stdin=io.StringIO(""), stdout=out, stderr=err, isatty=lambda: False, **kwargs)
        return code, out.getvalue(), err.getvalue()

    def test_run_requires_interval_and_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            with contextlib.redirect_stderr(io.StringIO()):
                for argv in (["run", "demo", "t1", "--kit-root", str(kit)],
                             ["run", "demo", "t1", "--interval", "10", "--kit-root", str(kit)],
                             ["run", "demo", "t1", "--max-duration", "1h", "--kit-root", str(kit)]):
                    with self.subTest(argv=argv):
                        self.assertEqual(self._run(argv)[0], 1)

    def test_run_bad_duration_or_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            for interval, duration in (("10", "1d"), ("0", "1h"), ("x", "1h")):
                with self.subTest(interval=interval, duration=duration), contextlib.redirect_stderr(io.StringIO()):
                    code, _, err = self._run(["run", "demo", "t1", "--interval", interval, "--max-duration", duration,
                                              "--kit-root", str(kit)])
                    self.assertEqual(code, 1)
                    self.assertTrue(err)

    def _with_fake_run(self, result=None, raises=None):
        calls = []

        def fake_run(state_path, **kwargs):
            calls.append((state_path, kwargs))
            if raises is not None:
                raise raises
            return result

        return mock.patch.object(runner, "run", fake_run), calls

    def test_run_done_exit_0(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            patch, calls = self._with_fake_run(runner.RunResult("done", "", [1, 2], []))
            with patch:
                code, out, _ = self._run(["run", "demo", "t1", "--interval", "15", "--max-duration", "2h",
                                          "--notify-cmd", "notify-send x", "--kit-root", str(kit)],
                                         deps=FakeRunnerDeps())
            self.assertEqual(code, 0)
            self.assertIn("marina run: done", out)
            state_path, kwargs = calls[0]
            self.assertEqual(state_path, _state_path(kit))
            self.assertEqual((kwargs["interval"], kwargs["max_duration"], kwargs["notify_cmd"], kwargs["recover"]),
                             (15.0, 7200, "notify-send x", False))
            self.assertIsInstance(kwargs["deps"], FakeRunnerDeps)

    def test_run_stop_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            patch, _ = self._with_fake_run(runner.RunResult("stop", "second_fail", [1, 2, 3, 4], []))
            with patch:
                code, out, _ = self._run(["run", "demo", "t1", "--interval", "15", "--max-duration", "2h",
                                          "--kit-root", str(kit)], deps=FakeRunnerDeps())
            self.assertEqual(code, 1)
            self.assertIn("marina run: stop second_fail", out)

    def test_run_refused_when_locked(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            patch, _ = self._with_fake_run(raises=runner.RunRefused("lock held"))
            with patch:
                code, _, err = self._run(["run", "demo", "t1", "--interval", "15", "--max-duration", "2h",
                                          "--recover", "--kit-root", str(kit)], deps=FakeRunnerDeps())
            self.assertEqual(code, 1)
            self.assertIn("lock held", err)

    def test_status_prints_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            code, out, _ = self._run(["status", "demo", "t1", "--kit-root", str(kit)])
            self.assertEqual(code, 0)
            self.assertIn("task: t1", out)
            self.assertIn("envelope: not approved", out)
            self.assertEqual(self._run(["status", "demo", "t9", "--kit-root", str(kit)])[0], 1)

    def test_stop_without_run_exit_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            code, _, err = self._run(["stop", "demo", "t1", "--kit-root", str(kit)])
            self.assertEqual(code, 1)
            self.assertIn("no marina run", err)

    def test_stop_creates_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            task_dir = _state_path(kit).parent
            (task_dir / runner.LOCK_NAME).write_text('{"pid": 1}', encoding="utf-8")
            code, out, _ = self._run(["stop", "demo", "t1", "--kit-root", str(kit)])
            self.assertEqual(code, 0)
            self.assertTrue((task_dir / runner.STOP_NAME).exists())


class McpCliTests(unittest.TestCase):
    def test_mcp_subcommand_serves(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            stdin = io.StringIO('{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
                                '{"jsonrpc":"2.0","id":2,"method":"tools/list"}\n')
            out = io.StringIO()
            code = cli.main(["mcp", "--kit-root", str(kit)], stdin=stdin, stdout=out, stderr=io.StringIO())
            self.assertEqual(code, 0)
            ids = [json.loads(line)["id"] for line in out.getvalue().splitlines()]
            self.assertEqual(ids, [1, 2])


class GoCliTests(unittest.TestCase):
    """F7: `marina go` approves on dispatch and starts `marina run` detached."""

    def _go(self, kit: Path, *extra: str, tty: bool = True):
        out, err, spawns = io.StringIO(), io.StringIO(), []

        def spawn(argv, cwd, log_path):
            spawns.append((list(argv), cwd, log_path))
            return 4321

        code = cli.main(["go", "demo", "t1", "--kit-root", str(kit), "--grace", "0", *extra],
                        stdin=io.StringIO(""), stdout=out, stderr=err, isatty=lambda: tty, spawn=spawn)
        return code, out.getvalue(), err.getvalue(), spawns

    def test_go_spawns_run_with_envelope_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            code, out, err, spawns = self._go(kit)
            self.assertEqual(code, 0, err)
            argv, cwd, log = spawns[0]
            self.assertEqual(argv, runner.run_argv(kit, "demo", "t1", interval=30, max_duration="8h", notify_cmd=None))
            self.assertEqual((cwd, log), (kit, _state_path(kit).parent / runner.LOG_NAME))
            self.assertIsNotNone(env_mod.envelope_from_doc(state.read_state(_state_path(kit))).approval)
            self.assertIn("pid 4321", out)
            self.assertIn("marina status demo t1", out)

    def test_go_passes_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            code, _, err, spawns = self._go(kit, "--interval", "5", "--max-duration", "1h", "--notify-cmd", "x y")
            self.assertEqual(code, 0, err)
            self.assertEqual(spawns[0][0], runner.run_argv(kit, "demo", "t1", interval=5, max_duration="1h",
                                                           notify_cmd="x y"))

    def test_go_with_live_lock_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            lock = _state_path(kit).parent / runner.LOCK_NAME
            lock.write_text(json.dumps({"pid": os.getpid(), "started_at": "x"}), encoding="utf-8")
            code, out, _, spawns = self._go(kit)
            self.assertEqual((code, spawns), (0, []))
            self.assertIn("already in progress", out)
            self.assertIsNone(env_mod.envelope_from_doc(state.read_state(_state_path(kit))).approval)

    def test_go_refusal_does_not_spawn(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            code, _, err, spawns = self._go(kit, tty=False)
            self.assertEqual((code, spawns), (1, []))
            self.assertIn("interactive terminal", err)

    def test_go_bad_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            for extra in (("--interval", "0"), ("--max-duration", "1d"), ("--grace", "-1")):
                with self.subTest(extra=extra):
                    code, _, _, spawns = self._go(kit, *extra)
                    self.assertEqual((code, spawns), (1, []))


class BinWrapperTests(unittest.TestCase):
    def test_bin_wrapper_is_executable(self):
        self.assertTrue(os.access(BIN, os.X_OK))

    def test_bin_wrapper_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [str(BIN), "--help"], cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for command in ("approve", "go", "run", "status", "stop", "mcp"):
            self.assertIn(command, proc.stdout)

    def test_bin_wrapper_refuses_without_tty(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit = _fake_kit(tmp)
            before = _state_path(kit).read_bytes()
            proc = subprocess.run(
                [str(BIN), "approve", "demo", "t1", "--kit-root", str(kit)], cwd=tmp, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(proc.returncode, 1)
            self.assertIn("interactive terminal", proc.stderr)
            self.assertEqual(_state_path(kit).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
