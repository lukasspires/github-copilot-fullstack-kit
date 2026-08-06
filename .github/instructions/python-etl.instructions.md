---
applyTo: "**/*.py,**/pyproject.toml,**/requirements*.txt"
---

# Python ETL instructions

- Respect the Python version, package manager, formatter, linter, type checker, and test framework configured by the repository.
- Prefer typed functions and immutable data at transformation boundaries.
- Separate connectors/adapters from transformation rules and orchestration.
- Use context managers for files, streams, database connections, and HTTP sessions.
- Configure explicit connect/read timeouts for network calls.
- Implement bounded retries only for transient failures; do not retry validation, authentication, or deterministic client errors.
- Stream or chunk large files and result sets instead of loading them fully into memory.
- Make timezone assumptions explicit and normalize timestamps at boundaries.
- Use fixtures and recorded/synthetic responses for tests; avoid live network calls.
- Never use broad `except Exception` without re-raising, translating, or logging actionable context.
