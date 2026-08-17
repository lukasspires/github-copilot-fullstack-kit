---
applyTo: "**/*.go,**/go.mod,**/go.sum,**/*.proto,**/buf.yaml,**/buf.gen.yaml"
---

# Go backend instructions

- Detect the Go version, framework, HTTP/RPC protocol, architecture, persistence, migrations, and test stack; do not impose a framework or storage library.
- Keep transports thin and domain/application behavior separate. Define stable request, response, RPC, and error contracts.
- Validate and authenticate at boundaries, authorize protected operations, and never leak internals or secrets through errors, logs, metrics, or traces.
- Propagate `context.Context`, honor cancellation and deadlines, close resources, and preserve `errors.Is` and `errors.As` behavior.
- Place transactions at consistency boundaries; avoid remote calls in long transactions and prevent N+1, eager, or unbounded queries.
- Bound goroutines, queues, retries, backoff, and execution time. Add focused unit and integration tests; run `gofmt` and discovered checks.
