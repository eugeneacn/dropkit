# Archived specs

These six files are the original AI-adoption spec chain. They have
been superseded by [`../ai-adoption-report.md`](../ai-adoption-report.md)
as of 2026-05-19.

| Archived file | Replaced by |
|---|---|
| `ai-adoption-baseline.md` | `ai-adoption-report.md` — baseline mode |
| `ai-adoption-baseline-plan.md` | (to be drafted alongside the new spec) |
| `ai-adoption-cohort.md` | `ai-adoption-report.md` — cohort mode |
| `ai-adoption-cohort-plan.md` | (to be drafted alongside the new spec) |
| `ai-value-report.md` | `ai-adoption-report.md` — program mode |
| `ai-value-report-plan.md` | (to be drafted alongside the new spec) |

## Why the reframe

The original chain modelled three separately-packaged skills
(baseline, cohort, value-report) sitting on top of `flow-metrics`.
Each skill carried its own integrity envelope, schema-version
negotiation, hand-coded JSON Schema validator, atomic-write contract,
and adversarial flag system. Reviewing the chain end-to-end surfaced
two things:

1. **The three skills do one job** — pair flow-metrics outputs and
   render deltas — at three different scopes (cross-time,
   within-window cohort vs control, across-scope program rollup).
   Splitting them tripled the surface area without tripling the work.
2. **The defensive ceremony was solving an audit problem we don't
   have.** This is internal tooling for many teams in a single
   program. The consumer (the program team) trusts the producer
   (`flow-metrics`); git is the integrity layer for stored JSONs.

The replacement collapses the three skills into one with a `mode`
argument. The supporting flow-metrics tool is unchanged.

## What was cut, not just refactored

- The integrity-envelope abstraction (SHA-derived snapshot IDs across
  skill boundaries) — replaced by passing `flow-metrics`'s own config
  SHAs through to the report's provenance block.
- Cross-skill schema-version negotiation — single repo, single schema,
  notes-only on mixed-major inputs.
- The adversarial flag system (five flags with explain-mode row
  shapes) — the report emits raw deltas; reviewers form their own
  judgment.
- Hand-coded JSON Schema validators — the report trusts `flow-metrics`
  as the producer and validates only the meta fields it actually
  consumes.
- Path-expansion ceremony (tilde, env-var, recursive glob) — paths
  are literal; `--inputs DIR` globs `*.json` directly.
- The immutability ceremony around baselines (PID-liveness checks,
  three overwrite flags) — a baseline is a flow-metrics JSON in a
  git-tracked directory.

## When to consult the archive

- To recover a specific behaviour that the new spec deliberately
  omits.
- To understand prior review history (each archived spec carries its
  own multi-round review record).
- To audit the reframe itself.

These files are retained for traceability and should not be referenced
from new work. New work targets `ai-adoption-report.md`.
