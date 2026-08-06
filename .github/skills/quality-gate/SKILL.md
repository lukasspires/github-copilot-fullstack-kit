---
name: quality-gate
description: Validate a cross-stack change before merge by checking correctness, security, tests, formatting, builds, API compatibility, data migrations, observability, and rollback readiness.
argument-hint: "[diff, branch, or feature]"
---

# Quality gate

1. Inspect the diff and identify affected runtimes and contracts.
2. Run only repository-supported checks.
3. Review correctness, security, data integrity, idempotency, bounded resource usage, compatibility, and operational behavior.
4. Verify tests cover changed behavior and failure paths.
5. Check generated files, migrations, API specs, configuration, secrets, logs, and deployment impact.
6. Report verified failures separately from unexecuted checks and assumptions.

Use [the review checklist](./templates/review-checklist.md).
