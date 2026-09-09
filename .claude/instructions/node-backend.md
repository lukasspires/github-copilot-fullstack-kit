# Node.js backend instructions

- Detect Node.js/TypeScript versions, package manager, module system, framework, validation, auth, test and build setup from the target. Follow its patterns; do not impose a framework.
- Keep BFF orchestration and transport mapping separate from domain behavior where the existing architecture supports it. Preserve each upstream/downstream contract, including field names, envelopes, business outcome tags, and authentication context.
- Validate untrusted input and upstream responses; forward only intended headers and never log credentials. Authorize protected operations using the project's established rules.
- Preserve cancellation/timeouts, bounded payloads and existing resource limits. Retry only safe transient operations and avoid blocking the event loop.
- Add focused behavior/regression tests with controlled upstream fixtures; use the discovered scripts and lockfile-compatible package manager. Change dependencies only when necessary.
