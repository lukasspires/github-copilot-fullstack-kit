# Repository instructions for GitHub Copilot

## Communication

- Respond in Brazilian Portuguese unless the user requests another language.
- Keep identifiers, public API names, code comments, logs, and technical documentation in English unless the repository already uses another convention.
- State assumptions explicitly. Do not invent libraries, endpoints, schemas, credentials, commands, or project versions.

## Repository-first workflow

Before changing code:

1. Inspect the relevant manifests and configuration files, such as `pyproject.toml`, `requirements*.txt`, `go.mod`, `package.json`, `angular.json`, `pom.xml`, `build.gradle*`, Docker files, CI workflows, and existing architecture documentation.
2. Identify the affected modules, public contracts, tests, migrations, deployment files, and backward-compatibility risks.
3. Follow the existing project structure and dependency versions. Do not introduce a new framework or major dependency when the existing stack can solve the problem.
4. Prefer the smallest coherent change. Do not perform unrelated refactors.

## Architecture and code quality

- Apply SOLID and Clean Code pragmatically; avoid abstractions that do not reduce real duplication or coupling.
- Keep domain logic independent from infrastructure where the existing architecture permits it.
- Use explicit types at boundaries and validate untrusted input.
- Prefer dependency injection, small interfaces, composition, and deterministic functions.
- Handle errors explicitly and preserve useful context without leaking secrets.
- Keep configuration outside business logic and read secrets only from approved secret stores or environment variables.
- Avoid hidden global state and nondeterministic tests.

## Data pipelines and ETLs

- Separate extraction, transformation, validation, and loading responsibilities.
- Design for idempotency, retries with bounded exponential backoff, timeouts, checkpointing, incremental execution, and safe replay.
- Define source and target schemas, nullability, keys, deduplication rules, timezone handling, and failure behavior.
- Never silently discard invalid records. Route them to a quarantine/dead-letter mechanism or return a clear validation report.
- Add structured logs and metrics for records read, accepted, rejected, retried, and written.
- Do not bypass authentication, CAPTCHA, rate limits, robots rules, terms of service, or access controls.

## Frontend

- Preserve the Angular version and architecture already used by the repository.
- Keep components focused, prefer typed forms and typed service boundaries, and avoid business logic in templates.
- Include loading, empty, error, and success states where applicable.
- Preserve accessibility, keyboard navigation, semantic HTML, and responsive behavior.

## Java backend

- Preserve the framework, Java version, build tool, package conventions, and dependency-management strategy already present.
- Keep transport models, domain models, and persistence models separated when the project architecture already distinguishes them.
- Validate request boundaries, centralize error mapping, use transactions deliberately, and avoid exposing internal exceptions.
- Keep database access bounded and observable; avoid N+1 queries and unbounded result sets.

## Testing and verification

- Add or update tests for changed behavior, including failure paths and boundary cases.
- Prefer unit tests for pure logic and integration tests for external contracts, persistence, serialization, and framework wiring.
- Mock external services at the network boundary; do not make live external calls in the default test suite.
- Run only commands supported by the repository. Prefer wrapper scripts such as `mvnw` or `gradlew` when present.
- Report commands executed and any checks that could not be run.

## Security

- Never commit credentials, tokens, private keys, session cookies, production data, or sensitive personal data.
- Use parameterized queries and safe serializers. Validate paths, URLs, redirects, uploaded files, and archive extraction.
- Apply least privilege to tools, service accounts, network access, and file permissions.
- Redact secrets and sensitive values from logs and error messages.

## Completion format

When finishing a code task, provide:

1. What changed.
2. Files changed.
3. Validation/tests executed.
4. Remaining risks, assumptions, or manual steps.
