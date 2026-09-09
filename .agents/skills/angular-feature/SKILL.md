---
name: angular-feature
description: Implement Angular features with repository patterns, accessibility, API contracts, visual states, and tests.
---

# Angular feature implementation

Inspect only the affected Angular modules and their versions, routing, forms, state, UI, API and test patterns. Load this skill for Angular responsibility, not TypeScript alone.

- Preserve the actual consumer contract, including endpoint, context, response envelope and HTTP/business errors. For evidenced company governance, consult `codice-api-contracts` only where relevant; historical summaries do not override published contracts.
- Reuse existing components and models; do not introduce DTOs, endpoints or state infrastructure unless the change requires them.
- Implement the affected validation, permission and visual states, including keyboard/focus and accessibility where interaction changes.
- Consult only relevant items in [the feature checklist](templates/feature-checklist.md). It is a thinking aid, not a required artifact or a demand to add telemetry/E2E tests.
- Test changed behavior with nearby conventions and run relevant discovered commands. Report checks skipped and why.
