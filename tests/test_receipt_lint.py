"""Tests for scripts/receipt_lint.py — canonical heading-based field
extraction (docs/agent-workflow.md, "Handoffs and continuity", "Canonical
receipt structure"), required fields/enums, and risks_digest extraction.

Uses small synthetic fixtures under tests/fixtures/receipts/ (never the
real, git-ignored .agent-state/ contents) for the general regression
suite, covering both the combined `## Profile and Instructions Read`
heading shape and the two-separate-headings (`## profile_read` / `##
instructions_read`) shape, including the narrow inline `**status:**`/
`**verdict:**` fallback the latter shape sometimes needs (real example:
.agent-state/.../kit-tooling-role/{01,02}-reviewer-receipt.md).

The cross-check against the 10 real, already-accepted receipt/handoff
pairs named in this task's handoff, and against the two legacy
`.agent-state/visible-sessions/{02,03}-reviewer-receipt.md` files
(explicitly not required to pass), is exercised manually via the CLI and
reported as receipt evidence, not here, per the instruction that
`unittest` never depends on real `.agent-state/` content.
"""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from scripts import receipt_lint

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "receipts"


class ParseReceiptCombinedHeadingTests(unittest.TestCase):
    """Combined `## Profile and Instructions Read` heading shape."""

    def test_good_reviewer_receipt_parses_all_fields(self):
        text = (FIXTURES / "good-reviewer-receipt.md").read_text(encoding="utf-8")
        data = receipt_lint.parse_receipt(text)
        self.assertEqual(data.status, "done")
        self.assertEqual(
            data.profile_read, "/mnt/dados/GitHub/github-copilot-fullstack-kit/.claude/agents/reviewer.md"
        )
        self.assertEqual(len(data.instructions_read), 2)
        self.assertEqual(data.verdict, "PASS_WITH_RISKS")
        self.assertEqual(len(data.risks_titles), 2)

    def test_trailing_prose_on_an_instructions_read_line_is_ignored(self):
        # good-reviewer-receipt.md's second instructions_read line carries a
        # "(read-only reference)" annotation after the backtick-quoted path
        # (acceptance criterion 3: do not omit useful annotations to
        # satisfy a linter, but do not let them break path extraction).
        text = (FIXTURES / "good-reviewer-receipt.md").read_text(encoding="utf-8")
        data = receipt_lint.parse_receipt(text)
        self.assertIn(
            "/mnt/dados/GitHub/github-copilot-fullstack-kit/CLAUDE.md", data.instructions_read
        )
        for path in data.instructions_read:
            self.assertNotIn("(", path)

    def test_role_from_filename(self):
        self.assertEqual(receipt_lint.role_from_filename("02-reviewer-receipt.md"), "reviewer")
        self.assertEqual(receipt_lint.role_from_filename("01-node-backend-receipt.md"), "node-backend")
        self.assertIsNone(receipt_lint.role_from_filename("not-a-receipt.md"))

    def test_prose_bullet_with_relative_fragments_is_not_a_false_instructions_read_entry(self):
        # Regression for a real shape found in this kit's own accepted
        # receipts (gate-launch-scripts/{01,03}-kit-tooling-receipt.md):
        # an instructions_read bullet may be a descriptive sentence that
        # happens to backtick-quote one or more *relative* fragments
        # ("Every file under `scripts/` and `tests/`...", or a bare list
        # of relative filenames) rather than declaring its own absolute
        # path. Such a bullet must not be counted as an instructions_read
        # entry at all (and must therefore never trip a false "not
        # absolute" defect) — only the genuinely absolute-path bullet in
        # the same list is counted.
        text = (FIXTURES / "good-reviewer-prose-bullet-receipt.md").read_text(encoding="utf-8")
        data = receipt_lint.parse_receipt(text)
        self.assertEqual(
            data.instructions_read,
            ["/mnt/dados/GitHub/github-copilot-fullstack-kit/AGENTS.md"],
        )
        errors, _ = receipt_lint.lint_receipt(text, role="reviewer")
        self.assertEqual(errors, [])


class ParseReceiptSeparateHeadingsTests(unittest.TestCase):
    """Two-separate-headings shape (`## profile_read` / `## instructions_read`)."""

    def test_heading_based_status_and_verdict_parse(self):
        text = (FIXTURES / "good-reviewer-separate-headings-receipt.md").read_text(encoding="utf-8")
        data = receipt_lint.parse_receipt(text)
        self.assertEqual(data.status, "done")
        self.assertEqual(data.verdict, "PASS")
        self.assertEqual(
            data.profile_read, "/mnt/dados/GitHub/github-copilot-fullstack-kit/.claude/agents/reviewer.md"
        )
        self.assertEqual(len(data.instructions_read), 2)

    def test_profile_read_section_body_need_not_repeat_the_field_name(self):
        # The "## profile_read" section's own body is just a bare bullet
        # naming the path, with no "profile_read:" text repeated inside it
        # (real example: kit-tooling-role's receipts) — acceptance
        # criterion / handoff item 2's documented fallback.
        text = (FIXTURES / "good-reviewer-separate-headings-receipt.md").read_text(encoding="utf-8")
        data = receipt_lint.parse_receipt(text)
        self.assertTrue(data.profile_read.endswith("reviewer.md"))

    def test_inline_status_and_verdict_fallback_when_no_heading_present(self):
        # Real shape: kit-tooling-role/{01,02}-reviewer-receipt.md use
        # **status:**/**verdict:** markers in the preamble, before any
        # heading, alongside heading-based profile_read/instructions_read.
        text = (FIXTURES / "inline-status-verdict-separate-headings-receipt.md").read_text(encoding="utf-8")
        data = receipt_lint.parse_receipt(text)
        self.assertEqual(data.status, "done")
        self.assertEqual(data.verdict, "FAIL")
        self.assertEqual(len(data.instructions_read), 1)


class LegacyFormatNotSupportedTests(unittest.TestCase):
    def test_inline_bold_status_without_heading_and_combined_profile_section_fails(self):
        # This mirrors the two legacy .agent-state/visible-sessions/{02,03}
        # receipts' shape: **Status:** inline with no heading, but the
        # profile/instructions section uses the *combined* heading (not
        # the separate-headings shape) — so the narrow inline-status
        # fallback (scoped to the separate-headings shape only) does not
        # apply, and the older inline-bold format stays unsupported, per
        # this task's handoff item 5.
        text = (FIXTURES / "legacy-inline-bold-not-supported-receipt.md").read_text(encoding="utf-8")
        data = receipt_lint.parse_receipt(text)
        self.assertIsNone(data.status)
        # Verdict and profile/instructions still parse fine (they use a
        # heading / the combined section respectively) — only status is
        # actually unrecoverable in this shape.
        self.assertEqual(data.verdict, "PASS")
        self.assertIsNotNone(data.profile_read)

        errors, _ = receipt_lint.lint_receipt(text, role="reviewer")
        self.assertTrue(any(e.startswith("status") for e in errors))


class LintReceiptTests(unittest.TestCase):
    def test_good_reviewer_receipt_is_valid(self):
        text = (FIXTURES / "good-reviewer-receipt.md").read_text(encoding="utf-8")
        errors, summary = receipt_lint.lint_receipt(text, role="reviewer")
        self.assertEqual(errors, [])
        self.assertEqual(summary.status, "done")
        self.assertEqual(summary.verdict, "PASS_WITH_RISKS")
        self.assertTrue(summary.profile_ok)
        self.assertEqual(
            summary.risks_digest,
            ["example finding one", "second finding with a hyphenated-word"],
        )

    def test_good_node_backend_receipt_does_not_require_verdict(self):
        text = (FIXTURES / "good-node-backend-receipt.md").read_text(encoding="utf-8")
        errors, summary = receipt_lint.lint_receipt(text, role="node-backend")
        self.assertEqual(errors, [])
        self.assertEqual(summary.verdict, "")

    def test_good_reviewer_separate_headings_receipt_is_valid(self):
        text = (FIXTURES / "good-reviewer-separate-headings-receipt.md").read_text(encoding="utf-8")
        errors, summary = receipt_lint.lint_receipt(text, role="reviewer")
        self.assertEqual(errors, [])
        self.assertEqual(summary.status, "done")
        self.assertEqual(summary.verdict, "PASS")

    def test_inline_status_verdict_receipt_is_valid(self):
        text = (FIXTURES / "inline-status-verdict-separate-headings-receipt.md").read_text(encoding="utf-8")
        errors, summary = receipt_lint.lint_receipt(text, role="reviewer")
        self.assertEqual(errors, [])
        self.assertEqual(summary.status, "done")
        self.assertEqual(summary.verdict, "FAIL")

    def test_bad_reviewer_receipt_reports_all_defects(self):
        # instructions_read list-membership requires an absolute-shaped
        # candidate on the bullet itself (see
        # `_first_absolute_value_token`'s docstring — real receipts
        # interleave purely-descriptive/relative bullets in the same
        # list, which must not be surfaced as "not absolute" defects on
        # a field the receipt never actually populated). A bullet with
        # *only* a relative value is therefore silently not counted, so
        # this fixture's single relative instructions_read bullet
        # correctly reads as "missing or empty", not "not absolute" —
        # unlike profile_read, a single labeled field, which still
        # reports a genuinely-declared relative value as "not absolute".
        text = (FIXTURES / "bad-reviewer-receipt.md").read_text(encoding="utf-8")
        errors, summary = receipt_lint.lint_receipt(text, role="reviewer")
        joined = " ".join(errors)
        self.assertIn("status", joined)
        self.assertIn("verdict", joined)
        self.assertIn("profile_read is not an absolute path", joined)
        self.assertIn("instructions_read missing or empty", joined)
        self.assertFalse(summary.profile_ok)

    def test_reviewer_missing_verdict_alone_is_flagged(self):
        text = (
            "# t — reviewer — 01 — revisão\n\n"
            "## Status\n\ndone\n\n"
            "## Profile and Instructions Read\n\n"
            "- **profile_read:** `/abs/path.md`\n"
            "- **instructions_read:**\n"
            "  - `/abs/path.md`\n"
        )
        errors, _ = receipt_lint.lint_receipt(text, role="reviewer")
        self.assertTrue(any("verdict" in e for e in errors))

    def test_non_reviewer_role_never_requires_verdict(self):
        text = (
            "# t — node-backend — 01 — implementação\n\n"
            "## Status\n\ndone\n\n"
            "## Profile and Instructions Read\n\n"
            "- **profile_read:** `/abs/path.md`\n"
            "- **instructions_read:**\n"
            "  - `/abs/path.md`\n"
        )
        errors, _ = receipt_lint.lint_receipt(text, role="node-backend")
        self.assertFalse(any("verdict" in e for e in errors))

    def test_profile_read_mismatch_with_handoff_flagged(self):
        text = (FIXTURES / "good-node-backend-receipt.md").read_text(encoding="utf-8")
        errors, _ = receipt_lint.lint_receipt(text, role="node-backend", handoff_profile="/some/other/profile.md")
        self.assertTrue(any("does not match handoff profile" in e for e in errors))

    def test_secret_content_is_flagged(self):
        text = (FIXTURES / "secret-node-backend-receipt.md").read_text(encoding="utf-8")
        errors, _ = receipt_lint.lint_receipt(text, role="node-backend")
        self.assertTrue(any("secret" in e for e in errors))

    def test_invalid_status_enum_flagged(self):
        text = (
            "# t — node-backend — 01 — implementação\n\n"
            "## Status\n\nfinished\n\n"
            "## Profile and Instructions Read\n\n"
            "- **profile_read:** `/abs/path.md`\n"
            "- **instructions_read:**\n"
            "  - `/abs/path.md`\n"
        )
        errors, _ = receipt_lint.lint_receipt(text, role="node-backend")
        self.assertTrue(any(e.startswith("status") for e in errors))


class LintFileTests(unittest.TestCase):
    def test_lint_file_passes_explicit_role_through(self):
        path = FIXTURES / "good-reviewer-receipt.md"
        errors, summary = receipt_lint.lint_file(path, role="reviewer")
        self.assertEqual(errors, [])
        self.assertEqual(summary.verdict, "PASS_WITH_RISKS")

    def test_lint_file_infers_role_from_filename(self):
        # good-node-backend-receipt.md has no verdict, which is fine for its
        # real role (node-backend) but not for a reviewer receipt. Copy it to
        # a temp file literally named "NN-reviewer-receipt.md" and call
        # lint_file with role=None: if the role=None -> role_from_filename(path)
        # fallback fires, role is inferred as "reviewer" and the missing-verdict
        # error appears; if the fallback were broken (role stayed None), that
        # error would not appear. This distinguishes the two outcomes, unlike
        # passing role explicitly.
        text = (FIXTURES / "good-node-backend-receipt.md").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as tmp_dir:
            renamed = Path(tmp_dir) / "02-reviewer-receipt.md"
            renamed.write_text(text, encoding="utf-8")
            errors, summary = receipt_lint.lint_file(renamed, role=None)
        self.assertTrue(any("reviewer receipt requires a verdict" in e for e in errors))
        self.assertEqual(summary.verdict, "")


class MainCliTests(unittest.TestCase):
    def test_main_exit_code_0_on_valid_receipt(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = receipt_lint.main([str(FIXTURES / "good-reviewer-receipt.md"), "--role", "reviewer"])
        self.assertEqual(rc, 0)
        self.assertIn("PASS receipt_validated", buf.getvalue())
        self.assertIn("second finding with a hyphenated-word", buf.getvalue())

    def test_main_exit_code_1_on_invalid_receipt(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = receipt_lint.main([str(FIXTURES / "bad-reviewer-receipt.md"), "--role", "reviewer"])
        self.assertEqual(rc, 1)
        self.assertIn("FAIL receipt_invalid", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
