"""Tests for scripts/marina — the Stop hook `hook require-receipt`.

The hook keeps a background specialist from ending its session until its
receipt exists and passes receipt-lint (spec §3.5; F1 findings H4). Every
test writes its receipt/handoff into a temporary directory; nothing here
reads the real, git-ignored `.agent-state/` or invokes the Claude CLI.
"""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.marina import cli, hooks

KIT_ROOT = Path(__file__).resolve().parent.parent
GOOD_RECEIPT = KIT_ROOT / "tests" / "fixtures" / "receipts" / "good-node-backend-receipt.md"


def _write_pair(tmp: str, *, receipt_text: str | None = None) -> tuple[Path, Path]:
    """Write a node-backend receipt and a handoff whose profile matches it."""

    receipt = Path(tmp) / "01-node-backend-receipt.md"
    handoff = Path(tmp) / "01-node-backend-handoff.md"
    if receipt_text is None:
        receipt_text = GOOD_RECEIPT.read_text(encoding="utf-8")
    receipt.write_text(receipt_text.replace("__KIT_ROOT__", str(KIT_ROOT)), encoding="utf-8")
    handoff.write_text(
        f"# demo\n\n- **Absolute profile (read explicitly):** `{KIT_ROOT}/.claude/agents/node-backend.md`\n",
        encoding="utf-8",
    )
    return receipt, handoff


class RequireReceiptTests(unittest.TestCase):
    def test_stop_hook_active_always_releases(self):
        code, _ = hooks.require_receipt({"stop_hook_active": True}, receipt=Path("/nonexistent"), handoff=Path("/nonexistent"))
        self.assertEqual(code, 0)

    def test_missing_receipt_blocks_with_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "01-node-backend-receipt.md"
            code, msg = hooks.require_receipt({"stop_hook_active": False}, receipt=receipt, handoff=Path(tmp) / "h.md")
            self.assertEqual(code, 2)
            self.assertIn(str(receipt), msg)
            self.assertIn("needs_input", msg)

    def test_unreadable_handoff_is_non_blocking(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt = Path(tmp) / "01-node-backend-receipt.md"
            receipt.write_text("x\n", encoding="utf-8")
            code, msg = hooks.require_receipt({}, receipt=receipt, handoff=Path(tmp) / "missing-handoff.md")
            self.assertEqual(code, 1)
            self.assertIn("missing-handoff.md", msg)

    def test_invalid_receipt_blocks_with_lint_errors(self):
        text = GOOD_RECEIPT.read_text(encoding="utf-8").replace("## Status\n\ndone\n\n", "")
        with tempfile.TemporaryDirectory() as tmp:
            receipt, handoff = _write_pair(tmp, receipt_text=text)
            code, msg = hooks.require_receipt({"stop_hook_active": False}, receipt=receipt, handoff=handoff)
            self.assertEqual(code, 2)
            self.assertIn("receipt-lint", msg)
            self.assertIn("status", msg)

    def test_valid_receipt_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt, handoff = _write_pair(tmp)
            code, msg = hooks.require_receipt({"stop_hook_active": False}, receipt=receipt, handoff=handoff)
            self.assertEqual((code, msg), (0, ""))


class CliTests(unittest.TestCase):
    def _run(self, argv, stdin_text):
        err = io.StringIO()
        code = cli.main(argv, stdin=io.StringIO(stdin_text), stderr=err)
        return code, err.getvalue()

    def test_invalid_hook_input_is_non_blocking(self):
        for text in ("", "not json", "[1, 2]"):
            with self.subTest(text=text):
                code, err = self._run(["hook", "require-receipt", "--receipt", "/r", "--handoff", "/h"], text)
                self.assertEqual(code, 1)
                self.assertTrue(err)

    def test_bad_arguments_are_non_blocking(self):
        # argparse exits 2 on bad arguments, which a Stop hook reads as "block"; it
        # fails before stop_hook_active is read, so every Stop would block again.
        for argv in (
            ["hook", "require-receipt", "--receipt", "/r"],
            ["hook", "require-receipt"],
            ["hook", "unknown-hook"],
            [],
        ):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                code, err = self._run(argv, '{"stop_hook_active": true}')
                self.assertEqual(code, 1)
                self.assertTrue(err)

    def test_block_message_goes_to_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, err = self._run(
                ["hook", "require-receipt", "--receipt", f"{tmp}/r.md", "--handoff", f"{tmp}/h.md"],
                '{"hook_event_name": "Stop", "stop_hook_active": false}',
            )
            self.assertEqual(code, 2)
            self.assertIn("receipt missing", err)

    def test_valid_receipt_exits_zero_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            receipt, handoff = _write_pair(tmp)
            code, err = self._run(
                ["hook", "require-receipt", "--receipt", str(receipt), "--handoff", str(handoff)],
                '{"stop_hook_active": false}',
            )
            self.assertEqual((code, err), (0, ""))

    def test_runs_as_a_script_by_path(self):
        # The Stop hook invokes the file by absolute path from an arbitrary cwd.
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(KIT_ROOT / "scripts" / "marina" / "__main__.py"), "hook", "require-receipt",
                 "--receipt", f"{tmp}/r.md", "--handoff", f"{tmp}/h.md"],
                input='{"stop_hook_active": true}', capture_output=True, text=True, cwd=tmp, timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
