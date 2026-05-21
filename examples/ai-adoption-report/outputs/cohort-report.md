# AI-adoption report — cohort

**Mode:** cohort
**Generated at:** 2026-01-15T09:00:00Z
**Inputs:** 1 file(s) — see §Provenance.
**Window:** 2025-10-01..2025-12-31 | **Scope:** kind=project+team;project=CHECKOUT;team=Foo;program_id=;portfolio_id= | **Cohort JQL:** labels = ai-assisted

## Summary

cohort vs control: throughput down 22.2%, cycle time p50 down 28.9%, rework rate up 61.5%.

## Metric deltas

| Metric | control | cohort | Δ abs | Δ % |
|---|---|---|---|---|
| throughput | 54 | 42 | −12 | −22.2% |
| wip | 8 | 6 | −2 | −25.0% |
| flow_load | 3.1 | 2.3 | −0.8 | −25.8% |
| cycle_time_hours p50 | 38 | 27 | −11 | −28.9% |
| cycle_time_hours p75 | 62 | 43 | −19 | −30.6% |
| cycle_time_hours p90 | 104 | 72 | −32 | −30.8% |
| lead_time_hours p50 | 102 | 80 | −22 | −21.6% |
| lead_time_hours p75 | 172 | 132 | −40 | −23.3% |
| lead_time_hours p90 | 300 | 240 | −60 | −20.0% |
| flow_time_hours p50 | 76 | 58 | −18 | −23.7% |
| flow_time_hours p75 | 128 | 92 | −36 | −28.1% |
| flow_time_hours p90 | 222 | 168 | −54 | −24.3% |
| flow_efficiency p50 | 0.42 | 0.52 | 0.1 | +23.8% |
| flow_efficiency p75 | 0.54 | 0.64 | 0.1 | +18.5% |
| flow_efficiency p90 | 0.68 | 0.76 | 0.08 | +11.8% |
| rework_rate | 0.13 | 0.21 | 0.08 | +61.5% |
| defect_ratio | 0.19 | 0.17 | −0.02 | −10.5% |
| flow_distribution.feature | 0.54 | 0.63 | 0.09 | +16.7% |
| flow_distribution.defect | 0.19 | 0.17 | −0.02 | −10.5% |
| flow_distribution.debt | 0.14 | 0.1 | −0.04 | −28.6% |
| flow_distribution.risk | 0.05 | 0.03 | −0.02 | −40.0% |
| flow_distribution.subtask | 0 | 0 | 0 | — |
| flow_distribution.other | 0.08 | 0.07 | −0.01 | −12.5% |

## Notes

- flow_distribution.subtask zero on both sides; percent delta undefined
- n-differs: cycle_time_hours n=54 in control, n=42 in cohort (>10% delta)
- n-differs: flow_distribution n=59 in control, n=47 in cohort (>10% delta)
- n-differs: flow_efficiency n=54 in control, n=42 in cohort (>10% delta)
- n-differs: flow_time_hours n=54 in control, n=42 in cohort (>10% delta)
- n-differs: lead_time_hours n=54 in control, n=42 in cohort (>10% delta)

## Provenance

- CHECKOUT-Foo-2025Q4-with-cohort.json — project=CHECKOUT team=Foo — 2025-10-01..2025-12-31 — sha state=a3f9b2c1d4e5670089abcdef0123456789abcdef0123456789abcdef01234567 issuetype=b4e8c3d2a5f6710089abcdef0123456789abcdef0123456789abcdef01234568 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
