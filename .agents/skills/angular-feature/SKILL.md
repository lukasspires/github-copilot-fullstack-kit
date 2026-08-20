---
name: angular-feature
description: Implement Angular features with repository patterns, accessibility, API contracts, visual states, and tests.
---

# Angular feature implementation

1. Inspect the Angular/TypeScript versions and existing routing, state, forms, UI, tests, API patterns, and whether Códice governance applies.
2. When Códice governance is evidenced, apply `codice-api-contracts`: send required request context, parse business outcomes from `tag` rather than HTTP status alone, and preserve the `/healthz` exception. Do not impose this behavior on unrelated APIs.
3. Complete [the feature checklist](./templates/feature-checklist.md) for behavior, permissions, contracts, validation, and visual states.
4. Reuse existing components and keep components focused, templates simple, and external data strictly narrowed.
5. Implement accessibility, focus/keyboard, responsive, loading, empty, error, and success behavior.
6. Add nearby-style tests and run configured lint, types, tests, and build.
