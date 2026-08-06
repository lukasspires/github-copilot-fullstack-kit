# Agent operating guide

This file gives repository-level operational context to AI coding agents.

## First actions

1. Read `.github/copilot-instructions.md`.
2. Inspect the relevant language-specific instruction files in `.github/instructions/`.
3. Detect the actual project layout and versions from repository files.
4. Read nearby tests before changing production code.

## Project map

Update this section in each repository:

- Python ETLs: `[path or N/A]`
- Go ETLs/services: `[path or N/A]`
- Angular frontend: `[path or N/A]`
- Java backend: `[path or N/A]`
- Shared contracts/OpenAPI: `[path or N/A]`
- Data analysis, SQL, and notebooks: `[path or N/A]`
- Infrastructure and deployment: `[path or N/A]`

## Commands

Discover commands from project files before running them. Typical commands are examples only:

- Python: configured `pytest`, `ruff`, `mypy`, or project task runner.
- Go: `go test ./...`, `go vet ./...`, and `gofmt` when a Go module exists.
- Angular: scripts declared in `package.json`, preferably through the repository package manager lockfile.
- Java: `./mvnw ...` or `./gradlew ...` when wrappers exist.

Do not claim a command passed unless it was actually executed successfully.

## Change discipline

- Keep changes scoped to the requested behavior.
- Preserve public contracts unless a breaking change is explicitly approved.
- Add tests before or alongside the implementation.
- Do not rewrite generated files manually when a generator is authoritative.
- Do not edit lockfiles unless dependency resolution actually changed.
