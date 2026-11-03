---
name: marina-plan
description: Turn a confirmed brief into plan.md, stage handoff templates and an envelope the user dispatches with marina go. Adapted from Superpowers 7.0.0 writing-plans for the kit's sequential visible sessions.
---

# Plan from the brief

Start only from a brief confirmed under [marina-intake](../marina-intake/SKILL.md). The plan is the set of decisions a specialist cannot make alone: which files, contracts, values and checks prove each stage. Execution stays `marina run`: visible sessions, one writer at a time, never resumed, no commit without authorization.

## Stages

- **One stage per independently reviewable deliverable**, owned by one writer role. Fold setup and documentation into the stage that needs them.
- **Writer roles.** A plan may change role between stages; `marina run` links them with `encadeia`. More than one role requires `review = "each_stage"`. Route by the kit guide's team mapping; SQL migrations go to the module owner.
- **Analysis first.** A material architecture decision, shared contract, migration or backfill first gets an `analisa` node for the architect, run by the manual procedure before the envelope exists.
- **Scope.** Give each stage `targets` (a subset of the envelope's) and an `allowlist` of `Bash(...)` rules that name a target path, derived from the brief's checks. Reviews in `each_stage` use the stage's allowlist, so it includes what the reviewer needs (for example `Bash(git -C <target> diff *)`).
- **Commits and pushes.** No commit or push rule unless the brief records that authorization.

## Files

All files live in `<kit_root>/.agent-state/<project>/tasks/<task>/`:

- **`plan.md`** from [the plan template](templates/plan-template.md): goal, the brief's global constraints, a review focus (the inputs or failure modes most likely to bite that no stage's criteria cover), and one section per stage.
- **`stage-<n>-handoff-template.md`**, never named like `NN-<role>-handoff.md`. Sections:
  - `Objective`, `Write scope` and `Acceptance criteria` are required;
  - `Checks and workdir` and `Contracts` follow;
  - `Expected inputs` and `Expected outputs` are what `marina watch` shows for the stage.

  Each step leaves one reasonable implementation: exact files, names, values and the tests that prove them. Where tests apply, the criteria ask the receipt to show the test failing before the change and passing after it.
- **`[envelope]`** through `mcp__marina__envelope_draft`: stages with role, handoff, `targets` and `allowlist`; branches; `review`; `max_corrections` (0 or 1); `max_duration`; `judge_max_calls`; `on_pass_with_risks`.

## Self-review

1. Every acceptance criterion of the brief maps to a stage.
2. No step says "handle edge cases" or anything else that decides nothing.
3. Names and paths are consistent across stages.
4. Allowlists name targets and cover the reviewers.
5. `envelope_show`, `gate_check` and `decision_preview` report no errors.

Fix what you find; do not ask for a second review of the plan.

## Handing over

Link `plan.md` and ask the user to review it. When they are satisfied, give them the ready command:

```bash
<kit_root>/bin/marina go <project> <task>
```

Running it in a terminal of their own is the approval of the whole plan:
- it shows the plan;
- waits 10 s, during which Ctrl-C cancels without writing anything;
- records the approval hash;
- starts `marina run` detached;
- opens `marina watch`.

No tool approves an envelope. Any later edit to the envelope or a template stops the run with `envelope_changed`. When the run ends, read the generated `## Execução marina-run` section and consolidate evidence per criterion as task-execution says.
