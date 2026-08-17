#!/usr/bin/env python3
"""Validate the structural subset used by this customization kit.

The validator intentionally does not implement YAML. Frontmatter is limited to
top-level fields whose values are either scalars or JSON-compatible inline
arrays. This keeps the command dependency-free and makes unsupported metadata
fail explicitly instead of being parsed approximately.

Context budgets use UTF-8 bytes divided by four as a stable regression proxy,
not as a claim about any model's tokenizer.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from typing import Iterable, Optional, Sequence
from urllib.parse import unquote


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
FIELD = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9_-]*):(?P<value>.*)$")
URI_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*:")
WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:[\\/]")
INSTALLED_PLACEHOLDER = re.compile(r"\[path\s+or\s+N/A\]", re.IGNORECASE)
CLAUDE_AGENT_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
EXPECTED_AGENTS = frozenset(
    ("alice", "bruno", "clara", "diana", "gabriel", "gustavo", "marina", "paula", "sofia")
)
EXPECTED_SKILLS = frozenset(
    (
        "angular-feature", "api-ingestion", "data-analysis", "etl-pipeline",
        "file-ingestion", "java-rest-api", "quality-gate", "web-scraping",
    )
)
READ_ONLY_AGENTS = frozenset(("clara", "marina", "sofia"))
BUILTIN_PROMPT_AGENTS = frozenset(("ask", "agent", "plan"))
TOKEN_BUDGETS = {
    "agent": 600,
    "instruction": 350,
    "prompt": 250,
    "skill": 500,
}
TOKEN_BUDGET_OVERRIDES = {
    "AGENTS.md": 450,
    "CLAUDE.md": 300,
    ".github/copilot-instructions.md": 650,
    ".github/agents/task-coordinator.agent.md": 1000,
}
COORDINATOR_RECEIPT_FIELDS = (
    "status:",
    "changed:",
    "checks:",
    "evidence:",
    "risks:",
    "next:",
)


class Severity(str, Enum):
    """Diagnostic severity exposed by the CLI."""

    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True)
class Diagnostic:
    """A deterministic, source-located validation result."""

    code: str
    severity: Severity
    path: str
    line: int
    message: str

    def render(self) -> str:
        return (
            f"{self.code} {self.severity.value} "
            f"{self.path}:{max(1, self.line)}: {self.message}"
        )

    def promoted(self) -> "Diagnostic":
        if self.severity is Severity.WARNING:
            return replace(self, severity=Severity.ERROR)
        return self


@dataclass(frozen=True)
class ParsedDocument:
    """Frontmatter plus source information needed by policy checks."""

    metadata: dict[str, object]
    field_lines: dict[str, int]
    body: str
    text: str


@dataclass(frozen=True)
class Identifier:
    """A case-sensitive identifier indexed through its case-folded value."""

    name: str
    path: str
    line: int


def _relative_path(root: Path, path: Path) -> str:
    try:
        return path.resolve(strict=False).relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def _diagnostic(
    code: str,
    severity: Severity,
    root: Path,
    path: Path,
    line: int,
    message: str,
) -> Diagnostic:
    return Diagnostic(code, severity, _relative_path(root, path), line, message)


def _reject_json_constant(value: str) -> object:
    raise ValueError(f"non-standard JSON value {value!r}")


def parse_frontmatter(
    path: Path, root: Path
) -> tuple[ParsedDocument, list[Diagnostic]]:
    """Parse the supported frontmatter subset and report unsupported forms."""

    diagnostics: list[Diagnostic] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        diagnostics.append(
            _diagnostic(
                "IO001",
                Severity.ERROR,
                root,
                path,
                1,
                f"cannot read UTF-8 text: {error}",
            )
        )
        return ParsedDocument({}, {}, "", ""), diagnostics

    lines = text.splitlines()
    if not lines or lines[0] != "---":
        diagnostics.append(
            _diagnostic(
                "FM001",
                Severity.ERROR,
                root,
                path,
                1,
                "missing opening '---' frontmatter delimiter",
            )
        )
        return ParsedDocument({}, {}, text, text), diagnostics

    closing_index: Optional[int] = None
    for index in range(1, len(lines)):
        if lines[index] == "---":
            closing_index = index
            break
    if closing_index is None:
        diagnostics.append(
            _diagnostic(
                "FM002",
                Severity.ERROR,
                root,
                path,
                1,
                "missing closing '---' frontmatter delimiter",
            )
        )
        return ParsedDocument({}, {}, "", text), diagnostics

    metadata: dict[str, object] = {}
    field_lines: dict[str, int] = {}
    seen_fields: set[str] = set()
    for index in range(1, closing_index):
        line_number = index + 1
        line = lines[index]
        if not line.strip():
            continue
        if line != line.lstrip():
            diagnostics.append(
                _diagnostic(
                    "FM003",
                    Severity.ERROR,
                    root,
                    path,
                    line_number,
                    "nested or indented frontmatter is not supported",
                )
            )
            continue

        match = FIELD.match(line)
        if not match:
            diagnostics.append(
                _diagnostic(
                    "FM003",
                    Severity.ERROR,
                    root,
                    path,
                    line_number,
                    "expected a top-level 'key: value' field",
                )
            )
            continue

        key = match.group("key")
        raw_value = match.group("value").strip()
        if key in seen_fields:
            diagnostics.append(
                _diagnostic(
                    "FM004",
                    Severity.ERROR,
                    root,
                    path,
                    line_number,
                    f"duplicate frontmatter field {key!r}",
                )
            )
            continue
        seen_fields.add(key)
        if not raw_value:
            diagnostics.append(
                _diagnostic(
                    "FM005",
                    Severity.ERROR,
                    root,
                    path,
                    line_number,
                    "empty, nested, and multiline field values are not supported",
                )
            )
            continue

        value: object
        if raw_value.startswith("["):
            try:
                value = json.loads(
                    raw_value, parse_constant=_reject_json_constant
                )
            except (json.JSONDecodeError, ValueError) as error:
                diagnostics.append(
                    _diagnostic(
                        "FM006",
                        Severity.ERROR,
                        root,
                        path,
                        line_number,
                        f"invalid JSON inline array: {error}",
                    )
                )
                continue
            if not isinstance(value, list) or any(
                isinstance(item, (dict, list)) for item in value
            ):
                diagnostics.append(
                    _diagnostic(
                        "FM007",
                        Severity.ERROR,
                        root,
                        path,
                        line_number,
                        "arrays must be inline JSON arrays containing only scalar values",
                    )
                )
                continue
        elif raw_value.startswith('"'):
            try:
                value = json.loads(raw_value)
            except json.JSONDecodeError as error:
                diagnostics.append(
                    _diagnostic(
                        "FM008",
                        Severity.ERROR,
                        root,
                        path,
                        line_number,
                        f"invalid JSON-quoted scalar: {error}",
                    )
                )
                continue
            if not isinstance(value, str):
                diagnostics.append(
                    _diagnostic(
                        "FM008",
                        Severity.ERROR,
                        root,
                        path,
                        line_number,
                        "double-quoted frontmatter values must be JSON strings",
                    )
                )
                continue
        elif raw_value[0] in "{'|>":
            diagnostics.append(
                _diagnostic(
                    "FM009",
                    Severity.ERROR,
                    root,
                    path,
                    line_number,
                    "mapping, single-quoted, and multiline YAML values are not supported",
                )
            )
            continue
        else:
            value = raw_value

        metadata[key] = value
        field_lines[key] = line_number

    body = "\n".join(lines[closing_index + 1 :])
    return ParsedDocument(metadata, field_lines, body, text), diagnostics


def parse_agent_toml(
    path: Path, root: Path
) -> tuple[ParsedDocument, list[Diagnostic]]:
    """Parse the dependency-free TOML subset used by Codex agent files."""

    diagnostics: list[Diagnostic] = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        diagnostics.append(
            _diagnostic("IO001", Severity.ERROR, root, path, 1, f"cannot read UTF-8 text: {error}")
        )
        return ParsedDocument({}, {}, "", ""), diagnostics

    metadata: dict[str, object] = {}
    field_lines: dict[str, int] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line_number = index + 1
        line = lines[index].strip()
        index += 1
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            diagnostics.append(
                _diagnostic(
                    "TOML004", Severity.ERROR, root, path, line_number,
                    "Codex agent files must use top-level scalar fields only",
                )
            )
            continue
        if "=" not in line:
            diagnostics.append(
                _diagnostic("TOML001", Severity.ERROR, root, path, line_number, "expected 'key = value'")
            )
            continue
        key, raw_value = (part.strip() for part in line.split("=", 1))
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", key):
            diagnostics.append(
                _diagnostic("TOML001", Severity.ERROR, root, path, line_number, f"invalid key {key!r}")
            )
            continue
        if key in metadata:
            diagnostics.append(
                _diagnostic("TOML002", Severity.ERROR, root, path, line_number, f"duplicate field {key!r}")
            )
            continue
        value: Optional[str] = None
        if raw_value == '"""':
            content: list[str] = []
            while index < len(lines) and lines[index].strip() != '"""':
                content.append(lines[index])
                index += 1
            if index >= len(lines):
                diagnostics.append(
                    _diagnostic("TOML003", Severity.ERROR, root, path, line_number, f"unterminated multiline string for {key!r}")
                )
                continue
            index += 1
            value = "\n".join(content)
        elif raw_value.startswith('"'):
            try:
                decoded = json.loads(raw_value)
            except json.JSONDecodeError as error:
                diagnostics.append(
                    _diagnostic("TOML003", Severity.ERROR, root, path, line_number, f"invalid quoted string: {error}")
                )
                continue
            if isinstance(decoded, str):
                value = decoded
        if value is None:
            diagnostics.append(
                _diagnostic(
                    "TOML003", Severity.ERROR, root, path, line_number,
                    "agent fields must be quoted strings or multiline strings",
                )
            )
            continue
        metadata[key] = value
        field_lines[key] = line_number

    return ParsedDocument(metadata, field_lines, str(metadata.get("developer_instructions", "")), text), diagnostics


def _sorted_paths(paths: Iterable[Path]) -> list[Path]:
    return sorted(paths, key=lambda item: (item.as_posix().casefold(), item.as_posix()))


def _estimated_tokens(text: str) -> int:
    """Return a tokenizer-independent regression estimate based on UTF-8 size."""

    return (len(text.encode("utf-8")) + 3) // 4


def _context_budget_paths(root: Path) -> list[tuple[Path, int]]:
    """Return runtime customization artifacts and their estimated-token budgets."""

    github = root / ".github"
    candidates: dict[Path, int] = {}

    def add(paths: Iterable[Path], budget: int) -> None:
        for path in paths:
            if path.is_file():
                candidates[path] = budget

    agent_dir = github / "agents"
    add(agent_dir.glob("*.md") if agent_dir.is_dir() else [], TOKEN_BUDGETS["agent"])
    instruction_dir = github / "instructions"
    add(
        instruction_dir.glob("*.instructions.md")
        if instruction_dir.is_dir()
        else [],
        TOKEN_BUDGETS["instruction"],
    )
    prompt_dir = github / "prompts"
    add(
        prompt_dir.glob("*.prompt.md") if prompt_dir.is_dir() else [],
        TOKEN_BUDGETS["prompt"],
    )
    skill_dir = github / "skills"
    add(
        skill_dir.glob("*/SKILL.md") if skill_dir.is_dir() else [],
        TOKEN_BUDGETS["skill"],
    )

    codex_agent_dir = root / ".codex" / "agents"
    add(
        codex_agent_dir.glob("*.toml") if codex_agent_dir.is_dir() else [],
        TOKEN_BUDGETS["agent"],
    )
    codex_instruction_dir = root / ".codex" / "instructions"
    add(
        codex_instruction_dir.glob("*.md")
        if codex_instruction_dir.is_dir()
        else [],
        TOKEN_BUDGETS["instruction"],
    )
    codex_skill_dir = root / ".agents" / "skills"
    add(
        codex_skill_dir.glob("*/SKILL.md") if codex_skill_dir.is_dir() else [],
        TOKEN_BUDGETS["skill"],
    )

    claude_agent_dir = root / ".claude" / "agents"
    add(
        claude_agent_dir.glob("*.md") if claude_agent_dir.is_dir() else [],
        TOKEN_BUDGETS["agent"],
    )
    claude_rule_dir = root / ".claude" / "rules"
    add(
        claude_rule_dir.glob("*.md") if claude_rule_dir.is_dir() else [],
        TOKEN_BUDGETS["instruction"],
    )
    claude_skill_dir = root / ".claude" / "skills"
    add(
        claude_skill_dir.glob("*/SKILL.md") if claude_skill_dir.is_dir() else [],
        TOKEN_BUDGETS["skill"],
    )

    for relative_path, budget in TOKEN_BUDGET_OVERRIDES.items():
        path = root / relative_path
        if path.is_file():
            candidates[path] = budget

    return [(path, candidates[path]) for path in _sorted_paths(candidates)]


def _validate_token_budgets(root: Path, diagnostics: list[Diagnostic]) -> None:
    """Warn when runtime context exceeds a deterministic size guardrail."""

    for path, budget in _context_budget_paths(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        estimated = _estimated_tokens(text)
        if estimated > budget:
            diagnostics.append(
                _diagnostic(
                    "TOK001",
                    Severity.WARNING,
                    root,
                    path,
                    1,
                    f"estimated context size {estimated} exceeds token budget "
                    f"{budget} (UTF-8 bytes/4 regression proxy)",
                )
            )


def _required_string(
    document: ParsedDocument,
    field: str,
    root: Path,
    path: Path,
    diagnostics: list[Diagnostic],
) -> Optional[str]:
    value = document.metadata.get(field)
    line = document.field_lines.get(field, 1)
    if value is None or (isinstance(value, str) and not value.strip()):
        diagnostics.append(
            _diagnostic(
                "META001",
                Severity.ERROR,
                root,
                path,
                line,
                f"missing required non-empty field {field!r}",
            )
        )
        return None
    if not isinstance(value, str):
        diagnostics.append(
            _diagnostic(
                "META002",
                Severity.ERROR,
                root,
                path,
                line,
                f"field {field!r} must be a scalar string",
            )
        )
        return None
    return value


def _optional_string(
    document: ParsedDocument,
    field: str,
    root: Path,
    path: Path,
    diagnostics: list[Diagnostic],
) -> Optional[str]:
    if field not in document.metadata:
        return None
    value = document.metadata[field]
    if not isinstance(value, str) or not value.strip():
        diagnostics.append(
            _diagnostic(
                "META002",
                Severity.ERROR,
                root,
                path,
                document.field_lines.get(field, 1),
                f"field {field!r} must be a non-empty scalar string",
            )
        )
        return None
    return value


def _optional_string_list(
    document: ParsedDocument,
    field: str,
    root: Path,
    path: Path,
    diagnostics: list[Diagnostic],
    *,
    required: bool = False,
) -> Optional[list[str]]:
    value = document.metadata.get(field)
    line = document.field_lines.get(field, 1)
    if value is None:
        if required:
            diagnostics.append(
                _diagnostic(
                    "META001",
                    Severity.ERROR,
                    root,
                    path,
                    line,
                    f"missing required array field {field!r}",
                )
            )
        return None
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        diagnostics.append(
            _diagnostic(
                "META003",
                Severity.ERROR,
                root,
                path,
                line,
                f"field {field!r} must be an inline JSON array of non-empty strings",
            )
        )
        return None
    return value


def _register_identifier(
    identifiers: dict[str, Identifier],
    name: str,
    root: Path,
    path: Path,
    line: int,
    kind: str,
    diagnostics: list[Diagnostic],
) -> None:
    key = name.casefold()
    previous = identifiers.get(key)
    if previous is not None:
        diagnostics.append(
            _diagnostic(
                "ID001",
                Severity.ERROR,
                root,
                path,
                line,
                f"case-insensitive duplicate {kind} identifier {name!r}; "
                f"first declared at "
                f"{previous.path}:{previous.line}",
            )
        )
        return
    identifiers[key] = Identifier(name, _relative_path(root, path), line)


def _check_reference(
    reference: str,
    identifiers: dict[str, Identifier],
    root: Path,
    path: Path,
    line: int,
    context: str,
    diagnostics: list[Diagnostic],
) -> None:
    identifier = identifiers.get(reference.casefold())
    if identifier is None:
        diagnostics.append(
            _diagnostic(
                "REF001",
                Severity.ERROR,
                root,
                path,
                line,
                f"{context} references unknown agent {reference!r}",
            )
        )
    elif identifier.name != reference:
        diagnostics.append(
            _diagnostic(
                "REF002",
                Severity.ERROR,
                root,
                path,
                line,
                f"{context} uses {reference!r}, but the declared casing is "
                f"{identifier.name!r}",
            )
        )


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def _fence_marker(line: str) -> Optional[tuple[str, int, str]]:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3:
        return None
    match = re.match(r"(?P<marker>`{3,}|~{3,})(?P<rest>.*)$", stripped)
    if not match:
        return None
    marker = match.group("marker")
    return marker[0], len(marker), match.group("rest")


def _unfenced_lines(text: str) -> Iterable[tuple[int, str]]:
    fence_character: Optional[str] = None
    fence_length = 0
    offset = 0
    for line_with_ending in text.splitlines(keepends=True):
        line = line_with_ending.rstrip("\r\n")
        marker = _fence_marker(line)
        if fence_character is not None:
            if (
                marker is not None
                and marker[0] == fence_character
                and marker[1] >= fence_length
                and not marker[2].strip()
            ):
                fence_character = None
                fence_length = 0
            offset += len(line_with_ending)
            continue
        if marker is not None and not (
            marker[0] == "`" and "`" in marker[2]
        ):
            fence_character, fence_length = marker[0], marker[1]
            offset += len(line_with_ending)
            continue
        yield offset, line
        offset += len(line_with_ending)


def _label_end(line: str, opening: int) -> Optional[int]:
    depth = 1
    index = opening + 1
    while index < len(line):
        if line[index] == "\\" and index + 1 < len(line):
            index += 2
            continue
        if line[index] == "[":
            depth += 1
        elif line[index] == "]":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _title_and_link_end(line: str, index: int) -> Optional[int]:
    while index < len(line) and line[index] in " \t":
        index += 1
    if index >= len(line):
        return None
    if line[index] == ")":
        return index + 1

    opener = line[index]
    if opener in ('"', "'"):
        index += 1
        while index < len(line):
            if line[index] == "\\" and index + 1 < len(line):
                index += 2
                continue
            if line[index] == opener:
                index += 1
                break
            index += 1
        else:
            return None
    elif opener == "(":
        depth = 1
        index += 1
        while index < len(line):
            if line[index] == "\\" and index + 1 < len(line):
                index += 2
                continue
            if line[index] == "(":
                depth += 1
            elif line[index] == ")":
                depth -= 1
                if depth == 0:
                    index += 1
                    break
            index += 1
        if depth:
            return None
    else:
        return None

    while index < len(line) and line[index] in " \t":
        index += 1
    return index + 1 if index < len(line) and line[index] == ")" else None


def _link_destination(line: str, opening: int) -> Optional[tuple[str, int]]:
    index = opening + 1
    while index < len(line) and line[index] in " \t":
        index += 1
    if index >= len(line):
        return None

    if line[index] == "<":
        start = index + 1
        index = start
        while index < len(line):
            if line[index] == "\\" and index + 1 < len(line):
                index += 2
                continue
            if line[index] == ">":
                end = _title_and_link_end(line, index + 1)
                if end is None:
                    return None
                return line[start:index], end
            index += 1
        return None

    start = index
    nested_parentheses = 0
    while index < len(line):
        character = line[index]
        if character == "\\" and index + 1 < len(line):
            index += 2
            continue
        if character == "(":
            nested_parentheses += 1
        elif character == ")":
            if nested_parentheses == 0:
                return line[start:index], index + 1
            nested_parentheses -= 1
        elif character in " \t":
            end = _title_and_link_end(line, index)
            if end is None:
                return None
            return line[start:index], end
        index += 1
    return None


def _unescape_link_target(target: str) -> str:
    return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\\\]^_`{|}~])", r"\1", target)


def _inline_links(text: str) -> Iterable[tuple[str, int]]:
    for offset, line in _unfenced_lines(text):
        index = 0
        while index < len(line):
            opening = line.find("[", index)
            if opening < 0:
                break
            if _is_escaped(line, opening):
                index = opening + 1
                continue
            closing = _label_end(line, opening)
            if closing is None or closing + 1 >= len(line) or line[closing + 1] != "(":
                index = opening + 1
                continue
            destination = _link_destination(line, closing + 1)
            if destination is None:
                index = closing + 1
                continue
            target, end = destination
            yield _unescape_link_target(target), offset + opening
            index = end


def _local_link_diagnostic(
    root: Path, source: Path, target: str, line: int
) -> Optional[Diagnostic]:
    if not target or target.startswith("#") or target.startswith("//"):
        return None
    if URI_SCHEME.match(target) and not WINDOWS_DRIVE.match(target):
        return None

    path_part = target.split("#", 1)[0].split("?", 1)[0]
    if not path_part:
        return None
    path_part = unquote(path_part)
    requested = Path(path_part)
    candidate = requested if requested.is_absolute() else source.parent / requested
    root_resolved = root.resolve()
    try:
        # Keep a lexical, normalized path for case comparison. Path.resolve()
        # may canonicalize casing on case-insensitive filesystems.
        root_lexical = Path(os.path.abspath(str(root)))
        candidate_lexical = Path(os.path.abspath(str(candidate)))
        relative = candidate_lexical.relative_to(root_lexical)
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        return _diagnostic(
            "LINK001",
            Severity.ERROR,
            root,
            source,
            line,
            f"local link escapes the repository root: {target!r}",
        )

    current = root_resolved
    for part in relative.parts:
        try:
            names = {entry.name: entry for entry in current.iterdir()}
        except OSError:
            return _diagnostic(
                "LINK002",
                Severity.ERROR,
                root,
                source,
                line,
                f"local link target does not exist: {target!r}",
            )
        exact = names.get(part)
        if exact is not None:
            current = exact
            continue
        case_matches = sorted(
            (name for name in names if name.casefold() == part.casefold()),
            key=lambda name: (name.casefold(), name),
        )
        if case_matches:
            actual = case_matches[0]
            return _diagnostic(
                "LINK003",
                Severity.ERROR,
                root,
                source,
                line,
                f"local link casing differs from disk: requested {part!r}, "
                f"found {actual!r}",
            )
        return _diagnostic(
            "LINK002",
            Severity.ERROR,
            root,
            source,
            line,
            f"local link target does not exist: {target!r}",
        )
    return None


def _markdown_files(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for name in ("README.md", "AGENTS.md", "CLAUDE.md"):
        path = root / name
        if path.is_file():
            candidates.add(path)
    for directory in (
        root / ".github",
        root / ".agents",
        root / ".codex",
        root / ".claude",
        root / "docs",
    ):
        if directory.is_dir():
            candidates.update(path for path in directory.rglob("*.md") if path.is_file())
    return _sorted_paths(candidates)


def _validate_links(root: Path, diagnostics: list[Diagnostic]) -> None:
    for path in _markdown_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            diagnostics.append(
                _diagnostic(
                    "IO001",
                    Severity.ERROR,
                    root,
                    path,
                    1,
                    f"cannot read UTF-8 text: {error}",
                )
            )
            continue
        for target, offset in _inline_links(text):
            line = text.count("\n", 0, offset) + 1
            result = _local_link_diagnostic(root, path, target, line)
            if result is not None:
                diagnostics.append(result)


def _validate_skill_tree(
    root: Path, skill_dir: Path, platform: str, diagnostics: list[Diagnostic]
) -> dict[str, Identifier]:
    """Validate one platform's independent Agent Skills tree."""

    skills: dict[str, Identifier] = {}
    paths = skill_dir.glob("*/SKILL.md") if skill_dir.is_dir() else []
    for path in _sorted_paths(paths):
        document, parse_diagnostics = parse_frontmatter(path, root)
        diagnostics.extend(parse_diagnostics)
        name = _required_string(document, "name", root, path, diagnostics)
        description = _required_string(document, "description", root, path, diagnostics)
        name_line = document.field_lines.get("name", 1)
        if name is not None:
            if name != path.parent.name:
                diagnostics.append(
                    _diagnostic(
                        "SKILL001", Severity.ERROR, root, path, name_line,
                        f"{platform} skill name {name!r} must exactly match directory {path.parent.name!r}",
                    )
                )
            if len(name) > 64:
                diagnostics.append(
                    _diagnostic("SKILL002", Severity.ERROR, root, path, name_line, "skill name exceeds 64 characters")
                )
            _register_identifier(skills, name, root, path, name_line, f"{platform} skill", diagnostics)
        if description is not None and len(description) > 1024:
            diagnostics.append(
                _diagnostic(
                    "SKILL003", Severity.ERROR, root, path,
                    document.field_lines.get("description", 1),
                    "skill description exceeds 1024 characters",
                )
            )
        if not document.body.strip():
            diagnostics.append(
                _diagnostic(
                    "SKILL004", Severity.ERROR, root, path,
                    max(document.field_lines.values(), default=1) + 2,
                    "skill body must contain instructions after frontmatter",
                )
            )
    return skills


def _validate_codex(root: Path, diagnostics: list[Diagnostic]) -> None:
    agent_dir = root / ".codex" / "agents"
    if not agent_dir.is_dir():
        return
    identifiers: dict[str, Identifier] = {}
    for path in _sorted_paths(agent_dir.glob("*.toml")):
        document, parse_diagnostics = parse_agent_toml(path, root)
        diagnostics.extend(parse_diagnostics)
        name = _required_string(document, "name", root, path, diagnostics)
        _required_string(document, "description", root, path, diagnostics)
        instructions = _required_string(document, "developer_instructions", root, path, diagnostics)
        sandbox = _required_string(document, "sandbox_mode", root, path, diagnostics)
        if name is None:
            continue
        _register_identifier(
            identifiers, name, root, path, document.field_lines.get("name", 1),
            "Codex agent", diagnostics,
        )
        if path.stem != name:
            diagnostics.append(
                _diagnostic("CODEX001", Severity.ERROR, root, path, 1, f"agent filename must match name {name!r}")
            )
        expected_sandbox = "read-only" if name in READ_ONLY_AGENTS else "workspace-write"
        if sandbox is not None and sandbox != expected_sandbox:
            diagnostics.append(
                _diagnostic(
                    "CODEX002", Severity.ERROR, root, path,
                    document.field_lines.get("sandbox_mode", 1),
                    f"agent {name!r} requires sandbox_mode {expected_sandbox!r}",
                )
            )
        if "model" in document.metadata or "model_reasoning_effort" in document.metadata:
            diagnostics.append(
                _diagnostic("CODEX003", Severity.ERROR, root, path, 1, "kit agents must inherit model and reasoning effort")
            )
        if instructions is not None and name in READ_ONLY_AGENTS and "never" not in instructions.casefold():
            diagnostics.append(
                _diagnostic("CODEX004", Severity.ERROR, root, path, 1, "read-only agent instructions must explicitly prohibit modification")
            )
    missing = sorted(EXPECTED_AGENTS.difference(identifiers))
    if missing:
        diagnostics.append(
            _diagnostic("CODEX005", Severity.ERROR, root, agent_dir, 1, "missing expected Codex agents: " + ", ".join(missing))
        )
    codex_skills = _validate_skill_tree(root, root / ".agents" / "skills", "Codex", diagnostics)
    missing_skills = sorted(EXPECTED_SKILLS.difference(codex_skills))
    if missing_skills:
        diagnostics.append(
            _diagnostic("CODEX006", Severity.ERROR, root, root / ".agents" / "skills", 1, "missing expected Codex skills: " + ", ".join(missing_skills))
        )


def _validate_claude(root: Path, diagnostics: list[Diagnostic]) -> None:
    agent_dir = root / ".claude" / "agents"
    if not agent_dir.is_dir():
        return
    identifiers: dict[str, Identifier] = {}
    claude_skills = _validate_skill_tree(root, root / ".claude" / "skills", "Claude", diagnostics)
    for path in _sorted_paths(agent_dir.glob("*.md")):
        document, parse_diagnostics = parse_frontmatter(path, root)
        diagnostics.extend(parse_diagnostics)
        name = _required_string(document, "name", root, path, diagnostics)
        _required_string(document, "description", root, path, diagnostics)
        tools = _optional_string_list(document, "tools", root, path, diagnostics, required=True)
        model = _optional_string(document, "model", root, path, diagnostics)
        _required_string(document, "permissionMode", root, path, diagnostics)
        preloaded = _optional_string_list(document, "skills", root, path, diagnostics)
        if name is None:
            continue
        _register_identifier(
            identifiers, name, root, path, document.field_lines.get("name", 1),
            "Claude agent", diagnostics,
        )
        if not CLAUDE_AGENT_NAME.fullmatch(name) or path.stem != name:
            diagnostics.append(
                _diagnostic("CLAUDE001", Severity.ERROR, root, path, 1, "Claude agent name must be lowercase hyphenated and match its filename")
            )
        if model is not None and model != "inherit":
            diagnostics.append(
                _diagnostic("CLAUDE002", Severity.ERROR, root, path, document.field_lines.get("model", 1), "kit agents must use model: inherit")
            )
        write_tools = {"Edit", "Write"}
        if tools is not None:
            if name in READ_ONLY_AGENTS and write_tools.intersection(tools):
                diagnostics.append(
                    _diagnostic("CLAUDE003", Severity.ERROR, root, path, document.field_lines.get("tools", 1), f"read-only agent {name!r} cannot expose Edit or Write")
                )
            if name not in READ_ONLY_AGENTS and not write_tools.issubset(tools):
                diagnostics.append(
                    _diagnostic("CLAUDE004", Severity.ERROR, root, path, document.field_lines.get("tools", 1), f"writer agent {name!r} requires Edit and Write")
                )
        for skill in preloaded or []:
            if skill.casefold() not in claude_skills:
                diagnostics.append(
                    _diagnostic("CLAUDE005", Severity.ERROR, root, path, document.field_lines.get("skills", 1), f"agent preloads unknown Claude skill {skill!r}")
                )
    missing = sorted(EXPECTED_AGENTS.difference(identifiers))
    if missing:
        diagnostics.append(
            _diagnostic("CLAUDE006", Severity.ERROR, root, agent_dir, 1, "missing expected Claude agents: " + ", ".join(missing))
        )
    missing_skills = sorted(EXPECTED_SKILLS.difference(claude_skills))
    if missing_skills:
        diagnostics.append(
            _diagnostic("CLAUDE007", Severity.ERROR, root, root / ".claude" / "skills", 1, "missing expected Claude skills: " + ", ".join(missing_skills))
        )

    rule_dir = root / ".claude" / "rules"
    for path in _sorted_paths(rule_dir.glob("*.md") if rule_dir.is_dir() else []):
        document, parse_diagnostics = parse_frontmatter(path, root)
        diagnostics.extend(parse_diagnostics)
        _optional_string_list(document, "paths", root, path, diagnostics, required=True)


def _validate_installed(root: Path, diagnostics: list[Diagnostic]) -> None:
    path = root / "AGENTS.md"
    if not path.is_file():
        diagnostics.append(
            _diagnostic(
                "INST001",
                Severity.ERROR,
                root,
                path,
                1,
                "installed mode requires AGENTS.md",
            )
        )
        return
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        diagnostics.append(
            _diagnostic(
                "IO001",
                Severity.ERROR,
                root,
                path,
                1,
                f"cannot read UTF-8 text: {error}",
            )
        )
        return
    for match in INSTALLED_PLACEHOLDER.finditer(text):
        diagnostics.append(
            _diagnostic(
                "INST002",
                Severity.ERROR,
                root,
                path,
                text.count("\n", 0, match.start()) + 1,
                "replace the project-map placeholder before using installed mode",
            )
        )


def validate(
    root: Optional[Path] = None, *, installed: bool = False, strict: bool = False
) -> list[Diagnostic]:
    """Validate a repository and return stable, source-located diagnostics."""

    root = (root or DEFAULT_ROOT).resolve()
    diagnostics: list[Diagnostic] = []
    github = root / ".github"
    if not github.is_dir():
        diagnostics.append(
            _diagnostic(
                "CFG001",
                Severity.ERROR,
                root,
                github,
                1,
                "missing .github customization directory",
            )
        )

    agent_documents: list[tuple[Path, ParsedDocument]] = []
    agents: dict[str, Identifier] = {}
    agent_dir = github / "agents"
    for path in _sorted_paths(agent_dir.glob("*.md") if agent_dir.is_dir() else []):
        document, parse_diagnostics = parse_frontmatter(path, root)
        diagnostics.extend(parse_diagnostics)
        agent_documents.append((path, document))
        name = _required_string(document, "name", root, path, diagnostics)
        _required_string(document, "description", root, path, diagnostics)
        _optional_string_list(
            document, "tools", root, path, diagnostics, required=True
        )
        if name is not None:
            _register_identifier(
                agents,
                name,
                root,
                path,
                document.field_lines.get("name", 1),
                "agent",
                diagnostics,
            )

    for path, document in agent_documents:
        tools = _optional_string_list(document, "tools", root, path, [], required=False)
        whitelist_diagnostics: list[Diagnostic] = []
        whitelist = _optional_string_list(
            document, "agents", root, path, whitelist_diagnostics, required=False
        )
        diagnostics.extend(whitelist_diagnostics)
        whitelist_line = document.field_lines.get("agents", 1)
        if whitelist is not None:
            seen: set[str] = set()
            for reference in whitelist:
                folded = reference.casefold()
                if folded in seen:
                    diagnostics.append(
                        _diagnostic(
                            "REF003",
                            Severity.ERROR,
                            root,
                            path,
                            whitelist_line,
                            f"agents whitelist repeats {reference!r} case-insensitively",
                        )
                    )
                else:
                    seen.add(folded)
                _check_reference(
                    reference,
                    agents,
                    root,
                    path,
                    whitelist_line,
                    "agents whitelist",
                    diagnostics,
                )
            if tools is None or "agent" not in tools:
                diagnostics.append(
                    _diagnostic(
                        "POL002",
                        Severity.ERROR,
                        root,
                        path,
                        whitelist_line,
                        "an agents whitelist requires the 'agent' tool",
                    )
                )
        if path.name.casefold() == "task-coordinator.agent.md":
            if not whitelist:
                diagnostics.append(
                    _diagnostic(
                        "POL004",
                        Severity.ERROR,
                        root,
                        path,
                        document.field_lines.get("name", 1),
                        "task coordinator requires a non-empty agents whitelist",
                    )
                )
            if tools is None or "agent" not in tools:
                diagnostics.append(
                    _diagnostic(
                        "POL005",
                        Severity.ERROR,
                        root,
                        path,
                        document.field_lines.get("tools", 1),
                        "task coordinator requires the 'agent' tool",
                    )
                )
            missing_receipt_fields = tuple(
                field
                for field in COORDINATOR_RECEIPT_FIELDS
                if field not in document.body.casefold()
            )
            if missing_receipt_fields:
                diagnostics.append(
                    _diagnostic(
                        "POL006",
                        Severity.ERROR,
                        root,
                        path,
                        1,
                        "task coordinator requires compact receipt fields: "
                        + ", ".join(missing_receipt_fields),
                    )
                )
        if tools is not None and "agent" in tools and not whitelist:
            diagnostics.append(
                _diagnostic(
                    "POL003",
                    Severity.WARNING,
                    root,
                    path,
                    document.field_lines.get("tools", 1),
                    "kit policy recommends an explicit agents whitelist for delegation",
                )
            )

    prompts: dict[str, Identifier] = {}
    prompt_documents: list[tuple[Path, ParsedDocument, Optional[str]]] = []
    prompt_dir = github / "prompts"
    for path in _sorted_paths(prompt_dir.glob("*.prompt.md") if prompt_dir.is_dir() else []):
        document, parse_diagnostics = parse_frontmatter(path, root)
        diagnostics.extend(parse_diagnostics)
        name = _required_string(document, "name", root, path, diagnostics)
        _required_string(document, "description", root, path, diagnostics)
        agent = _optional_string(document, "agent", root, path, diagnostics)
        if "tools" in document.metadata:
            _optional_string_list(document, "tools", root, path, diagnostics)
        if name is not None:
            _register_identifier(
                prompts,
                name,
                root,
                path,
                document.field_lines.get("name", 1),
                "prompt",
                diagnostics,
            )
        prompt_documents.append((path, document, agent))

    for path, document, agent in prompt_documents:
        if agent is not None and agent not in BUILTIN_PROMPT_AGENTS:
            _check_reference(
                agent,
                agents,
                root,
                path,
                document.field_lines.get("agent", 1),
                "prompt",
                diagnostics,
            )

    instruction_dir = github / "instructions"
    for path in _sorted_paths(
        instruction_dir.glob("*.instructions.md") if instruction_dir.is_dir() else []
    ):
        document, parse_diagnostics = parse_frontmatter(path, root)
        diagnostics.extend(parse_diagnostics)
        _required_string(document, "applyTo", root, path, diagnostics)

    skills: dict[str, Identifier] = {}
    skill_dir = github / "skills"
    skill_paths = skill_dir.glob("*/SKILL.md") if skill_dir.is_dir() else []
    for path in _sorted_paths(skill_paths):
        document, parse_diagnostics = parse_frontmatter(path, root)
        diagnostics.extend(parse_diagnostics)
        name = _required_string(document, "name", root, path, diagnostics)
        description = _required_string(
            document, "description", root, path, diagnostics
        )
        name_line = document.field_lines.get("name", 1)
        if name is not None:
            if name != path.parent.name:
                diagnostics.append(
                    _diagnostic(
                        "SKILL001",
                        Severity.ERROR,
                        root,
                        path,
                        name_line,
                        f"skill name {name!r} must exactly match directory "
                        f"{path.parent.name!r}",
                    )
                )
            if len(name) > 64:
                diagnostics.append(
                    _diagnostic(
                        "SKILL002",
                        Severity.ERROR,
                        root,
                        path,
                        name_line,
                        "skill name exceeds 64 characters",
                    )
                )
            _register_identifier(
                skills,
                name,
                root,
                path,
                name_line,
                "skill",
                diagnostics,
            )
        if description is not None and len(description) > 1024:
            diagnostics.append(
                _diagnostic(
                    "SKILL003",
                    Severity.ERROR,
                    root,
                    path,
                    document.field_lines.get("description", 1),
                    "skill description exceeds 1024 characters",
                )
            )
        if not document.body.strip():
            diagnostics.append(
                _diagnostic(
                    "SKILL004",
                    Severity.ERROR,
                    root,
                    path,
                    max(document.field_lines.values(), default=1) + 2,
                    "skill body must contain instructions after frontmatter",
                )
            )

    for key in sorted(set(prompts).intersection(skills)):
        prompt = prompts[key]
        skill = skills[key]
        diagnostics.append(
            Diagnostic(
                "POL001",
                Severity.WARNING,
                prompt.path,
                prompt.line,
                f"prompt {prompt.name!r} collides case-insensitively with skill "
                f"{skill.name!r} at {skill.path}:{skill.line}",
            )
        )

    _validate_codex(root, diagnostics)
    _validate_claude(root, diagnostics)
    _validate_links(root, diagnostics)
    _validate_token_budgets(root, diagnostics)
    if installed:
        _validate_installed(root, diagnostics)

    if strict:
        diagnostics = [diagnostic.promoted() for diagnostic in diagnostics]
    diagnostics = list(dict.fromkeys(diagnostics))
    return sorted(
        diagnostics,
        key=lambda item: (
            item.path.casefold(),
            item.path,
            item.line,
            item.code,
            item.severity.value,
            item.message,
        ),
    )


class DiagnosticArgumentParser(argparse.ArgumentParser):
    """Argument parser that keeps usage failures machine-readable."""

    def error(self, message: str) -> None:
        self._print_message(
            Diagnostic(
                "CLI003",
                Severity.ERROR,
                "<arguments>",
                1,
                f"invalid arguments: {message}",
            ).render()
            + "\n",
            sys.stderr,
        )
        raise SystemExit(2)


def _build_parser() -> argparse.ArgumentParser:
    parser = DiagnosticArgumentParser(
        description=(
            "Validate the dependency-free structural subset used by the "
            "Copilot, Codex, and Claude Code customization kit."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="repository root to validate (default: script repository)",
    )
    parser.add_argument(
        "--installed",
        action="store_true",
        help="also reject unresolved project-map placeholders in AGENTS.md",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="promote policy warnings to errors",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
    except (OSError, RuntimeError) as error:
        print(
            Diagnostic(
                "CLI002",
                Severity.ERROR,
                str(args.root),
                1,
                f"cannot resolve --root ({type(error).__name__}): {error}",
            ).render(),
            file=sys.stderr,
        )
        return 2
    if not root.is_dir():
        print(
            Diagnostic(
                "CLI001",
                Severity.ERROR,
                str(args.root),
                1,
                "--root must reference an existing directory",
            ).render(),
            file=sys.stderr,
        )
        return 2

    try:
        diagnostics = validate(
            root, installed=args.installed, strict=args.strict
        )
    except Exception as error:  # Translate unexpected failures into exit code 2.
        print(
            Diagnostic(
                "INT001",
                Severity.ERROR,
                "<internal>",
                1,
                f"unexpected validation failure ({type(error).__name__}): {error}",
            ).render(),
            file=sys.stderr,
        )
        return 2

    for diagnostic in diagnostics:
        print(diagnostic.render())
    errors = sum(item.severity is Severity.ERROR for item in diagnostics)
    warnings = sum(item.severity is Severity.WARNING for item in diagnostics)
    if errors:
        print(f"Customization validation failed: {errors} error(s), {warnings} warning(s).")
        return 1
    if warnings:
        print(f"Customization validation passed with {warnings} warning(s).")
    else:
        print("Customization validation passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
