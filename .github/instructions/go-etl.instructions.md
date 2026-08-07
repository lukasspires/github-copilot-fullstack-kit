---
applyTo: "**/*.go,**/go.mod,**/go.sum"
---

# Go ETL instructions

- Respect the `go.mod` version/dependencies; keep packages cohesive and interfaces consumer-owned.
- Propagate `context.Context` across I/O, honor cancellation/deadlines, close resources, and wrap errors while preserving `errors.Is`/`errors.As`.
- Bound goroutines, queues, retries, and memory; use worker pools/rate limits plus streaming or buffered I/O for large payloads.
- Keep transformations deterministic and table-tested; avoid mutable package state unless synchronized and justified.
- Run `gofmt` and the repository's configured test and quality commands.
