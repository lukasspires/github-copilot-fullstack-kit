---
name: modify-etl
description: Safely alter an existing ETL while preserving contracts and restartability.
agent: task-coordinator
---

Inspect the existing ETL, its tests, schemas, schedules, checkpoints, consumers, and operational documentation.

Have `task-coordinator` delegate first to `solution-architect` for a compact impact analysis covering behavior changes, migration/backfill needs, compatibility, idempotency, replay, and rollback. After that read-only analysis returns, have it delegate sequentially to the correct implementation agent, `etl-python` or `etl-go`.

Do not make speculative changes outside the requested scope.
