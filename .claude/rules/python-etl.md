---
paths: ["**/*.py", "**/pyproject.toml", "**/requirements*.txt"]
---

# Python ETL instructions

- Respect configured Python, package manager, formatter, linter, type checker, and tests.
- Use typed functions and immutable boundaries; separate connectors, transformations, and orchestration.
- Manage resources with context managers and explicit timeouts; retry only bounded transient failures.
- Stream or chunk large inputs, normalize timezones explicitly, and test with synthetic or sanitized offline fixtures.
