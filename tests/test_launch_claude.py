"""Tests for scripts/launch_claude.py — G2 transition
`prepared -> launched | uncertain`.

Never invokes the real `claude` binary: `subprocess.run` is always
injected. `run_launch` is exercised against a self-contained temp
kit_root+handoff (same pattern as tests/test_preflight.py's `_KitFixture`)
so both the `preflight`-first fail-fast path and the launch path are real
code, not stubs.
"""

from __future__ import annotations

import datetime
import subprocess
import tempfile
import unittest
from pathlib import Path

import scripts.state as st
from scripts import launch_claude, preflight

AT = datetime.datetime(2026, 1, 1, 10, 0, 0, tzinfo=datetime.timezone.utc)

# The real example from docs/agent-workflow.md's "Claude Code" section
# (acceptance criterion 5), reproduced verbatim as a handoff body.
REDMINE_HANDOFF_TEXT = """\
# redmine-1234 — java-backend — 01 — implementação

## Objective

Demo objective matching docs/agent-workflow.md's Claude Code example.

## Role and profile

- **Role:** java-backend
- **Absolute profile (read explicitly):** `/absolute/kit/.claude/agents/java-backend.md`

## Roots

- **kit_root:** `/absolute/kit`
- **target_root:** `/absolute/api`

## Write scope

- Assigned scope only.

## Acceptance criteria

1. Demo criterion.

## Assignment metadata

- **Task:** redmine-1234
- **nn:** 01
- **Type:** implementação
- **Receipt path (write here only):** `/absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-receipt.md`
- **Granted allowlist:** `Bash(mvn test)`
"""

EXPECTED_DOC_ARGV = [
    "claude",
    "--bg",
    "--agent",
    "java-backend",
    "--name",
    "redmine-1234 — java-backend — 01 — implementação",
    "--add-dir",
    "/absolute/api",
    "--settings",
    '{"worktree":{"bgIsolation":"none"}}',
    "--permission-mode",
    "acceptEdits",
    "--allowedTools",
    "Bash(mvn test)",
    "--",
    "Act as java-backend. Read /absolute/kit/.claude/agents/java-backend.md and "
    "/absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-handoff.md, then execute the assignment.",
]


class ParseHandoffTests(unittest.TestCase):
    def test_parses_the_documented_example(self):
        data = launch_claude.parse_handoff(REDMINE_HANDOFF_TEXT)
        self.assertEqual(data.task, "redmine-1234")
        self.assertEqual(data.role, "java-backend")
        self.assertEqual(data.nn, 1)
        self.assertEqual(data.type_, "implementação")
        self.assertEqual(data.profile, "/absolute/kit/.claude/agents/java-backend.md")
        self.assertEqual(data.targets, ["/absolute/api"])
        self.assertEqual(data.allowlist, ["Bash(mvn test)"])

    def test_missing_title_line_refused(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.parse_handoff("no title line here\n")


class BuildArgvDocumentedExampleTest(unittest.TestCase):
    """Acceptance criterion 5: field-for-field match against the real
    docs/agent-workflow.md example."""

    def test_argv_matches_field_for_field(self):
        data = launch_claude.parse_handoff(REDMINE_HANDOFF_TEXT)
        argv = launch_claude.build_argv(
            data, handoff_path="/absolute/kit/.agent-state/api/tasks/redmine-1234/01-java-backend-handoff.md"
        )
        self.assertEqual(argv, EXPECTED_DOC_ARGV)


class ForbiddenConstructionTests(unittest.TestCase):
    """Acceptance criterion 6: one test per forbidden flag/behavior, plus
    the bare/wildcard --allowedTools case. All via build_argv; never a
    real subprocess call."""

    def _data(self, allowlist: list[str] | None = None):
        data = launch_claude.parse_handoff(REDMINE_HANDOFF_TEXT)
        if allowlist is not None:
            data.allowlist = allowlist
        return data

    def test_refuses_bypass_permissions(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.build_argv(self._data(), handoff_path="/x", extra_args=["--permission-mode", "bypassPermissions"])

    def test_refuses_permission_prompts_none(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.build_argv(self._data(), handoff_path="/x", extra_args=["--permission-prompts", "none"])

    def test_refuses_resume(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.build_argv(self._data(), handoff_path="/x", extra_args=["--resume", "some-id"])

    def test_refuses_continue(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.build_argv(self._data(), handoff_path="/x", extra_args=["--continue"])

    def test_refuses_fork_session(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.build_argv(self._data(), handoff_path="/x", extra_args=["--fork-session"])

    def test_refuses_bare_bash_allowlist_entry(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.build_argv(self._data(allowlist=["Bash"]), handoff_path="/x")

    def test_refuses_wildcard_bash_allowlist_entry(self):
        with self.assertRaises(launch_claude.LaunchRefused):
            launch_claude.build_argv(self._data(allowlist=["Bash(*)"]), handoff_path="/x")

    def test_ordinary_extra_args_are_not_refused(self):
        argv = launch_claude.build_argv(self._data(), handoff_path="/x", extra_args=["--model", "sonnet"])
        self.assertIn("--model", argv)


class ExtractShortIdTests(unittest.TestCase):
    def test_extracts_real_shaped_id(self):
        self.assertEqual(launch_claude.extract_short_id("Started background session 182689df\n"), "182689df")

    def test_last_match_wins(self):
        stdout = "note: 12345678\nStarted background session c1897dee\n"
        self.assertEqual(launch_claude.extract_short_id(stdout), "c1897dee")

    def test_no_match_returns_none(self):
        self.assertIsNone(launch_claude.extract_short_id("timed out waiting for a response\n"))


HANDOFF_TEMPLATE = """\
# {task} — {role} — {nn:02d} — {type_}

## Objective

Demo objective for launch-claude tests.

## Role and profile

- **Role:** {role}
- **Absolute profile (read explicitly):** `{profile}`

## Roots

- **kit_root / target_root:** `{kit_root}`

## Write scope

- Assigned scope only.

## Acceptance criteria

1. Demo criterion.

## Assignment metadata

- **Receipt path (write here only):** `{receipt}`
- **Granted allowlist:** {allowlist}
"""


class _KitFixture:
    """A minimal, disposable kit_root with one reserved assignment
    (same shape as tests/test_preflight.py's `_KitFixture`)."""

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
            project="demo-project", slug="demo-task", title="Demo task", phase="implementation",
            kit_root=str(self.kit_root), targets=[str(self.kit_root)],
            journal=str(task_dir.relative_to(self.kit_root) / "checkpoint.md"),
            next_nn=1, created_at=AT, updated_at=AT,
        )
        doc = st.StateDoc(schema=1, task=task, assignments=[])
        self.assignment = st.add_assignment(
            doc, role="node-backend", type_="implementação", edge="inicia", predecessor=0,
            targets=[str(self.kit_root)], allowlist=allowlist, at=AT,
        )
        st.write_state(self.state_path, doc)

        handoff_path = self.kit_root / self.assignment.handoff
        handoff_path.write_text(
            HANDOFF_TEMPLATE.format(
                task="demo-task", role="node-backend", nn=1, type_="implementação",
                profile=self.profile_path, kit_root=self.kit_root,
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


class _RecordingSubprocess:
    def __init__(self, stdout: str, returncode: int = 0):
        self.stdout = stdout
        self.returncode = returncode
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        return subprocess.CompletedProcess(argv, self.returncode, stdout=self.stdout, stderr="")


class RunLaunchTests(unittest.TestCase):
    def test_preflight_failure_aborts_before_constructing_anything(self):
        """Acceptance criterion 7."""

        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(cd /x && node --test)"])
            recorder = _RecordingSubprocess("182689df\n")

            def failing_preflight(*args, **kwargs):
                return preflight.run_preflight(
                    *args, which=_fake_which({"git"}), list_sessions=_no_sessions, **kwargs
                )

            result = launch_claude.run_launch(
                fixture.state_path, 1, kit_root=fixture.kit_root,
                run_preflight=failing_preflight, run_subprocess=recorder,
            )
            self.assertFalse(result.ok)
            self.assertIsNone(result.argv)
            self.assertEqual(recorder.calls, [], "must not construct/launch anything after preparation_failed")

            doc = st.read_state(fixture.state_path)
            self.assertEqual(doc.get_assignment(1).state, "preparation_failed")

    def test_successful_preflight_then_launch_records_launched(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            recorder = _RecordingSubprocess("Started background session 182689df\n")

            def ok_preflight(*args, **kwargs):
                return preflight.run_preflight(
                    *args, which=_fake_which({"git"}), list_sessions=_no_sessions, **kwargs
                )

            result = launch_claude.run_launch(
                fixture.state_path, 1, kit_root=fixture.kit_root,
                run_preflight=ok_preflight, run_subprocess=recorder,
            )
            self.assertTrue(result.ok, result.reasons)
            self.assertEqual(result.session_id, "182689df")
            self.assertEqual(len(recorder.calls), 1, "never launch more than one session per invocation")

            doc = st.read_state(fixture.state_path)
            assignment = doc.get_assignment(1)
            self.assertEqual(assignment.state, "launched")
            self.assertEqual(assignment.native.id, "182689df")

    def test_no_id_captured_records_uncertain_not_launched(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            recorder = _RecordingSubprocess("timed out\n")

            def ok_preflight(*args, **kwargs):
                return preflight.run_preflight(
                    *args, which=_fake_which({"git"}), list_sessions=_no_sessions, **kwargs
                )

            result = launch_claude.run_launch(
                fixture.state_path, 1, kit_root=fixture.kit_root,
                run_preflight=ok_preflight, run_subprocess=recorder,
            )
            self.assertFalse(result.ok)
            doc = st.read_state(fixture.state_path)
            self.assertEqual(doc.get_assignment(1).state, "uncertain")

    def test_bare_allowlist_entry_aborts_before_launching(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash"])
            recorder = _RecordingSubprocess("182689df\n")

            def ok_preflight(*args, **kwargs):
                return preflight.run_preflight(
                    *args, which=_fake_which({"git"}), list_sessions=_no_sessions, **kwargs
                )

            result = launch_claude.run_launch(
                fixture.state_path, 1, kit_root=fixture.kit_root,
                run_preflight=ok_preflight, run_subprocess=recorder,
            )
            self.assertFalse(result.ok)
            self.assertEqual(recorder.calls, [])

    def test_never_invokes_the_real_claude_binary(self):
        """Source-grep sanity check: `run_subprocess` is only ever *called*
        as the injected parameter (`run_subprocess(...)`), never as a
        direct `subprocess.run(...)` call site anywhere in the module —
        every test above replaces the default with `_RecordingSubprocess`."""

        text = (Path(__file__).resolve().parent.parent / "scripts" / "launch_claude.py").read_text(encoding="utf-8")
        self.assertNotIn("subprocess.run(", text)
        self.assertIn("run_subprocess(argv", text)


class RunLaunchForbiddenPipelineTests(unittest.TestCase):
    """Acceptance criterion 6, at the full `run_launch` level: each of the
    five forbidden flags/behaviors, passed through as `extra_args`, aborts
    before the mocked `subprocess` is ever called — one test per case."""

    def _run_with_extra_args(self, extra_args: list[str]):
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _KitFixture(Path(tmp), allowlist=["Bash(git status --short)"])
            recorder = _RecordingSubprocess("182689df\n")

            def ok_preflight(*args, **kwargs):
                return preflight.run_preflight(
                    *args, which=_fake_which({"git"}), list_sessions=_no_sessions, **kwargs
                )

            result = launch_claude.run_launch(
                fixture.state_path, 1, kit_root=fixture.kit_root,
                run_preflight=ok_preflight, run_subprocess=recorder, extra_args=extra_args,
            )
            self.assertFalse(result.ok)
            self.assertEqual(recorder.calls, [], f"must never call the mocked subprocess for {extra_args!r}")
            return result

    def test_pipeline_refuses_bypass_permissions(self):
        self._run_with_extra_args(["--permission-mode", "bypassPermissions"])

    def test_pipeline_refuses_permission_prompts_none(self):
        self._run_with_extra_args(["--permission-prompts", "none"])

    def test_pipeline_refuses_resume(self):
        self._run_with_extra_args(["--resume", "some-id"])

    def test_pipeline_refuses_continue(self):
        self._run_with_extra_args(["--continue"])

    def test_pipeline_refuses_fork_session(self):
        self._run_with_extra_args(["--fork-session"])


if __name__ == "__main__":
    unittest.main()
