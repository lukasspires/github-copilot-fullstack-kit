# Go backend instructions

- Detect the Go version, framework, HTTP/RPC protocol, architecture, persistence, migrations, test stack, and whether Códice governance applies; do not impose a framework or storage library on unrelated or legacy projects.
- When supported by available project requirements for a new governed Go API, consult the native `codice-go-echo-api` and `codice-api-contracts` skills. Preserve an existing legacy framework/layout unless migration is explicitly approved.
- Keep transports thin and domain/application behavior separate. Define stable request, response, RPC, and error contracts.
- Validate and authenticate at boundaries, authorize each protected operation, and never leak internals or secrets through errors, logs, metrics, or traces.
- Propagate `context.Context`, honor cancellation and deadlines, close resources, and preserve `errors.Is` and `errors.As` behavior.
- Place transactions at consistency boundaries; avoid remote calls in long transactions and prevent N+1, eager, or unbounded queries.
- Bound goroutines, queues, retries, backoff, and execution time. Add focused unit and integration tests; run `gofmt` and discovered repository checks.
