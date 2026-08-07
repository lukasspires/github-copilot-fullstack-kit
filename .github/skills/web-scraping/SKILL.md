---
name: web-scraping
description: Build authorized scrapers with rate limits, offline parser tests, checkpoints, stable extraction, and change detection.
argument-hint: "[target site and data to collect]"
---

# Authorized web scraping

## Preconditions

- Confirm public or explicit authorization and prefer an official API/export/feed when available.
- Never bypass login, paywalls, CAPTCHA, anti-bot mechanisms, robots restrictions, rate limits, or other controls.

## Workflow

1. Review [scraping safeguards](./references/safeguards.md); separate acquisition from parsing/normalization.
2. Configure identification when appropriate, explicit timeouts, conservative rates, and bounded backoff.
3. Prefer semantic/structured selectors and stable IDs; validate status, content, page markers, and record counts.
4. Persist checkpoints/stable keys, use sanitized offline parser fixtures, and fail visibly on layout/schema drift.
5. Minimize collection and retention of personal or sensitive data.
