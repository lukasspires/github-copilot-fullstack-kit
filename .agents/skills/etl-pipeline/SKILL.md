---
name: etl-pipeline
description: Design or modify multi-stage ETLs with contracts, idempotency, checkpoints, replay, validation, and observability; not connector-only changes.
---

# Reliable ETL pipeline

Use for changes to multi-stage contracts, orchestration, recovery or replay. Connector-only fixes use the matching API, file or scraping skill.

- Inspect affected runtime, scheduler, source/destination schema, keys, transformations and recovery paths; reuse established patterns and evidence.
- Consult affected items in [the pipeline checklist](templates/pipeline-checklist.md). A small correction does not mandate new checkpoints, metrics, artifacts or a complete pipeline redesign.
- Preserve precision, audit, null/default and timezone semantics unless explicitly changed. For normalization of keys, investigate collisions, upsert behavior and existing historical rows before deciding whether migration/backfill is needed.
- Involve Sofia for material architecture, shared contracts, migrations/backfills. Live replay/backfill requires corresponding authorization; local implementation/testing can continue independently.
- For new or affected recovery logic, establish idempotency, durable checkpoint ordering, partial-failure restart and bounds on memory/concurrency/retries. Add observability or run/recovery documentation where changed behavior needs it.
- Test the altered transformations and failure boundaries with representative offline fixtures. Use Clara for data-integrity or critical operational changes and report unresolved historical-data risks.
