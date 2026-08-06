---
name: add-api-source
description: Add a paginated, rate-limited, observable API source to an ETL.
agent: task-coordinator
---

Route this API-ingestion task through `task-coordinator`. Have it inspect the repository, classify the risk, and delegate sequentially to `etl-python` or `etl-go` according to the existing implementation.

Verify authentication, base URL/configuration, pagination, cursor or incremental strategy, rate limits, timeout policy, retryable status codes, schema validation, deduplication key, checkpoint persistence, and secret handling. Add contract fixtures and tests without live network calls. Document operational metrics and failure behavior.
