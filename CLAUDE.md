@AGENTS.md

# Claude Code runtime

Start the session at the kit root; use `claude --agent marina --add-dir /absolute/project-root` for coordination. Additional directories grant access and automatically expose their `.claude/skills/`, but do not load their agents. Keep the kit as the session root for its profiles and read each target's applicable instructions explicitly.

- Native profiles: `<kit_root>/.claude/agents/`; skills: `<kit_root>/.claude/skills/`.
- Domain guidance: `<kit_root>/.claude/instructions/<domain>.md`, loaded explicitly by responsibility. These files are not automatic path rules.
- Marina is the main-session role with normal runtime permissions; do not launch her as a background coordinator. Models inherit the session. Tool availability does not bypass permissions.
- If the runtime cannot delegate, the main session performs the bounded specialist work and reports that limitation.
