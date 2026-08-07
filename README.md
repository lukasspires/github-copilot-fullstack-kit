# GitHub Copilot Full-Stack Configuration Kit

Starter configuration for repositories containing:

- Python and Go ETLs
- Web scraping, API ingestion, and repository/file ingestion
- Angular frontend
- Java web backend, including Spring Boot when already used by the project
- Cross-stack architecture and code review
- Reproducible SQL, notebook, metric, and statistical data analysis
- Coordinated intake and routing for development or analysis requests

## Structure

```text
.github/
├── copilot-instructions.md        # Always-on repository guidance
├── agents/                        # Coordinator and specialist profiles
├── instructions/                  # Path/language-specific rules
├── prompts/                       # Legacy reusable prompt files
└── skills/                        # On-demand workflows and resources
AGENTS.md                           # Operational project map for agents
.vscode/settings.json              # Parent-repository discovery for monorepos
docs/agent-workflow.md              # Team roles, routing, and definition of done
scripts/validate_customizations.py  # Standard-library structural validation
```

## How the layers differ

- `copilot-instructions.md`: small rules that should affect almost every task.
- `*.instructions.md`: rules automatically applied to matching paths/extensions.
- `*.agent.md`: selectable specialist roles with their own tools and behavior.
- `*.prompt.md`: legacy reusable commands for compatible Copilot Chat surfaces.
- `skills/*/SKILL.md`: detailed procedures and related templates loaded when relevant.
- `AGENTS.md`: repository operational context for compatible agent surfaces.

Avoid duplicating the same long rules in every layer. Global rules belong in repository instructions; detailed procedures belong in skills.

## Token-efficient defaults

- Keep repository-wide instructions cross-cutting; put stack rules in matching path instructions and detailed workflows in on-demand skills.
- Select a focused specialist directly for a narrow task. Use `Marina` for unclassified, cross-stack, or multi-specialist work.
- Give `Marina` the outcome, acceptance criteria, constraints, affected areas, and expected checks. Reference repository paths instead of pasting available files or long logs.
- Use a connector skill alone for connector-only work; add `etl-pipeline` only for multi-stage contracts, orchestration, replay, or recovery.
- Prompt files remain compact legacy adapters and add context only when invoked.

The validator uses a deterministic UTF-8-bytes/4 proxy to detect context growth; it is a regression metric, not a model tokenizer. Default budgets are 300 for `AGENTS.md`, 650 for repository instructions, 1,000 for `Marina`, 600 for other agents, 350 for path instructions, 250 for prompts, and 500 for each `SKILL.md`. `TOK001` is a warning normally and an error with `--strict`.

## IDE compatibility as of August 2026

| Feature | VS Code | JetBrains/IntelliJ | Eclipse |
|---|---:|---:|---:|
| Repository instructions | Supported | Preview/supported surface | Preview/supported surface |
| Path-specific instructions | Supported | Preview; verify plugin version | Not used by Eclipse Copilot Chat |
| Prompt files | Supported | Preview | Not supported |
| Custom agents | Supported | Preview | Preview |
| Agent skills | Supported | Preview | Not supported |
| MCP servers | Supported | Supported | Supported |

Keep the latest stable IDE and GitHub Copilot extension/plugin installed. Preview behavior may change.

Prompt files are supported by some VS Code Copilot Chat surfaces but are not used by the VS Code Agent Host. The primary workflow in this kit therefore starts by selecting a custom agent, not by invoking a prompt file. See the [VS Code prompt files documentation](https://code.visualstudio.com/docs/agent-customization/prompt-files) for the current surface limitations.

## Installation

1. Inventory the destination repository's existing `.github/`, `.vscode/`, and `AGENTS.md` content.
2. Merge the kit files selectively. Do not replace `.github/`, `.vscode/settings.json`, or `AGENTS.md` wholesale; preserve and reconcile repository-specific instructions, settings, agents, prompts, and skills.
3. Edit `AGENTS.md` with the real module paths and commands.
4. Review the `applyTo` globs in `.github/instructions/` for the destination layout.
5. Remove irrelevant agents, prompts, or skills together with their dependent references, then rerun validation.
6. With Python 3.9 or newer, run the structural validator described below.
7. Open Copilot Chat and inspect the Customizations/Agents diagnostics before use.

### VS Code

- Open the Command Palette and run `Chat: Open Customizations`.
- Select `Marina` in the agent picker for unclassified development or data-analysis work. This is the primary Agent Host entry point.
- All implementation specialists remain visible and can be selected directly for narrowly scoped work.
- Prompts are read from `.github/prompts` only by compatible legacy/extension-host surfaces and can be invoked there with `/prompt-name`; the Agent Host does not use them.
- Skills are read from `.github/skills` and can load automatically or appear as slash commands.
- The included setting helps a subfolder workspace discover customizations from a parent monorepo root.

### IntelliJ and other JetBrains IDEs

- Open GitHub Copilot Chat.
- Use the settings/gear menu and open `Customizations` or `Configure Agents`.
- Repository files remain under `.github`, but several customization features are still preview features; verify them with the installed plugin version.

### Eclipse

- `.github/copilot-instructions.md` is the dependable shared repository instruction layer for Copilot Chat.
- Custom agents under `.github/agents` are available in preview on supported/current plugin versions.
- Prompt files and Agent Skills are not currently supported in Eclipse. Use the same instructions and agents, or paste a prompt's body manually when necessary.

## Suggested usage

### VS Code Agent Host (primary)

Select a focused specialist for a bounded single-stack task; otherwise select `Marina`. The read-only coordinator discovers context, sends compact contracts, runs writers sequentially by write set, and consolidates verified evidence. Cross-stack work or migrations go to `Sofia` first. Unexpected changes inside an active write set stop that writer.

### Legacy prompt workflow

On compatible extension-host surfaces, `/execute-task` remains the legacy entry point for an unclassified request. Other available workflows include:

- `/plan-change` for cross-stack planning.
- `/create-python-etl`, `/create-go-etl`, `/add-api-source`, `/add-web-scraper`, and `/add-file-source` for ingestion work.
- `/modify-etl` for changing an existing ETL through coordinator-led architecture and implementation routing.
- `/java-endpoint` for Java endpoint work.
- `/analyze-data` for reproducible analytical work.
- `/review-change` for an explicitly requested independent review.

Do not depend on prompt files in the Agent Host. When prompts are unavailable, select `Marina` or the named specialist directly and provide the same task description in chat.

### Risk-based review

`Marina` proposes `Clara` only for high-risk development or an explicit review request. Authorized review returns `PASS`, `PASS_WITH_RISKS`, or `FAIL`; failures return to the original writer for at most two correction/review cycles. Declined review and residual risk are recorded. Pure analysis uses `Diana` self-validation; related production or contract changes use the normal policy.

See [the agent workflow](docs/agent-workflow.md) for the delegation contract, routing examples, risk policy, and shared definition of done.

## Validate the customization

The validator requires Python 3.9 or newer and has no third-party dependencies:

```shell
python scripts/validate_customizations.py
# After customizing a destination repository:
python scripts/validate_customizations.py --root . --installed --strict
```

Use `--root` to validate another repository root, `--installed` to reject unresolved `AGENTS.md` project-map placeholders, and `--strict` to promote structural warnings to errors. Exit code `0` means success, `1` means a configuration error, and `2` means invalid usage or an internal validation failure.

The script validates the structural subset adopted by this kit, including metadata, references, name collisions, local links, installed placeholders, and context-size budgets. It is not a complete GitHub Copilot schema validator or a real tokenizer and does not replace the Customizations diagnostics in VS Code. Run both after installation or customization.

When changing the validator itself, run its dependency-free test suite:

```shell
python -m unittest discover -s tests -v
```

## Customize before production use

- Replace placeholders in `AGENTS.md`.
- Narrow `applyTo` patterns in monorepos when TypeScript or Java files belong to multiple unrelated applications.
- Add real build/test commands only after confirming them in repository manifests.
- Add organization-specific security, architecture, naming, and deployment rules.
- Review every agent's `tools` list under least privilege.
- Do not pre-approve shell execution in third-party skills without reviewing all referenced scripts.

## Official references

- https://docs.github.com/en/copilot/reference/customization-cheat-sheet
- https://docs.github.com/en/copilot/reference/custom-instructions-support
- https://docs.github.com/en/copilot/how-tos/configure-custom-instructions-in-your-ide/add-repository-instructions-in-your-ide
- https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/create-custom-agents-in-your-ide
- https://code.visualstudio.com/docs/agent-customization/overview
- https://code.visualstudio.com/docs/agent-customization/custom-agents
- https://code.visualstudio.com/docs/agent-customization/prompt-files
- https://code.visualstudio.com/docs/agent-customization/agent-skills
