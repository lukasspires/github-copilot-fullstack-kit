"""Tests for scripts/common.py helpers: secret heuristic, profile-path
extraction, risk-title normalization, manager schema validation, git
status/diff formatting, and CLI-version header parsing.

Deterministic; git/manager subprocess calls are injected fakes, never the
real installed CLI.
"""

from __future__ import annotations

import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import common


class SecretHeuristicTests(unittest.TestCase):
    def test_plain_text_is_not_a_secret(self):
        self.assertFalse(common.looks_like_secret("Read the kit operating guide from kit_root."))

    def test_private_key_header_is_a_secret(self):
        self.assertTrue(common.looks_like_secret("-----BEGIN RSA PRIVATE KEY-----\nMIIB...\n"))

    def test_aws_key_id_is_a_secret(self):
        self.assertTrue(common.looks_like_secret("key=AKIAABCDEFGHIJKLMNOP"))

    def test_github_token_is_a_secret(self):
        self.assertTrue(common.looks_like_secret("ghp_" + "a" * 36))

    def test_key_value_assignment_is_a_secret(self):
        self.assertTrue(common.looks_like_secret('api_key: "sk-1234567890abcdef"'))

    def test_word_token_without_value_is_not_a_secret(self):
        self.assertFalse(common.looks_like_secret("native tool approvals remain in this execution"))


class ExtractProfilePathTests(unittest.TestCase):
    def test_current_template_with_backticks(self):
        text = "- **Absolute profile (read explicitly):** `/mnt/kit/.claude/agents/kit-tooling.md`"
        self.assertEqual(common.extract_profile_path(text), "/mnt/kit/.claude/agents/kit-tooling.md")

    def test_older_ad_hoc_format(self):
        text = "Profile: /mnt/dados/GitHub/github-copilot-fullstack-kit/.claude/agents/reviewer.md"
        self.assertEqual(
            common.extract_profile_path(text),
            "/mnt/dados/GitHub/github-copilot-fullstack-kit/.claude/agents/reviewer.md",
        )

    def test_receipt_profile_read_field(self):
        text = "- **profile_read:** /mnt/kit/.claude/agents/reviewer.md"
        self.assertEqual(common.extract_profile_path(text), "/mnt/kit/.claude/agents/reviewer.md")

    def test_heading_only_line_is_skipped(self):
        text = "## Profile and Instructions Read\n\n- **profile_read:** /abs/path.md\n"
        self.assertEqual(common.extract_profile_path(text), "/abs/path.md")

    def test_no_profile_mentioned_returns_none(self):
        self.assertIsNone(common.extract_profile_path("nothing relevant here"))


class RiskTitleTests(unittest.TestCase):
    def test_find_risk_titles(self):
        text = (
            "## Risks\n\n"
            "### RISK 1: Permission Enforcement Reliance on Instructions (Severity: Medium)\n"
            "body\n\n"
            "### RISK 2: Worktree.bgIsolation Setting Not Yet Validated in Practice (Severity: Medium)\n"
        )
        titles = common.find_risk_titles(text)
        self.assertEqual(
            titles,
            [
                "Permission Enforcement Reliance on Instructions (Severity: Medium)",
                "Worktree.bgIsolation Setting Not Yet Validated in Practice (Severity: Medium)",
            ],
        )

    def test_normalize_strips_severity_and_punctuation(self):
        raw = "Worktree.bgIsolation Setting Not Yet Validated in Practice (Severity: Medium)"
        self.assertEqual(
            common.normalize_risk_title(raw), "worktree bgisolation setting not yet validated in practice"
        )

    def test_normalize_preserves_hyphenated_compounds(self):
        raw = "Unexecuted Visible-Session Runtime Scenarios (Severity: Medium)"
        self.assertEqual(common.normalize_risk_title(raw), "unexecuted visible-session runtime scenarios")

    def test_normalize_keeps_digits(self):
        raw = "Carrying Forward Unexecuted Scenario Risk from Assignment 02 (Severity: Medium)"
        self.assertEqual(
            common.normalize_risk_title(raw), "carrying forward unexecuted scenario risk from assignment 02"
        )

    def test_normalize_inherited_severity_label(self):
        raw = "Permission Model Still Relies on Instructions Rather than Tooling (Severity: Inherited)"
        self.assertEqual(
            common.normalize_risk_title(raw),
            "permission model still relies on instructions rather than tooling",
        )

    def test_find_risk_titles_with_parenthetical_annotation(self):
        """Finding 4 (tooling-gaps-fix): real receipts commonly write
        `### RISK n (annotation): title` — a parenthetical between the
        number and the colon. Before the fix this silently produced an
        empty `risks_digest` (no parse error). The parenthetical itself
        must not leak into the captured title."""

        text = (
            "## Risks\n\n"
            "### RISK 1 (carried forward from 01 receipt, independently reproduced and endorsed): "
            "`receipt_lint.py` does not parse this project's actual current receipt convention "
            "(Severity: Medium — pre-existing Etapa 1 gap, not introduced by this assignment)\n"
            "body\n\n"
            "### RISK 2 (carried forward, now resolved): `find_task_sessions`'s original OR semantics "
            "(Severity: Low — fixed and tested, independently verified in this review)\n"
        )
        titles = common.find_risk_titles(text)
        self.assertEqual(
            titles,
            [
                "`receipt_lint.py` does not parse this project's actual current receipt convention "
                "(Severity: Medium — pre-existing Etapa 1 gap, not introduced by this assignment)",
                "`find_task_sessions`'s original OR semantics "
                "(Severity: Low — fixed and tested, independently verified in this review)",
            ],
        )

    def test_find_risk_titles_plain_form_still_matches(self):
        """Regression: the plain `### RISK n: title` shape (no
        parenthetical) already covered by `test_find_risk_titles` above
        must keep matching after the Finding 4 fix."""

        text = "### RISK 1: Plain Title With No Parenthetical\n"
        self.assertEqual(common.find_risk_titles(text), ["Plain Title With No Parenthetical"])


class ManagerSchemaTests(unittest.TestCase):
    def test_valid_session_passes(self):
        common.validate_manager_session_schema({"name": "task — role — 01", "state": "working"})

    def test_missing_name_fails_loudly(self):
        with self.assertRaises(common.ManagerSchemaError):
            common.validate_manager_session_schema({"state": "working"})

    def test_unknown_state_fails_loudly(self):
        with self.assertRaises(common.ManagerSchemaError):
            common.validate_manager_session_schema({"name": "x", "state": "sleeping"})

    def test_state_may_be_absent_interactive_session(self):
        common.validate_manager_session_schema({"name": "x"})

    def test_waiting_without_waiting_for_fails_loudly(self):
        with self.assertRaises(common.ManagerSchemaError):
            common.validate_manager_session_schema({"name": "x", "status": "waiting"})

    def test_non_dict_entry_fails_loudly(self):
        with self.assertRaises(common.ManagerSchemaError):
            common.validate_manager_session_schema("not-a-dict")


class GitStatusDiffTests(unittest.TestCase):
    def test_format_matches_kit_convention(self):
        calls = []

        def fake_runner(args, *, cwd, timeout):
            calls.append((tuple(args), cwd, timeout))
            if args[0] == "status":
                return " M foo.py\n"
            return " foo.py | 2 +-\n"

        text = common.git_status_diff("/tmp/x", runner=fake_runner)
        self.assertEqual(
            text, "# git status --short\n M foo.py\n\n# git diff --stat\n foo.py | 2 +-\n# untracked sha256\n"
        )
        self.assertEqual(calls[0][0], ("status", "--short"))
        self.assertEqual(calls[1][0], ("diff", "--stat"))

    def test_untracked_files_are_hashed(self):
        # F6 acceptance A7: a reviewer must be able to tell that a preexisting
        # untracked file kept its content, which `status --short` cannot show.
        def fake_runner(args, *, cwd, timeout):
            if args[:2] == ["status", "--porcelain=v1"]:
                return " M foo.py\0?? NOTES.md\0?? dir/a b.txt\0"
            return " M foo.py\n?? NOTES.md\n" if args[0] == "status" else ""

        def read_bytes(path):
            if path.name == "a b.txt":
                raise PermissionError("denied")
            return b"notes"

        text = common.git_status_diff("/repo", runner=fake_runner, read_bytes=read_bytes)
        section = text.split("# untracked sha256\n")[1]
        self.assertEqual(section, f"{hashlib.sha256(b'notes').hexdigest()}  NOTES.md\nunreadable  dir/a b.txt\n")


class CliVersionHeaderTests(unittest.TestCase):
    def test_declared_version_parsed(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "example.py"
            script.write_text('"""Minimum tested Claude CLI version: 2.1.267"""\n')
            self.assertEqual(common.declared_cli_version(script), "2.1.267")

    def test_missing_header_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "example.py"
            script.write_text('"""no header here"""\n')
            with self.assertRaises(ValueError):
                common.declared_cli_version(script)

    def test_parse_version(self):
        self.assertEqual(common.parse_version("2.1.267 (Claude Code)"), (2, 1, 267))
        self.assertIsNone(common.parse_version("no version here"))


class ClaudeSubprocessStdinTests(unittest.TestCase):
    """A child `claude` reads inherited stdin and acts on it (F1, X1), so
    every call the kit makes closes it."""

    def _patched(self, stdout: str):
        completed = subprocess.CompletedProcess(["claude"], 0, stdout=stdout, stderr="")
        return (
            mock.patch.object(common.shutil, "which", return_value="/usr/bin/claude"),
            mock.patch.object(common.subprocess, "run", return_value=completed),
        )

    def test_list_manager_sessions_closes_stdin(self):
        which, run = self._patched("[]")
        with which, run as fake_run:
            self.assertEqual(common.list_manager_sessions(), [])
        self.assertIs(fake_run.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_installed_claude_version_closes_stdin(self):
        which, run = self._patched("2.1.306 (Claude Code)")
        with which, run as fake_run:
            self.assertEqual(common.installed_claude_version(), "2.1.306 (Claude Code)")
        self.assertIs(fake_run.call_args.kwargs["stdin"], subprocess.DEVNULL)


class GitSnapshotTests(unittest.TestCase):
    """`git_snapshot` (F4): status + full diff hash + untracked content hashes."""

    def _runner(self, *, status: str = " M a.py\0?? new.txt\0", diff: str = "diff --git a/a.py\n+x\n"):
        calls: list[list[str]] = []

        def runner(args, *, cwd, timeout):
            calls.append(list(args))
            if args[0] == "status":
                return status
            if args[0] == "diff":
                return diff
            if args[0] == "rev-parse":
                return "feat/x\n"
            raise AssertionError(args)

        return runner, calls

    def _snapshot(self, runner, content: bytes = b"hello") -> str:
        return common.git_snapshot("/repo", runner=runner, read_bytes=lambda p: content)

    def test_snapshot_changes_with_diff_content(self):
        first, _ = self._runner(diff="diff --git a/a.py\n+x\n")
        second, _ = self._runner(diff="diff --git a/a.py\n+y\n")
        self.assertNotEqual(self._snapshot(first), self._snapshot(second))

    def test_untracked_content_change_is_foreign(self):
        runner, _ = self._runner()
        self.assertNotEqual(self._snapshot(runner, b"hello"), self._snapshot(runner, b"hello!"))

    def test_snapshot_is_stable(self):
        runner, _ = self._runner()
        self.assertEqual(self._snapshot(runner), self._snapshot(runner))

    def test_snapshot_lists_untracked_files(self):
        runner, _ = self._runner(status="?? b.txt\0?? a.txt\0")
        seen: list[Path] = []
        common.git_snapshot("/repo", runner=runner, read_bytes=lambda p: seen.append(p) or b"x")
        self.assertEqual(seen, [Path("/repo/a.txt"), Path("/repo/b.txt")])

    def test_accented_and_renamed_paths_are_read_unquoted(self):
        runner, calls = self._runner(status="?? an\u00e1lise.md\0R  novo.py\0velho.py\0?? dir/x y.txt\0")
        seen: list[Path] = []
        common.git_snapshot("/repo", runner=runner, read_bytes=lambda p: seen.append(p) or b"x")
        self.assertEqual(seen, [Path("/repo/an\u00e1lise.md"), Path("/repo/dir/x y.txt")])
        self.assertIn("-z", calls[0])

    def test_failed_git_raises_instead_of_empty_snapshot(self):
        failed = subprocess.CompletedProcess(["git"], 128, "", "fatal: not a git repository")
        with mock.patch("scripts.common.subprocess.run", return_value=failed):
            with self.assertRaises(common.GitCommandFailed):
                common.git_snapshot("/repo")
            with self.assertRaises(common.GitCommandFailed):
                common.git_current_branch("/repo")

    def test_current_branch_strips(self):
        runner, _ = self._runner()
        self.assertEqual(common.git_current_branch("/repo", runner=runner), "feat/x")

    def test_git_calls_are_read_only(self):
        runner, calls = self._runner()
        self._snapshot(runner)
        common.git_current_branch("/repo", runner=runner)
        self.assertTrue(calls)
        self.assertTrue(all(c[0] in ("status", "diff", "rev-parse") for c in calls), calls)


if __name__ == "__main__":
    unittest.main()
