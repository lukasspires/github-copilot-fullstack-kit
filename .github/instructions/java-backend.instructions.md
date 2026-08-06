---
applyTo: "**/*.java,**/pom.xml,**/build.gradle,**/build.gradle.kts,**/settings.gradle,**/settings.gradle.kts"
---

# Java backend instructions

- Detect the Java version, framework, build tool, test stack, and architecture from the repository before coding.
- When Spring Boot is present, follow the existing conventions for configuration, dependency injection, validation, transactions, persistence, and exception handling.
- Prefer constructor injection and immutable dependencies.
- Keep controllers/transport adapters thin and move business rules into application/domain services.
- Use dedicated request/response DTOs when exposing persistence entities would couple the API to storage.
- Validate inputs at the boundary and return stable, documented error responses.
- Use transactions at service boundaries based on consistency requirements; avoid long transactions around remote calls.
- Prevent N+1 queries, unbounded queries, and accidental eager loading.
- Add unit tests for business rules and integration tests for serialization, persistence, and framework wiring as appropriate.
- Prefer Maven or Gradle wrappers when present and do not bypass configured quality gates.
