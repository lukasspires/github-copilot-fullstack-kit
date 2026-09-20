#!/usr/bin/env python3
"""scripts/receipt_lint.py — G2 transition
`receipt_received -> receipt_validated | receipt_invalid`.

Validates a receipt's required fields/enums per docs/agent-workflow.md
"Handoffs and continuity" — parsing the canonical `##`-heading receipt
structure documented there (see the module-level comment below for the
two accepted profile/instructions shapes and the narrow inline
status/verdict fallback) — and extracts `receipt_summary`/`risks_digest`
by parsing normalized risk titles out of `## Risks` / `### RISK n`
headings (docs/plano-estado-estruturado-e-grafos.md §2.3/§2.4). Never
evaluates merit, only form (docs/analise-scripts-apoio-coordenacao.md
§4.5).

Minimum tested Claude CLI version: none (neutral script; no native CLI
invoked).

Read-only: never writes anything (the `receipt_summary` it computes is
returned/printed for a caller such as `state set` to record — this
script itself only reads the receipt/handoff files given to it).
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common
from scripts.state.model import RECEIPT_STATUS_ENUM, ReceiptSummary, VERDICT_ENUM

# --------------------------------------------------------------------------
# Canonical receipt structure (docs/agent-workflow.md, "Handoffs and
# continuity", "Canonical receipt structure"): `##`-level, case-insensitive
# headings, one per field; the field's value is the heading's own body
# text, not an inline `**Field:**` bold marker. Two real, already-accepted
# shapes for the profile/instructions section both validate: one combined
# `## Profile and Instructions Read` heading, or two separate `##
# profile_read` / `## instructions_read` headings (both real, per the doc's
# own note on observed variance). A heading may carry a suffix after its
# core word (`## Risks` / `## risks / findings`) and is matched
# case-insensitively.
#
# One additional real, narrow accommodation, not a revival of the older
# full inline-bold format: two already-accepted receipts
# (kit-tooling-role/{01,02}-reviewer-receipt.md) use the separate
# profile_read/instructions_read heading shape but give `status`/`verdict`
# as a `**status:**`/`**verdict:**` marker in the preamble before any
# heading, with no `## Status`/`## Verdict` heading at all. `_INLINE_*_RE`
# below is only ever consulted as a fallback, and only when the separate-
# heading shape was detected for profile/instructions — see
# `_extract_profile_and_instructions`'s `separate_shape` return value and
# risks in the accompanying receipt for why this is scoped this way rather
# than a blanket inline-marker fallback (which would also revive the two
# legacy `.agent-state/visible-sessions/{02,03}-reviewer-receipt.md`
# receipts, deliberately not supported here).
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^##(?!#)[ \t]*(.+?)\s*$", re.MULTILINE)
_BACKTICK_VALUE_RE = re.compile(r"`([^`]+)`")
_LEADING_BULLET_RE = re.compile(r"^-\s*")
_LEADING_BOLD_LABEL_RE = re.compile(r"^\*\*[^*]+\*\*:?\s*")
_FIELD_TOKEN_RE = re.compile(r"[A-Za-z_]+")
_INLINE_STATUS_RE = re.compile(r"\*\*status:\*\*\s*([A-Za-z_]+)", re.IGNORECASE)
_INLINE_VERDICT_RE = re.compile(r"\*\*verdict:\*\*\s*([A-Za-z_]+)", re.IGNORECASE)
_RECEIPT_FILENAME_RE = re.compile(r"^\d+-([a-z0-9-]+)-receipt\.md$")


@dataclasses.dataclass
class ReceiptData:
    status: str | None
    changed: str | None
    profile_read: str | None
    instructions_read: list[str]
    risks_titles: list[str]
    verdict: str | None


def _split_sections(text: str) -> list[tuple[str, str]]:
    """Split `text` into `(heading, body)` pairs, one per `##`-level heading.

    A section's body runs from just after its heading line to the start
    of the next `##`-level heading (never a `###` one, e.g. `### RISK n`
    stays inside its parent `## Risks` body) or end of text.
    """

    matches = list(_HEADING_RE.finditer(text))
    sections: list[tuple[str, str]] = []
    for i, match in enumerate(matches):
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((match.group(1).strip(), text[start:end]))
    return sections


def _section_body(sections: list[tuple[str, str]], *, prefix: str) -> str | None:
    """First section body whose normalized heading equals or starts with `prefix`."""

    for name, body in sections:
        norm = re.sub(r"\s+", " ", name.strip().lower())
        if norm == prefix or norm.startswith(prefix + " ") or norm.startswith(prefix + "/") or norm.startswith(prefix + ":"):
            return body
    return None


def _first_value_token(line: str) -> str | None:
    """First path-like value on `line`, ignoring trailing prose.

    A backtick-quoted value (``... `/abs/path` (read-only reference)``)
    is taken verbatim from inside the backticks, trailing annotation
    discarded. Otherwise, strip a leading bullet dash and an optional
    `**label:**` bold marker, then take the first whitespace-delimited
    token — this deliberately does not require the token to already look
    like an absolute path (a relative value is still returned, so
    `lint_receipt` can flag it as "not an absolute path" instead of
    silently reporting the field as missing).
    """

    backtick = _BACKTICK_VALUE_RE.search(line)
    if backtick:
        value = backtick.group(1).strip()
        return value or None

    stripped = _LEADING_BULLET_RE.sub("", line.strip())
    stripped = _LEADING_BOLD_LABEL_RE.sub("", stripped)
    parts = stripped.split()
    return parts[0] if parts else None


def _first_absolute_value_token(line: str) -> str | None:
    """`_first_value_token`, but only when the value is itself absolute.

    Used for `instructions_read` **list membership**: a real bullet may
    be prose describing several already-covered relative paths rather
    than declaring one of its own (e.g. "Every file under `scripts/` and
    `tests/` that existed before this assignment (`common.py`, ...)" —
    a real line from this kit's own `gate-launch-scripts` receipts). Such
    a bullet is silently not counted as an `instructions_read` entry
    (it never was one), rather than surfaced as a "not absolute" defect
    on a field the receipt never actually populated with it — the
    profile_read field itself still uses the permissive
    `_first_value_token` so a genuinely mis-declared *relative*
    profile_read is still caught by `lint_receipt`'s own absolute-path
    check, not silently dropped.
    """

    value = _first_value_token(line)
    return value if value and value.startswith("/") else None


def _first_field_token(body: str) -> str | None:
    """First `[A-Za-z_]+` token on the first non-empty line of `body`."""

    for line in body.splitlines():
        if not line.strip():
            continue
        match = _FIELD_TOKEN_RE.search(line)
        return match.group(0) if match else None
    return None


def _extract_profile_and_instructions(
    sections: list[tuple[str, str]],
) -> tuple[str | None, list[str], bool]:
    """Return `(profile_read, instructions_read, separate_shape)`.

    Tries the combined `## Profile and Instructions Read` heading first,
    then the two-separate-headings shape (`## profile_read` / `##
    instructions_read`). `separate_shape` is `True` only for the latter —
    used by `parse_receipt` to scope the narrow inline status/verdict
    fallback (see module docstring above).
    """

    combined = _section_body(sections, prefix="profile and instructions read")
    if combined is not None:
        lines = combined.splitlines()
        profile_idx = next((i for i, line in enumerate(lines) if "profile_read" in line.lower()), None)
        profile_read = _first_value_token(lines[profile_idx]) if profile_idx is not None else None
        if profile_read is None:
            for line in lines:
                path = _first_absolute_value_token(line)
                if path:
                    profile_read = path
                    break

        instr_idx = next((i for i, line in enumerate(lines) if "instructions_read" in line.lower()), None)
        instructions: list[str] = []
        if instr_idx is not None:
            for line in lines[instr_idx + 1 :]:
                stripped = line.strip()
                if not stripped.startswith("-"):
                    continue
                path = _first_absolute_value_token(line)
                if path:
                    instructions.append(path)
        return profile_read, instructions, False

    profile_body = _section_body(sections, prefix="profile_read")
    instructions_body = _section_body(sections, prefix="instructions_read")
    if profile_body is None and instructions_body is None:
        return None, [], False

    profile_read = None
    if profile_body is not None:
        for line in profile_body.splitlines():
            if not line.strip():
                continue
            path = _first_value_token(line)
            if path:
                profile_read = path
                break

    instructions = []
    if instructions_body is not None:
        for line in instructions_body.splitlines():
            stripped = line.strip()
            if not stripped.startswith("-"):
                continue
            path = _first_absolute_value_token(line)
            if path:
                instructions.append(path)

    return profile_read, instructions, True


def parse_receipt(text: str) -> ReceiptData:
    sections = _split_sections(text)

    profile_read, instructions, separate_shape = _extract_profile_and_instructions(sections)

    status_body = _section_body(sections, prefix="status")
    status = _first_field_token(status_body) if status_body is not None else None
    if status is None and separate_shape:
        inline_match = _INLINE_STATUS_RE.search(text)
        status = inline_match.group(1) if inline_match else None

    verdict_body = _section_body(sections, prefix="verdict")
    verdict = _first_field_token(verdict_body) if verdict_body is not None else None
    if verdict is None and separate_shape:
        inline_match = _INLINE_VERDICT_RE.search(text)
        verdict = inline_match.group(1) if inline_match else None

    changed_body = _section_body(sections, prefix="changed")
    changed = changed_body.strip() if changed_body is not None else None

    return ReceiptData(
        status=status,
        changed=changed,
        profile_read=profile_read,
        instructions_read=instructions,
        risks_titles=common.find_risk_titles(text),
        verdict=verdict,
    )


def role_from_filename(path: str | Path) -> str | None:
    match = _RECEIPT_FILENAME_RE.match(Path(path).name)
    return match.group(1) if match else None


def lint_receipt(
    text: str,
    *,
    role: str | None = None,
    handoff_profile: str | None = None,
) -> tuple[list[str], ReceiptSummary]:
    """Validate a receipt's form; returns (errors, receipt_summary).

    `errors` is empty iff the receipt would transition to
    `receipt_validated` rather than `receipt_invalid`.
    """

    errors: list[str] = []
    data = parse_receipt(text)

    if data.status is None or data.status not in RECEIPT_STATUS_ENUM:
        errors.append(f"status missing or not in {sorted(RECEIPT_STATUS_ENUM)}: {data.status!r}")

    if role == "reviewer":
        if data.verdict is None or data.verdict not in (VERDICT_ENUM - {""}):
            errors.append(f"reviewer receipt requires a verdict in {sorted(VERDICT_ENUM - {''})}: {data.verdict!r}")

    profile_ok = False
    if not data.profile_read:
        errors.append("profile_read missing")
    else:
        profile_path = Path(data.profile_read)
        if not profile_path.is_absolute():
            errors.append(f"profile_read is not an absolute path: {data.profile_read}")
        elif handoff_profile is not None and str(profile_path) != handoff_profile:
            errors.append(f"profile_read {profile_path} does not match handoff profile {handoff_profile}")
        else:
            profile_ok = True

    if not data.instructions_read:
        errors.append("instructions_read missing or empty")
    else:
        for raw_path in data.instructions_read:
            instr_path = Path(raw_path)
            if not instr_path.is_absolute():
                errors.append(f"instructions_read path is not absolute: {raw_path}")
            elif not instr_path.exists():
                errors.append(f"instructions_read path does not exist: {raw_path}")

    if common.looks_like_secret(text):
        errors.append("receipt content matches the secret heuristic (see scripts/common.py)")

    risks_digest = [common.normalize_risk_title(t) for t in data.risks_titles]
    summary = ReceiptSummary(
        status=data.status or "",
        verdict=data.verdict or "",
        profile_ok=profile_ok,
        risks_digest=risks_digest,
    )
    return errors, summary


def lint_file(path: str | Path, *, role: str | None = None, handoff: str | Path | None = None) -> tuple[list[str], ReceiptSummary]:
    text = Path(path).read_text(encoding="utf-8")
    if role is None:
        role = role_from_filename(path)
    handoff_profile = None
    if handoff is not None:
        handoff_text = Path(handoff).read_text(encoding="utf-8")
        handoff_profile = common.extract_profile_path(handoff_text)
    return lint_receipt(text, role=role, handoff_profile=handoff_profile)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="receipt-lint", description="Validate a receipt's form and extract its risks_digest."
    )
    parser.add_argument("receipt", help="path to a <NN>-<role>-receipt.md file")
    parser.add_argument("--role", default=None, help="defaults to the role parsed from the filename")
    parser.add_argument("--handoff", default=None, help="matching handoff, to cross-check profile_read")
    args = parser.parse_args(argv)

    errors, summary = lint_file(args.receipt, role=args.role, handoff=args.handoff)
    print(f"status={summary.status!r} verdict={summary.verdict!r} profile_ok={summary.profile_ok}")
    print("risks_digest:")
    for title in summary.risks_digest:
        print(f"  - {title}")
    if errors:
        print("FAIL receipt_invalid")
        for error in errors:
            print(f"  - {error}")
        return 1
    print("PASS receipt_validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
