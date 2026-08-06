---
name: api-ingestion
description: Implement robust REST, GraphQL, or similar API ingestion with authentication, pagination, rate-limit handling, retries, incremental cursors, schema validation, and contract tests.
argument-hint: "[API and target dataset]"
---

# API ingestion

1. Inspect existing HTTP client, auth, configuration, logging, and serialization patterns.
2. Define the connector contract with [the connector checklist](./templates/connector-contract.md).
3. Keep secrets outside source code and logs.
4. Set connect/read/overall timeouts.
5. Retry only transient failures with bounded exponential backoff and jitter; honor server retry hints.
6. Implement pagination and incremental cursors explicitly.
7. Validate response status, content type, schema, and required fields.
8. Make writes idempotent and persist checkpoints atomically.
9. Use mock servers, fixtures, or recorded sanitized responses for tests.
10. Emit metrics for requests, latency, pages, records, retries, throttling, and failures.
