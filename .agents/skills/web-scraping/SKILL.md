---
name: web-scraping
description: Build authorized scrapers with rate limits, offline parser tests, checkpoints, stable extraction, and change detection.
---

# Authorized web scraping

Use public or explicitly authorized resources and prefer an available official API/export/feed. Do not bypass access restrictions or rate limits. Apply [scraping safeguards](references/safeguards.md) to affected acquisition or data handling.

- Reuse existing acquisition/parser separation, cached responses and sanitized fixtures. A selector fix does not require a crawler redesign.
- For new or affected acquisition, use appropriate identification, timeouts, conservative concurrency and bounded backoff.
- Prefer stable semantic/structured selectors and validate affected page/content markers so layout drift is visible rather than silent record loss.
- Preserve keys and checkpoints already in use. Add durable recovery or metrics only when required by the requested acquisition/restart behavior.
- Test altered parsing offline against representative success and changed-layout/invalid cases; minimize sensitive collection and retention.
