---
name: java-rest-api
description: Implement or modify Java web APIs with stable contracts, validation, authorization, transaction boundaries, persistence, error mapping, observability, migrations, and tests. Use Spring Boot conventions only when present.
argument-hint: "[endpoint or backend behavior]"
---

# Java REST API

1. Inspect the Java version, framework, build tool, security, persistence, migration, API documentation, and test conventions.
2. Define request/response/error contracts and compatibility expectations.
3. Validate and authorize at the boundary.
4. Keep controllers thin and business rules in appropriate services/domain objects.
5. Deliberately define transaction scope; avoid remote calls inside long transactions.
6. Bound queries and pagination and check for N+1 behavior.
7. Map internal failures to stable external errors without leaking sensitive details.
8. Add unit and integration tests and update API documentation/migrations when needed.
9. Run wrapper-based build and configured quality gates.

Use [the endpoint checklist](./templates/endpoint-checklist.md).
