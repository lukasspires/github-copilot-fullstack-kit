---
name: data-analysis
description: Analyze repository data reproducibly with profiling, metric validation, reconciliation, and evidence-backed conclusions.
---

# Reproducible data analysis

Use for a substantive question, metric or reconciliation investigation; a SQL file or migration alone does not require analysis work.

- Establish question, source, grain, timeframe and definitions from available evidence. Consult relevant fields of [the analysis contract](references/analysis-contract.md) only when they resolve ambiguity; do not require a separate artifact.
- Profile dimensions that can affect the conclusion: freshness, nulls, duplicates, types, units, joins or boundaries. Reuse already verified source/schema evidence.
- Preserve raw inputs and compute reproducibly with deterministic SQL/code and controlled randomness when used. Respect module-specific dependency restrictions without expanding them to unrelated modules.
- Reconcile material results through independent totals or calculations where practical. Separate observed findings, assumptions, uncertainty and causal claims.
- Deliver requested results with provenance, computation/query or rerun command and limitations. Persist reusable artifacts only when useful or requested; do not store sensitive extracts by default.
