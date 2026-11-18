# Test instructions

- Test behavior rather than implementation details.
- Use deterministic data, fixed clocks, controlled randomness, and isolated state; avoid network calls, ordering dependencies, and sleeps.
- Cover success, invalid or empty input, boundaries, and transient and permanent dependency failures as applicable.
- Keep fixtures minimal, representative, and free of secrets or personal data.
- Add a regression test for bug fixes.
- When a check needs a real database (application startup, health checks, integration tests), use the target's `dev` environment database, which is free to use; prefer it over a local Docker database. Never use QA, stage or production, and never record its credentials or host.
