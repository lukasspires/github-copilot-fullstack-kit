---
name: add-file-source
description: Add ingestion for repository, local, object-storage, or shared files.
agent: task-coordinator
---

Route this file-ingestion task through `task-coordinator`. Have it inspect the repository, classify the risk, and delegate sequentially to `etl-python` or `etl-go` according to the existing implementation.

Determine file formats, encoding, compression, naming, location, schema version, expected size, update frequency, duplicate detection, malformed-record handling, and archive safety. Stream or chunk large files, validate paths and archive entries, use checksums or stable identifiers, quarantine invalid records, and add representative fixtures.
