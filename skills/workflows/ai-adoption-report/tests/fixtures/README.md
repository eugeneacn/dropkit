# ai-adoption-report test fixtures

Small, hand-curated `flow-metrics` JSON files used across the test
suite. Each fixture exists to exercise one specific spec rule.

## Subdirectories

### `inputs/`

Single-file flow-metrics outputs consumed by `test_t2_inputs.py`,
`test_t3_modes.py`, `test_t4_program_discovery.py`, and
`test_t8_write.py`. One file per scope kind (and per shape variant):

| File | Used by | Exercises |
|---|---|---|
| `baseline_q1_alpha.json` | T3, T8 | baseline-mode A side (project=ALPHA, 2026-Q1). |
| `current_q2_alpha.json` | T3, T8 | baseline-mode B side; pairs with `baseline_q1_alpha.json`. |
| `current_q2_beta.json` | T3 | baseline-mode scope-mismatch case (project=BETA vs ALPHA). |
| `current_back_to_back_alpha.json` | T3 | baseline-mode back-to-back-windows allowance. |
| `project_basic.json` | T2, T4 | minimal `kind=project` scope. |
| `project_team.json` | T2, T3, T4 | `kind=project+team` scope. |
| `project_with_cohort.json` | T3 | scope+cohort_breakdown shape used by cohort mode. |
| `program.json` | T2, T3, T4 | `kind=program` with non-empty `per_team` — program-mode per-team flattening. |
| `portfolio.json` | T2, T3, T4 | `kind=portfolio` scope. |
| `schema_v2.json` | T2 | `schema_version: "2.0"` for the mixed-major notes test. |

### `render/`

In-Python fixture builders for T7 / T8 render+write tests. Holds a
small `Python` module that builds `ReportData` objects directly so the
render tests don't have to round-trip through file I/O. The
`__init__.py` files in `tests/fixtures/` and `tests/fixtures/render/`
exist solely to make `from fixtures.render import ...` valid.

The T4 (`test_t4_program_discovery.py`) and T6
(`test_t6_aggregation.py`) tests build their per-scenario input sets
in-memory via `tmp_path` rather than checking in disk fixtures; this
is intentional — those scenarios are too numerous to maintain as
checked-in JSON, and the in-memory builders keep the test data
co-located with the assertions.

### `golden/`

Byte-fixed expected outputs for the three modes. The T9 golden-diff
tests re-run the CLI with
`AI_ADOPTION_REPORT_GENERATED_AT=2026-05-19T14:30:00Z` and `LC_ALL=C`
against the inputs below and assert byte-for-byte match.

| Path | What it pins |
|---|---|
| `golden/baseline/inputs/PROJ-Foo-2024Q1.json` + `PROJ-Foo-2025Q4.json` | baseline-mode input pair. |
| `golden/baseline/expected.md` + `expected.json` | the report the CLI must produce. |
| `golden/cohort/input.json` | cohort-mode input (carries `cohort_breakdown`). |
| `golden/cohort/expected.md` + `expected.json` | the report the CLI must produce. |
| `golden/program/inputs/PROJ-Alpha.json` + `PROJ-Beta.json` + `PROJ-Gamma.json` | program-mode input set (three projects, same window). |
| `golden/program/expected.md` + `expected.json` | the report the CLI must produce. |

To regenerate a golden file after a deliberate output-shape change,
re-run the CLI manually with the same env vars and inspect the diff
before committing. Do NOT regenerate as a side effect of running the
tests — the test asserts byte-identity against the checked-in bytes.
