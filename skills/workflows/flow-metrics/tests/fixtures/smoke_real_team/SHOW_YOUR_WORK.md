# Hand-computed reference values for `smoke_real_team`

This file derives every entry in `reference_values.json` step-by-step
from the issue list, so a reviewer can verify the smoke gate's ground
truth without re-running the implementation.

## Per-issue derived values

| Key       | Type  | Delivered | Cycle (h) | Lead (h) | Rework | Cancelled | WIP@to |
|-----------|-------|-----------|-----------|----------|--------|-----------|--------|
| PROJ-001  | Story | yes       | 12        | 24       | 0      | no        | no     |
| PROJ-002  | Story | yes       | 18        | 30       | 0      | no        | no     |
| PROJ-003  | Bug   | yes       | 24        | 36       | 0      | no        | no     |
| PROJ-004  | Story | yes       | 36        | 48       | 0      | no        | no     |
| PROJ-005  | Bug   | yes       | 48        | 60       | 0      | no        | no     |
| PROJ-006  | Story | yes       | 60        | 72       | 0      | no        | no     |
| PROJ-007  | Story | yes       | 72        | 84       | 0      | no        | no     |
| PROJ-008  | Bug   | yes       | 96        | 108      | 0      | no        | no     |
| PROJ-009  | Story | yes       | 120       | 132      | 0      | no        | no     |
| PROJ-010  | Story | yes       | 144       | 156      | 0      | no        | no     |
| PROJ-011  | Story | yes       | 48        | 60       | 1      | no        | no     |
| PROJ-012  | Bug   | yes       | —         | 24       | 0      | no        | no     |
| PROJ-013  | Story | no        | —         | —        | 0      | yes       | no     |
| PROJ-014  | Story | no        | —         | —        | 0      | no        | yes    |

Cycle-eligible delivered issues (have a first-commit transition):
PROJ-001 … PROJ-011 (11 issues). PROJ-012 is delivered but skipped
commitment, so excluded from `cycle_time` per spec.

## Throughput

Spec definition: count of delivered-in-window non-subtask issues
(default `--include-subtasks=false`).

Delivered & non-subtask: PROJ-001 … PROJ-012 = **12**.

## Cycle time (hours)

Population: cycle-eligible delivered non-subtask. Eleven values:

    [12, 18, 24, 36, 48, 48, 60, 72, 96, 120, 144]   (sorted ascending)

`statistics.quantiles(data, n=100, method="exclusive")` returns 99 cut
points; we read indices 49 / 74 / 89 for p50 / p75 / p90.

For sorted data of length **N=11**, with `m = N + 1 = 12`:

- p50 (i=50): `j = 50*12 // 100 = 6`, `delta = 50*12 − 6*100 = 0`,
  `interpolated = data[j−1]*(100−delta)/100 + data[j]*delta/100 = data[5] = 48`
- p75 (i=75): `j = 75*12 // 100 = 9`, `delta = 75*12 − 9*100 = 0`,
  `interpolated = data[8] = 96`
- p90 (i=90): `j = 90*12 // 100 = 10`, `delta = 90*12 − 10*100 = 80`,
  `interpolated = data[9]*20/100 + data[10]*80/100 = 120*0.2 + 144*0.8 = 24 + 115.2 = 139.2`

**cycle_time = { p50: 48, p75: 96, p90: 139.2 }**

## Lead time (hours)

Population: all delivered-in-window non-subtask. Twelve values:

    PROJ-001..010: cycle + 12 → [24, 30, 36, 48, 60, 72, 84, 108, 132, 156]
    PROJ-011: 60
    PROJ-012: 24

Sorted ascending:

    [24, 24, 30, 36, 48, 60, 60, 72, 84, 108, 132, 156]   (N=12, m=13)

- p50 (i=50): `j = 50*13 // 100 = 6`, `delta = 650 − 600 = 50`,
  `interpolated = data[5]*0.5 + data[6]*0.5 = (60 + 60)/2 = 60`
- p75 (i=75): `j = 75*13 // 100 = 9`, `delta = 975 − 900 = 75`,
  `interpolated = data[8]*0.25 + data[9]*0.75 = 84*0.25 + 108*0.75 = 21 + 81 = 102`
- p90 (i=90): `j = 90*13 // 100 = 11`, `delta = 1170 − 1100 = 70`,
  `interpolated = data[10]*0.30 + data[11]*0.70 = 132*0.3 + 156*0.7 = 39.6 + 109.2 = 148.8`

**lead_time = { p50: 60, p75: 102, p90: 148.8 }**

## Rework rate

`rework_rate = sum(row.rework_count for delivered) / throughput`.

Only PROJ-011 has a rework edge before delivery
(`In Progress → Backlog` at 2026-02-16T00:00:00Z, which precedes
delivery at 2026-02-17T12:00:00Z and matches the default state
config's rework signal `from in_progress to backlog`).

Numerator = 1; throughput = 12. **rework_rate = 1/12 ≈ 0.0833**.

## Flow distribution + defect_ratio

Buckets among the 12 delivered-in-window issues:

- `feature` (Story → feature per issuetype.default.json):
  PROJ-001, 002, 004, 006, 007, 009, 010, 011 = **8**
- `defect` (Bug → defect): PROJ-003, 005, 008, 012 = **4**
- Other buckets: **0**

Denominator = 12. `defect_ratio = 4/12 ≈ 0.3333`.

## Cancelled count

PROJ-013 transitions to Cancelled at 2026-02-23T00:00:00Z, in-window.
**cancelled_count = 1**.

## WIP at --to and Flow Load

WIP at `--to` (anchor: `2026-02-29T00:00:00Z − 1µs`):

- PROJ-014 is in `In Progress` (canonical: in_progress, in
  `active_states`) at that anchor — **WIP = 1**.

Flow Load: sum of per-day WIP samples / sample count (28 days).

- PROJ-014 contributes a `True` sample on every one of the 28 days
  (entered IP on 2026-01-20, still IP at every day-end anchor through
  2026-02-28) → **28 contributions**.
- PROJ-013 contributes a `True` on 2026-02-22 only (anchored at
  2026-02-22T23:59:59.999999Z; IP from 2026-02-22T12:00 until
  2026-02-23T00:00, so the 02-22 anchor lands inside the IP span)
  → **1 contribution**.
- Every other issue is either delivered (samples forced to all False)
  or created after the start of the window and not in an active state
  at any day-end anchor outside the patterns above — **0 contributions**.

Total per-day-wip sum = 28 + 1 = 29. Flow Load = 29/28 ≈ **1.0357**.

## What we do NOT pin in `reference_values.json`

`flow_efficiency` percentiles, `flow_time` (alias of `lead_time`), and
the full per-bucket `flow_distribution` are computed by the same code
paths as the cycle / lead / throughput numbers above; locking them in
the smoke test would replicate unit-test coverage without adding
signal. The smoke test pins the six metrics named in the brief
(cycle_time p50/p75/p90, lead_time p50, throughput, rework_rate,
cancelled_count) plus `defect_ratio` for symmetry with the unit suite.
