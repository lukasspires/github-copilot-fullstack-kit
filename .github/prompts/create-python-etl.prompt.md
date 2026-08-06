---
name: create-python-etl
description: Create a production-oriented Python ETL from a web, API, or file source.
agent: etl-python
---

Create the requested Python ETL. If essential information is missing, ask only for source, target, schema/key, incremental behavior, expected volume, authentication method, and execution environment.

Before coding, inspect existing pipeline patterns and dependencies. Implement extraction, transformation, validation, and loading as separate concerns. Include idempotency, timeouts, bounded retries, observability, configuration, tests, and a concise runbook. Do not add dependencies when the repository already provides an adequate option.
