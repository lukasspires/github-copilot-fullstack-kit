"""scripts/marina/judge.py — adapter for the headless Marina-judge (spec §3.3, "Contrato da juíza").

`ask` runs `claude -p --agent marina-judge` restricted to `Read` (`--tools
Read`), with a JSON schema whose `decision` enum is exactly the options
`decide` validated, and reads the answer from `structured_output`. The
`marina-judge` profile has no `tools` list, because a `tools` list makes the
CLI ignore `--json-schema` silently. Sessions started with `-p` do not show
up in `claude agents --json --all`, so they never affect `gate`/`preflight`.

Minimum tested Claude CLI version: 2.1.306 — `--json-schema` with
`--output-format json` returns the validated object in `structured_output`
and respects the enum; `--tools Read` removes every other tool; a `claude`
child reads inherited stdin, so stdin is always closed
(docs/achados-f1-spike-hooks-e-juiza-2026-10.md, H7–H9, X1, X5).

Any failure — the CLI missing, timeout, non-zero exit, invalid JSON, `is_error`, a
non-success `subtype` (budget exhausted), missing `structured_output`, an
option not offered, a missing or long reason — raises `JudgeFailed`; the
runner turns it into `stop(judge_failed)`.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from typing import Callable

from scripts.marina.decide import Question

JUDGE_MAX_BUDGET_USD = "0.50"
JUDGE_TIMEOUT_S = 180
_REASON_MAX = 200


class JudgeFailed(RuntimeError):
    """The judge gave no usable answer."""


@dataclasses.dataclass(frozen=True)
class JudgeAnswer:
    decision: str
    reason: str


def build_schema(options: tuple[str, ...]) -> dict:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": list(options)},
            "reason": {"type": "string", "maxLength": _REASON_MAX},
        },
        "required": ["decision", "reason"],
        "additionalProperties": False,
    }


def build_prompt(question: Question, paths: list[str]) -> str:
    lines = [
        f"Question: {question.kind} for assignment nn={question.nn:02d}.",
        f"Options (choose exactly one): {', '.join(question.options)}.",
        "Read only these files:",
        *[f"- {path}" for path in paths],
        "Answer with the decision and a reason of at most 200 characters. "
        "Do not edit, run, launch or coordinate anything; choose stop when unsure.",
    ]
    return "\n".join(lines)


def build_argv(question: Question, paths: list[str], *, cli: str = "claude") -> list[str]:
    schema = json.dumps(build_schema(question.options), separators=(",", ":"))
    return [
        cli, "-p",
        "--agent", "marina-judge",
        "--tools", "Read",
        "--permission-mode", "dontAsk",
        "--json-schema", schema,
        "--output-format", "json",
        "--max-budget-usd", JUDGE_MAX_BUDGET_USD,
        "--no-session-persistence",
        "--", build_prompt(question, paths),
    ]


def ask(
    question: Question,
    paths: list[str],
    *,
    run_subprocess: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    timeout: int = JUDGE_TIMEOUT_S,
    cwd: str | None = None,
) -> JudgeAnswer:
    """Ask the judge; `cwd` should be the kit root, where `marina-judge` resolves."""

    argv = build_argv(question, paths)
    try:
        proc = run_subprocess(
            argv, capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL, cwd=cwd
        )
    except subprocess.TimeoutExpired as exc:
        raise JudgeFailed(f"judge timed out after {timeout}s") from exc
    except OSError as exc:
        raise JudgeFailed(f"judge could not run: {exc}") from exc
    if proc.returncode != 0:
        raise JudgeFailed(f"judge exited with exit code {proc.returncode}")
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise JudgeFailed(f"judge output is not JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise JudgeFailed("judge output is not a JSON object")
    if payload.get("is_error") or payload.get("subtype") != "success":
        raise JudgeFailed(f"judge reported an error (subtype={payload.get('subtype')!r})")
    answer = payload.get("structured_output")
    if not isinstance(answer, dict):
        raise JudgeFailed("judge output has no structured_output object")
    decision, reason = answer.get("decision"), answer.get("reason")
    if decision not in question.options:
        raise JudgeFailed(f"judge chose an option not offered: {decision!r}")
    if not isinstance(reason, str) or len(reason) > _REASON_MAX:
        raise JudgeFailed("judge reason is missing or longer than 200 characters")
    return JudgeAnswer(decision=decision, reason=reason)
