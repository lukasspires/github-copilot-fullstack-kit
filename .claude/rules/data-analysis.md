---
paths: ["**/*.sql", "**/*.ipynb", "**/analysis/**", "**/analytics/**", "**/notebooks/**"]
---

# Data analysis instructions

- Define the question, population, grain, metrics, dimensions, filters, time range, timezone, and acceptance criteria.
- Verify provenance, freshness, schemas, keys, joins, nullability, units, and duplicates before calculating.
- Keep raw inputs immutable and transformations deterministic; make missing-data, exclusion, outlier, deduplication, and sampling rules explicit.
- Reconcile important results and separate facts, assumptions, interpretations, and causal claims.
- Minimize sensitive data and report sources, limitations, artifacts, and rerun commands.
