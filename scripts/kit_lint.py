#!/usr/bin/env python3
"""scripts/kit_lint.py — the kit's own static checks
(docs/analise-scripts-apoio-coordenacao.md §4.7), plus `state-lint`.

Checks: `.claude/agents/*.md` <-> `.codex/agents/*.toml` parse and body
parity; `.claude/instructions/` <-> `.codex/instructions/` byte identity;
`.claude/skills/**` <-> `.agents/skills/**` byte identity (except
`agents/openai.yaml`, Codex-only); `git diff --check`; the `unittest`
suite under `tests/`; and `state-lint` on the versioned fixture (or a
given `state.toml`).

Minimum tested Claude CLI version: 2.1.267 (only used to cross-check each
script's declared "Minimum tested Claude CLI version" header against the
installed `claude --version`; skipped, not failed, when the CLI is not
installed).

Read-only: never writes anything, never `git add`/`commit`/`checkout`.
"""

from __future__ import annotations

import argparse
import dataclasses
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common, state_lint

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)

# Codex bodies use `.codex/instructions` and `.agents/skills`; Claude bodies
# use `.claude/instructions` and `.claude/skills`. Markdown backtick
# formatting (inline code) has no plain-text equivalent in a TOML
# triple-quoted string, so it is also normalized away.
_PATH_SUBSTITUTIONS = (
    (".codex/instructions", ".claude/instructions"),
    (".agents/skills", ".claude/skills"),
)


@dataclasses.dataclass
class CheckResult:
    name: str
    ok: bool
    details: list[str]


def _parse_frontmatter(md_path: Path) -> tuple[dict, str]:
    text = md_path.read_text(encoding="utf-8")
    match = FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{md_path}: missing YAML-ish frontmatter (---...---)")
    fm_text, body = match.groups()
    frontmatter: dict[str, str] = {}
    for line in fm_text.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
    return frontmatter, body


def _normalize_body(text: str) -> str:
    for codex_form, claude_form in _PATH_SUBSTITUTIONS:
        text = text.replace(codex_form, claude_form)
    text = text.replace("`", "")
    return " ".join(text.split())


def check_agent_profile_parity(kit_root: Path) -> CheckResult:
    claude_dir = kit_root / ".claude" / "agents"
    codex_dir = kit_root / ".codex" / "agents"
    details: list[str] = []
    md_files = sorted(claude_dir.glob("*.md")) if claude_dir.is_dir() else []
    if not md_files:
        return CheckResult("agent_profile_parity", False, [f"no *.md profiles found under {claude_dir}"])

    for md_path in md_files:
        role = md_path.stem
        toml_path = codex_dir / f"{role}.toml"
        if not toml_path.is_file():
            details.append(f"{role}: missing Codex counterpart {toml_path}")
            continue
        try:
            frontmatter, body = _parse_frontmatter(md_path)
        except ValueError as exc:
            details.append(str(exc))
            continue
        try:
            with toml_path.open("rb") as fh:
                codex_data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            details.append(f"{role}: {toml_path} does not parse as TOML: {exc}")
            continue

        for required in ("name", "description"):
            if required not in codex_data:
                details.append(f"{role}: {toml_path} missing top-level {required!r}")
        if "developer_instructions" not in codex_data:
            details.append(f"{role}: {toml_path} missing 'developer_instructions'")
            continue

        md_description = frontmatter.get("description", "").strip('"')
        codex_description = codex_data.get("description", "")
        if md_description != codex_description:
            details.append(f"{role}: description differs between {md_path} and {toml_path}")

        if _normalize_body(body) != _normalize_body(codex_data["developer_instructions"]):
            details.append(f"{role}: body differs between {md_path} and {toml_path} (after normalization)")

    # Also flag Codex profiles with no Claude counterpart.
    codex_files = sorted(codex_dir.glob("*.toml")) if codex_dir.is_dir() else []
    claude_roles = {p.stem for p in md_files}
    for toml_path in codex_files:
        if toml_path.stem not in claude_roles:
            details.append(f"{toml_path.stem}: Codex profile has no Claude counterpart {claude_dir / (toml_path.stem + '.md')}")

    return CheckResult("agent_profile_parity", not details, details)


def check_instructions_parity(kit_root: Path) -> CheckResult:
    claude_dir = kit_root / ".claude" / "instructions"
    codex_dir = kit_root / ".codex" / "instructions"
    details: list[str] = []
    claude_files = sorted(claude_dir.glob("*.md")) if claude_dir.is_dir() else []
    for claude_path in claude_files:
        codex_path = codex_dir / claude_path.name
        if not codex_path.is_file():
            details.append(f"missing Codex counterpart: {codex_path}")
            continue
        if claude_path.read_bytes() != codex_path.read_bytes():
            details.append(f"not byte-identical: {claude_path} vs {codex_path}")
    codex_files = sorted(codex_dir.glob("*.md")) if codex_dir.is_dir() else []
    claude_names = {p.name for p in claude_files}
    for codex_path in codex_files:
        if codex_path.name not in claude_names:
            details.append(f"Codex instructions file has no Claude counterpart: {codex_path}")
    return CheckResult("instructions_parity", not details, details)


def check_skills_identity(kit_root: Path) -> CheckResult:
    claude_dir = kit_root / ".claude" / "skills"
    codex_dir = kit_root / ".agents" / "skills"
    details: list[str] = []
    if not claude_dir.is_dir():
        return CheckResult("skills_identity", False, [f"missing {claude_dir}"])

    claude_files = sorted(p for p in claude_dir.rglob("*") if p.is_file())
    for claude_path in claude_files:
        rel = claude_path.relative_to(claude_dir)
        codex_path = codex_dir / rel
        if not codex_path.is_file():
            details.append(f"missing Codex counterpart: {codex_path}")
            continue
        if claude_path.read_bytes() != codex_path.read_bytes():
            details.append(f"not byte-identical: {claude_path} vs {codex_path}")

    if codex_dir.is_dir():
        codex_files = sorted(p for p in codex_dir.rglob("*") if p.is_file())
        claude_rels = {p.relative_to(claude_dir) for p in claude_files}
        for codex_path in codex_files:
            rel = codex_path.relative_to(codex_dir)
            # Codex-only exception: */agents/openai.yaml has no Claude side.
            if rel.name == "openai.yaml" and rel.parent.name == "agents":
                continue
            if rel not in claude_rels:
                details.append(f"Codex-only file with no Claude counterpart: {codex_path}")

    return CheckResult("skills_identity", not details, details)


def check_git_diff(kit_root: Path, *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> CheckResult:
    proc = runner(
        ["git", "diff", "--check"], cwd=str(kit_root), capture_output=True, text=True, timeout=30, check=False
    )
    ok = proc.returncode == 0
    details = [] if ok else [proc.stdout.strip() or proc.stderr.strip() or f"exit code {proc.returncode}"]
    return CheckResult("git_diff_check", ok, details)


def check_unittests(
    kit_root: Path, *, runner: Callable[..., subprocess.CompletedProcess] = subprocess.run
) -> CheckResult:
    proc = runner(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=str(kit_root),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    ok = proc.returncode == 0
    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-20:])
    return CheckResult("unittest_suite", ok, [] if ok else [tail])


def check_state_lint(kit_root: Path, state_toml: Path | None = None) -> CheckResult:
    path = state_toml or (kit_root / "tests" / "fixtures" / "visible-sessions" / "state.toml")
    results = state_lint.lint_file(path)
    details = [f"{name}: {err}" for name, errors in results.items() for err in errors]
    return CheckResult("state_lint", not details, details)


def check_cli_versions(
    kit_root: Path, *, installed_version: Callable[[], str | None] = common.installed_claude_version
) -> CheckResult:
    details: list[str] = []
    scripts_dir = kit_root / "scripts"
    main_guard_re = re.compile(r"""if\s+__name__\s*==\s*['"]__main__['"]\s*:""")
    executable_scripts = sorted(
        p for p in scripts_dir.rglob("*.py") if main_guard_re.search(p.read_text(encoding="utf-8"))
    )
    if not executable_scripts:
        return CheckResult("cli_version_headers", True, [])

    for script in executable_scripts:
        try:
            common.declared_cli_version(script)
        except ValueError as exc:
            details.append(str(exc))

    version_text = installed_version()
    if version_text is None:
        # claude CLI not installed: header-presence check above still applies,
        # but drift comparison against an installed version is skipped.
        return CheckResult("cli_version_headers", not details, details)

    installed = common.parse_version(version_text)
    if installed is None:
        return CheckResult("cli_version_headers", not details, details)

    for script in executable_scripts:
        try:
            declared = common.declared_cli_version(script)
        except ValueError:
            continue
        declared_version = common.parse_version(declared)
        if declared_version is not None and installed < declared_version:
            details.append(
                f"{script}: declares minimum {declared!r} but installed claude is {version_text!r}"
            )

    return CheckResult("cli_version_headers", not details, details)


def run_all(kit_root: Path, *, state_toml: Path | None = None) -> list[CheckResult]:
    return [
        check_agent_profile_parity(kit_root),
        check_instructions_parity(kit_root),
        check_skills_identity(kit_root),
        check_git_diff(kit_root),
        check_cli_versions(kit_root),
        check_state_lint(kit_root, state_toml),
        check_unittests(kit_root),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kit-lint", description="Static checks for the kit itself.")
    parser.add_argument("--kit-root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--state", default=None, help="state.toml to run state-lint against (defaults to the fixture)")
    args = parser.parse_args(argv)

    kit_root = Path(args.kit_root)
    state_toml = Path(args.state) if args.state else None
    results = run_all(kit_root, state_toml=state_toml)

    ok = True
    for result in results:
        if result.ok:
            print(f"PASS {result.name}")
        else:
            ok = False
            print(f"FAIL {result.name}")
            for detail in result.details:
                print(f"  - {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
