---
name: java-rest-api
description: Implement Java APIs with stable contracts, validation, authorization, persistence, migrations, observability, and tests.
---

# Java REST API

1. Inspect the actual Java/framework/build, security, persistence, migration, documentation, and test conventions.
2. Complete [the endpoint checklist](./templates/endpoint-checklist.md) for contracts, compatibility, auth, transactions, queries, and rollout.
3. Keep controllers thin, validate/authorize at boundaries, and map failures to stable errors without leaking details.
4. Bound queries/pagination, prevent N+1 behavior, and avoid remote calls inside long transactions.
5. Add unit/integration tests, update API docs/migrations when needed, and run wrapper-based quality gates.

