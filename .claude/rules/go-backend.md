---
paths: ["**/*.go", "**/go.mod", "**/go.sum", "**/*.proto", "**/buf.yaml", "**/buf.gen.yaml"]
---

# Go backend instructions

- Detect the Go version, framework, HTTP/RPC protocol, architecture, persistence, migrations, and tests; do not impose a framework.
- Keep transports thin; define stable request, response, RPC, and error contracts.
- Validate, authenticate, and authorize at boundaries; do not leak internals or secrets through errors or observability.
- Propagate `context.Context`; bound queries, transactions, goroutines, queues, retries, and time.
- Add focused unit and integration tests; run `gofmt` and discovered checks.
