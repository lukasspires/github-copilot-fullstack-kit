# Plan — <task>

**Goal:** <one sentence from the brief>

**Brief:** `tasks/<task>/brief.md` (confirmed <date>)

## Global constraints

- <exact values from the brief: contracts, versions, authorizations, norms>

## Review focus

1. <input or failure mode no stage's criteria cover, and the expected behavior>

## Stage 1 — <role>: <deliverable>

- Targets: `<abs>` · allowlist: `Bash(<check naming the target>)`, `Bash(git -C <abs> diff *)`
- Template: `stage-1-handoff-template.md`
- Expected inputs: <predecessor result, contract, data>
- Expected outputs: <files, tests, receipt evidence>
- Typical size: <small / medium / large: the reason>

## Envelope

- review: `each_stage` | `final` · max_corrections: <0|1> · max_duration: <e.g. 2h> · on_pass_with_risks: <accept|judge|stop> · judge_max_calls: <n>

## Dispatch

`<kit_root>/bin/marina go <project> <task>`
