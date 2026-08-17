---
paths: ["**/*.go", "**/go.mod", "**/go.sum"]
---

# Go ETL instructions

- Respect `go.mod`; keep packages cohesive and interfaces consumer-owned.
- Propagate `context.Context`, honor cancellation and deadlines, close resources, and preserve `errors.Is` and `errors.As`.
- Bound goroutines, queues, retries, and memory; stream large payloads.
- Keep transformations deterministic and table-tested; run `gofmt` and discovered checks.
