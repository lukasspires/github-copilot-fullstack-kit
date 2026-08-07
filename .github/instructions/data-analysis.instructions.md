---
applyTo: "**/*.sql,**/*.ipynb,**/analysis/**,**/analytics/**,**/notebooks/**"
---

# Data analysis instructions

- Define the question, population, grain, metrics, dimensions, filters, time range, timezone, and acceptance criteria.
- Verify provenance, freshness, schemas, keys, join cardinality, nullability, units, and duplicates before calculating results.
- Keep raw inputs immutable and transformations deterministic and reproducible in versioned SQL, scripts, or notebooks.
- Make missing-data, exclusion, outlier, deduplication, and sampling rules explicit; seed randomness.
- Reconcile row counts, totals, ranges, and important results independently when practical.
- Separate facts, assumptions, interpretations, and causal claims; quantify uncertainty when applicable.
- Minimize sensitive data and report metric definitions, sources, refresh time, limitations, artifacts, and rerun commands.
