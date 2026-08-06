---
name: web-scraping
description: Build or modify authorized web scrapers with conservative rate limiting, stable extraction, fixture-based parser tests, checkpointing, and change detection. Use for public or explicitly authorized websites only.
argument-hint: "[target site and data to collect]"
---

# Authorized web scraping

## Preconditions

- Confirm that access is public or explicitly authorized.
- Prefer an official API, export, feed, or repository file when available.
- Do not bypass login, paywalls, CAPTCHA, anti-bot mechanisms, robots restrictions, rate limits, or other access controls.

## Workflow

1. Separate HTTP/browser acquisition from parsing and normalization.
2. Configure an identifying user agent when appropriate, explicit timeouts, conservative rate limits, and bounded backoff.
3. Prefer semantic attributes, structured data, and stable identifiers over fragile visual selectors.
4. Validate status, content type, expected page markers, and extracted record counts.
5. Persist checkpoints and stable keys so retries do not duplicate data.
6. Store sanitized fixtures and test parsers offline.
7. Detect layout/schema changes and fail visibly rather than emitting corrupted data.
8. Minimize collection and retention of personal or sensitive data.

Review [scraping safeguards](./references/safeguards.md) before implementation.
