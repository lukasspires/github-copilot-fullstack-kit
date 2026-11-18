# Java backend instructions

- Detect Java, framework, build, architecture, and test versions; apply Spring conventions only when Spring is present.
- Prefer constructor injection and immutable dependencies; keep transport adapters thin and domain rules out of controllers.
- Use DTOs when exposing persistence entities would couple API and storage.
- Validate and authorize at boundaries; return stable errors without leaking internals.
- Place transactions at consistency boundaries, avoid remote calls inside long transactions, and prevent unbounded or N+1 queries.
- Use repository wrappers and configured quality gates.
- In SES/NADS Spring microservices, the `sprint` profile (`application-sprint.properties`) points to the `dev` database by default (verified 2026-11-18 in the 8 local `ms/` repositories with a datasource). For a local run against `dev`, start the packaged jar with `--spring.profiles.active=sprint` (port 8080) instead of a local or Docker database. Before starting, confirm the profile's datasource URL still targets `dev` and whether Flyway is enabled (it migrates on startup, so check for new migrations in the change). Run it from a scratch working directory, because the shared component writes `logs/` relative to the working directory. Never record the URL or credentials.
