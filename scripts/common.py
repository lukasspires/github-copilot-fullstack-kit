"""scripts/common.py — shared helpers for the kit's coordination tooling.

Library only, no `__main__` guard: does not declare a "Minimum tested
Claude CLI version" header, consistent with every other library-only
module under scripts/ (kit_lint.check_cli_versions only enforces that
header on scripts with a `__main__` guard). The native-manager call this
module wraps (`claude agents --json --all`) is exercised, and its CLI
version constraint enforced, from the entry-point script that actually
invokes it.

Stdlib only. No network. Git usage is read-only (status/diff). Never
responds to a native approval prompt; callers must print `claude attach
<id>` for the human instead.
"""

from __future__ import annotations

import dataclasses
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Iterable

# --------------------------------------------------------------------------
# Secret heuristic (deliberately simple; see docs/analise-scripts-apoio-
# coordenacao.md 4.5 "heurística simples" and plan §5 invariant 8).
# --------------------------------------------------------------------------

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bgh[opusr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(
        r"(?i)\b(api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*"
        r"['\"]?[A-Za-z0-9/_.+=-]{8,}"
    ),
)


def looks_like_secret(text: str) -> bool:
    """Best-effort, deliberately simple secret heuristic.

    Not a substitute for a real secret scanner; catches the obvious
    patterns (private key headers, common cloud/token prefixes, and
    `key: value`/`key=value` assignments naming a credential).
    """

    return any(pattern.search(text) for pattern in _SECRET_PATTERNS)


# --------------------------------------------------------------------------
# Handoff/receipt text helpers.
# --------------------------------------------------------------------------


_PROFILE_PATH_AFTER_WORD_RE = re.compile(r"(?:^|(?<=[\s`\"'(]))(/[^\s`\"')]+)")


def extract_profile_path(text: str) -> str | None:
    """Find the first absolute path following the word "profile" on a line.

    Handles both the current handoff template
    (``**Absolute profile (read explicitly):** `/abs/path` ``) and the
    older ad hoc format (``Profile: /abs/path``), and the receipt field
    (``- **profile_read:** /abs/path``).

    Scoped to *after* the "profile" match on each candidate line, and
    requires the path-like token to start at a natural boundary
    (preceded by whitespace, a backtick/quote, an opening paren, or the
    start of that scan window) rather than matching the first `/`
    anywhere on the line. This avoids two real false positives seen in
    this kit's own handoffs: a `/`-containing word earlier in the same
    line before "profile" is ever mentioned (e.g. "prints/executes ...
    profile"), and a `/`-containing word appearing *after* "profile" but
    embedded mid-word rather than starting a real path (e.g. "agent
    profile parsing/parity"). A line mentioning "profile" with no
    boundary-anchored absolute path following it is skipped rather than
    treated as a match, so the scan continues to the next candidate
    line.
    """

    for line in text.splitlines():
        lower = line.lower()
        idx = lower.find("profile")
        if idx == -1:
            continue
        match = _PROFILE_PATH_AFTER_WORD_RE.search(line[idx:])
        if match:
            return match.group(1)
    return None


_RISK_HEADING_RE = re.compile(
    r"^#{2,3}\s*RISK\s+\d+\s*(?:\([^)]*\))?\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE
)
_SEVERITY_SUFFIX_RE = re.compile(r"\(severity:[^)]*\)\s*$", re.IGNORECASE)
# Punctuation is replaced with a space, except hyphens: compound words like
# "visible-session" stay hyphenated in risks_digest (matches the fixture).
_NON_WORD_RE = re.compile(r"[^\w\s-]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")


def find_risk_titles(text: str) -> list[str]:
    """Return raw (un-normalized) ``### RISK n: <title>`` headings, in order.

    Also matches ``### RISK n (annotation): <title>`` — an optional
    parenthetical between the risk number and the colon (e.g. a severity
    or provenance note such as ``(carried forward, endorsed)``), which
    real receipts throughout this project commonly write. The
    parenthetical itself is excluded from the captured title group; only
    the text after the real colon is returned (tooling-gaps-fix Finding
    4: the stricter, colon-immediately-after-the-number regex silently
    produced an empty `risks_digest` for every receipt using this shape,
    with no parse error).
    """

    return [m.group(1) for m in _RISK_HEADING_RE.finditer(text)]


def normalize_risk_title(raw_title: str) -> str:
    """Normalize a risk heading into the short title form used in `risks_digest`.

    Strips a trailing "(Severity: ...)" annotation, replaces punctuation
    with spaces, collapses whitespace, and lowercases — e.g.
    "Worktree.bgIsolation Setting Not Yet Validated in Practice
    (Severity: Medium)" -> "worktree bgisolation setting not yet
    validated in practice".
    """

    s = _SEVERITY_SUFFIX_RE.sub("", raw_title)
    s = _NON_WORD_RE.sub(" ", s)
    s = _WHITESPACE_RE.sub(" ", s).strip().lower()
    return s


# --------------------------------------------------------------------------
# Git (read-only only: status, diff, rev-parse).
# --------------------------------------------------------------------------


def _run_git(args: list[str], *, cwd: str, timeout: int) -> str:
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return proc.stdout


def git_status_diff(target: str, *, timeout: int = 15, runner: Callable[..., str] = _run_git) -> str:
    """Read-only `git status --short` + `git diff --stat` for one target.

    Format matches the kit's existing `git-before-NN.txt` convention.
    """

    status = runner(["status", "--short"], cwd=target, timeout=timeout)
    diff_stat = runner(["diff", "--stat"], cwd=target, timeout=timeout)
    return f"# git status --short\n{status}\n# git diff --stat\n{diff_stat}"


# --------------------------------------------------------------------------
# Native session manager (Claude CLI): `claude agents --json --all` only.
# --------------------------------------------------------------------------


class ManagerUnavailable(RuntimeError):
    """The native session manager could not be reached (CLI missing, etc.)."""


class ManagerSchemaError(RuntimeError):
    """The manager's JSON output does not match the documented schema."""


REQUIRED_SESSION_FIELDS: tuple[str, ...] = ("name",)
KNOWN_SESSION_STATES = {"working", "blocked", "done", "failed", "stopped"}


def validate_manager_session_schema(session: Any) -> None:
    """Fail loudly on drift from the documented `claude agents --json --all` schema.

    Only the fields documented in docs/agent-workflow.md ("Claude Code")
    are required/validated: `name` must be present; `state`, when
    present, must be one of the documented values; `status: waiting`
    requires `waitingFor`. Interactive sessions may omit `state`/`status`
    (documented), so their absence alone is not a schema error.
    """

    if not isinstance(session, dict):
        raise ManagerSchemaError(f"manager session entry is not an object: {session!r}")
    missing = [field for field in REQUIRED_SESSION_FIELDS if field not in session]
    if missing:
        raise ManagerSchemaError(
            f"manager session missing required field(s) {missing}; got keys={sorted(session.keys())}"
        )
    if "state" in session and session["state"] not in KNOWN_SESSION_STATES:
        raise ManagerSchemaError(f"unknown manager session state: {session['state']!r}")
    if session.get("status") == "waiting" and "waitingFor" not in session:
        raise ManagerSchemaError("manager session status=waiting without waitingFor")


def list_manager_sessions(*, cli: str = "claude", timeout: int = 10) -> list[dict]:
    """Call `claude agents --json --all` (read-only) and return the parsed list.

    Raises `ManagerUnavailable` if the CLI is not installed or errors out,
    and `ManagerSchemaError` if the output is not the documented JSON
    array. Callers decide whether "unavailable" is fatal for their
    transition; preflight treats it as a skipped, noted check rather than
    a hard failure, since the kit-tooling development environment may not
    have the Claude CLI installed.
    """

    exe = shutil.which(cli)
    if exe is None:
        raise ManagerUnavailable(f"{cli!r} not found on PATH")
    try:
        proc = subprocess.run(
            [exe, "agents", "--json", "--all"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except OSError as exc:  # pragma: no cover - defensive
        raise ManagerUnavailable(str(exc)) from exc
    if proc.returncode != 0:
        raise ManagerUnavailable(
            f"`{cli} agents --json --all` exited {proc.returncode}: {proc.stderr.strip()}"
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise ManagerSchemaError(f"manager output is not valid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ManagerSchemaError(f"expected a JSON array of sessions, got {type(data).__name__}")
    for session in data:
        validate_manager_session_schema(session)
    return data


# --------------------------------------------------------------------------
# CLI version header (declared by every executable script; checked by
# kit-lint against the installed `claude --version`).
# --------------------------------------------------------------------------

_CLI_VERSION_RE = re.compile(r"Minimum tested Claude CLI version:\s*(.+)")


def declared_cli_version(script_path: Path) -> str:
    """Read the "Minimum tested Claude CLI version: ..." header line.

    Raises `ValueError` if the script does not declare one (kit-lint
    treats that as a failure — every executable script must declare it,
    even when the value is "none (neutral script; no native CLI invoked)").
    """

    text = Path(script_path).read_text(encoding="utf-8")
    match = _CLI_VERSION_RE.search(text)
    if not match:
        raise ValueError(f"{script_path} does not declare 'Minimum tested Claude CLI version'")
    return match.group(1).strip().rstrip('"')


def installed_claude_version(*, cli: str = "claude", timeout: int = 10) -> str | None:
    """Return the installed `claude --version` output, or None if unavailable."""

    exe = shutil.which(cli)
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=timeout, check=False
        )
    except OSError:  # pragma: no cover - defensive
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or proc.stderr.strip() or None


def parse_version(text: str) -> tuple[int, ...] | None:
    """Extract a dotted numeric version (e.g. "2.1.267") from free text."""

    match = re.search(r"(\d+(?:\.\d+)+)", text)
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


@dataclasses.dataclass
class Sanitized:
    """Marker wrapper documenting that a value has been sanitized for
    `.agent-state/` output (enumerated fields only, never a full
    environment dump, transcript, or complete log)."""

    value: Any


def enumerate_only(mapping: dict, allowed_keys: Iterable[str]) -> dict:
    """Return only the allowed keys from `mapping`, sanitized for `.agent-state/`."""

    allowed = set(allowed_keys)
    return {k: v for k, v in mapping.items() if k in allowed}
