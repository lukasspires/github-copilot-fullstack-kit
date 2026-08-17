---
paths: ["**/test/**", "**/tests/**", "**/*_test.go", "**/*.spec.ts", "**/*Test.java", "**/*Tests.java", "**/test_*.py", "**/*_test.py"]
---

# Test instructions

- Test behavior rather than implementation details.
- Use deterministic data, fixed clocks, controlled randomness, and isolated state; avoid network calls, ordering dependencies, and sleeps.
- Cover success, invalid or empty input, boundaries, and dependency failures.
- Keep fixtures minimal and free of secrets or personal data; add a regression test for bug fixes.
