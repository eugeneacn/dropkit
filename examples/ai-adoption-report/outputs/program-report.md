# AI-adoption report — program

**Mode:** program
**Generated at:** 2026-01-15T09:00:00Z
**Inputs:** 4 file(s) — see §Provenance.
**Window:** 2025-10-01..2025-12-31 | **Scopes:** 4 (project=4, program=0, portfolio=0)

## Summary

Program rollup across 4 scope(s); see per-scope rows and program aggregates below.

## Per-scope rows

| Scope | throughput | wip | flow_load | cycle_p50 | lead_p50 | flow_time_p50 | flow_eff_p50 | rework_rate | defect_ratio | fd.feature | fd.defect | fd.debt | fd.risk | fd.subtask | fd.other |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| project=BILLING | 52 | 7 | 3 | 38 | — | — | — | 0.09 | 0.27 | 0.44 | 0.27 | 0.18 | 0.04 | 0 | 0.07 |
| project=CHECKOUT | 96 | 14 | 5.4 | 33 | — | — | — | 0.17 | 0.18 | 0.58 | 0.18 | 0.12 | 0.04 | 0 | 0.08 |
| project=RISK | 41 | 11 | 4.8 | 58 | — | — | — | 0.24 | 0.31 | 0.39 | 0.31 | 0.19 | 0.04 | 0 | 0.07 |
| project=SEARCH | 64 | 9 | 3.6 | 46 | — | — | — | 0.11 | 0.14 | 0.62 | 0.14 | 0.16 | 0.02 | 0 | 0.06 |
| Aggregate | 253 | 41 | 16.8 | 42 | — | — | — | 0.1497 | 0.2105 | 0.529 | 0.2105 | 0.1543 | 0.035 | 0 | 0.0712 |

## Notes

- median-of-medians-approximation: distribution aggregates (cycle_time/lead_time/flow_time/flow_efficiency) computed as median-of-medians across scopes; see per-scope rows for distribution detail

## Provenance

- BILLING-2025Q4.json — project=BILLING — 2025-10-01..2025-12-31 — sha state=a3f9b2c1d4e5670089abcdef0123456789abcdef0123456789abcdef01234567 issuetype=b4e8c3d2a5f6710089abcdef0123456789abcdef0123456789abcdef01234568 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
- CHECKOUT-2025Q4.json — project=CHECKOUT — 2025-10-01..2025-12-31 — sha state=a3f9b2c1d4e5670089abcdef0123456789abcdef0123456789abcdef01234567 issuetype=b4e8c3d2a5f6710089abcdef0123456789abcdef0123456789abcdef01234568 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
- RISK-2025Q4.json — project=RISK — 2025-10-01..2025-12-31 — sha state=a3f9b2c1d4e5670089abcdef0123456789abcdef0123456789abcdef01234567 issuetype=b4e8c3d2a5f6710089abcdef0123456789abcdef0123456789abcdef01234568 — generated 2026-01-04T08:00:00Z — upstream schema 1.0
- SEARCH-2025Q4.json — project=SEARCH — 2025-10-01..2025-12-31 — sha state=a3f9b2c1d4e5670089abcdef0123456789abcdef0123456789abcdef01234567 issuetype=b4e8c3d2a5f6710089abcdef0123456789abcdef0123456789abcdef01234568 — generated 2026-01-03T08:00:00Z — upstream schema 1.0
