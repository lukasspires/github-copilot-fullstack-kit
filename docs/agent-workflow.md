# Agent workflow

This kit uses a non-editing coordinator, implementation specialists, and an independent review role across Copilot, Codex, and Claude Code. In the VS Code Agent Host, select `Marina` directly. Prompt files are a Copilot-only legacy compatibility surface.

When agent delegation is unavailable, select the named specialist manually and include the delegation contract below in the chat. Specialists remain visible so focused work does not need to pass through the coordinator.

## Roles

| Role | Responsibility | Edits files |
|---|---|---:|
| `Marina` | Intake, discovery, risk classification, sequential delegation, review coordination, and final handoff | No |
| `Sofia` | Cross-stack impact analysis, sequencing, migration, rollout, and rollback planning | No |
| `Alice` | Angular UI, state, accessibility, and frontend tests | Yes |
| `Bruno` | Java APIs, domain behavior, persistence, security, and tests | Yes |
| `Paula` | Python extraction, transformation, validation, loading, and recovery | Yes |
| `Gabriel` | Go ingestion and ETL with bounded concurrency and reliable I/O | Yes |
| `Diana` | SQL, notebooks, metrics, profiling, statistical analysis, and reproducible findings | Yes |
| `Clara` | Independent correctness, security, data-integrity, compatibility, and test review | No |

## Delivery flow

 1. Select `Marina` in the VS Code Agent Host. On a compatible legacy extension host, `/execute-task` may be used instead.
2. Discover manifests, instructions, architecture, contracts, nearby tests, and data definitions.
3. Define the outcome, acceptance criteria, assumptions, affected contracts, risks, authorized write set, and verification plan.
4. Classify the request as low, medium, or high risk.
 5. For cross-stack work or migrations, delegate read-only planning to `Sofia` first.
6. Delegate implementation to one writer at a time. Writers keep code, tests, analysis artifacts, and documentation in sync and run repository-supported checks.
7. Immediately before the gate, ask about independent review only when the work is high risk. Explain why review is recommended.
 8. If authorized, run `Clara` with `quality-gate`; route `FAIL` findings to the original writer and repeat for at most two correction/review cycles.
9. Consolidate the final handoff with changed files, contracts, executed checks, evidence, assumptions, review status, and remaining risks.

## Delegation contract

Every coordinator-to-specialist delegation includes:

- the objective and acceptance criteria;
- explicit assumptions and known risks;
- affected public, data, or integration contracts;
- the files or directories authorized for writing;
- required repository-supported commands and checks.

Keep the contract task-specific: reference repository paths and summarize prior evidence instead of copying available instructions, unchanged files, or full logs.

Every specialist returns:

- files changed and contracts modified;
- commands executed and their results;
- limitations, skipped checks, and remaining work;
- any unexpected change found inside the authorized write set.

Writer agents never run concurrently. Read-only discovery can run in parallel when its outputs do not conflict. If another actor changes a file inside the active write set, the specialist stops editing and returns control to the coordinator for re-planning; it must not overwrite the external change.

## Context discipline

- Select a focused specialist directly for bounded single-stack work; use `Marina` when routing or coordination adds value.
- Load only matching path instructions and relevant skills. Use `etl-pipeline` with a connector skill only for multi-stage contracts, orchestration, replay, or recovery.
- Keep handoffs and command evidence concise; point to artifacts and summarize failures before including detailed logs.
- Repository instructions, `AGENTS.md`, and the selected agent form the hot path. Size budgets are enforced by `TOK001` in the structural validator.

## Risk and review policy

| Level | Typical characteristics | Independent review |
|---|---|---|
| Low | Isolated, reversible change with no public contract or sensitive-data impact | Do not prompt unless explicitly requested |
| Medium | Contained behavioral change with adequate tests and rollback | Do not prompt unless explicitly requested |
| High | Security/auth, sensitive data, migration/backfill, public contract, cross-stack, infrastructure, critical concurrency/idempotency, or an essential check that could not run | Ask immediately before the gate and recommend review |

If high-risk review is authorized, `Clara` applies `quality-gate` and returns one of these statuses:

- `PASS`: no blocking findings.
- `PASS_WITH_RISKS`: no blocking findings, with explicitly recorded residual risk.
- `FAIL`: blocking findings return to the original writer for correction.

The coordinator performs no more than two correction/review cycles. If blocking findings remain after the second cycle, the final status remains `FAIL` and the unresolved findings are reported. If the user declines review, the coordinator completes without a reviewer and records both the declined review and the associated risk.

Pure analytical work is self-validated by `Diana` for source traceability, metric definitions, reproducibility, reconciliation, and limitations. It does not trigger a separate `data-review`. Changes to code, schemas, migrations, or production behavior that accompany an analysis use the normal risk classification and review policy.

## Routing examples

| Request | Primary role | Supporting workflow |
|---|---|---|
| Add an accessible Angular form backed by an API | `Alice` | `angular-feature` |
| Add a transactional Java endpoint | `Bruno` | `java-rest-api` |
| Ingest a paginated API in Python | `Paula` | `api-ingestion` and `etl-pipeline` |
| Modify an existing ETL or its data contract | `Marina` | `/modify-etl`, then `Sofia` and the affected ETL specialist |
| Compare retention by signup cohort | `Diana` | `data-analysis` |
| Change a schema used by several modules | `Sofia` | `plan-change`, then the affected specialists |
| Review a proposed merge | `Clara` | `quality-gate` |

## Compatibility paths

- **VS Code Agent Host (primary):** select `Marina` or a focused specialist directly. The coordinator delegates through the agent tool.
- **Compatible legacy extension host:** prompt files such as `/execute-task`, `/modify-etl`, and `/analyze-data` remain available when that host loads `.github/prompts`.
- **Manual fallback:** select each specialist in the documented sequence and paste the delegation contract and preceding agent's handoff into the next chat.
- **Codex:** launch at the repository root. The main thread follows `AGENTS.md` and delegates to project agents under `.codex/agents/`; skills load from `.agents/skills/`.
- **Claude Code:** use `claude --agent marina` for coordinated work or `claude --agent <specialist>` for a bounded task. Marina must be the main session agent rather than a background subagent; skills and path rules load from `.claude/skills/` and `.claude/rules/`.

Prompt files are not used by the VS Code Agent Host. Check the [VS Code prompt files documentation](https://code.visualstudio.com/docs/agent-customization/prompt-files) for current limitations and the [custom agents documentation](https://code.visualstudio.com/docs/agent-customization/custom-agents) for agent delegation behavior.

## Definition of done

- The delivered behavior or analysis matches explicit acceptance criteria.
- Existing public contracts remain compatible or the approved break is documented.
- Tests cover changed behavior and important failure or boundary cases.
- Analytical results are traceable, reproducible, and qualified by limitations.
- Security, privacy, migration, observability, and rollback impacts are addressed when relevant.
- Every reported check was actually executed; skipped checks include a reason.
- Writer changes stayed within their authorized write sets, or conflicts were returned to the coordinator.
- High-risk review was completed, explicitly declined, or left as `FAIL` with unresolved findings documented.
