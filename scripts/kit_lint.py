#!/usr/bin/env python3
"""scripts/kit_lint.py — the kit's own static checks
(docs/analise-scripts-apoio-marina.md §4.7), plus `state-lint`.

Checks: `.claude/agents/*.md` frontmatter (`name` matching the filename,
`description`) and non-empty body; no `.codex/` or `.agents/` directory
(the kit is Claude Code-only since 2026-10); `git diff --check`; the
`unittest` suite under `tests/`; and `state-lint` on the versioned
fixture (or a given `state.toml`).

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
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import common, state_lint

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)

# Directories of other agent runtimes; their presence means a removed
# compatibility layer came back.
FOREIGN_RUNTIME_DIRS = (".codex", ".agents")


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


def check_agent_profiles(kit_root: Path) -> CheckResult:
    claude_dir = kit_root / ".claude" / "agents"
    details: list[str] = []
    md_files = sorted(claude_dir.glob("*.md")) if claude_dir.is_dir() else []
    if not md_files:
        return CheckResult("agent_profiles", False, [f"no *.md profiles found under {claude_dir}"])

    for md_path in md_files:
        role = md_path.stem
        try:
            frontmatter, body = _parse_frontmatter(md_path)
        except ValueError as exc:
            details.append(str(exc))
            continue
        name = frontmatter.get("name", "")
        if name != role:
            details.append(f"{role}: frontmatter name {name!r} differs from filename")
        if not frontmatter.get("description", "").strip('"').strip():
            details.append(f"{role}: missing description")
        if not body.strip():
            details.append(f"{role}: empty body")

    return CheckResult("agent_profiles", not details, details)


def check_no_foreign_runtime(kit_root: Path) -> CheckResult:
    details = [
        f"foreign runtime directory present: {kit_root / name}"
        for name in FOREIGN_RUNTIME_DIRS
        if (kit_root / name).exists()
    ]
    return CheckResult("no_foreign_runtime", not details, details)


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
        check_agent_profiles(kit_root),
        check_no_foreign_runtime(kit_root),
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
