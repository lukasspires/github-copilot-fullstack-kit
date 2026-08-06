---
name: file-ingestion
description: Ingest repository, local, network, or object-storage files safely with streaming, schema validation, encoding detection, checksums, archive-path protection, quarantine, and incremental processing.
argument-hint: "[file location and format]"
---

# File ingestion

1. Determine location, ownership, naming, format, encoding, compression, schema version, expected size, and update cadence.
2. Use streaming or chunks for large files.
3. Validate paths and prevent traversal or unsafe archive extraction.
4. Detect duplicates with stable identifiers or checksums.
5. Validate headers, types, required fields, row counts, and trailer/control totals when present.
6. Quarantine malformed files or records with a machine-readable report.
7. Persist checkpoints only after durable downstream writes.
8. Add representative small, large, malformed, duplicate, and encoding fixtures.
9. Document retention, replay, and cleanup behavior.

Use [the schema checklist](./templates/schema-contract.md).
