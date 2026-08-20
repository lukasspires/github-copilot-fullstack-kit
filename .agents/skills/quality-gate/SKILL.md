---
name: quality-gate
description: Review changes for correctness, security, tests, compatibility, data integrity, and operational readiness.
---

# Quality gate

1. Inspect the diff, affected runtimes/contracts, governance evidence, and [the review checklist](./templates/review-checklist.md).
2. When Códice governance applies, load the matching `codice-*` or Git skill and verify its contract. Do not report Códice deviations for unrelated repositories.
3. Run only repository-supported, non-mutating checks.
4. Review correctness, security, data integrity/idempotency, resource bounds, compatibility, tests, and operations.
5. For completed task branches, verify the required `[Unreleased]` entry. For APIs, distinguish business endpoints from the explicit `GET /healthz` and `200/503` exception.
6. Check generated files, migrations, API specs, configuration, secrets/logs, deployment, and rollback.
7. Separate verified failures from questions, assumptions, residual risks, and unexecuted checks.
