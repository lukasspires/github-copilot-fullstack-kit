"""Tests for scripts/kit_lint.py.

Positive checks run against the real kit_root (read-only: parsing and
byte-comparison only, no writes) to satisfy the handoff's acceptance
criterion 6. The deliberate-break test (criterion 7) uses a disposable
temp copy of a *minimal* two-file profile pair, never the real kit
files. `check_unittests`/`check_git_diff` are tested with an injected
fake subprocess runner to avoid ever re-invoking the whole suite from
within itself (which would recurse).
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import kit_lint

REAL_KIT_ROOT = Path(__file__).resolve().parent.parent


class RealKitPositiveTests(unittest.TestCase):
    """These exercise the actual kit_root; read-only, no writes."""

    def test_agent_profile_parity_passes_on_real_kit(self):
        result = kit_lint.check_agent_profile_parity(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)

    def test_instructions_parity_passes_on_real_kit(self):
        result = kit_lint.check_instructions_parity(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)

    def test_skills_identity_passes_on_real_kit(self):
        result = kit_lint.check_skills_identity(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)

    def test_git_diff_check_passes_on_real_kit(self):
        result = kit_lint.check_git_diff(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)

    def test_state_lint_passes_on_default_fixture(self):
        result = kit_lint.check_state_lint(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)

    def test_cli_version_headers_present_on_real_scripts(self):
        result = kit_lint.check_cli_versions(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)


def _write_profile_pair(root: Path, role: str, *, md_body: str, toml_body: str) -> None:
    (root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".codex" / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "agents" / f"{role}.md").write_text(
        f'---\nname: {role}\ndescription: "Demo role."\n---\n\n{md_body}\n', encoding="utf-8"
    )
    (root / ".codex" / "agents" / f"{role}.toml").write_text(
        'name = "%s"\ndescription = "Demo role."\ndeveloper_instructions = """\n%s\n"""\n' % (role, toml_body),
        encoding="utf-8",
    )


class DeliberateParityBreakTests(unittest.TestCase):
    """Acceptance criterion 7: kit-lint fails loudly and specifically on a
    deliberate parity break, in a disposable copy only."""

    def test_matching_pair_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_profile_pair(root, "demo-role", md_body="Do the thing.", toml_body="Do the thing.")
            result = kit_lint.check_agent_profile_parity(root)
            self.assertTrue(result.ok, result.details)

    def test_diverging_body_fails_specifically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_profile_pair(
                root, "demo-role", md_body="Do the thing.", toml_body="Do a DIFFERENT thing entirely."
            )
            result = kit_lint.check_agent_profile_parity(root)
            self.assertFalse(result.ok)
            self.assertTrue(any("demo-role" in d and "body differs" in d for d in result.details))

    def test_missing_codex_counterpart_fails_specifically(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude" / "agents").mkdir(parents=True)
            (root / ".codex" / "agents").mkdir(parents=True)
            (root / ".claude" / "agents" / "orphan-role.md").write_text(
                '---\nname: orphan-role\n---\nBody.\n', encoding="utf-8"
            )
            result = kit_lint.check_agent_profile_parity(root)
            self.assertFalse(result.ok)
            self.assertTrue(any("orphan-role" in d and "missing Codex counterpart" in d for d in result.details))

    def test_normalization_ignores_native_path_and_backticks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_profile_pair(
                root,
                "demo-role",
                md_body="Read `<kit_root>/.claude/instructions/demo-role.md`.",
                toml_body="Read <kit_root>/.codex/instructions/demo-role.md.",
            )
            result = kit_lint.check_agent_profile_parity(root)
            self.assertTrue(result.ok, result.details)


class InstructionsAndSkillsBreakTests(unittest.TestCase):
    def test_instructions_not_byte_identical_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude" / "instructions").mkdir(parents=True)
            (root / ".codex" / "instructions").mkdir(parents=True)
            (root / ".claude" / "instructions" / "x.md").write_text("same\n", encoding="utf-8")
            (root / ".codex" / "instructions" / "x.md").write_text("different\n", encoding="utf-8")
            result = kit_lint.check_instructions_parity(root)
            self.assertFalse(result.ok)

    def test_skills_missing_codex_counterpart_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude" / "skills" / "demo").mkdir(parents=True)
            (root / ".agents" / "skills").mkdir(parents=True)
            (root / ".claude" / "skills" / "demo" / "SKILL.md").write_text("body\n", encoding="utf-8")
            result = kit_lint.check_skills_identity(root)
            self.assertFalse(result.ok)

    def test_skills_openai_yaml_exception_does_not_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".claude" / "skills" / "demo").mkdir(parents=True)
            (root / ".agents" / "skills" / "demo" / "agents").mkdir(parents=True)
            (root / ".claude" / "skills" / "demo" / "SKILL.md").write_text("body\n", encoding="utf-8")
            (root / ".agents" / "skills" / "demo" / "SKILL.md").write_text("body\n", encoding="utf-8")
            (root / ".agents" / "skills" / "demo" / "agents" / "openai.yaml").write_text("x: 1\n", encoding="utf-8")
            result = kit_lint.check_skills_identity(root)
            self.assertTrue(result.ok, result.details)


class InjectedRunnerTests(unittest.TestCase):
    """Avoids ever spawning a real nested `unittest discover` from within
    the suite itself (which would recurse)."""

    def test_check_unittests_ok_on_zero_exit(self):
        def fake_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="OK\n", stderr="")

        result = kit_lint.check_unittests(REAL_KIT_ROOT, runner=fake_runner)
        self.assertTrue(result.ok)

    def test_check_unittests_fails_on_nonzero_exit_with_tail(self):
        def fake_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="FAILED (failures=1)\n")

        result = kit_lint.check_unittests(REAL_KIT_ROOT, runner=fake_runner)
        self.assertFalse(result.ok)
        self.assertTrue(any("FAILED" in d for d in result.details))

    def test_check_git_diff_ok_on_zero_exit(self):
        def fake_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        result = kit_lint.check_git_diff(REAL_KIT_ROOT, runner=fake_runner)
        self.assertTrue(result.ok)

    def test_check_git_diff_fails_with_detail(self):
        def fake_runner(*args, **kwargs):
            return subprocess.CompletedProcess(args, 2, stdout="foo.py:1: trailing whitespace.\n", stderr="")

        result = kit_lint.check_git_diff(REAL_KIT_ROOT, runner=fake_runner)
        self.assertFalse(result.ok)
        self.assertIn("trailing whitespace", result.details[0])


class CliVersionDriftTests(unittest.TestCase):
    def test_declares_but_installed_is_older_reports_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "example.py").write_text(
                '"""Minimum tested Claude CLI version: 9.9.9"""\n'
                "if __name__ == \"__main__\":\n    pass\n",
                encoding="utf-8",
            )
            result = kit_lint.check_cli_versions(root, installed_version=lambda: "1.0.0 (Claude Code)")
            self.assertFalse(result.ok)
            self.assertTrue(any("9.9.9" in d for d in result.details))

    def test_missing_header_reported_even_without_installed_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            (root / "scripts" / "example.py").write_text(
                "if __name__ == \"__main__\":\n    pass\n", encoding="utf-8"
            )
            result = kit_lint.check_cli_versions(root, installed_version=lambda: None)
            self.assertFalse(result.ok)

    def test_no_executable_scripts_is_a_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            result = kit_lint.check_cli_versions(root, installed_version=lambda: None)
            self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()
