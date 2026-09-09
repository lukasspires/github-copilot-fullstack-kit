# Codex and Claude Code multi-repository agent kit

Use this kit as the coordinating session root alongside the application's repositories. Give it a task in text, PDF or an accessible link; the main session identifies remaining work, delegates to the relevant specialists and consolidates local implementation and verification.

## Start from the kit

Opening folders in an IDE is not proof that a runtime has loaded the kit or can access every project. Select this kit as the session's working directory and explicitly add the target directories. Example paths below must be replaced with your actual absolute paths:

```bash
codex -C /absolute/agent-kit --add-dir /absolute/api --add-dir /absolute/bff
```

For Claude Code, start in `/absolute/agent-kit`:

```bash
claude --agent marina --add-dir /absolute/api --add-dir /absolute/bff
```

In an IDE, select the kit as the session root and grant the runtime access to the other workspace folders using its supported controls. At session start, confirm the kit's guide/profiles are discovered and each needed target is accessible. Restart after changing profiles if the runtime has already cached them. Additional-directory access does not guarantee discovery of every customization. Claude automatically discovers `.claude/skills/` in added directories, but does not load their agents; keep the kit as the session root for its profiles and read target instructions explicitly. See [Claude directory permissions](https://code.claude.com/docs/en/permissions#additional-directories-grant-file-access-not-configuration) and [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents).

If a workspace file is available, the coordinator may use its listed roots; it does not scan the computer or clone repositories. Missing access or unavailable delegation is reported, with the main session assuming the specialty when necessary. No application repositories are bundled here.

## Native configurations

| Layer | Codex | Claude Code |
|---|---|---|
| Entry | `AGENTS.md` | `CLAUDE.md`, importing `AGENTS.md` |
| Profiles | `.codex/agents/` | `.claude/agents/` |
| On-demand skills | `.agents/skills/` | `.claude/skills/` |
| Explicit domain instructions | `.codex/instructions/` | `.claude/instructions/` |

Copies provide equivalent behavior with platform-native metadata. Changes to shared behavior must update both copies. Domain instructions are selected by module responsibility: backend TypeScript does not load Angular instructions, and Go ETL does not automatically load Go API guidance. Models inherit the session; implementation profiles do not disable runtime permission controls. Read-only profiles remain non-writing.

Marina is the main-session coordination behavior, not another background coordinator. A bounded task can go directly to Alice (Angular), Bruno (Java), Gustavo (Go backend), Gabriel (Go ETL), Paula (Python ETL), `node-backend` (Node.js/BFF) or Diana (analysis). Sofia handles material architecture decisions and migrations; Clara independently reviews risky changes. `analista-redmine` is optional for complex histories.

## Usage and delivery

Describe the outcome and relevant projects, attach task evidence, and specify known acceptance criteria. The coordinator checks history against current code and preserves existing local changes. It delegates functional code with an explicit working directory, write set, contracts and checks; writers execute sequentially. Small general documentation/configuration work can remain in the main session.

Official company norms can be supplied per project later. Existing corporate summaries have unverified currency and apply only where governance is evidenced. Missing documents do not block unrelated implementation or justify changing legacy contracts. Source/version evidence accompanies any compliance claim.

Delivery is local code and relevant checks. Commits, published MRs, Redmine changes, deployment and live-data operations require corresponding authorization; already-granted authorization is reused. Long tasks keep one ignored, sanitized checkpoint under `.agent-state/`; short tasks stay in conversation.

## Efficiency and verification

Load only relevant instructions and skills; reuse discoveries and PDF extracts; route narrowly and review by consequences. Connector-only changes do not require full pipeline procedures. Measure actual tokens only when the runtime exposes them; fewer agents or bytes are not a token-savings percentage.

The kit contains no permanent customization validator. Evaluate changes with targeted structural checks and realistic task simulations, reporting skipped runtime/application checks honestly. See [the workflow](docs/agent-workflow.md) for routing, receipts and evaluation cases.
