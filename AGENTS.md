# Agent operating guide

## Before work

- Read `.github/copilot-instructions.md`, matching path instructions, relevant manifests/configuration, and nearby tests.
- Derive the actual layout, versions, contracts, and supported commands from repository files; examples are not evidence.

## Project map

Update this section in each repository:

- Python ETLs: `[path or N/A]`
- Go ETLs/services: `[path or N/A]`
- Angular frontend: `[path or N/A]`
- Java backend: `[path or N/A]`
- Shared contracts/OpenAPI: `[path or N/A]`
- Data analysis, SQL, and notebooks: `[path or N/A]`
- Infrastructure and deployment: `[path or N/A]`

## Delivery rules

- Keep changes scoped to the requested behavior.
- Preserve public contracts unless a breaking change is explicitly approved.
- Add tests before or alongside the implementation.
- Run only discovered repository commands and report exact results or skipped checks.
- Do not hand-edit generated files or change lockfiles unless their source or dependencies changed.
