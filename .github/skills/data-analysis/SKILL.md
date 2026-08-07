---
name: data-analysis
description: Analyze repository data reproducibly with profiling, metric validation, reconciliation, and evidence-backed conclusions.
---

# Reproducible data analysis

1. Translate the request into a measurable question and complete [the analysis contract](./references/analysis-contract.md); mark unavailable details as assumptions.
2. Discover data access, schemas, metric definitions, repository conventions, privacy rules, and rerun/test commands.
3. Profile freshness, counts, types, keys, nulls, duplicates, ranges, units, and join cardinality.
4. Preserve raw inputs and use deterministic, reviewable SQL/code with seeded randomness.
5. Reconcile important results through totals, boundaries, or an independent calculation when practical.
6. Store reusable artifacts/tests without sensitive extracts. Separate conclusions from methods, assumptions, limitations, uncertainty, and unsupported causal claims.

## Required outcomes

- Numbers trace to sources and reproducible computations.
- Metrics, filters, data-quality handling, and expected-volume bounds are explicit.
- The handoff includes conclusions, limitations, artifact paths, and exact rerun commands.
