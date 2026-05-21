# AI-adoption report — cohort

**Mode:** cohort
**Generated at:** 2026-05-19T14:30:00Z
**Inputs:** 1 file(s) — see §Provenance.
**Window:** 2025-10-01..2025-12-31 | **Scope:** kind=project+team;project=PROJ;team=Foo;program_id=;portfolio_id= | **Cohort JQL:** labels = ai-assisted

## Summary

cohort vs control: throughput down 58.3%, cycle time p50 down 23.5%, rework rate down 33.3%.

## Metric deltas

| Metric | control | cohort | Δ abs | Δ % |
|---|---|---|---|---|
| throughput | 72 | 30 | −42 | −58.3% |
| wip | 11 | 5 | −6 | −54.5% |
| flow_load | 4.4 | 1.8 | −2.6 | −59.1% |
| cycle_time_hours p50 | 34 | 26 | −8 | −23.5% |
| cycle_time_hours p75 | 55 | 41 | −14 | −25.5% |
| cycle_time_hours p90 | 90 | 70 | −20 | −22.2% |
| rework_rate | 0.18 | 0.12 | −0.06 | −33.3% |
| defect_ratio | 0.17 | 0.13 | −0.04 | −23.5% |

## Notes

- n-differs: cycle_time_hours n=72 in control, n=30 in cohort (>10% delta)

## Provenance

- input.json — project=PROJ team=Foo — 2025-10-01..2025-12-31 — sha state=1111111111111111111111111111111111111111111111111111111111111111 issuetype=2222222222222222222222222222222222222222222222222222222222222222 — generated 2026-01-02T08:00:00Z — upstream schema 1.0
