#!/usr/bin/env python3
"""scripts/state_lint.py — the 8 invariants of
docs/plano-estado-estruturado-e-grafos.md §5, checked against any
`state.toml` (defaults to the versioned fixture).

Minimum tested Claude CLI version: none (neutral script; no native CLI
invoked).

Read-only: never writes anything. `kit-lint` runs this against the
fixture as one of its checks (docs/analise-scripts-apoio-coordenacao.md
§4.7); the coordinator/`gate` (Etapa 2, out of scope here) would also run
it against the real `state.toml` before any G3 transition.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common
from scripts.state import parse_state_text
from scripts.state.model import ACTIVE_WRITER_STATES, EDGES, StateDoc, TERMINAL_STATES, mode_for_role

DEFAULT_FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "visible-sessions" / "state.toml"


# --------------------------------------------------------------------------
# The 8 invariants (docs/plano-estado-estruturado-e-grafos.md §5).
# --------------------------------------------------------------------------


def check_nn_sequence(doc: StateDoc) -> list[str]:
    """1. `nn` strictly increasing and contiguous; `next_nn = max(nn) + 1`."""

    errors: list[str] = []
    nns = [a.nn for a in doc.assignments]
    expected = list(range(1, len(nns) + 1))
    # Compares list order, not just the `nn` value set — stricter than a literal reading, and also catches reordered assignments.
    if nns != expected:
        errors.append(f"assignment nn values are not strictly increasing/contiguous from 1: {nns}")
    expected_next_nn = (max(nns) if nns else 0) + 1
    if doc.task.next_nn != expected_next_nn:
        errors.append(f"task.next_nn={doc.task.next_nn} but expected {expected_next_nn} (max(nn) + 1)")
    return errors


def check_predecessor_exists(doc: StateDoc) -> list[str]:
    """2. `predecessor < nn` and it exists (or is 0)."""

    errors: list[str] = []
    nn_set = {a.nn for a in doc.assignments}
    for a in doc.assignments:
        if a.predecessor == 0:
            continue
        if a.predecessor >= a.nn:
            errors.append(f"nn={a.nn}: predecessor {a.predecessor} is not < nn")
        elif a.predecessor not in nn_set:
            errors.append(f"nn={a.nn}: predecessor {a.predecessor} does not exist")
    return errors


_CLOSED_OR_ACCEPTED_PENDING = {"accepted", "closed_pending"}
_TERMINAL_WITHOUT_RESULT = {"preparation_failed", "abandoned", "receipt_missing", "receipt_invalid"}
_CLOSED_NEEDS_INPUT_OR_PENDING = {"closed_needs_input", "closed_pending"}


def check_edge_compatibility(doc: StateDoc) -> list[str]:
    """3. `edge` compatible with the predecessor's state (G3 table)."""

    errors: list[str] = []
    by_nn = {a.nn: a for a in doc.assignments}
    for a in doc.assignments:
        if a.edge not in EDGES:
            errors.append(f"nn={a.nn}: unknown edge {a.edge!r}")
            continue
        pred = by_nn.get(a.predecessor) if a.predecessor else None

        if a.edge == "inicia":
            if a.predecessor != 0:
                errors.append(f"nn={a.nn}: edge=inicia requires predecessor=0, got {a.predecessor}")
        elif a.edge == "revisa":
            if pred is None or pred.mode != "writer" or pred.state not in _CLOSED_OR_ACCEPTED_PENDING:
                got = pred.state if pred else None
                errors.append(
                    f"nn={a.nn}: edge=revisa requires a writer predecessor in accepted/closed_pending, got {got!r}"
                )
        elif a.edge in ("revisa_direta", "analisa"):
            if pred is not None and pred.state not in TERMINAL_STATES:
                errors.append(f"nn={a.nn}: edge={a.edge} requires predecessor closed or none, got {pred.state!r}")
        elif a.edge == "corrige":
            ok = (
                pred is not None
                and pred.role == "reviewer"
                and pred.state == "accepted"
                and pred.receipt_summary is not None
                and pred.receipt_summary.verdict == "FAIL"
            )
            if not ok:
                errors.append(
                    f"nn={a.nn}: edge=corrige requires a reviewer predecessor accepted with verdict=FAIL"
                )
        elif a.edge == "continua":
            if pred is None or pred.state not in _CLOSED_NEEDS_INPUT_OR_PENDING:
                got = pred.state if pred else None
                errors.append(
                    f"nn={a.nn}: edge=continua requires predecessor in closed_needs_input/closed_pending, got {got!r}"
                )
        elif a.edge == "substitui":
            if pred is None or pred.state not in _TERMINAL_WITHOUT_RESULT:
                got = pred.state if pred else None
                errors.append(
                    f"nn={a.nn}: edge=substitui requires predecessor in a terminal-without-result state, got {got!r}"
                )
    return errors


def check_single_active_writer(doc: StateDoc) -> list[str]:
    """4. At most one active `writer` per intersection of `targets`."""

    errors: list[str] = []
    actives = [a for a in doc.assignments if a.mode == "writer" and a.state in ACTIVE_WRITER_STATES]
    for i in range(len(actives)):
        for j in range(i + 1, len(actives)):
            a, b = actives[i], actives[j]
            if set(a.targets) & set(b.targets):
                errors.append(
                    f"nn={a.nn} and nn={b.nn} are both active writers with overlapping targets "
                    f"({sorted(set(a.targets) & set(b.targets))})"
                )
    return errors


def check_state_matches_events(doc: StateDoc) -> list[str]:
    """5. `state` equals the last event's `to`; events monotonic in `at`."""

    errors: list[str] = []
    for a in doc.assignments:
        if not a.events:
            errors.append(f"nn={a.nn}: no events recorded")
            continue
        last = a.events[-1]
        if last.to != a.state:
            errors.append(f"nn={a.nn}: state={a.state!r} does not match last event.to={last.to!r}")
        for prev_event, next_event in zip(a.events, a.events[1:]):
            if next_event.at < prev_event.at:
                errors.append(
                    f"nn={a.nn}: events not monotonic in 'at' ({prev_event.at} -> {next_event.at})"
                )
    return errors


def check_native_metadata(doc: StateDoc) -> list[str]:
    """6. `platform=unavailable` requires `reason`; `platform=codex` with `id` requires `host`."""

    errors: list[str] = []
    for a in doc.assignments:
        native = a.native
        if native.platform == "unavailable" and not native.reason.strip():
            errors.append(f"nn={a.nn}: native.platform=unavailable requires a non-empty reason")
        if native.platform == "codex" and native.id and not native.host.strip():
            errors.append(f"nn={a.nn}: native.platform=codex with id set requires a non-empty host")
    return errors


def check_mode_matches_role(doc: StateDoc) -> list[str]:
    """7. `mode` coherent with `role`."""

    errors: list[str] = []
    for a in doc.assignments:
        expected = mode_for_role(a.role)
        if a.mode != expected:
            errors.append(f"nn={a.nn}: role={a.role!r} implies mode={expected!r}, got {a.mode!r}")
    return errors


def check_no_secrets(doc: StateDoc, raw_text: str | None) -> list[str]:
    """8. No value matches the secret heuristic."""

    if raw_text is not None and common.looks_like_secret(raw_text):
        return ["state.toml content matches the secret heuristic (see scripts/common.py)"]
    return []


CheckFn = Callable[[StateDoc], list[str]]

# Order matches docs/plano-estado-estruturado-e-grafos.md §5.
CHECKS: list[tuple[str, CheckFn]] = [
    ("nn_sequence", check_nn_sequence),
    ("predecessor_exists", check_predecessor_exists),
    ("edge_compatibility", check_edge_compatibility),
    ("single_active_writer", check_single_active_writer),
    ("state_matches_events", check_state_matches_events),
    ("native_metadata", check_native_metadata),
    ("mode_matches_role", check_mode_matches_role),
]


def lint_doc(doc: StateDoc, raw_text: str | None = None) -> dict[str, list[str]]:
    """Run all 8 invariants; returns {invariant_name: [violation, ...]}."""

    results = {name: fn(doc) for name, fn in CHECKS}
    results["no_secrets"] = check_no_secrets(doc, raw_text)
    return results


def lint_text(text: str) -> dict[str, list[str]]:
    doc = parse_state_text(text)
    return lint_doc(doc, raw_text=text)


def lint_file(path: str | Path) -> dict[str, list[str]]:
    text = Path(path).read_text(encoding="utf-8")
    return lint_text(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="state-lint", description="Check the 8 schema-v0 invariants against a state.toml file."
    )
    parser.add_argument(
        "state_toml", nargs="?", default=str(DEFAULT_FIXTURE), help="defaults to the versioned fixture"
    )
    args = parser.parse_args(argv)

    results = lint_file(args.state_toml)
    ok = True
    for name, errors in results.items():
        if errors:
            ok = False
            print(f"FAIL {name}")
            for error in errors:
                print(f"  - {error}")
        else:
            print(f"PASS {name}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
