---
name: java-rest-api
description: Implement Java APIs with stable contracts, validation, authorization, persistence, migrations, observability, and tests.
---

# Java REST API

Inspect affected Java modules, framework/build, contracts, security, persistence and nearby tests. Use existing layers and models.

- Preserve published methods, fields, envelopes, HTTP statuses and consumer semantics. For evidenced governance, consult `codice-api-contracts` on affected contracts; its historical conventions do not override local evidence.
- Validate and authorize at the appropriate boundary; request context identifiers are not authentication. Keep controllers focused and avoid sensitive error details.
- When persistence changes, review transaction boundaries, query bounds, indexes and N+1 risks; do not add pagination or migrations unrelated to the task.
- Consult affected items in [the endpoint checklist](templates/endpoint-checklist.md), without requiring a new checklist artifact or DTO.
- Add regression/unit/integration checks appropriate to changed behavior and run relevant discovered project commands. Update API specs or rollout/migration documentation only when affected.
