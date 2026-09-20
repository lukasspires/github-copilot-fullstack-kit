"""Tests for scripts/preflight.py — G2 transition
`reserved -> prepared | preparation_failed`.

Builds a self-contained temp kit_root per test (never the real kit_root's
.agent-state/, never real fixtures beyond what each test constructs) so
every scenario is deterministic and isolated. `which`, `list_sessions`
and the clock are always injected; only the write-scope test uses real
filesystem writes (still entirely inside a temp directory) to demonstrate
containment for real, per the handoff's acceptance criteria.
"""

from __future__ import annotations

import datetime
import subprocess
import tempfile
import unittest
from pathlib import Path

import scripts.state as st
from scripts import preflight

AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)

HANDOFF_TEMPLATE = """\
# {task} — {role} — {nn:02d} — {type_}

## Objective

Demo objective for preflight tests.

## Role and profile

- **Role:** {role}
- **Absolute profile (read explicitly):** `{profile}`

## Roots

- **kit_root / target_root:** {kit_root}

## Write scope

- Assigned scope only.

## Acceptance criteria

1. Demo criterion.

## Assignment metadata

- **Receipt path (write here only):** `{receipt}`
- **Granted allowlist:** {allowlist}
"""


class _KitFixture:
    """A minimal, disposable kit_root with one reserved assignment."""

    def __init__(self, tmp_path: Path, *, allowlist: list[str]):
        self.kit_root = tmp_path
        (self.kit_root / "AGENTS.md").write_text("Agent operating guide.\n", encoding="utf-8")
        (self.kit_root / "CLAUDE.md").write_text("Claude runtime notes.\n", encoding="utf-8")
        agents_dir = self.kit_root / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        self.profile_path = agents_dir / "node-backend.md"
        self.profile_path.write_text("---\nname: node-backend\n---\nDemo profile body.\n", encoding="utf-8")

        task_dir = self.kit_root / ".agent-state" / "demo-project" / "tasks" / "demo-task"
        task_dir.mkdir(parents=True)
        self.task_dir = task_dir
        self.state_path = task_dir / "state.toml"

        task = st.Task(
            project="demo-project",
            slug="demo-task",
            title="Demo task",
            phase="implementation",
            kit_root=str(self.kit_root),
            targets=[str(self.kit_root)],
            journal=str(task_dir.relative_to(self.kit_root) / "checkpoint.md"),
            next_nn=1,
            created_at=AT,
            updated_at=AT,
        )
        doc = st.StateDoc(schema=1, task=task, assignments=[])
        self.assignment = st.add_assignment(
            doc,
            role="node-backend",
            type_="implementação",
            edge="inicia",
            predecessor=0,
            targets=[str(self.kit_root)],
            allowlist=allowlist,
            at=AT,
        )
        st.write_state(self.state_path, doc)

        handoff_path = self.kit_root / self.assignment.handoff
        handoff_path.write_text(
            HANDOFF_TEMPLATE.format(
                task="demo-task",
                role="node-backend",
                nn=1,
                type_="implementação",
                profile=self.profile_path,
                kit_root=self.kit_root,
                receipt=self.kit_root / self.assignment.receipt,
                allowlist=", ".join(f"`{a}`" for a in allowlist),
            ),
            encoding="utf-8",
        )

        subprocess.run(["git", "init", "-q"], cwd=str(self.kit_root), check=True)


def _fake_which(available: set[str]):
    def which(cmd: str) -> str | None:
        return f"/usr/bin/{cmd}" if cmd in available else None

    return which


def _no_sessions() -> list[dict]:
    return []


class Node1RegressionTest(unittest.TestCase):
    """Acceptance criterion 5: reproduce the real historical outcome for
    node 1 of the fixture — `node` not resolvable on PATH must still
    produce `preparation_failed`, matching
    tests/fixtures/visible-sessions/state.toml's own recorded note:
    "node não resolvido no PATH da sessão em background"."""

    def test_missing_check_executable_fails_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(
                Path(tmp), allowlist=[f"Bash(cd {Path(tmp)}/fixture && node --test)"]
            )
            result = preflight.run_preflight(
                fixture.state_path,
                1,
                kit_root=fixture.kit_root,
                now=AT,
                which=_fake_which({"git"}),  # "node" deliberately absent, like the real incident
                list_sessions=_no_sessions,
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("node" in r for r in result.reasons))

            doc = st.read_state(fixture.state_path)
            assignment = doc.get_assignment(1)
            self.assertEqual(assignment.state, "preparation_failed")
            self.assertEqual(assignment.events[-1].by, "preflight")


class PositivePreflightTest(unittest.TestCase):
    def test_all_checks_pass_transitions_to_prepared(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            result = preflight.run_preflight(
                fixture.state_path,
                1,
                kit_root=fixture.kit_root,
                now=AT,
                which=_fake_which({"git"}),
                list_sessions=_no_sessions,
            )
            self.assertTrue(result.ok, result.reasons)
            doc = st.read_state(fixture.state_path)
            assignment = doc.get_assignment(1)
            self.assertEqual(assignment.state, "prepared")
            self.assertTrue(assignment.git_before)
            git_before_path = fixture.kit_root / assignment.git_before
            self.assertTrue(git_before_path.is_file())
            self.assertIn("# git status --short", git_before_path.read_text(encoding="utf-8"))

    def test_manager_working_session_for_same_task_fails_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])

            def one_working_session() -> list[dict]:
                return [{"name": "demo-task — node-backend — 07 — implementação", "state": "working"}]

            result = preflight.run_preflight(
                fixture.state_path,
                1,
                kit_root=fixture.kit_root,
                now=AT,
                which=_fake_which({"git"}),
                list_sessions=one_working_session,
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("already working" in r for r in result.reasons))

    def test_manager_unavailable_is_noted_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])

            def unavailable():
                from scripts.common import ManagerUnavailable

                raise ManagerUnavailable("claude not found on PATH")

            result = preflight.run_preflight(
                fixture.state_path,
                1,
                kit_root=fixture.kit_root,
                now=AT,
                which=_fake_which({"git"}),
                list_sessions=unavailable,
            )
            self.assertTrue(result.ok, result.reasons)
            self.assertTrue(any("unavailable" in n for n in result.notes))

    def test_rerun_on_non_reserved_node_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                which=_fake_which({"git"}), list_sessions=_no_sessions,
            )
            with self.assertRaises(Exception):
                preflight.run_preflight(
                    fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                    which=_fake_which({"git"}), list_sessions=_no_sessions,
                )

    def test_receipt_already_exists_fails_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            receipt_path = fixture.kit_root / fixture.assignment.receipt
            receipt_path.write_text("stale receipt", encoding="utf-8")
            result = preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                which=_fake_which({"git"}), list_sessions=_no_sessions,
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("receipt already exists" in r for r in result.reasons))


class WriteScopeTest(unittest.TestCase):
    """Acceptance criterion 10: preflight, run for real (real filesystem,
    not mocked I/O), writes only inside
    `.agent-state/<project>/tasks/<task>/`."""

    def test_only_task_dir_files_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            fixture = _KitFixture(tmp_path, allowlist=["Bash(git status --short)"])

            def snapshot() -> dict[str, float]:
                return {
                    str(p.relative_to(tmp_path)): p.stat().st_mtime_ns
                    for p in tmp_path.rglob("*")
                    if p.is_file() and ".git" not in p.parts
                }

            before = snapshot()
            result = preflight.run_preflight(
                fixture.state_path,
                1,
                kit_root=fixture.kit_root,
                now=AT,
                which=_fake_which({"git"}),
                list_sessions=_no_sessions,
            )
            self.assertTrue(result.ok, result.reasons)
            after = snapshot()

            task_dir_rel = str(fixture.task_dir.relative_to(tmp_path))
            changed_or_new = {
                path for path in after if path not in before or after[path] != before[path]
            }
            self.assertTrue(changed_or_new, "expected at least the state.toml write to be observed")
            for path in changed_or_new:
                self.assertTrue(
                    path.startswith(task_dir_rel),
                    f"preflight wrote outside its runtime write scope: {path}",
                )


if __name__ == "__main__":
    unittest.main()
