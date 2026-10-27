"""scripts/marina/handoff_gen.py — canonical handoffs for the nodes `marina run` opens.

The envelope's stage handoffs are templates (docs/plano-f4-runner-e-juiza-2026-10.md,
decision 1): they hold the human-authored Objective, Write scope and
Acceptance criteria, never a canonical `NN-<role>-handoff.md` name, because
the generated handoff would otherwise overwrite a file the approval hash
covers. Each `render_*` returns text that `handoff_sync.validate_handoff`
accepts and that `handoff_sync.synchronize` leaves unchanged, so preflight
and launch_claude treat it exactly like a handoff Marina wrote by hand.

Library only and pure: callers read templates and earlier handoffs and
write the result (`handoff_sync.write_atomic`).
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.handoff_sync import _section
from scripts.state import Assignment, StateDoc

TEMPLATE_REQUIRED = ("Objective", "Write scope", "Acceptance criteria")
TEMPLATE_OPTIONAL = ("Target instructions to read explicitly", "Checks and workdir", "Preservation")
CANONICAL_NAME_RE = re.compile(r"^\d{2}-[a-z0-9-]+-(handoff|receipt)\.md$")

_DEFAULT_PRESERVATION = (
    "Other sessions may be working; preserve their changes. Do not run `git add`, `commit`, `checkout`, "
    "`reset` or `stash`. Commands outside the granted allowlist are denied: record each one in the receipt "
    "as a skipped check with the reason, and use `needs_input` or `blocked` if acceptance depends on it."
)
_CLOSING = (
    "Never continue, fork, or resume this assignment into a new coordination session. "
    "If clarification is needed, record `needs_input`."
)


def _body(text: str, heading: str) -> str:
    section = _section(text, heading)
    return section[2].strip() if section is not None else ""


def template_errors(text: str) -> list[str]:
    """One message per required section that is missing or empty."""

    errors = []
    for heading in TEMPLATE_REQUIRED:
        if _section(text, heading) is None:
            errors.append(f"template section '## {heading}' is missing")
        elif not re.search(r"\w", _body(text, heading)):
            errors.append(f"template section '## {heading}' is empty")
    return errors


def _default_instructions(kit_root: Path, targets: list[str]) -> str:
    lines = [f"- `{kit_root / 'AGENTS.md'}`"]
    lines += [f"- `{Path(t) / name}` (if present)" for t in targets for name in ("AGENTS.md", "CLAUDE.md")]
    return "\n".join(lines)


def _render(
    doc: StateDoc,
    a: Assignment,
    *,
    kit_root: Path,
    objective: str,
    context: str,
    write_scope: str,
    acceptance: str,
    instructions: str = "",
    checks: str = "",
    preservation: str = "",
) -> str:
    roots = [f"- **kit_root:** `{kit_root}`"] + [f"- **target_root:** `{t}`" for t in a.targets]
    metadata = [
        f"- **Task:** {doc.task.slug} (project: {doc.task.project})",
        f"- **nn:** {a.nn:02d}",
        f"- **Predecessor:** {a.predecessor:02d}",
        f"- **Edge:** {a.edge}",
        f"- **Type:** {a.type}",
        f"- **Receipt path (write here only):** `{kit_root / a.receipt}`",
        "- **Granted allowlist:** " + " ".join(f"`{entry}`" for entry in a.allowlist),
    ]
    sections = [
        f"# {a.title}",
        f"## Objective\n\n{objective}",
        f"## Role and profile\n\n- **Role:** {a.role}\n"
        f"- **Absolute profile (read explicitly):** `{kit_root / '.claude' / 'agents' / f'{a.role}.md'}`",
        "## Roots\n\n" + "\n".join(roots),
        f"## Target instructions to read explicitly\n\n{instructions or _default_instructions(kit_root, a.targets)}",
        f"## Context\n\n{context}",
        f"## Write scope\n\n{write_scope}",
        f"## Acceptance criteria\n\n{acceptance}",
        f"## Checks and workdir\n\n{checks or 'Run the granted allowlist commands from each target root.'}",
        f"## Preservation\n\n{preservation or _DEFAULT_PRESERVATION}",
        "## Assignment metadata\n\n" + "\n".join(metadata) + f"\n\n{_CLOSING}",
    ]
    return "\n\n".join(sections) + "\n"


def _template_kwargs(template_text: str) -> dict[str, str]:
    return {
        "write_scope": _body(template_text, "Write scope"),
        "instructions": _body(template_text, "Target instructions to read explicitly"),
        "checks": _body(template_text, "Checks and workdir"),
        "preservation": _body(template_text, "Preservation"),
    }


def render_stage_handoff(doc: StateDoc, a: Assignment, *, kit_root: Path, template_text: str) -> str:
    """Handoff for an `inicia`/`prossegue` writer, from its stage template."""

    context = f"Envelope stage writer opened by `marina run` (edge {a.edge}, predecessor nn={a.predecessor:02d})."
    return _render(
        doc, a, kit_root=kit_root,
        objective=_body(template_text, "Objective"),
        context=context,
        acceptance=_body(template_text, "Acceptance criteria"),
        **_template_kwargs(template_text),
    )


def render_review_handoff(doc: StateDoc, a: Assignment, *, kit_root: Path, writer_handoff_text: str) -> str:
    """Handoff for a `revisa` reviewer of the writer `a.predecessor`."""

    writer = doc.get_assignment(a.predecessor)
    task_dir = kit_root / Path(doc.task.journal).parent
    context = "\n".join([
        f"- Writer handoff: `{kit_root / writer.handoff}`",
        f"- Writer receipt: `{kit_root / writer.receipt}`",
        f"- Target state before the writer: `{task_dir / f'git-before-{writer.nn:02d}.txt'}`; "
        "review the targets' current diff against it.",
    ])
    acceptance = (
        f"{_body(writer_handoff_text, 'Acceptance criteria')}\n\n"
        "Verdict `PASS`, `PASS_WITH_RISKS` or `FAIL`, with findings (severity, location, evidence, impact, correction)."
    )
    return _render(
        doc, a, kit_root=kit_root,
        objective=f"Revisão independente do nn={writer.nn:02d} ({writer.role}, {writer.edge}).",
        context=context,
        write_scope="None. Read-only review; write only the receipt below.",
        acceptance=acceptance,
        instructions=_body(writer_handoff_text, "Target instructions to read explicitly"),
        checks=_body(writer_handoff_text, "Checks and workdir"),
    )


def render_correction_handoff(doc: StateDoc, a: Assignment, *, kit_root: Path, template_text: str) -> str:
    """Handoff for a `corrige` writer answering the FAIL review `a.predecessor`."""

    reviewer = doc.get_assignment(a.predecessor)
    writer = doc.get_assignment(reviewer.predecessor)
    context = "\n".join([
        f"- FAIL review receipt: `{kit_root / reviewer.receipt}`",
        f"- Reviewed writer handoff: `{kit_root / writer.handoff}`",
        f"- Reviewed writer receipt: `{kit_root / writer.receipt}`",
    ])
    acceptance = (
        f"{_body(template_text, 'Acceptance criteria')}\n\n"
        f"Every finding of the receipt nn={reviewer.nn:02d} is fixed or justified in this receipt."
    )
    return _render(
        doc, a, kit_root=kit_root,
        objective=f"Corrigir os achados do nn={reviewer.nn:02d} (FAIL).",
        context=context,
        acceptance=acceptance,
        **_template_kwargs(template_text),
    )
