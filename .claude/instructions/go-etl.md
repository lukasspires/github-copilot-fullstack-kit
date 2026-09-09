# Go ETL instructions

- Respect `go.mod`; keep packages cohesive and interfaces consumer-owned.
- Propagate `context.Context` across I/O, honor cancellation and deadlines, close resources, and preserve `errors.Is` and `errors.As`.
- Bound goroutines, queues, retries, and memory; stream large payloads.
- Keep transformations deterministic and table-tested; avoid mutable package state unless synchronized and justified.
- Run `gofmt` and discovered test and quality commands.
