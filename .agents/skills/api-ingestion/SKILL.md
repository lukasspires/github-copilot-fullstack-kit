---
name: api-ingestion
description: Build API ingestion with authentication, pagination, rate limits, retries, checkpoints, validation, and contract tests.
---

# API ingestion

Inspect the affected connector's HTTP, auth, schema, storage and test patterns. Reuse intake evidence; a narrow fix does not require redesigning the ingestion pipeline.

- Preserve source/destination contracts and existing pagination, keys and recovery behavior unless the requested change affects them.
- For new or affected acquisition logic, address explicit timeouts, bounded transient retries and server rate hints. Add pagination/cursors only if the source needs them; never retry permanent validation failures blindly.
- When writes or recovery change, establish durable-write/checkpoint ordering and idempotency. Keep secrets out of code, logs and fixtures.
- Consult affected items in [the connector contract](templates/connector-contract.md); no complete document or new metrics/checkpoint system is required for a trivial correction.
- Test the changed success/failure boundaries with sanitized fixtures or mocks. Add observability only where needed to detect the affected failure mode.
