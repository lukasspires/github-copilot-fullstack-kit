#!/usr/bin/env python3
"""scripts/launch_claude.py — G2 transition `prepared -> launched | uncertain`.

Builds the exact `claude --bg ...` command described in
docs/agent-workflow.md's "Claude Code" section from an already-`prepared`
assignment's state, runs `preflight` first (fail-fast: aborts before
constructing or launching anything on `preparation_failed`), launches at
most one session per invocation, and records the observed outcome via
`scripts.state` (never hand-edits `state.toml` text).

Minimum tested Claude CLI version: 2.1.306 — `--permission-mode dontAsk`
denies (and records in `permission_denials`) every tool call outside
`--allowedTools`; `Edit(//<abs>/**)` rules also bound `Write`; and a Stop
hook passed through `--settings` fires in `--bg` sessions
(docs/achados-f1-spike-hooks-e-juiza-2026-10.md). The flags below were
first re-checked directly against the installed CLI on 2026-09-19:
`--allowedTools`/`--allowed-tools <tools...>` takes a space-separated list
in one flag invocation (confirmed via `claude --help`, not assumed from
the single-entry example in docs/agent-workflow.md); `--add-dir
<directories...>` also accepts multiple, but this module still repeats
`--add-dir` once per target, matching that section's documented
convention ("Repeat --add-dir for other targets") rather than the newer
capability. `--bg`/`--name`/`--agent`/`--settings`/`--permission-mode`
were also re-confirmed present.

Never launches a real session from its own tests: the `subprocess.run`
boundary is always injectable (default `subprocess.run`, replaced with a
fake in every test). Refuses to construct `bypassPermissions`,
`--permission-prompts none`, `--resume`, `--continue`, `--fork-session`,
or a bare/wildcard `--allowedTools` entry (`Bash`, `Bash(*)`) — see
`LaunchRefused` and the explicit safe flag allowlist.

File-write rules never come from the state's allowlist: `derive_write_rules`
builds them at launch from the assignment (writer: one `Edit(//<target>/**)`
per target; every role: `Edit(//<receipt>)`), and `build_settings` adds the
Stop hook `scripts/marina/__main__.py hook require-receipt`, which keeps the
session open until its receipt passes receipt-lint. The child's stdin is
always closed: a `claude` child reads inherited stdin and acts on it.

Runtime write scope: `--state`'s `state.toml` (native.* + one event) and
the handoff metadata, inside `.agent-state/<project>/tasks/<task>/` — never `scripts/`, `tests/`,
or a target repository.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common, handoff_sync, preflight
from scripts.preflight import PreflightResult
from scripts.state import append_event, read_state, write_state
from scripts.state.model import StateError, mode_for_role

CANONICAL_PROMPT = "Act as {role}. Read {profile} and {handoff}, then execute the assignment."

# The five behaviors this script must never construct (plan §5 P0 /
# docs/analise-scripts-apoio-marina.md §10 "Flags proibidas"), plus a
# bare/wildcard allowlist entry, checked separately against the parsed
# handoff's own `allowlist`.
FORBIDDEN_EXTRA_ARG_TOKENS: tuple[str, ...] = (
    "bypassPermissions",
    "--permission-prompts",
    "--resume",
    "--continue",
    "--fork-session",
)
_BARE_ALLOWLIST_RE = re.compile(r"^Bash(?:\(\s*\*\s*\))?$", re.IGNORECASE)
_FILE_WRITE_RULE_RE = re.compile(r"^(?:Edit|Write|NotebookEdit|MultiEdit)\b", re.IGNORECASE)

_SHORT_ID_RE = re.compile(r"\b[0-9a-f]{8}\b")


class LaunchRefused(RuntimeError):
    """launch-claude refuses to construct/launch the requested command."""


@dataclasses.dataclass
class HandoffData:
    task: str
    role: str
    nn: int
    type_: str
    profile: str
    targets: list[str]
    allowlist: list[str]


_TITLE_RE = re.compile(
    r"^#\s*(?P<task>.+?)\s+—\s+(?P<role>.+?)\s+—\s+(?P<nn>\d+)\s+—\s+(?P<type_>.+?)\s*$", re.MULTILINE
)
_ALLOWLIST_LINE_RE = re.compile(r"\*\*Granted allowlist:\*\*\s*(.+)", re.IGNORECASE)
_BACKTICK_RE = re.compile(r"`([^`]+)`")
_ROOTS_SECTION_RE = re.compile(r"^##\s*Roots\s*\n(.*?)(?=\n##\s|\Z)", re.MULTILINE | re.DOTALL)


def parse_handoff(text: str) -> HandoffData:
    """Parse the fields `build_argv` needs out of a `<NN>-<role>-handoff.md`.

    Deliberately narrow (not a general handoff schema validator — that is
    `preflight`'s job, already run before this is ever called): title
    line, absolute profile (`common.extract_profile_path`, reused), target
    roots (`## Roots` section, any line naming `target_root`), and the
    granted allowlist.
    """

    title_match = _TITLE_RE.search(text)
    if not title_match:
        raise LaunchRefused("handoff title line does not match '# <task> — <role> — <NN> — <type>'")

    profile = common.extract_profile_path(text)
    if not profile:
        raise LaunchRefused("no absolute profile path found in the handoff")

    targets: list[str] = []
    roots_match = _ROOTS_SECTION_RE.search(text)
    if roots_match:
        for line in roots_match.group(1).splitlines():
            if "target_root" not in line.lower():
                continue
            for path in _BACKTICK_RE.findall(line):
                if path.startswith("/") and path not in targets:
                    targets.append(path)

    allowlist: list[str] = []
    allow_match = _ALLOWLIST_LINE_RE.search(text)
    if allow_match:
        allowlist = _BACKTICK_RE.findall(allow_match.group(1))

    return HandoffData(
        task=title_match.group("task"),
        role=title_match.group("role"),
        nn=int(title_match.group("nn")),
        type_=title_match.group("type_"),
        profile=profile,
        targets=targets,
        allowlist=allowlist,
    )


def _check_forbidden_allowlist(allowlist: list[str]) -> None:
    if not allowlist:
        raise LaunchRefused("refusing to construct an empty --allowedTools list")
    for entry in allowlist:
        if _BARE_ALLOWLIST_RE.fullmatch(entry.strip()):
            raise LaunchRefused(
                f"refusing to construct a bare/wildcard --allowedTools entry: {entry!r}"
            )
        if _FILE_WRITE_RULE_RE.match(entry.strip()):
            raise LaunchRefused(
                "file-write rules are derived from the assignment's targets and receipt, "
                f"never granted through the allowlist: {entry!r}"
            )


def _check_forbidden_extra_args(extra_args: list[str]) -> None:
    """Only flags with no access or permission effect may be appended."""
    seen: set[str] = set()
    index = 0
    while index < len(extra_args):
        flag = extra_args[index]
        if flag in seen or flag not in {"--verbose", "--model"}:
            raise LaunchRefused(f"refusing extra flag/behavior: {flag!r}")
        seen.add(flag)
        if flag == "--model":
            index += 1
            if index >= len(extra_args) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", extra_args[index]):
                raise LaunchRefused("--model requires a single model name")
        index += 1


def derive_write_rules(mode: str, targets: list[str], receipt: str) -> list[str]:
    """File-write rules for one assignment: writers get each target, every role its receipt.

    Paths must be absolute; they are normalized so a trailing slash or a
    `..` component cannot produce a rule the CLI would not match. A leading
    `/` on the absolute path yields the CLI's `Edit(//<abs>)` form.
    """

    paths = [*targets, receipt] if mode == "writer" else [receipt]
    for path in paths:
        if not os.path.isabs(path):
            raise LaunchRefused(f"write rules need absolute paths, got {path!r}")
    rules = [f"Edit(/{os.path.normpath(t)}/**)" for t in targets] if mode == "writer" else []
    rules.append(f"Edit(/{os.path.normpath(receipt)})")
    return rules


def build_settings(kit_root: Path, receipt: str, handoff: str) -> str:
    """The per-invocation `--settings` JSON: shared checkout plus the receipt Stop hook."""

    command = shlex.join([
        "python3", str(kit_root / "scripts" / "marina" / "__main__.py"),
        "hook", "require-receipt", "--receipt", receipt, "--handoff", handoff,
    ])
    settings = {
        "worktree": {"bgIsolation": "none"},
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": command}]}]},
    }
    return json.dumps(settings, separators=(",", ":"), ensure_ascii=False)


def build_argv(
    handoff: HandoffData,
    *,
    handoff_path: str,
    receipt_path: str,
    kit_root: Path,
    extra_args: list[str] | None = None,
    cli: str = "claude",
) -> list[str]:
    """Build the exact `claude --bg ...` argv for one already-`prepared` node.

    Never accepts `--permission-mode`/`--settings` overrides from the
    caller — the mode is always `dontAsk` and the settings always
    `build_settings(...)`. Under `dontAsk` the `--allowedTools` list is the
    real boundary: the launch-derived write rules (`derive_write_rules`)
    come first, then the assignment's check-derived `Bash(...)` rules;
    anything else is denied, not queued. The ban on `bypassPermissions`
    and `--permission-prompts` still applies unchanged. `extra_args`
    accepts only `--verbose` and a single `--model <name>` pair.
    """

    _check_forbidden_allowlist(handoff.allowlist)
    extra_args = list(extra_args or [])
    _check_forbidden_extra_args(extra_args)
    write_rules = derive_write_rules(mode_for_role(handoff.role), handoff.targets, receipt_path)

    argv = [cli, "--bg", "--agent", handoff.role, "--name", f"{handoff.task} — {handoff.role} — {handoff.nn:02d} — {handoff.type_}"]
    for target in handoff.targets:
        argv += ["--add-dir", target]
    argv += ["--settings", build_settings(kit_root, receipt_path, handoff_path)]
    argv += ["--permission-mode", "dontAsk"]
    argv += ["--allowedTools", *write_rules, *handoff.allowlist]
    argv += extra_args
    prompt = CANONICAL_PROMPT.format(role=handoff.role, profile=handoff.profile, handoff=handoff_path)
    argv += ["--", prompt]
    return argv


def extract_short_id(stdout: str) -> str | None:
    """Best-effort extraction of the printed short session id.

    The exact stdout format of a real `claude --bg` launch is not
    confirmed by this assignment (actually launching one is explicitly
    out of scope/forbidden here); every real short id captured so far in
    this kit's history (`182689df`, `c1897dee`, `70409944`, `08c07bc9`,
    `d0edc324`, ...) is 8 lowercase hex characters, so that shape is what
    is matched — on the *last* line containing a match, most-specific
    first. No match means "no ID confirmed", which is exactly what the G2
    `uncertain` state (not a guessed `launched`) exists for.
    """

    match = None
    for line in stdout.splitlines():
        found = _SHORT_ID_RE.search(line)
        if found:
            match = found
    return match.group(0) if match else None


@dataclasses.dataclass
class LaunchResult:
    ok: bool
    argv: list[str] | None
    reasons: list[str]
    session_id: str | None = None
    preflight_result: PreflightResult | None = None
    notes: list[str] = dataclasses.field(default_factory=list)


def run_launch(
    state_path: str | Path,
    nn: int,
    *,
    kit_root: str | Path,
    run_preflight: Callable[..., PreflightResult] = preflight.run_preflight,
    run_subprocess: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    read_text: Callable[[Path], str] = lambda p: p.read_text(encoding="utf-8"),
    extra_args: list[str] | None = None,
    timeout: int = 30,
) -> LaunchResult:
    """Run `preflight` (fail-fast), then build+launch at most one session.

    Aborts before constructing anything if `preflight` does not leave the
    node `prepared` (i.e. it went to `preparation_failed`); this is a
    Python return-value check, not reliance on `set -e`, per the handoff.
    """

    kit_root = Path(kit_root)
    doc = read_state(state_path)
    assignment = doc.get_assignment(nn)
    try:
        handoff_sync.validate_task_paths(state_path, doc, assignment, kit_root)
    except handoff_sync.HandoffError as exc:
        return LaunchResult(ok=False, argv=None, reasons=[str(exc)])

    pre_result: PreflightResult | None = None
    if assignment.state == "reserved":
        pre_result = run_preflight(state_path, nn, kit_root=kit_root)
        if not pre_result.ok:
            return LaunchResult(ok=False, argv=None, reasons=["preflight -> preparation_failed"] + pre_result.reasons, preflight_result=pre_result)
        doc = read_state(state_path)
        assignment = doc.get_assignment(nn)
        try:
            handoff_sync.validate_task_paths(state_path, doc, assignment, kit_root)
        except handoff_sync.HandoffError as exc:
            return LaunchResult(ok=False, argv=None, reasons=[str(exc)], preflight_result=pre_result)

    if assignment.state != "prepared":
        return LaunchResult(
            ok=False, argv=None, reasons=[f"nn={nn} is not 'prepared' (state={assignment.state!r}); refuse to launch"],
            preflight_result=pre_result,
        )

    handoff_path = kit_root / assignment.handoff
    handoff_text = read_text(handoff_path)
    notes: list[str] = []
    try:
        handoff_sync.validate_location(handoff_path, Path(state_path).parent)
        profile = handoff_sync.validate_handoff(handoff_text, assignment, kit_root)
        if profile != str(kit_root / ".claude" / "agents" / f"{assignment.role}.md"):
            raise LaunchRefused("handoff does not name the Claude profile for this role")
        synchronized, sync_fields = handoff_sync.synchronize(handoff_text, assignment, kit_root)
        if sync_fields:
            handoff_sync.write_atomic(handoff_path, synchronized, handoff_path.parent)
            notes.append(f"synchronized handoff fields: {', '.join(sync_fields)}")
        handoff_data = HandoffData(
            task=doc.task.slug, role=assignment.role, nn=assignment.nn,
            type_=assignment.type,
            profile=profile,
            targets=list(assignment.targets), allowlist=list(assignment.allowlist),
        )
        receipt_path = str(kit_root / assignment.receipt)
        argv = build_argv(
            handoff_data, handoff_path=str(handoff_path), receipt_path=receipt_path,
            kit_root=kit_root, extra_args=extra_args,
        )
        write_rule_count = len(derive_write_rules(mode_for_role(assignment.role), handoff_data.targets, receipt_path))
    except (LaunchRefused, handoff_sync.HandoffError) as exc:
        return LaunchResult(ok=False, argv=None, reasons=[str(exc)], preflight_result=pre_result, notes=notes)

    proc = run_subprocess(argv, capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    session_id = extract_short_id(proc.stdout) if proc.returncode == 0 else None

    if session_id:
        sync_note = f"; synchronized: {', '.join(sync_fields)}" if sync_fields else ""
        append_event(
            assignment, "launched", by="launch-claude",
            note=f"id={session_id}; write_rules={write_rule_count}{sync_note}",
        )
        assignment.native.platform = "claude"
        assignment.native.id = session_id
        write_state(state_path, doc)
        return LaunchResult(ok=True, argv=argv, reasons=[], session_id=session_id, preflight_result=pre_result, notes=notes)

    append_event(
        assignment,
        "uncertain",
        by="launch-claude",
        note=f"command emitted; no id confirmed (exit={proc.returncode})" +
             (f"; synchronized: {', '.join(sync_fields)}" if sync_fields else ""),
    )
    write_state(state_path, doc)
    return LaunchResult(
        ok=False,
        argv=argv,
        reasons=[f"no session id captured (exit={proc.returncode}); recorded as uncertain, not launched"],
        preflight_result=pre_result,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="launch-claude", description="prepared -> launched | uncertain (Claude).")
    parser.add_argument("--state", required=True)
    parser.add_argument("--nn", required=True, type=int)
    parser.add_argument("--kit-root", required=True)
    args = parser.parse_args(argv)

    try:
        result = run_launch(args.state, args.nn, kit_root=args.kit_root)
    except (StateError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if result.preflight_result is not None:
        for note in result.preflight_result.notes:
            print(f"NOTE: {note}")
    for note in result.notes:
        print(f"NOTE: {note}")
    if result.argv is not None:
        print("argv:", " ".join(repr(a) for a in result.argv))
    if result.ok:
        print(f"PASS nn={args.nn} -> launched id={result.session_id}")
        return 0
    print(f"FAIL nn={args.nn}")
    for reason in result.reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
