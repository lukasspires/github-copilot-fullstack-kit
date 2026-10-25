"""Tests for scripts/kit_lint.py.

Positive checks run against the real kit_root (read-only: parsing and
byte-comparison only, no writes) to satisfy the handoff's acceptance
criterion 6. Deliberate-break tests use a disposable temp directory,
never the real kit files. `check_unittests`/`check_git_diff` are tested with an injected
fake subprocess runner to avoid ever re-invoking the whole suite from
within itself (which would recurse).
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from scripts import kit_lint

REAL_KIT_ROOT = Path(__file__).resolve().parent.parent


class RealKitPositiveTests(unittest.TestCase):
    """These exercise the actual kit_root; read-only, no writes."""

    def test_agent_profiles_pass_on_real_kit(self):
        result = kit_lint.check_agent_profiles(REAL_KIT_ROOT)
        self.assertTrue(result.ok, result.details)

    def test_no_foreign_runtime_passes_on_real_kit(self):
        result = kit_lint.check_no_foreign_runtime(REAL_KIT_ROOT)
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

    def test_run_all_order(self):
        # Patch the suite runner so run_all never re-invokes the test suite recursively.
        fake = lambda kit_root, **_: kit_lint.CheckResult("unittest_suite", True, [])
        with unittest.mock.patch.object(kit_lint, "check_unittests", fake):
            results = kit_lint.run_all(REAL_KIT_ROOT)
        self.assertEqual(
            [r.name for r in results],
            ["agent_profiles", "no_foreign_runtime", "git_diff_check", "cli_version_headers", "state_lint", "unittest_suite"],
        )


def _write_profile(root: Path, filename: str, text: str) -> None:
    (root / ".claude" / "agents").mkdir(parents=True, exist_ok=True)
    (root / ".claude" / "agents" / filename).write_text(text, encoding="utf-8")


class AgentProfilesTests(unittest.TestCase):
    """Deliberate breaks in a disposable copy only, never the real kit files."""

    def test_valid_profile_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", '---\nname: demo\ndescription: "Demo."\n---\n\nBody.\n')
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertTrue(result.ok, result.details)

    def test_no_profiles_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("no *.md profiles" in d for d in result.details))

    def test_name_differs_from_filename_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", '---\nname: other\ndescription: "Demo."\n---\n\nBody.\n')
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("demo" in d and "name" in d for d in result.details))

    def test_missing_description_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", "---\nname: demo\n---\n\nBody.\n")
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("description" in d for d in result.details))

    def test_empty_body_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", '---\nname: demo\ndescription: "Demo."\n---\n\n')
            result = kit_lint.check_agent_profiles(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any("body" in d for d in result.details))

    def test_missing_frontmatter_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_profile(Path(tmp), "demo.md", "Body only.\n")
            self.assertFalse(kit_lint.check_agent_profiles(Path(tmp)).ok)


class NoForeignRuntimeTests(unittest.TestCase):
    def test_clean_root_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(kit_lint.check_no_foreign_runtime(Path(tmp)).ok)

    def test_codex_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".codex" / "agents").mkdir(parents=True)
            result = kit_lint.check_no_foreign_runtime(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any(".codex" in d for d in result.details))

    def test_agents_dir_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / ".agents" / "skills" / "demo").mkdir(parents=True)
            (Path(tmp) / ".agents" / "skills" / "demo" / "SKILL.md").write_text("x\n", encoding="utf-8")
            result = kit_lint.check_no_foreign_runtime(Path(tmp))
            self.assertFalse(result.ok)
            self.assertTrue(any(".agents" in d for d in result.details))


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
