"""Tests for scripts/common.py helpers: secret heuristic, profile-path
extraction, risk-title normalization, manager schema validation, git
status/diff formatting, and CLI-version header parsing.

Deterministic; git/manager subprocess calls are injected fakes, never the
real installed CLI.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
        self.assertEqual(text, "# git status --short\n M foo.py\n\n# git diff --stat\n foo.py | 2 +-\n")
        self.assertEqual(calls[0][0], ("status", "--short"))
        self.assertEqual(calls[1][0], ("diff", "--stat"))


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


if __name__ == "__main__":
    unittest.main()
