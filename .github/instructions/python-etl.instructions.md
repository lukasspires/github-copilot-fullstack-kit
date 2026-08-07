---
applyTo: "**/*.py,**/pyproject.toml,**/requirements*.txt"
---

# Python ETL instructions

- Respect the configured Python version, package manager, formatter, linter, type checker, and test framework.
- Use typed functions and immutable transformation boundaries; separate connectors, transformation rules, and orchestration.
- Manage files, streams, databases, and HTTP sessions with context managers and explicit connect/read timeouts.
- Retry only transient failures with bounds; do not retry validation, authentication, or deterministic client errors.
- Stream or chunk large inputs, make timezone handling explicit, and normalize timestamps at boundaries.
- Test with synthetic/sanitized fixtures, never live services. Translate, re-raise, or log actionable context for broad exceptions.
