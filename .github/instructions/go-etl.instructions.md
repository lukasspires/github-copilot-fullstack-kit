---
applyTo: "**/*.go,**/go.mod,**/go.sum"
---

# Go ETL instructions

- Respect the Go version and module dependencies declared in `go.mod`.
- Keep packages cohesive and interfaces consumer-owned.
- Pass `context.Context` through I/O boundaries and honor cancellation and deadlines.
- Wrap errors with operational context while preserving errors for `errors.Is` and `errors.As`.
- Close response bodies, rows, files, and other resources deterministically.
- Bound concurrency with worker pools, semaphores, or rate limiters; avoid unbounded goroutines.
- Prefer streaming decoders and buffered I/O for large payloads.
- Keep transformation functions deterministic and table-test them.
- Run `gofmt` on changed Go files and use the repository's configured lint/test commands.
- Avoid package-level mutable state unless it is deliberately synchronized and justified.
