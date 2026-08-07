# Repository instructions for GitHub Copilot

## Communication

- Respond in Brazilian Portuguese unless the user requests another language.
- Keep identifiers, public API names, code comments, logs, and technical documentation in English unless the repository already uses another convention.
- State assumptions explicitly. Do not invent libraries, endpoints, schemas, credentials, commands, or project versions.

## Repository evidence

- Before editing, read the nearest `AGENTS.md`, matching path instructions, relevant manifests/configuration, contracts, and nearby tests.
- Detect the actual layout, versions, architecture, dependencies, and supported commands from repository files.
- Identify affected modules, public contracts, tests, migrations, deployment files, and compatibility risks.
- Prefer the smallest coherent change. Avoid unrelated refactors, new frameworks, or dependencies when the existing stack is sufficient.

## Engineering

- Follow existing architecture and conventions; add abstractions only when they reduce real duplication or coupling.
- Keep domain logic deterministic and separated from infrastructure where the repository already does so.
- Use explicit types at boundaries, validate untrusted input, and bound I/O, concurrency, retries, queries, pagination, and memory.
- Handle errors with useful context but no secrets. Keep configuration outside business logic and avoid hidden global state.
- Preserve public contracts unless a breaking change is explicitly approved.

## Verification and safety

- Add or update tests for changed behavior, failure paths, and boundaries. Keep default tests deterministic and offline.
- Run only repository-supported commands; report exact results and explain skipped checks.
- Never commit credentials, private data, or production extracts. Redact sensitive values from logs and fixtures.
- Use safe serializers and parameterized queries; validate paths, URLs, redirects, uploads, and archives.
- Apply least privilege and never bypass authentication, access controls, CAPTCHA, rate limits, robots rules, or terms of service.

## Completion format

Report what changed, affected files/contracts, executed checks with exact outcomes, and remaining assumptions, risks, or manual steps.
