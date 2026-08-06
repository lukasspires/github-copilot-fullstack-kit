---
name: etl-pipeline
description: Design or modify reliable ETL pipelines with explicit contracts, idempotency, checkpoints, observability, validation, replay, and failure handling. Use for any multi-stage data pipeline task.
argument-hint: "[pipeline goal or affected module]"
---

# Reliable ETL pipeline

Use this skill when creating or changing a pipeline that extracts, transforms, validates, and loads data.

## Workflow

1. Inspect existing pipeline patterns, runtime, scheduler, storage, schemas, checkpoints, and tests.
2. Define the source and destination contracts using [the pipeline checklist](./templates/pipeline-checklist.md).
3. Classify failures as transient, permanent, validation, authorization, or configuration errors.
4. Design idempotency and replay before implementation.
5. Bound memory, concurrency, retries, pagination, and execution time.
6. Add structured logs and metrics for each stage.
7. Add unit tests for transformations and integration/contract tests for adapters.
8. Document run, recovery, backfill, and rollback procedures.

## Required outcomes

- No silent record loss.
- Safe restart after partial failure.
- Stable deduplication keys.
- Explicit schema and timezone behavior.
- Tests that do not depend on live external services.
