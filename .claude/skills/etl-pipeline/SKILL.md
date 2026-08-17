---
name: etl-pipeline
description: Design or modify multi-stage ETLs with contracts, idempotency, checkpoints, replay, validation, and observability; not connector-only changes.
---

# Reliable ETL pipeline

Use this skill for multi-stage pipeline contracts, orchestration, recovery, or replay. For a connector-only change, use the matching API, file, or scraping skill instead.

## Workflow

1. Inspect runtime, scheduler, storage, schemas, checkpoints, tests, and established pipeline patterns.
2. Complete [the pipeline checklist](./templates/pipeline-checklist.md), including contracts and failure classes.
3. Design idempotency, checkpoints, replay, and validation behavior before implementation.
4. Bound memory, concurrency, retries, pagination, and execution time; add stage logs and metrics.
5. Test transformations and adapter contracts; document run, recovery, backfill, and rollback.

## Required outcomes

- No silent loss; stable keys and safe restart after partial failure.
- Explicit schema/timezone behavior and offline tests.

