# Explanation

Understanding-oriented discussion. The *why* behind design decisions:
why metrics are defined the way they are, why the read-only contract
is an allowlist not a denylist, why cancelled is its own canonical
state, why cohort + control don't weighted-average to global.

## Available pages

- [The cohort model](cohort-model.md) — what a cohort is, why
  cohort identity is a manual JQL filter (not auto-detected), why
  cohort and control sides aren't weighted-averaged into a global,
  and what goes wrong when labelling discipline drifts.

## What's not here yet

For design rationale not yet covered above, the `## Decisions` and
`## Why` sections of each spec carry the load:

- [`flow-metrics.md`](../../specs/flow-metrics.md) — 39 numbered
  design decisions with reasoning.
- [`ai-adoption-report.md`](../../specs/ai-adoption-report.md) —
  design decisions for the report layer.
