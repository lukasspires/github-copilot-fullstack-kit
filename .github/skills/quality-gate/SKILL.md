---
name: quality-gate
description: Review changes for correctness, security, tests, compatibility, data integrity, and operational readiness.
argument-hint: "[diff, branch, or feature]"
---

# Quality gate

1. Inspect the diff, affected runtimes/contracts, and [the review checklist](./templates/review-checklist.md).
2. Run only repository-supported, non-mutating checks.
3. Review correctness, security, data integrity/idempotency, resource bounds, compatibility, tests, and operations.
4. Check generated files, migrations, API specs, configuration, secrets/logs, deployment, and rollback.
5. Separate verified failures from questions, assumptions, residual risks, and unexecuted checks.
