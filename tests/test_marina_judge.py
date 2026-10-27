"""Tests for scripts/marina/judge.py — the headless marina-judge adapter.

The subprocess is always a fake; every failure mode the spec lists (timeout,
invalid JSON, option not offered, budget, missing structured_output) must
raise `JudgeFailed`, which the runner turns into `stop(judge_failed)`.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from scripts.marina import judge
from scripts.marina.decide import Question

KIT_ROOT = Path(__file__).resolve().parent.parent
QUESTION = Question("pass_with_risks", 2, ("continue", "stop"))
PATHS = ["/kit/.agent-state/demo/tasks/t1/02-reviewer-receipt.md"]


class FakeRun:
    def __init__(self, stdout: str = "", returncode: int = 0, raises: Exception | None = None):
        self.stdout, self.returncode, self.raises = stdout, returncode, raises
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, "")


def _result(**overrides) -> str:
    payload = {"type": "result", "subtype": "success", "is_error": False,
               "structured_output": {"decision": "continue", "reason": "ok"}}
    payload.update(overrides)
    return json.dumps(payload)


class ArgvTests(unittest.TestCase):
    def test_argv_shape(self):
        argv = judge.build_argv(QUESTION, PATHS)
        self.assertEqual(argv[:4], ["claude", "-p", "--agent", "marina-judge"])
        self.assertEqual(argv[argv.index("--tools") + 1], "Read")
        self.assertEqual(argv[argv.index("--permission-mode") + 1], "dontAsk")
        self.assertEqual(argv[argv.index("--output-format") + 1], "json")
        self.assertEqual(argv[argv.index("--max-budget-usd") + 1], judge.JUDGE_MAX_BUDGET_USD)
        self.assertIn("--no-session-persistence", argv)
        self.assertIn("--strict-mcp-config", argv)
        self.assertNotIn("--mcp-config", argv)
        self.assertEqual(argv[-2], "--")
        self.assertIn(PATHS[0], argv[-1])
        for forbidden in ("--allowedTools", "bypassPermissions", "--permission-prompts", "--resume"):
            self.assertNotIn(forbidden, argv)

    def test_schema_enum_is_options(self):
        schema = judge.build_schema(("continue", "stop"))
        self.assertEqual(schema["properties"]["decision"]["enum"], ["continue", "stop"])
        self.assertEqual(schema["properties"]["reason"]["maxLength"], 200)
        self.assertFalse(schema["additionalProperties"])
        argv = judge.build_argv(QUESTION, PATHS)
        self.assertEqual(json.loads(argv[argv.index("--json-schema") + 1]), schema)

    def test_prompt_names_options_and_paths(self):
        prompt = judge.build_prompt(QUESTION, PATHS)
        for fragment in ("pass_with_risks", "nn=02", "continue", "stop", PATHS[0]):
            self.assertIn(fragment, prompt)


class AskTests(unittest.TestCase):
    def test_valid_answer(self):
        run = FakeRun(_result())
        self.assertEqual(judge.ask(QUESTION, PATHS, run_subprocess=run), judge.JudgeAnswer("continue", "ok"))
        self.assertIs(run.calls[0][1]["stdin"], subprocess.DEVNULL)
        self.assertEqual(run.calls[0][1]["timeout"], judge.JUDGE_TIMEOUT_S)

    def _fails(self, run: FakeRun, fragment: str) -> None:
        with self.assertRaises(judge.JudgeFailed) as ctx:
            judge.ask(QUESTION, PATHS, run_subprocess=run)
        self.assertIn(fragment, str(ctx.exception))

    def test_missing_structured_output_fails(self):
        payload = {"type": "result", "subtype": "success", "is_error": False, "result": "I choose continue."}
        self._fails(FakeRun(json.dumps(payload)), "structured_output")

    def test_option_not_offered_fails(self):
        self._fails(FakeRun(_result(structured_output={"decision": "corrige", "reason": "x"})), "not offered")

    def test_timeout_fails(self):
        self._fails(FakeRun(raises=subprocess.TimeoutExpired(["claude"], 180)), "timed out")

    def test_missing_cli_fails(self):
        self._fails(FakeRun(raises=FileNotFoundError("claude")), "could not run")

    def test_cwd_is_passed_to_the_child(self):
        run = FakeRun(_result())
        judge.ask(QUESTION, PATHS, run_subprocess=run, cwd="/kit")
        self.assertEqual(run.calls[0][1]["cwd"], "/kit")

    def test_nonzero_exit_fails(self):
        self._fails(FakeRun(_result(), returncode=1), "exit")

    def test_is_error_or_budget_subtype_fails(self):
        self._fails(FakeRun(_result(is_error=True)), "error")
        self._fails(FakeRun(_result(subtype="error_max_budget_usd")), "error_max_budget_usd")

    def test_invalid_json_fails(self):
        self._fails(FakeRun("not json"), "JSON")
        self._fails(FakeRun("[1, 2]"), "JSON object")

    def test_long_or_missing_reason_fails(self):
        self._fails(FakeRun(_result(structured_output={"decision": "stop", "reason": "x" * 201})), "reason")
        self._fails(FakeRun(_result(structured_output={"decision": "stop"})), "reason")


class ProfileTests(unittest.TestCase):
    def test_profile_has_no_tools_list(self):
        text = (KIT_ROOT / ".claude" / "agents" / "marina-judge.md").read_text(encoding="utf-8")
        frontmatter = text.split("---")[1]
        keys = {line.split(":", 1)[0].strip() for line in frontmatter.splitlines() if ":" in line}
        self.assertIn("name", keys)
        self.assertIn("description", keys)
        self.assertNotIn("tools", keys)


if __name__ == "__main__":
    unittest.main()
