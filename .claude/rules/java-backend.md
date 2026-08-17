---
paths: ["**/*.java", "**/pom.xml", "**/build.gradle", "**/build.gradle.kts", "**/settings.gradle", "**/settings.gradle.kts"]
---

# Java backend instructions

- Detect Java, framework, build, architecture, and tests; apply Spring conventions only when Spring is present.
- Prefer constructor injection and immutable dependencies; keep transport adapters thin and domain rules out of controllers.
- Validate and authorize at boundaries; return stable errors without leaking internals.
- Place transactions at consistency boundaries, avoid remote calls inside long transactions, and prevent unbounded or N+1 queries.
- Use repository wrappers and configured quality gates.
