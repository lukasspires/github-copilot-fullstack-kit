"""scripts/marina/envelope.py — the human-approved envelope of a task.

Implements spec §3.2 (docs/plano-marina-executavel-e-exclusividade-claude-2026-10.md)
as planned in docs/plano-f3-envelope-e-decide-2026-10.md:

- `parse_envelope` checks the shape of the opaque `[envelope]` table that
  `scripts.state` preserves (`StateDoc.envelope`). Unknown keys are refused,
  because the approval hash only covers the known ones (plan decision 4).
- `validate_envelope` checks it against the task and the kit: writer roles
  with a profile (never `marina`, and the same role in every stage, since
  G3 `prossegue` requires the predecessor's role — plan decision 9),
  handoffs inside the task directory, absolute targets that belong to the
  task and each have a branch (decision 5), and the same allowlist
  refusals as `launch_claude`.
- `compute_hash` covers the envelope without its approval plus the content
  of every stage handoff, so editing a handoff after approval invalidates
  it.

"Schema v1" is the envelope's own first version inside a `schema = 1`
`state.toml` (plan decision 2). Library only; `approve` (the one writer)
lives here too and is reached through `marina approve`.
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Callable, TextIO

from scripts.launch_claude import LaunchRefused, _check_forbidden_allowlist
from scripts.state import StateDoc, StateError, read_state, write_state
from scripts.state.model import mode_for_role

REVIEW_MODES = ("each_stage", "final")
PASS_WITH_RISKS_POLICIES = ("accept", "judge", "stop")

_REQUIRED_KEYS = (
    "targets",
    "branches",
    "allowlist",
    "review",
    "max_corrections",
    "max_duration",
    "judge_max_calls",
    "on_pass_with_risks",
    "stages",
)
_DURATION_RE = re.compile(r"^([1-9][0-9]*)([smh])$")
_DURATION_UNITS = {"s": 1, "m": 60, "h": 3600}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class EnvelopeError(StateError):
    """The `[envelope]` table is malformed."""


@dataclasses.dataclass(frozen=True)
class Stage:
    role: str
    handoff: str


@dataclasses.dataclass(frozen=True)
class Approval:
    at: datetime.datetime
    sha256: str


@dataclasses.dataclass(frozen=True)
class Envelope:
    targets: tuple[str, ...]
    branches: dict[str, str]
    allowlist: tuple[str, ...]
    review: str
    max_corrections: int
    max_duration: str
    judge_max_calls: int
    on_pass_with_risks: str
    stages: tuple[Stage, ...]
    approval: Approval | None = None


# --------------------------------------------------------------------------
# Shape
# --------------------------------------------------------------------------


def _str_list(raw: dict, key: str) -> tuple[str, ...]:
    value = raw[key]
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise EnvelopeError(f"[envelope] {key} must be an array of strings")
    return tuple(value)


def _int(raw: dict, key: str) -> int:
    value = raw[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise EnvelopeError(f"[envelope] {key} must be an integer")
    return value


def _str(raw: dict, key: str) -> str:
    value = raw[key]
    if not isinstance(value, str):
        raise EnvelopeError(f"[envelope] {key} must be a string")
    return value


def _parse_stages(value: object) -> tuple[Stage, ...]:
    if not isinstance(value, list):
        raise EnvelopeError("[envelope] stages must be an array of tables")
    stages = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, dict)
            or set(item) != {"role", "handoff"}
            or not all(isinstance(item[k], str) for k in ("role", "handoff"))
        ):
            raise EnvelopeError(f"[envelope] stages[{index}] must have exactly string keys role and handoff")
        stages.append(Stage(role=item["role"], handoff=item["handoff"]))
    return tuple(stages)


def _parse_approval(value: object) -> Approval:
    if not isinstance(value, dict) or set(value) != {"at", "sha256"}:
        raise EnvelopeError("[envelope.approval] must have exactly the keys at and sha256")
    at, sha256 = value["at"], value["sha256"]
    if not isinstance(at, datetime.datetime) or at.utcoffset() is None:
        raise EnvelopeError("[envelope.approval] at must be a datetime with a UTC offset")
    if not isinstance(sha256, str) or not _SHA256_RE.fullmatch(sha256):
        raise EnvelopeError("[envelope.approval] sha256 must be 64 lowercase hex characters")
    return Approval(at=at, sha256=sha256)


def parse_envelope(raw: dict) -> Envelope:
    """Shape and type check of an `[envelope]` table; raises `EnvelopeError`."""

    if not isinstance(raw, dict):
        raise EnvelopeError("[envelope] must be a table")
    unknown = sorted(set(raw) - set(_REQUIRED_KEYS) - {"approval"})
    if unknown:
        raise EnvelopeError(f"[envelope] unknown key(s): {', '.join(unknown)}")
    missing = [k for k in _REQUIRED_KEYS if k not in raw]
    if missing:
        raise EnvelopeError(f"[envelope] missing key(s): {', '.join(missing)}")
    branches = raw["branches"]
    if not isinstance(branches, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in branches.items()
    ):
        raise EnvelopeError("[envelope] branches must be a table of strings")
    return Envelope(
        targets=_str_list(raw, "targets"),
        branches=dict(branches),
        allowlist=_str_list(raw, "allowlist"),
        review=_str(raw, "review"),
        max_corrections=_int(raw, "max_corrections"),
        max_duration=_str(raw, "max_duration"),
        judge_max_calls=_int(raw, "judge_max_calls"),
        on_pass_with_risks=_str(raw, "on_pass_with_risks"),
        stages=_parse_stages(raw["stages"]),
        approval=_parse_approval(raw["approval"]) if "approval" in raw else None,
    )


def envelope_to_raw(env: Envelope) -> dict:
    """Inverse of `parse_envelope`: the plain table written to `state.toml`."""

    raw: dict = {
        "targets": list(env.targets),
        "branches": dict(env.branches),
        "allowlist": list(env.allowlist),
        "review": env.review,
        "max_corrections": env.max_corrections,
        "max_duration": env.max_duration,
        "judge_max_calls": env.judge_max_calls,
        "on_pass_with_risks": env.on_pass_with_risks,
        "stages": [{"role": s.role, "handoff": s.handoff} for s in env.stages],
    }
    if env.approval is not None:
        raw["approval"] = {"at": env.approval.at, "sha256": env.approval.sha256}
    return raw


def envelope_from_doc(doc: StateDoc) -> Envelope | None:
    return None if doc.envelope is None else parse_envelope(doc.envelope)


def parse_duration(text: str) -> int:
    """`"8h"` -> 28800 seconds; only `<positive int><s|m|h>`."""

    match = _DURATION_RE.fullmatch(text)
    if not match:
        raise EnvelopeError(f"max_duration must look like 30s, 90m or 8h, got {text!r}")
    return int(match.group(1)) * _DURATION_UNITS[match.group(2)]


# --------------------------------------------------------------------------
# Semantics
# --------------------------------------------------------------------------


def _role_errors(env: Envelope, kit_root: Path) -> list[str]:
    errors = []
    for index, stage in enumerate(env.stages):
        if stage.role == "marina":
            errors.append(f"stages[{index}] role 'marina' is the coordinator, not a writer specialist")
        elif not (kit_root / ".claude" / "agents" / f"{stage.role}.md").is_file():
            errors.append(f"stages[{index}] role {stage.role!r} has no profile in .claude/agents/")
        elif mode_for_role(stage.role) != "writer":
            errors.append(f"stages[{index}] role {stage.role!r} is a reader role; stages need a writer")
    roles = {s.role for s in env.stages}
    if not errors and len(roles) > 1:
        errors.append(
            f"stages use different roles {sorted(roles)}; G3 prossegue requires the predecessor's role, "
            "so every stage must use the same role"
        )
    return errors


def _handoff_errors(env: Envelope, task_dir: Path) -> list[str]:
    errors = []
    root = task_dir.resolve()
    for index, stage in enumerate(env.stages):
        if os.path.isabs(stage.handoff):
            errors.append(f"stages[{index}] handoff {stage.handoff!r} must be relative to the task directory")
            continue
        resolved = (task_dir / stage.handoff).resolve()
        if not resolved.is_relative_to(root):
            errors.append(f"stages[{index}] handoff {stage.handoff!r} resolves outside the task directory")
        elif not resolved.is_file():
            errors.append(f"stages[{index}] handoff {stage.handoff!r} does not exist in the task directory")
    return errors


def _target_errors(env: Envelope, doc: StateDoc) -> list[str]:
    errors = []
    if not env.targets:
        errors.append("targets must name at least one target")
    if len(set(env.targets)) != len(env.targets):
        errors.append("targets contains duplicates")
    for target in env.targets:
        if not os.path.isabs(target) or os.path.normpath(target) != target:
            errors.append(f"target {target!r} must be an absolute, normalized path")
        elif target not in doc.task.targets:
            errors.append(f"target {target!r} is not one of the task's targets")
    if set(env.branches) != set(env.targets):
        errors.append("branches must have exactly one branch per target")
    errors += [f"branch for {t!r} is empty" for t, b in env.branches.items() if not b.strip()]
    return errors


def validate_envelope(env: Envelope, *, doc: StateDoc, kit_root: Path, task_dir: Path) -> list[str]:
    """Every reason `env` cannot be approved or run; empty when valid."""

    errors: list[str] = []
    if not env.stages:
        errors.append("stages must list at least one stage")
    errors += _role_errors(env, kit_root)
    errors += _handoff_errors(env, task_dir)
    errors += _target_errors(env, doc)
    try:
        _check_forbidden_allowlist(list(env.allowlist))
    except LaunchRefused as exc:
        errors.append(f"allowlist: {exc}")
    if env.max_corrections not in (0, 1):
        errors.append(f"max_corrections must be 0 or 1, got {env.max_corrections}")
    if env.judge_max_calls < 0:
        errors.append(f"judge_max_calls must be >= 0, got {env.judge_max_calls}")
    try:
        parse_duration(env.max_duration)
    except EnvelopeError as exc:
        errors.append(str(exc))
    if env.review not in REVIEW_MODES:
        errors.append(f"review must be one of {', '.join(REVIEW_MODES)}, got {env.review!r}")
    if env.on_pass_with_risks not in PASS_WITH_RISKS_POLICIES:
        errors.append(
            f"on_pass_with_risks must be one of {', '.join(PASS_WITH_RISKS_POLICIES)}, got {env.on_pass_with_risks!r}"
        )
    return errors


def compute_hash(env: Envelope, *, task_dir: Path) -> str:
    """sha256 of the envelope without approval plus every stage handoff's bytes."""

    body = envelope_to_raw(dataclasses.replace(env, approval=None))
    h = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    for stage in env.stages:
        h.update(b"\0" + stage.handoff.encode("utf-8") + b"\0" + (task_dir / stage.handoff).read_bytes())
    return h.hexdigest()


# --------------------------------------------------------------------------
# Approval (`marina approve`)
# --------------------------------------------------------------------------


def format_summary(env: Envelope, doc: StateDoc, sha256: str) -> str:
    """What the human reads before typing the slug: every approved field."""

    lines = [f"task: {doc.task.slug} — {doc.task.title}", "stages:"]
    lines += [f"  {n}. {s.role} — {s.handoff}" for n, s in enumerate(env.stages, 1)]
    lines.append("targets:")
    lines += [f"  {t} (branch {env.branches.get(t, '?')})" for t in env.targets]
    lines.append("allowlist:")
    lines += [f"  {entry}" for entry in env.allowlist]
    lines += [
        f"review: {env.review}",
        f"max_corrections: {env.max_corrections}",
        f"max_duration: {env.max_duration}",
        f"judge_max_calls: {env.judge_max_calls}",
        f"on_pass_with_risks: {env.on_pass_with_risks}",
        f"sha256: {sha256}",
    ]
    return "\n".join(lines)


def approve(
    state_path: Path,
    *,
    kit_root: Path,
    stdin: TextIO,
    stdout: TextIO,
    stderr: TextIO,
    isatty: Callable[[], bool],
    now: Callable[[], datetime.datetime],
) -> int:
    """Record `[envelope.approval]` after the human types the task slug.

    Refuses (exit 1, nothing written) without a TTY, without a valid
    envelope, when the typed line is not the slug, or when the envelope or
    a handoff changed while the prompt waited. It re-reads `state_path`
    before writing, so changes made meanwhile by other tools are kept, and
    replaces the file atomically. The only writer of the approval; it
    writes nothing but `state_path`.
    """

    if not isatty():
        print("marina approve: requires an interactive terminal", file=stderr)
        return 1
    doc = read_state(state_path)
    task_dir = Path(state_path).parent
    if doc.envelope is None:
        print(f"marina approve: no [envelope] in {state_path}", file=stderr)
        return 1
    try:
        env = parse_envelope(doc.envelope)
    except EnvelopeError as exc:
        print(f"marina approve: {exc}", file=stderr)
        return 1
    errors = validate_envelope(env, doc=doc, kit_root=kit_root, task_dir=task_dir)
    if errors:
        for error in errors:
            print(f"marina approve: {error}", file=stderr)
        return 1

    sha256 = compute_hash(env, task_dir=task_dir)
    print(format_summary(env, doc, sha256), file=stdout)
    if env.approval is not None:
        print(f"previous approval: {env.approval.sha256}", file=stdout)
    print(f"Type the task slug ({doc.task.slug}) to approve: ", end="", file=stdout, flush=True)
    if stdin.readline().strip() != doc.task.slug:
        print("marina approve: not approved", file=stderr)
        return 1

    # The human may sit at the prompt for minutes: approve exactly what was
    # shown, on top of whatever else was written to state.toml meanwhile.
    fresh = read_state(state_path)
    try:
        unchanged = fresh.envelope == doc.envelope and compute_hash(env, task_dir=task_dir) == sha256
    except OSError:
        unchanged = False
    if not unchanged:
        print("marina approve: the envelope or a handoff changed while waiting; nothing written", file=stderr)
        return 1
    at = now()
    fresh.envelope = envelope_to_raw(dataclasses.replace(env, approval=Approval(at=at, sha256=sha256)))
    fresh.task.updated_at = at
    _write_state_atomically(Path(state_path), fresh)
    print(f"approved {doc.task.slug} sha256={sha256}", file=stdout)
    return 0


def _write_state_atomically(state_path: Path, doc: StateDoc) -> None:
    tmp = state_path.with_name(f".{state_path.name}.approve-tmp")
    try:
        write_state(tmp, doc)
        os.replace(tmp, state_path)
    finally:
        tmp.unlink(missing_ok=True)
