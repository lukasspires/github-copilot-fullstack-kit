---
name: java-rest-api
description: Implement Java APIs with stable contracts, validation, authorization, persistence, migrations, observability, and tests.
---

# Java REST API

1. Inspect the actual Java/framework/build, security, persistence, migration, documentation, test conventions, and whether Códice governance applies.
2. For governed APIs, apply `codice-api-contracts`; its POST/body/tag rules and `/healthz` exception override generic HTTP defaults, while security and compatibility constraints still apply. Do not retrofit an incompatible legacy contract without approval.
3. Complete [the endpoint checklist](./templates/endpoint-checklist.md) for contracts, compatibility, auth, transactions, queries, and rollout.
4. Keep controllers thin, validate/authorize at boundaries, and map failures to stable errors without leaking details.
5. Bound queries/pagination, prevent N+1 behavior, and avoid remote calls inside long transactions.
6. Add unit/integration tests, update API docs/migrations when needed, and run wrapper-based quality gates.
