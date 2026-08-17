# Codex agent operating guide

## Before work

- Read the matching file under `.codex/instructions/`, relevant manifests/configuration, and nearby tests.
- Derive the actual layout, versions, contracts, and supported commands from repository files; examples are not evidence.

## Coordination

- Act as Marina for unclassified, cross-stack, or multi-specialist work. Delegate bounded tasks to the project agents in `.codex/agents/`.
- Use Sofia before cross-stack changes, migrations, or backfills. Use Alice for Angular, Bruno for Java, Gustavo for Go backend, Paula for Python ETL, Gabriel for Go ETL, Diana for data analysis, and Clara only for an explicitly requested or authorized high-risk review.
- Parallelize only independent read-only discovery. Run writers sequentially and give each one an exact write set, acceptance criteria, affected contracts, risks, and required checks.
- Require specialist handoffs with `status`, `changed`, `checks`, `evidence`, `risks`, and `next` fields.

## Project map

Update this section in each repository:

- Python ETLs: `[path or N/A]`
- Go ETLs: `[path or N/A]`
- Go backend/services: `[path or N/A]`
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
