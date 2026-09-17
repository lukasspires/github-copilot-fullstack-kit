@AGENTS.md

# Claude Code runtime

Start the session at the kit root; use `claude --agent marina --add-dir /absolute/project-root` for coordination. Additional directories grant access and automatically expose their `.claude/skills/`, but do not load their agents. Keep the kit as the session root for its profiles and read each target's applicable instructions explicitly.

- Native profiles: `<kit_root>/.claude/agents/`; skills: `<kit_root>/.claude/skills/`.
- Domain guidance: `<kit_root>/.claude/instructions/<domain>.md`, loaded explicitly by responsibility. These files are not automatic path rules.
- Marina is the main-session role with normal runtime permissions; do not launch her as a background coordinator. Each independent session uses the user-configured model; do not assume it inherits Marina’s model. Tool availability does not bypass permissions.
- Specialist assignments use fresh visible background sessions with `--bg --agent <role> --name "<task> — <role> — <NN> — <type>"`, explicit target `--add-dir` arguments, per-invocation `--settings '{"worktree":{"bgIsolation":"none"}}'` for shared local files, `--permission-mode acceptEdits` and a check-derived `--allowedTools`. The short prompt names the role, absolute profile and handoff. Read `docs/agent-workflow.md` before launch.
- Native `Agent` is restricted to role-free read-only discovery (`Agent(Explore)` in Marina's tools), never specialist roles. Do not use `--resume`, `--continue` or `--fork-session` for assignments.
- If visible sessions are unavailable, follow the disclosed main-session fallback in AGENTS.md. An uncertain launch must be reconciled in `claude agents --json --all` before any replacement writer.
- Read-only specialists may write only their assigned receipt. This is an instruction-level write boundary, not a claim that `acceptEdits` enforces path isolation.
