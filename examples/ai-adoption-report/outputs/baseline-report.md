# AI-adoption report — baseline

**Mode:** baseline
**Generated at:** 2026-01-15T09:00:00Z
**Inputs:** 2 file(s) — see §Provenance.
**Baseline window:** 2024-01-01..2024-03-31 | **Current window:** 2025-10-01..2025-12-31 | **Scope:** kind=project+team;project=CHECKOUT;team=Foo;program_id=;portfolio_id=

## Summary

throughput up 23.1%, cycle time p50 down 21.4%, rework rate up 21.4%.

## Metric deltas

| Metric | baseline | current | Δ abs | Δ % |
|---|---|---|---|---|
| throughput | 78 | 96 | 18 | +23.1% |
| wip | 12 | 14 | 2 | +16.7% |
| flow_load | 4.8 | 5.4 | 0.6 | +12.5% |
| cycle_time_hours p50 | 42 | 33 | −9 | −21.4% |
| cycle_time_hours p75 | 68.5 | 54 | −14.5 | −21.2% |
| cycle_time_hours p90 | 112 | 91 | −21 | −18.8% |
| lead_time_hours p50 | 120 | 92 | −28 | −23.3% |
| lead_time_hours p75 | 192 | 156 | −36 | −18.8% |
| lead_time_hours p90 | 336 | 276 | −60 | −17.9% |
| flow_time_hours p50 | 86 | 68 | −18 | −20.9% |
| flow_time_hours p75 | 140 | 112 | −28 | −20.0% |
| flow_time_hours p90 | 240 | 198 | −42 | −17.5% |
| flow_efficiency p50 | 0.38 | 0.46 | 0.08 | +21.1% |
| flow_efficiency p75 | 0.52 | 0.58 | 0.06 | +11.5% |
| flow_efficiency p90 | 0.66 | 0.71 | 0.05 | +7.6% |
| rework_rate | 0.14 | 0.17 | 0.03 | +21.4% |
| defect_ratio | 0.21 | 0.18 | −0.03 | −14.3% |
| flow_distribution.feature | 0.52 | 0.58 | 0.06 | +11.5% |
| flow_distribution.defect | 0.21 | 0.18 | −0.03 | −14.3% |
| flow_distribution.debt | 0.14 | 0.12 | −0.02 | −14.3% |
| flow_distribution.risk | 0.05 | 0.04 | −0.01 | −20.0% |
| flow_distribution.subtask | 0 | 0 | 0 | — |
| flow_distribution.other | 0.08 | 0.08 | 0 | +0.0% |

## Notes

- flow_distribution.subtask zero on both sides; percent delta undefined
- n-differs: cycle_time_hours n=78 in baseline, n=96 in current (>10% delta)
- n-differs: flow_distribution n=86 in baseline, n=106 in current (>10% delta)
- n-differs: flow_efficiency n=78 in baseline, n=96 in current (>10% delta)
- n-differs: flow_time_hours n=78 in baseline, n=96 in current (>10% delta)
- n-differs: lead_time_hours n=78 in baseline, n=96 in current (>10% delta)

## Provenance

- CHECKOUT-Foo-2024Q1.json — project=CHECKOUT team=Foo — 2024-01-01..2024-03-31 — sha state=a3f9b2c1d4e5670089abcdef0123456789abcdef0123456789abcdef01234567 issuetype=b4e8c3d2a5f6710089abcdef0123456789abcdef0123456789abcdef01234568 — generated 2024-04-02T08:00:00Z — upstream schema 1.0
- CHECKOUT-Foo-2025Q4.json — project=CHECKOUT team=Foo — 2025-10-01..2025-12-31 — sha state=a3f9b2c1d4e5670089abcdef0123456789abcdef0123456789abcdef01234567 issuetype=b4e8c3d2a5f6710089abcdef0123456789abcdef0123456789abcdef01234568 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
