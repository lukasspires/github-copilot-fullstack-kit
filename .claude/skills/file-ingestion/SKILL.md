---
name: file-ingestion
description: Ingest files safely with streaming, schema validation, deduplication, archive protection, quarantine, and incremental processing.
---

# File ingestion

1. Complete [the schema checklist](./templates/schema-contract.md) for location, ownership, format, encoding, compression, schema, size, and cadence.
2. Stream/chunk large files; validate paths and archive entries against traversal.
3. Use stable IDs/checksums, validate structural controls, and quarantine malformed inputs with a machine-readable report.
4. Persist checkpoints only after durable writes.
5. Test representative size, malformed, duplicate, and encoding cases; document retention, replay, and cleanup.

