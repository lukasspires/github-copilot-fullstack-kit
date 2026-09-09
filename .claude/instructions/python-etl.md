# Python ETL instructions

- Respect configured Python, package manager, formatter, linter, type checker, and test framework.
- Use typed functions and immutable transformation boundaries; separate connectors, transformations, and orchestration.
- Manage resources with context managers and explicit timeouts.
- Retry only bounded transient failures; do not retry validation, authentication, or deterministic client errors.
- Stream or chunk large inputs and make timezone normalization explicit.
- Test with synthetic or sanitized offline fixtures and retain actionable error context.
