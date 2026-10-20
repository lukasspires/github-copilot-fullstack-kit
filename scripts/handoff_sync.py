#!/usr/bin/env python3
"""Validate a Claude handoff and mirror assignment launch metadata into it.

Library only; runtime writes are confined to the selected task directory.
Minimum tested Claude CLI version: none (no native CLI invoked).
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from scripts.state.model import Assignment, StateDoc


class HandoffError(ValueError):
    """A handoff cannot safely be prepared or launched."""


def validate_task_paths(state_path: str | Path, doc: StateDoc, assignment: Assignment, kit_root: Path) -> Path:
    """Require every task file to occupy its canonical, non-escaped location."""

    root = kit_root.resolve()
    task_dir = root / ".agent-state" / doc.task.project / "tasks" / doc.task.slug
    if task_dir.resolve() != task_dir:
        raise HandoffError("canonical task directory escapes through a symlink")

    expected = {
        "state": task_dir / "state.toml",
        "journal": task_dir / "checkpoint.md",
        "handoff": task_dir / f"{assignment.nn:02d}-{assignment.role}-handoff.md",
        "receipt": task_dir / f"{assignment.nn:02d}-{assignment.role}-receipt.md",
    }
    paths = {
        "state": Path(state_path),
        "journal": root / doc.task.journal,
        "handoff": root / assignment.handoff,
        "receipt": root / assignment.receipt,
    }
    for field, path in paths.items():
        if path.absolute() != expected[field] or path.resolve() != expected[field]:
            raise HandoffError(f"{field} path is outside its canonical task location: {path}")
    return task_dir


_TITLE = re.compile(r"^#\s*(.+?)\s+—\s+(.+?)\s+—\s+(\d+)\s+—\s+(.+?)\s*$", re.MULTILINE)
_HEADING = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
_ROOT_LINE = re.compile(r"(?i)^[ \t]*[-*][ \t]*(?:\*\*)?[^\n:]*target_root[^\n:]*:.*(?:\r?\n|$)", re.MULTILINE)
_ALLOW_LINE = re.compile(r"(?i)^[ \t]*(?:[-*][ \t]*)?(?:\*\*)?Granted allowlist(?:\*\*)?:.*(?:\r?\n|$)", re.MULTILINE)
_ALLOW_BULLET = re.compile(
    r"^[ \t]*[-*][ \t]+`(?:[A-Z][A-Za-z0-9_.]*|mcp__[A-Za-z0-9_.]+)"
    r"(?:\([^`\r\n]*\))?`[ \t]*(?:\r?\n|$)"
)
_FIELD_PATH = re.compile(r"`?(/[^\s`]+)`?")
_BROAD_BASH = re.compile(r"^Bash(?:\(\s*\*\s*\))?$", re.IGNORECASE)


def _section(text: str, heading: str) -> tuple[int, int, str] | None:
    headings = list(_HEADING.finditer(text))
    for i, match in enumerate(headings):
        if match.group(1).strip().lower() == heading.lower():
            end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
            return match.end(), end, text[match.end():end]
    return None


def _line_value(body: str, field: str) -> str | None:
    pattern = re.compile(rf"(?im)^[ \t]*[-*][ \t]*(?:\*\*)?{re.escape(field)}[^\n:]*:[ \t]*(?:\*\*)?[ \t]*(.*?)[ \t]*$")
    match = pattern.search(body)
    return match.group(1).strip() if match else None


def validate_handoff(text: str, assignment: Assignment, kit_root: Path) -> str:
    """Validate identity and required human-authored content; return profile."""

    title = _TITLE.search(text)
    if not title or (title.group(1), title.group(2), int(title.group(3)), title.group(4)) != (
        assignment.title.split(" — ")[0], assignment.role, assignment.nn, assignment.type
    ) or title.group(0).removeprefix("# ").strip() != assignment.title:
        raise HandoffError("handoff title is missing or inconsistent with state")

    role_section = _section(text, "Role and profile")
    if role_section is None:
        raise HandoffError("handoff role/profile section is missing")
    role = _line_value(role_section[2], "Role")
    if role != assignment.role:
        raise HandoffError("handoff role is missing or inconsistent with state")
    profile_line = _line_value(role_section[2], "Absolute profile")
    profile_match = _FIELD_PATH.search(profile_line or "")
    profile = profile_match.group(1) if profile_match else ""
    expected_profiles = {
        str(kit_root / ".claude" / "agents" / f"{assignment.role}.md"),
        str(kit_root / ".codex" / "agents" / f"{assignment.role}.toml"),
    }
    if profile not in expected_profiles:
        raise HandoffError("handoff absolute profile is missing or inconsistent with role")

    for heading in ("Objective", "Write scope", "Acceptance criteria"):
        section = _section(text, heading)
        if section is None or not re.search(r"\w", section[2]):
            raise HandoffError(f"handoff {heading.lower()} is missing or empty")

    metadata = _section(text, "Assignment metadata")
    if metadata is None:
        raise HandoffError("handoff assignment metadata section is missing")
    receipt_line = _line_value(metadata[2], "Receipt path")
    receipt_match = _FIELD_PATH.search(receipt_line or "")
    if not receipt_match or receipt_match.group(1) != str(kit_root / assignment.receipt):
        raise HandoffError("handoff receipt path is missing or inconsistent with state")

    roots = _section(text, "Roots")
    if roots is not None:
        root_line = _line_value(roots[2], "kit_root")
        if root_line is None:
            # Also accept the legacy combined `kit_root / target_root` label.
            root_line = _line_value(roots[2], "kit_root / target_root")
        root_match = _FIELD_PATH.search(root_line or "")
        if not root_match or root_match.group(1) != str(kit_root):
            raise HandoffError("handoff kit_root is missing or inconsistent with state")
    return profile


def validate_launch_metadata(assignment: Assignment) -> None:
    if not assignment.targets or any(not Path(target).is_absolute() for target in assignment.targets):
        raise HandoffError("assignment targets must be nonempty absolute paths")
    if not assignment.allowlist or any(not entry.strip() or _BROAD_BASH.fullmatch(entry.strip()) for entry in assignment.allowlist):
        raise HandoffError("assignment allowlist is empty or contains bare/wildcard Bash")


def synchronize(text: str, assignment: Assignment, kit_root: Path) -> tuple[str, list[str]]:
    """Change only target-root lines and granted-allowlist metadata."""

    validate_launch_metadata(assignment)
    changed: list[str] = []
    newline = "\r\n" if "\r\n" in text else "\n"

    roots = _section(text, "Roots")
    if roots is None:
        role_section = _section(text, "Role and profile")
        if role_section is None:
            raise HandoffError("handoff role/profile section is missing")
        insertion = (f"## Roots{newline}{newline}- **kit_root:** `{kit_root}`{newline}"
                     + "".join(f"- **target_root:** `{target}`{newline}" for target in assignment.targets)
                     + newline)
        text = text[:role_section[1]] + insertion + text[role_section[1]:]
        changed.append("target_root")
        roots = _section(text, "Roots")
        assert roots is not None
    start, end, body = roots
    # A legacy combined kit_root / target_root line is split to retain its
    # kit root while replacing the target-root part.
    def remove_target(match: re.Match[str]) -> str:
        line = match.group(0)
        if "kit_root" in line.lower():
            return re.sub(r"(?i)\s*/\s*target_root", "", line)
        return ""

    lines = body.splitlines(keepends=True)
    target_indexes = [i for i, line in enumerate(lines) if _ROOT_LINE.fullmatch(line)]
    canonical_targets = [f"- **target_root:** `{target}`{newline}" for target in assignment.targets]
    if target_indexes:
        first = target_indexes[0]
        new_lines = []
        for i, line in enumerate(lines):
            if i == first:
                if "kit_root" in line.lower():
                    new_lines.append(remove_target(re.match(r".*", line, re.DOTALL)))
                new_lines.extend(canonical_targets)
            elif i not in target_indexes:
                new_lines.append(line)
        new_body = "".join(new_lines)
    else:
        # Insert before the separator blank line; all unrelated bytes stay put.
        insert_at = len(body.rstrip("\r\n"))
        separator = "" if insert_at == 0 or body[:insert_at].endswith(newline) else newline
        new_body = body[:insert_at] + separator + "".join(canonical_targets) + body[insert_at:]
    if new_body != body:
        text = text[:start] + new_body + text[end:]
        if "target_root" not in changed:
            changed.append("target_root")

    metadata = _section(text, "Assignment metadata")
    if metadata is None:
        raise HandoffError("handoff Assignment metadata section is missing")
    start, end, body = metadata
    canonical_allow = "- **Granted allowlist:** " + " ".join(f"`{entry}`" for entry in assignment.allowlist) + newline
    matches = list(_ALLOW_LINE.finditer(body))
    if matches:
        # Keep the first label's position, but remove every recognized label
        # and its directly attached legacy tool-entry list.
        parts = []
        cursor = 0
        for index, match in enumerate(matches):
            parts.append(body[cursor:match.start()])
            if index == 0:
                parts.append(canonical_allow)
            cursor = match.end()
            for line in body[cursor:].splitlines(keepends=True):
                if not _ALLOW_BULLET.fullmatch(line):
                    break
                cursor += len(line)
        parts.append(body[cursor:])
        new_body = "".join(parts)
    else:
        new_body = body.rstrip("\r\n") + newline + canonical_allow + newline
    if new_body != body:
        text = text[:start] + new_body + text[end:]
        changed.append("Granted allowlist")
    return text, changed


def write_atomic(path: Path, text: str, task_dir: Path) -> None:
    validate_location(path, task_dir)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=task_dir)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_location(path: Path, task_dir: Path) -> None:
    if path.is_symlink() or path.parent.resolve() != task_dir.resolve():
        raise HandoffError("handoff path is outside the task directory")
