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

A simple fix uses one specialist. Several technologies alone do not require Sofia; a shared-contract decision or migration does. Clara reviews authorization, public contracts, data integrity, migrations and critical operational behavior automatically, as well as explicit review requests. Pure analysis uses Diana's self-validation unless production behavior also changes. Repeated failures return to the same role in a new session for diagnosis rather than consuming a fixed number of retries and declaring completion.

## Handoffs and continuity

Marina stays in the main session and consolidates results. Every specialist assignment, including corrections and reviews, receives the next task-local NN and title `<task> — <role> — <NN> — <type>`. Types: `implementação`, `revisão`, `correção`, `análise`. Never reuse completed sessions, fork, resume, continue or restore their conversations for a new assignment.

Before dispatch Marina writes a sanitized, Git-ignored `<kit_root>/.agent-state/<task>/<NN>-<role>-handoff.md`. Use a lowercase letters/digits/hyphens task slug and reject symlinks escaping `.agent-state/`. Include:

- Objective; role and absolute native profile path; absolute kit_root and all target_root paths.
- Applicable target AGENTS.md/CLAUDE.md and domain instructions to read explicitly: launching from the kit does not automatically load target instructions.
- Allowed write scope; contracts; relevant evidence and already-verified results; applicable scoped authorizations.
- Acceptance criteria; discovered verification commands and workdirs; preservation warning because others may have worked on the same files.
- Assignment ID, predecessor, type, receipt path and exact granted tool allowlist.

The launch prompt is short: `Act as <role>. Read <absolute-profile> and <absolute-handoff>, then execute the assignment.` Do not paste prior conversations. The specialist performs only that assignment and writes the matching `-receipt.md`, never starts another coordination. Read-only roles may write that receipt only; they never edit targets. Their profiles intentionally rely on this instruction boundary and the existing runtime controls, rather than a blanket read-only mode that would also prohibit the receipt.

Receipts contain `status` (`done`, `pending`, `needs_input`, `blocked`), `changed`, `checks` (command/workdir/actual result or skip), `evidence`, `risks`, `next` (action and owner), plus `profile_read` and `instructions_read` with absolute paths actually read. Clara adds `verdict`: `PASS`, `PASS_WITH_RISKS`, or `FAIL`. A review may finish with `status: done` and `verdict: FAIL`. Missing profile confirmation means loading unverified; a log or final chat answer is not a substitute for the receipt file.

Marina maintains `<kit_root>/.agent-state/<task>.md` for every task with assignments, including short ones. For each invocation record NN, platform, role, native session/ID, predecessor, type, exact allowlist, state, absolute handoff/receipt paths and result. Record the reservation before launch and the returned ID immediately afterward. Keep task decisions, scoped authorizations, Git evidence and next action; exclude secrets and full transcripts. Do not automatically archive or delete completed sessions.

Before writer N+1 starts, require writer N's final receipt, manager evidence that it has stopped working, and target Git status/diff checked and recorded in the checkpoint. `pending`, `needs_input` and `blocked` can close an assignment but never establish acceptance. Check other sessions with the same cwd and any shared target, including sessions launched from a different cwd. Unknown activity requires reconciliation. Writers are sequential across targets. Clara, Sofia and analista-redmine may overlap with other readers and role-free discovery, never an active writer in their target. Reviews inspect actual files/diffs, and Marina does not edit those targets during review. Receipt files have separate ownership and do not constitute concurrent target writers.

On resumption read the checkpoint and native manager before creating anything; reconcile recorded IDs and current Git state. An uncertain creation result is recorded as uncertain, then matched by title, cwd, time and available ID in the manager. Do not retry or start a fallback writer until duplication has been ruled out. If uncertainty cannot be resolved, keep only that dependent launch pending. A clarification requiring additional work closes with `needs_input`; after the user replies, issue a new ID and handoff to the same role. Native tool approvals stay with the execution that requested them.

If the platform cannot provide visible sessions, execute in the main session and disclose in both checkpoint and response: `delegação visível indisponível: <motivo>; especialidade <papel> assumida na sessão principal`. Still record the assignment, handoff and receipt, using an unavailable native ID. This fallback is not independent review and cannot pass the real visible-session acceptance scenario.

## Codex desktop

Before dispatch inspect the installed tool schemas and available projects. The current desktop exposes `mcp__codex_app__list_projects`, `mcp__codex_app__create_thread`, `mcp__codex_app__wait_threads`, `mcp__codex_app__read_thread` and `mcp__codex_app__list_threads` (checked 2026-09-11). Availability and invocation authorization are separate: obey the calling environment's restrictions on task creation; if it cannot create specialist sessions, use the disclosed fallback.

Select the project whose path is kit_root, and explicitly request the saved local checkout even when it is a Git repository:

```json
{
  "title": "redmine-1234 — bruno — 01 — implementação",
  "target": {
    "type": "project",
    "projectId": "<id returned by list_projects>",
    "environment": { "type": "local" }
  },
  "prompt": "Act as bruno. Read <absolute-profile> and <absolute-handoff>, then execute the assignment."
}
```

`create_thread` has no `agent_type`; reading a profile conveys instructions, not automatic enforcement of that file's runtime metadata. The receipt must confirm the profile read. Omit `model` and `thinking` to use the user's configured defaults, without assuming inheritance from Marina. Project-local approval controls are unchanged.

Record and present the returned threadId and hostId. If a pending response only has clientThreadId, do not pass it to tools requiring threadId; reconcile through the manager before retrying. Follow progress with `wait_threads` using targets, hostId and returned cursor as afterCursor; use bounded waits. Use `read_thread` for necessary details and `list_threads` to check other activity. A native completion plus receipt and Git verification releases the next writer; neither completion nor a receipt alone proves acceptance.

## Claude Code

The installed CLI was checked at version 2.1.267 on 2026-09-11: `--bg`, `--name`, `--agent`, `--add-dir`, `--permission-mode`, `--allowedTools`, `agents`, `attach`, and `logs` are available. Recheck help on other installations. From kit_root, with actual absolute paths and checks discovered in the target:

```bash
claude --bg --agent bruno \
  --name "redmine-1234 — bruno — 01 — implementação" \
  --add-dir /absolute/api \
  --permission-mode acceptEdits \
  --allowedTools "Bash(mvn test)" \
  -- "Act as bruno. Read /absolute/kit/.claude/agents/bruno.md and /absolute/kit/.agent-state/redmine-1234/01-bruno-handoff.md, then execute."
```

Repeat `--add-dir` for other targets; do not use worktree isolation because assignments share the same local files. Never use `--resume`, `--continue` or `--fork-session` for new assignments. Capture the printed short ID and present it to the user. Monitor with `claude agents --json --all` and inspect details with `claude logs <id>`. Humans use `claude agents` and `claude attach <id>`.

The documented JSON field `state` describes background work: `working`, `blocked`, `done`, `failed`, `stopped`. `state: done` indicates the last turn finished even if the process is alive; `status: idle` or a missing PID alone does not establish completion. `failed` and `stopped` require receipt/Git reconciliation before any replacement. `status: waiting` and `waitingFor: permission prompt` identify a live approval request. Confirm these fields against the installed manager output; interactive sessions may omit them. Use the receipt as the official result, not log scraping.

Background execution has no human terminal to answer prompts. Every launch explicitly sets `--permission-mode acceptEdits` and an `--allowedTools` derived from that assignment's discovered checks; record exact rules in the checkpoint. This permits file edits under the runtime mode and adds only the listed command approvals. Do not add bare Bash or broad command patterns. Existing managed/user/project permissions still apply: the CLI allowlist is additive, not a replacement policy. If existing broad grants would invalidate the promised outside-allowlist approval behavior, record the incompatibility and resolve it through native controls before claiming that test passed; do not silently rewrite user settings.

Commands outside the allowlist that require approval remain pending. Marina reports the exact command and ID, and the user answers through `claude attach <id>`. Never use `bypassPermissions` or `--permission-prompts none`, and never answer a native approval on the user's behalf. Do not carry per-assignment tool approvals to the next invocation; task-level development authorization remains scoped and separate.

Sources checked 2026-09-11: [Claude CLI reference](https://code.claude.com/docs/en/cli-reference), [agent view and JSON state](https://code.claude.com/docs/en/agent-view#list-sessions-as-json), [permissions](https://code.claude.com/docs/en/permissions), and [Codex features](https://learn.chatgpt.com/docs/features). Exact Codex tool names/arguments above come from the installed desktop schemas, not a claim that the public features page documents that API. Runtime availability checks do not prove the acceptance scenarios below.

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

## Visible-session acceptance scenarios

Static checks cover TOML/YAML syntax, equivalent `.codex/` and `.claude/` instructions, native profile paths, no role delegation through Agent, and no conflicting fallback/blanket no-write rules. These do not replace real execution.

Before marking this workflow fully validated, execute in each platform an implementation → review → correction → new review chain with four distinct visible native IDs, four handoffs and four specialist-written receipts. Use a local disposable fixture and preserve a preexisting change. Check the manager, actual shared files, profile/instruction confirmations and recorded Git gates between writers. Marina consolidates the evidence; do not invent a defect just to obtain a correction.

Also exercise an outside-allowlist command that visibly waits and is resolved by the human through attach without bypass; interrupted coordination resumed by checkpoint/manager without duplication; unavailable visible sessions with disclosed main-session fallback; clarification followed by a fresh assignment; and uncertain launch reconciliation without a duplicate writer. Record each as executed, failed, or pending with evidence. Simulated failure responses validate the coordinator's decision only and must not be labeled a real platform failure. Unavailable platforms, missing human interaction or unknown runtime state leave those acceptance criteria pending, not passed.
