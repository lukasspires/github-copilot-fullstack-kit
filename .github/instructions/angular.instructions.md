---
applyTo: "**/*.ts,**/*.html,**/*.scss,**/angular.json,**/package.json"
---

# Angular instructions

- Detect the installed Angular/TypeScript versions and follow the existing component, state, forms, RxJS, and UI-library patterns.
- Keep components focused; place reusable data access and domain behavior in services or stores.
- Use strict types, narrow external `unknown` values, and prevent subscription leaks with the repository's pattern.
- Treat templates as untrusted display boundaries; avoid unsafe HTML or direct DOM manipulation unless reviewed.
- Cover accessibility, keyboard/focus behavior, responsive layout, and loading, empty, validation, error, and success states.
- Update configured unit/component/E2E tests. Change dependencies or lockfiles only when required.
