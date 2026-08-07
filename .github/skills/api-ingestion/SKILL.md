---
name: api-ingestion
description: Build API ingestion with authentication, pagination, rate limits, retries, checkpoints, validation, and contract tests.
argument-hint: "[API and target dataset]"
---

# API ingestion

1. Inspect existing HTTP, auth, configuration, logging, and serialization patterns.
2. Complete [the connector checklist](./templates/connector-contract.md) before implementation.
3. Keep secrets out of code/logs; set explicit timeouts and bounded transient-only retries with jitter and server retry hints.
4. Implement pagination/cursors, validate status/content/schema, make writes idempotent, and persist checkpoints atomically.
5. Add request/latency/page/record/retry/throttle/failure metrics and offline contract tests using sanitized fixtures or mocks.
