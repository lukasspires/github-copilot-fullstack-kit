---
name: add-web-scraper
description: Add an authorized, resilient, rate-limited web scraper.
agent: task-coordinator
---

Route this scraping task through `task-coordinator`. Have it inspect the repository, classify the risk, and delegate sequentially to `etl-python` or `etl-go` according to the existing implementation.

Confirm the target is public or authorized. Do not bypass authentication, CAPTCHA, anti-bot controls, robots restrictions, rate limits, or terms of service. Prefer a documented API when available. Use stable selectors, explicit timeouts, conservative request rates, backoff, checkpoints, content validation, fixture-based parser tests, and clear handling for layout changes.
