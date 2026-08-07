---
applyTo: "**/*.java,**/pom.xml,**/build.gradle,**/build.gradle.kts,**/settings.gradle,**/settings.gradle.kts"
---

# Java backend instructions

- Detect the Java version, framework, build tool, architecture, and test stack; apply Spring conventions only when Spring is present.
- Prefer constructor injection and immutable dependencies. Keep transport adapters thin and business rules in application/domain services.
- Use request/response DTOs when exposing persistence entities would couple the API to storage.
- Validate and authorize at boundaries; return stable errors without leaking internals.
- Place transactions at consistency boundaries, avoid remote calls inside long transactions, and prevent N+1, eager, or unbounded queries.
- Add unit and integration tests for affected boundaries; use repository wrappers and configured quality gates.
