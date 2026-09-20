# Kit tooling instructions

- Location: scripts live under `<kit_root>/scripts/` (platform-neutral; never inside `.claude/` or `.codex/`); bash only for trivial wrappers.
- Python 3 stdlib only (`tomllib` requires ≥3.11); declare any optional dependency explicitly in the handoff, never assume it is installed.
- Do not assume the user's shell is fish; every script needs an explicit shebang (`#!/usr/bin/env python3` or equivalent), never relying on shell-specific syntax.
- No network access. Git usage is read-only (`status`, `diff`, `rev-parse`) — never `checkout`, `reset`, or `commit`.
- Role write scope (you, authoring this tooling): `scripts/`, `tests/`, and your own assignment's `.agent-state/<project>/tasks/<task>/` receipt, as scoped by the handoff; never a target repository.
- Script runtime write scope (a finished script, once it runs): only `.agent-state/<project>/tasks/<task>/` and the checkpoint — never `scripts/`, `tests/`, or a target repository. A script that writes outside this is out of scope regardless of who authored it.
- Native session manager access is limited to exactly `claude agents --json --all` and `claude logs <id>` with a bounded line limit — no other manager subcommand is sanctioned.
- Never respond to a native approval prompt from inside a script; print the exact `claude attach <id>` instruction for the human instead.
- One launch/dispatch per script invocation; never chain a second writer automatically.
- Refuse to construct `bypassPermissions`, `--permission-prompts none`, `--resume`, `--continue`, `--fork-session`, or a broad allowlist pattern (bare `Bash`, `Bash(*)`).
- Output must be readable by both a human and the coordinator, with a meaningful process exit code; an optional `--json` mode is allowed but never required.
- Validate any external schema explicitly (the native session manager's JSON fields in particular) and fail loudly on drift; do not silently tolerate a missing or renamed field.
- Declare the minimum tested CLI version in each script's header; `kit-lint` checks it against the installed `claude --version`.
- Sanitize all output and any file written under `.agent-state/`: enumerated fields only, never a full environment dump, transcript, or complete log.
- Test with `unittest` against fixtures under `tests/fixtures/`, never against the real, git-ignored `.agent-state/` contents; `kit-lint` runs these tests, not just hosts them.
- Any change under `scripts/` goes through an independent `reviewer` pass before it is trusted, same as any other kit-contract change.
