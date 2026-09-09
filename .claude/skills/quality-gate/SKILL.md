---
name: quality-gate
description: Review changes for correctness, security, tests, compatibility, data integrity, and operational readiness.
---

# Evidence-based quality gate

Use for an explicit review and automatically for changes to authorization, public contracts, data integrity, migrations or critical operations. This risk review is part of authorized local development; do not seek a second approval merely to review.

- Inspect the diff and affected contracts, tests and target instructions. Reuse intake/evidence and consult only applicable items in [the review checklist](templates/review-checklist.md).
- Evaluate correctness, security, compatibility, integrity and operational consequences that the change actually affects. Do not demand unrelated infrastructure, tests or checklist artifacts.
- With governance evidence, consult relevant company/Git guidance; report a normative failure only against a confirmed applicable source or project rule. Historical unverified summaries cannot independently justify failure, forced tags/statuses or a mandatory changelog.
- Run relevant discovered non-mutating checks; do not repair files or operate live systems during review. Report unexecuted checks accurately.
- Findings identify severity, concrete file/contract evidence, trigger, impact and suggested correction. Separate verified defects, material unanswered questions and residual risks; do not invent issues to fill categories.
- Return the six-field receipt (`status`, `changed`, `checks`, `evidence`, `risks`, `next`). Keep review verdict separate: `FAIL` for evidenced blocking defects, `PASS_WITH_RISKS` for material limitations/risks without a confirmed blocking defect, `PASS` when reviewed scope has no blocking findings or material remaining risk. A completed review can have `status: done` and verdict `FAIL`.
- Send corrections back through the coordinator to the same writer; do not start another implementation or claim global safety from a bounded review.
