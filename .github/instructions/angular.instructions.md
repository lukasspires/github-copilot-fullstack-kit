---
applyTo: "**/*.ts,**/*.html,**/*.scss,**/angular.json,**/package.json"
---

# Angular instructions

- Detect the installed Angular and TypeScript versions before selecting APIs or syntax.
- Follow the repository's current choice of standalone components, NgModules, state management, signals, RxJS patterns, and UI library.
- Keep components focused on presentation and orchestration; place reusable data access and domain behavior in appropriate services or stores.
- Use strict typing and avoid `any`; narrow `unknown` values at boundaries.
- Prevent subscription leaks using the project's established pattern.
- Treat templates as untrusted display boundaries: avoid unsafe HTML and direct DOM manipulation unless reviewed.
- Include accessible labels, keyboard support, focus behavior, and semantic markup.
- Cover loading, empty, validation, error, and success states.
- Add or update unit tests and, when configured, component or end-to-end tests.
- Do not change package versions or lockfiles unless dependency changes are required.
