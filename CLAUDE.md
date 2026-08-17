@AGENTS.md

# Claude Code

- Project subagents live in `.claude/agents/`; project skills live in `.claude/skills/`.
- Use `marina` as a main-session agent for coordinated work. Do not delegate coordination to Marina as a background subagent because background subagents cannot recursively orchestrate the full workflow reliably.
- Claude rules under `.claude/rules/` load by matching paths. Do not substitute Copilot or Codex tool names in Claude agent metadata.
