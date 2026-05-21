# AI-adoption report — program

**Mode:** program
**Generated at:** 2026-05-19T14:30:00Z
**Inputs:** 3 file(s) — see §Provenance.
**Window:** 2025-10-01..2025-12-31 | **Scopes:** 3 (project=3, program=0, portfolio=0)

## Summary

Program rollup across 3 scope(s); see per-scope rows and program aggregates below.

## Per-scope rows

| Scope | throughput | wip | flow_load | cycle_p50 | lead_p50 | flow_time_p50 | flow_eff_p50 | rework_rate | defect_ratio | fd.feature | fd.defect | fd.debt | fd.risk | fd.subtask | fd.other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| project=ALPHA | 50 | 8 | 3 | 32 | — | — | — | 0.12 | 0.15 | 0.6 | 0.15 | 0.1 | 0.05 | 0 | 0.1 |
| project=BETA | 64 | 11 | 4 | 28 | — | — | — | 0.1 | 0.12 | 0.65 | 0.12 | 0.1 | 0.03 | 0 | 0.1 |
| project=GAMMA | 38 | 6 | 2.5 | 41 | — | — | — | 0.18 | 0.22 | 0.5 | 0.22 | 0.15 | 0.03 | 0 | 0.1 |
| Aggregate | 152 | 25 | 9.5 | 32 | — | — | — | 0.1266 | 0.1544 | 0.5967 | 0.1544 | 0.1122 | 0.0367 | 0 | 0.1 |

## Notes

- median-of-medians-approximation: distribution aggregates (cycle_time/lead_time/flow_time/flow_efficiency) computed as median-of-medians across scopes; see per-scope rows for distribution detail

## Provenance

- PROJ-Alpha.json — project=ALPHA — 2025-10-01..2025-12-31 — sha state=1111111111111111111111111111111111111111111111111111111111111111 issuetype=2222222222222222222222222222222222222222222222222222222222222222 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
- PROJ-Beta.json — project=BETA — 2025-10-01..2025-12-31 — sha state=1111111111111111111111111111111111111111111111111111111111111111 issuetype=2222222222222222222222222222222222222222222222222222222222222222 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
- PROJ-Gamma.json — project=GAMMA — 2025-10-01..2025-12-31 — sha state=1111111111111111111111111111111111111111111111111111111111111111 issuetype=2222222222222222222222222222222222222222222222222222222222222222 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
