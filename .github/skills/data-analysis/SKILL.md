---
name: data-analysis
description: Produce reproducible and evidence-backed analysis from SQL databases, tabular files, notebooks, or repository datasets. Use for profiling, metric calculation, trend or cohort analysis, anomaly investigation, statistical comparisons, and validation of analytical results.
---

# Reproducible data analysis

1. Translate the request into a decision or question with explicit population, grain, measures, dimensions, filters, time range, timezone, and acceptance criteria.
2. Discover the repository's data access, schema, metric definitions, notebook/script conventions, privacy rules, and available test commands.
3. Complete [the analysis contract](./references/analysis-contract.md) before substantial computation. Mark unavailable details as assumptions instead of inventing them.
4. Profile sources for freshness, row counts, types, keys, nulls, duplicates, ranges, units, and join cardinality.
5. Preserve raw inputs. Implement deterministic transformations in reviewable SQL or code and seed any sampling or modeling randomness.
6. Validate important results with reconciled totals, boundary checks, or an independent calculation when practical.
7. Store reusable artifacts and tests in the repository's established locations. Do not commit sensitive or production data extracts.
8. Report conclusions separately from methodology, assumptions, quality limitations, and uncertainty. Avoid causal language unless the design supports it.

## Required outcomes

- Every reported number can be traced to a source and reproducible computation.
- Metric definitions and filters are explicit.
- Missing data, duplicates, exclusions, and outliers are handled visibly.
- Queries and computations are bounded for the expected data volume.
- The handoff includes artifact paths and exact rerun commands.
