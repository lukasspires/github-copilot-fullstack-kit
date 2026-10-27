"""Tests for `marina approve` through scripts/marina/cli.py and bin/marina.

A temporary directory stands in for the kit root (with one copied agent
profile) and holds `.agent-state/demo/tasks/t1/`; the hook subcommand is
checked only for not regressing (tests/test_marina_hooks.py covers it).
"""

from __future__ import annotations

import contextlib
import datetime
import io
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import state
from scripts.marina import cli
from scripts.marina import envelope as env_mod

KIT_ROOT = Path(__file__).resolve().parent.parent
BIN = KIT_ROOT / "bin" / "marina"
NOW = datetime.datetime(2026, 10, 26, 21, 0, 0, tzinfo=datetime.timezone.utc)
HANDOFF = "01-java-backend-handoff.md"


def _fake_kit(tmp: str) -> Path:
    kit = Path(tmp) / "kit"
    (kit / ".claude" / "agents").mkdir(parents=True)
    shutil.copy(KIT_ROOT / ".claude" / "agents" / "java-backend.md", kit / ".claude" / "agents")
    task_dir = kit / ".agent-state" / "demo" / "tasks" / "t1"
    task_dir.mkdir(parents=True)
    (task_dir / HANDOFF).write_text("# handoff\n", encoding="utf-8")
    doc = state.init_state(
        task_dir / "state.toml", project="demo", slug="t1", title="Demo", kit_root=str(kit),
        targets=["/abs/api"], at=NOW,
    )
    doc.envelope = {
        "targets": ["/abs/api"],
        "branches": {"/abs/api": "feat/x"},
        "allowlist": ["Bash(mvn test)"],
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


class BinWrapperTests(unittest.TestCase):
    def test_bin_wrapper_is_executable(self):
        self.assertTrue(os.access(BIN, os.X_OK))

    def test_bin_wrapper_help(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [str(BIN), "--help"], cwd=tmp, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30
            )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("approve", proc.stdout)

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
