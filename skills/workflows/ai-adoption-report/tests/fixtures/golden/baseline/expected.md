# AI-adoption report — baseline

**Mode:** baseline
**Generated at:** 2026-05-19T14:30:00Z
**Inputs:** 2 file(s) — see §Provenance.
**Baseline window:** 2024-01-01..2024-03-31 | **Current window:** 2025-10-01..2025-12-31 | **Scope:** kind=project+team;project=PROJ;team=Foo;program_id=;portfolio_id=

## Summary

throughput up 21.4%, cycle time p50 down 17.5%, rework rate up 33.3%.

## Metric deltas

| Metric | baseline | current | Δ abs | Δ % |
|---|---|---|---|---|
| throughput | 84 | 102 | 18 | +21.4% |
| wip | 14 | 16 | 2 | +14.3% |
| flow_load | 5.5 | 6.2 | 0.7 | +12.7% |
| cycle_time_hours p50 | 38.2 | 31.5 | −6.7 | −17.5% |
| cycle_time_hours p75 | 62 | 50 | −12 | −19.4% |
| cycle_time_hours p90 | 96.4 | 84 | −12.4 | −12.9% |
| lead_time_hours p50 | 96 | 78 | −18 | −18.8% |
| lead_time_hours p75 | 168 | 140 | −28 | −16.7% |
| lead_time_hours p90 | 312 | 264 | −48 | −15.4% |
| flow_efficiency p50 | 0.42 | 0.48 | 0.06 | +14.3% |
| flow_efficiency p75 | 0.58 | 0.62 | 0.04 | +6.9% |
| flow_efficiency p90 | 0.71 | 0.74 | 0.03 | +4.2% |
| rework_rate | 0.12 | 0.16 | 0.04 | +33.3% |
| defect_ratio | 0.18 | 0.16 | −0.02 | −11.1% |
| flow_distribution.feature | 0.55 | 0.6 | 0.05 | +9.1% |
| flow_distribution.defect | 0.18 | 0.16 | −0.02 | −11.1% |
| flow_distribution.debt | 0.12 | 0.1 | −0.02 | −16.7% |
| flow_distribution.risk | 0.05 | 0.04 | −0.01 | −20.0% |
| flow_distribution.subtask | 0 | 0 | 0 | — |
| flow_distribution.other | 0.1 | 0.1 | 0 | +0.0% |

## Notes

- flow_distribution.subtask zero on both sides; percent delta undefined
- n-differs: cycle_time_hours n=84 in baseline, n=102 in current (>10% delta)
- n-differs: flow_distribution n=92 in baseline, n=114 in current (>10% delta)
- n-differs: flow_efficiency n=84 in baseline, n=102 in current (>10% delta)
- n-differs: lead_time_hours n=84 in baseline, n=102 in current (>10% delta)

## Provenance

- PROJ-Foo-2024Q1.json — project=PROJ team=Foo — 2024-01-01..2024-03-31 — sha state=1111111111111111111111111111111111111111111111111111111111111111 issuetype=2222222222222222222222222222222222222222222222222222222222222222 — generated 2024-04-02T08:00:00Z — upstream schema 1.0
- PROJ-Foo-2025Q4.json — project=PROJ team=Foo — 2025-10-01..2025-12-31 — sha state=1111111111111111111111111111111111111111111111111111111111111111 issuetype=2222222222222222222222222222222222222222222222222222222222222222 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
