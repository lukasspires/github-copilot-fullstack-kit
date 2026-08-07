---
applyTo: "**/test/**,**/tests/**,**/*_test.go,**/*.spec.ts,**/*Test.java,**/*Tests.java,**/test_*.py,**/*_test.py"
---

# Test instructions

- Test behavior rather than implementation details.
- Use deterministic data, fixed clocks, controlled randomness, and isolated state; avoid network calls, order dependence, and sleeps.
- Cover success, invalid/empty input, boundaries, and transient/permanent dependency failures as applicable.
- Name tests by scenario and result; keep fixtures minimal, representative, and free of secrets or personal data.
- For bug fixes, add a regression test that fails before the fix and passes after it.
