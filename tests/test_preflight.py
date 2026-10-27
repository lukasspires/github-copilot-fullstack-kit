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
from scripts import handoff_sync, preflight

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
    def test_rejects_redirected_task_paths_before_handoff_write(self):
        for field in ("journal", "handoff", "receipt"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
                doc = st.read_state(fixture.state_path)
                wrong = fixture.kit_root / "elsewhere" / f"{field}.md"
                wrong.parent.mkdir()
                wrong.write_text("do not change", encoding="utf-8")
                if field == "journal":
                    doc.task.journal = str(wrong.relative_to(fixture.kit_root))
                else:
                    setattr(doc.get_assignment(1), field, str(wrong.relative_to(fixture.kit_root)))
                st.write_state(fixture.state_path, doc)
                original = fixture.state_path.read_bytes()
                canonical_handoff = fixture.task_dir / "01-node-backend-handoff.md"
                original_handoff = canonical_handoff.read_bytes()
                with self.assertRaisesRegex(Exception, "canonical task location"):
                    preflight.run_preflight(
                        fixture.state_path, 1, kit_root=fixture.kit_root,
                        now=AT, which=_fake_which({"git"}), list_sessions=_no_sessions,
                    )
                self.assertEqual(fixture.state_path.read_bytes(), original)
                self.assertEqual(canonical_handoff.read_bytes(), original_handoff)
                self.assertEqual(wrong.read_text(encoding="utf-8"), "do not change")

    def test_rejects_redirected_state_file_and_symlink_task_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            wrong = fixture.kit_root / "elsewhere" / "state.toml"
            wrong.parent.mkdir()
            wrong.write_bytes(fixture.state_path.read_bytes())
            before = wrong.read_bytes()
            with self.assertRaisesRegex(Exception, "canonical task location"):
                preflight.run_preflight(
                    wrong, 1, kit_root=fixture.kit_root,
                    now=AT, which=_fake_which({"git"}), list_sessions=_no_sessions,
                )
            self.assertEqual(wrong.read_bytes(), before)

            moved = fixture.kit_root / "escaped-task"
            fixture.task_dir.rename(moved)
            fixture.task_dir.symlink_to(moved, target_is_directory=True)
            handoff = moved / "01-node-backend-handoff.md"
            before_handoff = handoff.read_bytes()
            with self.assertRaisesRegex(Exception, "symlink"):
                preflight.run_preflight(
                    fixture.state_path, 1, kit_root=fixture.kit_root,
                    now=AT, which=_fake_which({"git"}), list_sessions=_no_sessions,
                )
            self.assertEqual(handoff.read_bytes(), before_handoff)

    def test_rejects_symlinked_handoff_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            handoff = fixture.task_dir / "01-node-backend-handoff.md"
            wrong = fixture.kit_root / "outside-handoff.md"
            handoff.rename(wrong)
            handoff.symlink_to(wrong)
            before = wrong.read_bytes()
            with self.assertRaisesRegex(Exception, "canonical task location"):
                preflight.run_preflight(
                    fixture.state_path, 1, kit_root=fixture.kit_root,
                    now=AT, which=_fake_which({"git"}), list_sessions=_no_sessions,
                )
            self.assertEqual(wrong.read_bytes(), before)

    def test_missing_roots_and_bullet_allowlist_are_synchronized(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)", "Bash(git diff *)"])
            handoff_path = fixture.kit_root / fixture.assignment.handoff
            original = handoff_path.read_text(encoding="utf-8")
            changed = original.replace(
                f"## Roots\n\n- **kit_root / target_root:** {fixture.kit_root}\n\n", ""
            ).replace(
                "- **Granted allowlist:** `Bash(git status --short)`, `Bash(git diff *)`",
                "- **Granted allowlist:**\n  - `Bash(echo stale)`",
            )
            handoff_path.write_text(changed, encoding="utf-8")
            result = preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                which=_fake_which({"git"}), list_sessions=_no_sessions,
            )
            self.assertTrue(result.ok, result.reasons)
            self.assertIn("synchronized handoff fields: target_root, Granted allowlist", result.notes)
            synchronized = handoff_path.read_text(encoding="utf-8")
            self.assertIn(f"## Roots\n\n- **kit_root:** `{fixture.kit_root}`", synchronized)
            self.assertIn(f"- **target_root:** `{fixture.kit_root}`", synchronized)
            self.assertIn("- **Granted allowlist:** `Bash(git status --short)` `Bash(git diff *)`", synchronized)
            self.assertNotIn("Bash(echo stale)", synchronized)
            self.assertIn("Demo objective for preflight tests.", synchronized)
            event = st.read_state(fixture.state_path).get_assignment(1).events[-1]
            self.assertEqual(event.note, "synchronized: target_root, Granted allowlist")

    def test_duplicate_allowlists_and_legacy_lists_collapse_without_other_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            handoff_path = fixture.kit_root / fixture.assignment.handoff
            source = handoff_path.read_text(encoding="utf-8")
            label = "- **Granted allowlist:** `Bash(git status --short)`"
            stale = (
                "- **Granted allowlist:** `Bash(echo stale)`\n"
                "  - `Bash(echo stale-list)`\n"
                "  - Preserve this unrelated note.\n"
                "- `example`\n"
                "- **Granted allowlist:** `Bash(*)`\n"
                "- `Bash(echo second-list)`\n"
                "- **No commit:** Keep this exact metadata."
            )
            expected = source.replace(
                label,
                "- **Granted allowlist:** `Bash(git status --short)`\n"
                "  - Preserve this unrelated note.\n"
                "- `example`\n"
                "- **No commit:** Keep this exact metadata.",
            ) + "\n## Receipt\n\nKeep this exact section.\n"
            handoff_path.write_text(
                source.replace(label, stale) + "\n## Receipt\n\nKeep this exact section.\n",
                encoding="utf-8",
            )

            result = preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                which=_fake_which({"git"}), list_sessions=_no_sessions,
            )
            self.assertTrue(result.ok, result.reasons)
            self.assertEqual(result.notes, ["synchronized handoff fields: target_root, Granted allowlist"])
            synchronized = handoff_path.read_text(encoding="utf-8")
            self.assertEqual(synchronized, expected.replace(
                f"- **kit_root / target_root:** {fixture.kit_root}",
                f"- **kit_root:** {fixture.kit_root}\n- **target_root:** `{fixture.kit_root}`",
            ))
            self.assertEqual(synchronized.count("Granted allowlist:"), 1)
            again, corrected = handoff_sync.synchronize(synchronized, fixture.assignment, fixture.kit_root)
            self.assertEqual(again, synchronized)
            self.assertEqual(corrected, [])

    def test_multiple_targets_follow_state_order_and_preserve_other_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            second = fixture.kit_root / "second-target"
            second.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=second, check=True)
            fixture.assignment.targets = [str(second), str(fixture.kit_root)]
            doc = st.read_state(fixture.state_path)
            doc.get_assignment(1).targets = fixture.assignment.targets
            st.write_state(fixture.state_path, doc)

            handoff_path = fixture.kit_root / fixture.assignment.handoff
            source = handoff_path.read_text(encoding="utf-8")
            source = source.replace("## Write scope", "Keep this exact sentence and spacing.\n\n## Write scope")
            handoff_path.write_text(source, encoding="utf-8")
            result = preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                which=_fake_which({"git"}), list_sessions=_no_sessions,
            )
            self.assertTrue(result.ok, result.reasons)
            expected = source.replace(
                f"- **kit_root / target_root:** {fixture.kit_root}",
                f"- **kit_root:** {fixture.kit_root}\n"
                f"- **target_root:** `{second}`\n- **target_root:** `{fixture.kit_root}`",
            )
            self.assertEqual(handoff_path.read_text(encoding="utf-8"), expected)

    def test_missing_acceptance_fails_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            handoff_path = fixture.kit_root / fixture.assignment.handoff
            handoff_path.write_text(
                handoff_path.read_text(encoding="utf-8").replace("1. Demo criterion.", ""),
                encoding="utf-8",
            )
            result = preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                which=_fake_which({"git"}), list_sessions=_no_sessions,
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("acceptance criteria" in reason for reason in result.reasons))
            self.assertEqual(st.read_state(fixture.state_path).get_assignment(1).state, "preparation_failed")

    def test_identity_mismatches_fail_preparation(self):
        replacements = {
            "title": ("# demo-task — node-backend — 01 — implementação",
                      "# other-task — node-backend — 01 — implementação"),
            "role": ("- **Role:** node-backend", "- **Role:** reviewer"),
            "profile": ("/.claude/agents/node-backend.md", "/.claude/agents/reviewer.md"),
            "codex profile": ("/.claude/agents/node-backend.md", "/.codex/agents/node-backend.toml"),
            "receipt": ("01-node-backend-receipt.md", "02-node-backend-receipt.md"),
            "write scope": ("Assigned scope only.", ""),
        }
        for field, (old, new) in replacements.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
                handoff_path = fixture.kit_root / fixture.assignment.handoff
                source = handoff_path.read_text(encoding="utf-8")
                self.assertIn(old, source)
                handoff_path.write_text(source.replace(old, new), encoding="utf-8")
                if field == "codex profile":
                    # The legacy profile file exists, so only the handoff's profile rule can reject it.
                    codex_profile = fixture.kit_root / ".codex" / "agents" / "node-backend.toml"
                    codex_profile.parent.mkdir(parents=True)
                    codex_profile.write_text('name = "node-backend"\n', encoding="utf-8")
                result = preflight.run_preflight(
                    fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                    which=_fake_which({"git"}), list_sessions=_no_sessions,
                )
                self.assertFalse(result.ok)
                self.assertEqual(st.read_state(fixture.state_path).get_assignment(1).state, "preparation_failed")
                if field == "codex profile":
                    self.assertTrue(any("absolute profile" in r for r in result.reasons), result.reasons)

    def test_empty_allowlist_fails_preparation(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=[])
            result = preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT,
                which=_fake_which({"git"}), list_sessions=_no_sessions,
            )
            self.assertFalse(result.ok)
            self.assertTrue(any("allowlist" in reason for reason in result.reasons))

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

    def test_session_that_ended_its_turn_as_working_idle_does_not_block(self):
        # F6 acceptance: a finished --bg session stayed `working`/`idle`; preflight must
        # classify it the way status_claude does instead of reading `state` alone.
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])

            def idle_session() -> list[dict]:
                return [{"name": "demo-task — node-backend — 07 — implementação", "state": "working", "status": "idle"}]

            result = preflight.run_preflight(
                fixture.state_path, 1, kit_root=fixture.kit_root, now=AT, which=_fake_which({"git"}),
                list_sessions=idle_session,
            )
            self.assertFalse(any("already working" in r for r in result.reasons), result.reasons)

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
