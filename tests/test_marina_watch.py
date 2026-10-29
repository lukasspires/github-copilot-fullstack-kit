"""Tests for scripts/marina/watch.py — `marina watch --once` and its fallbacks.

The curses loop needs a real terminal and is not exercised here; the
snapshot path uses the same `_Source` and `progress.render`.
"""

from __future__ import annotations

import datetime
import io
import tempfile
import unittest
from pathlib import Path

import scripts.state as st
from scripts import common
from scripts.marina import envelope as env_mod
from scripts.marina import watch

AT = datetime.datetime(2026, 10, 28, 21, 0, 0, tzinfo=datetime.timezone.utc)
TEMPLATE = "## Objective\n\nDo it.\n\n## Write scope\n\n- `src/`\n\n## Acceptance criteria\n\n1. Works.\n"


def _fixture(tmp: str) -> tuple[Path, Path]:
    kit = Path(tmp) / "kit"
    task_dir = kit / ".agent-state" / "demo" / "tasks" / "t1"
    task_dir.mkdir(parents=True)
    (task_dir / "stage-1-handoff-template.md").write_text(TEMPLATE, encoding="utf-8")
    doc = st.init_state(task_dir / "state.toml", project="demo", slug="t1", title="Demo", kit_root=str(kit),
                        targets=["/abs/api"], at=AT)
    doc.envelope = {"targets": ["/abs/api"], "branches": {"/abs/api": "feat/x"},
                    "allowlist": ["Bash(test -d /abs/api)"], "review": "each_stage", "max_corrections": 1,
                    "max_duration": "2h", "judge_max_calls": 1, "on_pass_with_risks": "accept",
                    "stages": [{"role": "java-backend", "handoff": "stage-1-handoff-template.md"}]}
    st.write_state(task_dir / "state.toml", doc)
    (kit / ".agent-state" / "other" / "tasks" / "broken").mkdir(parents=True)
    (kit / ".agent-state" / "other" / "tasks" / "broken" / "state.toml").write_text("not toml [", encoding="utf-8")
    return kit, task_dir / "state.toml"


def _deps(tmp: str, *, sessions=None, error: Exception | None = None) -> watch.WatchDeps:
    def list_sessions():
        if error is not None:
            raise error
        return sessions or []

    return watch.WatchDeps(list_sessions=list_sessions, now=lambda: AT, monotonic=lambda: 0.0,
                           pid_alive=lambda pid: False, projects_root=Path(tmp), terminal_width=lambda: 100)


class WatchOnceTests(unittest.TestCase):
    def _run(self, tmp: str, *, once=True, tty=True, **deps_kw) -> tuple[int, str, Path]:
        kit, state_path = _fixture(tmp)
        out = io.StringIO()
        code = watch.run_watch(state_path, kit_root=kit, once=once, stdout=out, isatty=lambda: tty,
                               manager_interval=10, deps=_deps(tmp, **deps_kw))
        return code, out.getvalue(), state_path

    def test_once_prints_snapshot_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit, state_path = _fixture(tmp)
            before = {p: p.stat().st_mtime_ns for p in kit.rglob("*") if p.is_file()}
            out = io.StringIO()
            code = watch.run_watch(state_path, kit_root=kit, once=True, stdout=out, isatty=lambda: True,
                                   manager_interval=10, deps=_deps(tmp))
            after = {p: p.stat().st_mtime_ns for p in kit.rglob("*") if p.is_file()}
        self.assertEqual(code, 0)
        self.assertEqual(before, after)
        self.assertIn("marina · t1 — Demo", out.getvalue())
        self.assertIn("envelope: não aprovado", out.getvalue())
        self.assertIn("próxima etapa: java-backend", out.getvalue())

    def test_no_tty_falls_back_to_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self._run(tmp, once=False, tty=False)
        self.assertEqual(code, 0)
        self.assertIn("etapas planejadas", out)

    def test_manager_unavailable_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = self._run(tmp, error=common.ManagerUnavailable("no claude"))
        self.assertEqual(code, 0)
        self.assertIn("manager indisponível", out)

    def test_history_skips_unreadable_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            kit, _ = _fixture(tmp)
            self.assertEqual([d.task.slug for d in watch._history(kit)], ["t1"])


if __name__ == "__main__":
    unittest.main()
