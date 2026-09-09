---
name: file-ingestion
description: Ingest files safely with streaming, schema validation, deduplication, archive protection, quarantine, and incremental processing.
---

# File ingestion

Inspect the affected reader, schema and persistence contract before changing behavior. Consult only relevant fields in [the schema checklist](templates/schema-contract.md); no completed form is required.

- Preserve encoding, precision, null/default and deduplication behavior outside the request.
- For new or affected large-file handling, use bounded streaming/chunks. When archive/path handling is affected, validate entries against traversal and decompression limits appropriate to the accepted input.
- Match malformed input handling to the established fail/skip/quarantine contract; do not silently drop records or add a quarantine subsystem for an unrelated fix.
- If writes or restart behavior change, use stable identity and advance checkpoints only after durable writes. Existing pipelines need no new checkpoint mechanism solely to satisfy a checklist.
- Test representative changed boundaries such as malformed rows, duplicates or encodings. Document retention/replay/cleanup only when the task changes those behaviors.
