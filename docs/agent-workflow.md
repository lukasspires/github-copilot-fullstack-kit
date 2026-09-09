# Agent workflow

The main session coordinates from the kit root with explicit access to each target repository. Load the native `task-execution` skill for the operational procedure; this page explains the roles and acceptance scenarios without duplicating that procedure.

## Roles and routing

| Role | Responsibility | Writes |
|---|---|---|
| Marina | Main-session intake, routing, continuity and consolidated evidence | Small general config/docs and checkpoints |
| Sofia | Material architecture decisions, shared contracts, migrations/backfills | No |
| Alice | Angular UI, state, accessibility, data access | Assigned scope |
| Bruno | Java APIs, domain behavior, persistence | Assigned scope |
| Gustavo | Go backend APIs/services | Assigned scope |
| Gabriel | Go ingestion/ETL | Assigned scope |
| Paula | Python ingestion/ETL | Assigned scope |
| node-backend | Node.js/TypeScript BFFs, APIs, integrations | Assigned scope |
| Diana | Reproducible SQL, notebooks, metrics and reconciliation | Assigned scope |
| analista-redmine | Optional complex-history analysis | No |
| Clara | Independent risk-based review | No |

A simple fix uses one specialist. Several technologies alone do not require Sofia; a shared-contract decision or migration does. Clara reviews authorization, public contracts, data integrity, migrations and critical operational behavior automatically, as well as explicit review requests. Pure analysis uses Diana's self-validation unless production behavior also changes. Repeated failures return to the same specialist for diagnosis rather than consuming a fixed number of retries and declaring completion.

## Handoffs and continuity

A delegation carries objective, absolute target/workdir, write set, applicable instructions, affected contracts, existing evidence, assumptions/risks, criteria and discovered checks. Writers know others may be working and preserve their edits. Only independent read-only investigations run concurrently; writers are sequential across repositories as well as within them.

Every receipt contains `status`, `changed`, `checks`, `evidence`, `risks`, and `next`. Status is `done`, `pending`, `needs_input`, or `blocked`; next names an action and owner. Checks name the command, working directory and actual outcome or reason skipped. Evidence connects criteria to code, artifacts or check results. Clara adds a separate `verdict` of `PASS`, `PASS_WITH_RISKS`, or `FAIL`. A missing independent reviewer is a pending limitation, never a self-issued independent approval.

A prolonged task uses one ignored `.agent-state/<task>.md` in the kit. The skill defines safe naming, minimal content and state rechecks on resume. Preserve decisions and the scope of prior authorizations without keeping secrets or full transcripts. Short tasks need no checkpoint.

## Local acceptance

- The observed behavior meets current acceptance criteria; reported implementation and task percentages are not proof.
- Contracts and existing local changes are preserved unless the corresponding change was authorized.
- Relevant behavior/regression checks ran with discovered repository commands; skipped checks and residual risks are explicit.
- Risk-based independent review is complete or explicitly pending with its limitations; blocking findings mean the task is not complete.
- Norm references identify actual available evidence. Unverified kit summaries or IDs alone cannot establish official conformity.
- Commits, published MRs, Redmine writes, deployments and live-data operations remain outside local delivery without corresponding authorization.

## Evaluation cases

Use temporary, read-only simulations with supplied task artifacts and accessible repositories. Do not execute the PDF demands against company systems as a kit test. Compare current requirements identified, routing, contract preservation, unnecessary delegation/re-reading and unsupported claims. Measure actual tokens only when available, and separate that metric from these proxies.

| Case | Expected decision |
|---|---|
| #5231 | Check later approval evidence against current code before reimplementation. |
| #5233 | Distinguish API/Gateway fields and envelopes and verify catalogue registration. |
| #8144 and #8145 | Recognize the decision for 3086, preserve 3083 and existing contracts, route BFF work to node-backend. |
| #7976 | Prioritize current corrections, preserve precision/audit and investigate normalization effects on keys/history before backfill. |
| Simple correction | One relevant specialist and only necessary instructions/checks. |
| Missing/conflicting norm | Continue independent scope without invented compliance; identify the specific dependent decision. |
| Multi-repository resume | Reuse decisions/authorization, recheck relevant Git state, preserve unrelated work. |
| External project | Do not impose corporate skills, frameworks or identifiers. |
| Native runtime | Confirm profile discovery and target access independently in Codex and Claude, without requiring the other platform's files. |

Native discovery is distinct from static parsing. If only configuration files can be inspected, report parsing/path checks as such and leave actual runtime delegation/access and application behavior unverified.
