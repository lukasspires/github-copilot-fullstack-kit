---
applyTo: "**/*.sql,**/*.ipynb,**/analysis/**,**/analytics/**,**/notebooks/**"
---

# Data analysis instructions

- Define the business question, dataset grain, population, metrics, dimensions, filters, time range, and timezone before analysis.
- Inspect schemas and data provenance; verify join cardinality, keys, nullability, units, freshness, and duplicate behavior.
- Keep raw inputs immutable and transformations reproducible in versioned SQL, scripts, or notebooks.
- Make missing-data, exclusion, outlier, deduplication, and sampling rules explicit.
- Validate row counts, totals, ranges, and important results with independent checks when practical.
- Use deterministic ordering and seeded randomness where results could otherwise vary.
- Distinguish facts, assumptions, interpretations, and causal claims. Quantify uncertainty when applicable.
- Minimize sensitive data, redact examples, and never commit production extracts, credentials, or personal data.
- Document metric definitions, source tables/files, refresh time, limitations, and how to rerun the analysis.
