---
applyTo: "**/test/**,**/tests/**,**/*_test.go,**/*.spec.ts,**/*Test.java,**/*Tests.java,**/test_*.py,**/*_test.py"
---

# Test instructions

- Test behavior rather than implementation details.
- Use deterministic data, fixed clocks, and controlled randomness.
- Cover the happy path, invalid input, empty input, boundary values, transient dependency failures, and permanent failures.
- Avoid network access, shared mutable state, order dependence, and sleeps in tests.
- Name tests so the scenario and expected result are clear.
- Keep fixtures minimal and representative; do not include production secrets or personal data.
- For bug fixes, add a regression test that fails before the fix and passes after it.
