#!/usr/bin/env python3
"""scripts/preflight.py — G2 transition `reserved -> prepared | preparation_failed`.

Runs exactly the P0 checks of docs/analise-scripts-apoio-marina.md
§4.1 for one assignment already recorded as `reserved` in `state.toml`,
then appends the observed transition. Never launches anything.

Minimum tested Claude CLI version: 2.1.267 (optionally lists
`claude agents --json --all`, read-only; skips gracefully, with a note,
when the CLI is not installed — this check is best-effort because the
kit-tooling development environment may not have it).

Runtime write scope: the task's handoff metadata, `--state`'s `state.toml`
and, on success, a `git-before-<NN>.txt` file next to it (all inside
`.agent-state/<project>/tasks/<task>/`) — never `scripts/`, `tests/`, or a
target repository. See tests/test_preflight.py::WriteScopeTest for a
real-filesystem demonstration of this.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime
import re
import shutil
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common, handoff_sync, status_claude
from scripts.state import append_event, read_state, write_state
from scripts.state.model import Assignment, StateDoc, StateError

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")
_BASH_ENTRY_RE = re.compile(r"^Bash\((.*)\)$")


@dataclasses.dataclass
class PreflightResult:
    ok: bool
    reasons: list[str]
    notes: list[str]


def _extract_check_commands(allowlist: list[str]) -> list[str]:
    """Pull the leading executable name out of each granted `Bash(...)` rule.

    E.g. "Bash(cd /x && node --test)" -> ["node"]; "Bash(git status --short)"
    -> ["git"]. Used to check each check executable resolves via `which`
    (docs/analise-scripts-apoio-marina.md §4.1: "cada executável dos
    checks resolve via `command -v`").
    """

    commands: list[str] = []
    for entry in allowlist:
        match = _BASH_ENTRY_RE.match(entry.strip())
        if not match:
            continue
        body = match.group(1)
        for part in re.split(r"&&|;|\|", body):
            tokens = part.strip().split()
            if not tokens:
                continue
            if tokens[0] == "cd":
                continue
            commands.append(tokens[0])
    return commands


def run_preflight(
    state_path: str | Path,
    nn: int,
    *,
    kit_root: str | Path,
    now: datetime.datetime | None = None,
    which: Callable[[str], str | None] = shutil.which,
    list_sessions: Callable[[], list[dict]] = common.list_manager_sessions,
    git_status_diff: Callable[[str], str] = common.git_status_diff,
    read_text: Callable[[Path], str] = lambda p: p.read_text(encoding="utf-8"),
) -> PreflightResult:
    """Run P0 and record `reserved -> prepared | preparation_failed`.

    All I/O boundaries (`which`, `list_sessions`, `git_status_diff`,
    `read_text`) are injectable so tests are deterministic (no reliance on
    the real installed Claude CLI, network, or wall clock).
    """

    reasons: list[str] = []
    notes: list[str] = []
    now = now or datetime.datetime.now().astimezone()
    kit_root = Path(kit_root)

    doc: StateDoc = read_state(state_path)
    assignment: Assignment = doc.get_assignment(nn)
    if assignment.state != "reserved":
        raise StateError(f"nn={nn} is not in state 'reserved' (found {assignment.state!r}); preflight only runs once")

    # This gate precedes every handoff read/write and every state write.
    task_dir = handoff_sync.validate_task_paths(state_path, doc, assignment, kit_root)

    # slug/project format (docs/analise-scripts-apoio-marina.md §4.1).
    if not _SLUG_RE.match(doc.task.slug):
        reasons.append(f"task.slug {doc.task.slug!r} does not match ^[a-z0-9-]+$")
    if not _SLUG_RE.match(doc.task.project):
        reasons.append(f"task.project {doc.task.project!r} does not match ^[a-z0-9-]+$")

    # No symlink escaping .agent-state/<project>/tasks/<task>/.
    if not task_dir.exists():
        reasons.append(f"task directory does not exist: {task_dir}")

    # Handoff identity and human-authored content must be sound; launch
    # metadata is mirrored from state before the node can be prepared.
    handoff_path = kit_root / assignment.handoff
    handoff_text = ""
    profile_path_str = ""
    sync_fields: list[str] = []
    if not handoff_path.is_file():
        reasons.append(f"handoff not found: {handoff_path}")
    else:
        handoff_text = read_text(handoff_path)
        if not handoff_text.strip():
            reasons.append(f"handoff is empty: {handoff_path}")
        else:
            try:
                handoff_sync.validate_location(handoff_path, task_dir)
                profile_path_str = handoff_sync.validate_handoff(handoff_text, assignment, kit_root)
                synchronized, sync_fields = handoff_sync.synchronize(handoff_text, assignment, kit_root)
                if sync_fields:
                    handoff_sync.write_atomic(handoff_path, synchronized, task_dir)
                    handoff_text = synchronized
                    notes.append(f"synchronized handoff fields: {', '.join(sync_fields)}")
            except handoff_sync.HandoffError as exc:
                reasons.append(str(exc))

    # Absolute profile referenced in the handoff exists and is readable.
    if profile_path_str:
        profile_path = Path(profile_path_str)
        if not profile_path.is_file() or not _is_readable(profile_path):
            reasons.append(f"profile referenced in handoff not found or unreadable: {profile_path}")

    # AGENTS.md / CLAUDE.md readable per target, when they exist.
    for target in assignment.targets:
        for fname in ("AGENTS.md", "CLAUDE.md"):
            candidate = Path(target) / fname
            if candidate.exists() and not (candidate.is_file() and _is_readable(candidate)):
                reasons.append(f"{candidate} exists but is not a readable regular file")

    # Receipt directory exists; receipt for this nn does not exist yet.
    receipt_path = kit_root / assignment.receipt
    if not receipt_path.parent.exists():
        reasons.append(f"receipt directory does not exist: {receipt_path.parent}")
    if receipt_path.exists():
        reasons.append(f"receipt already exists: {receipt_path}")

    # Each check executable resolves.
    check_commands = sorted(set(_extract_check_commands(assignment.allowlist)))
    missing_commands = [c for c in check_commands if which(c) is None]
    if missing_commands:
        reasons.append(f"check executable(s) not on PATH: {missing_commands}")

    # git-before snapshot (read-only; written only if everything else passed).
    git_before_parts: list[str] = []
    for target in assignment.targets:
        try:
            git_before_parts.append(git_status_diff(target))
        except Exception as exc:  # pragma: no cover - defensive, read-only call
            reasons.append(f"failed to capture git status/diff for {target}: {exc}")

    # Native manager: same-title-prefix sessions, flag any already `working`.
    try:
        sessions = list_sessions()
    except common.ManagerUnavailable as exc:
        notes.append(f"native manager unavailable, skipped: {exc}")
    else:
        prefix = f"{doc.task.slug} —"
        for session in sessions:
            common.validate_manager_session_schema(session)
            # classify_session, not `state` alone: a finished --bg session can stay `working`/`idle`.
            if session.get("name", "").startswith(prefix) and status_claude.classify_session(session) == "working":
                reasons.append(f"a native session for this task is already working: {session.get('name')}")

    ok = not reasons
    if ok:
        git_before_path = task_dir / f"git-before-{nn:02d}.txt"
        git_before_path.write_text("\n".join(git_before_parts) + "\n", encoding="utf-8")
        assignment.git_before = str(git_before_path.relative_to(kit_root))
        event_note = f"synchronized: {', '.join(sync_fields)}" if sync_fields else ""
        append_event(assignment, "prepared", by="preflight", note=event_note, at=now)
    else:
        append_event(assignment, "preparation_failed", by="preflight", note=reasons[0], at=now)

    doc.task.updated_at = now
    write_state(state_path, doc)
    return PreflightResult(ok=ok, reasons=reasons, notes=notes)


def _is_readable(path: Path) -> bool:
    try:
        with path.open("rb"):
            return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="preflight", description="G2 transition reserved -> prepared | preparation_failed."
    )
    parser.add_argument("--state", required=True, help="path to state.toml")
    parser.add_argument("--nn", required=True, type=int)
    parser.add_argument("--kit-root", required=True)
    args = parser.parse_args(argv)

    try:
        result = run_preflight(args.state, args.nn, kit_root=args.kit_root)
    except (StateError, handoff_sync.HandoffError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for note in result.notes:
        print(f"NOTE: {note}")
    if result.ok:
        print(f"PASS nn={args.nn} -> prepared")
        return 0
    print(f"FAIL nn={args.nn} -> preparation_failed")
    for reason in result.reasons:
        print(f"  - {reason}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
