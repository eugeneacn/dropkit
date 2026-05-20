# Spec: ai-adoption-report

- **Status:** Approved
- **Owner:** eugeneacn
- **Plan:** [`ai-adoption-report-plan.md`](ai-adoption-report-plan.md) (Approved, terminal-clean)
- **Constrained by:** [`flow-metrics.md`](flow-metrics.md) (Approved, terminal-clean)
- **Supersedes:** `ai-adoption-baseline.md`, `ai-adoption-cohort.md`, `ai-value-report.md` (all archived 2026-05-19; see [`archive/README.md`](archive/README.md))
- **Review history:** 5 adversarial review rounds (2026-05-19). Round 1: 1 blocker / 4 majors / 4 minors / 2 test gaps; round 2: 1 blocker / 2 majors / 1 minor / 1 test gap; round 3: 1 blocker / 1 major / 1 minor (invalid); round 4: 0 blockers / 0 majors / 2 minors; round 5: terminal-clean.

> **Spec contract:** this document defines what "done" means for the
> `ai-adoption-report` workflow skill. The implementing PR must match
> this spec or update it. Tests must be derivable from it.

## What this is

A read-only workflow skill that consumes one or more `flow-metrics`
JSON outputs and produces a comparison report. It has **three modes**,
all of which share one pairing-and-delta engine:

- **`baseline`** — compare a single scope across two windows
  (pre-AI vs current). Two `flow-metrics` JSONs in, deltas out.
- **`cohort`** — surface the within-window AI-cohort vs control split
  that `flow-metrics` already computed via `--cohort-jql`. One JSON
  in, deltas out.
- **`program`** — roll up many scopes for a single window. N JSONs in,
  per-scope rows + aggregates out.

The skill makes no upstream calls. It reads only `flow-metrics` JSON
files. It writes a Markdown report and an optional JSON sidecar.

## Why

`flow-metrics` produces consistent per-scope measurements. Many teams
across a program run it. Someone has to pair, subtract, and tabulate.
Doing that by hand or in ad-hoc notebooks breaks comparability across
teams and over time. One skill, three modes, one schema for the
program lead to consume.

The skill exists to be **boring**: pair files, subtract numbers,
render a table. It encodes no judgment about what the deltas mean. It
emits no flags. Interpretation belongs to the reader.

## Users and use cases

In priority order:

1. **Team lead, baseline mode.** "How are our flow metrics now vs.
   pre-AI?"
   `ai-adoption-report baseline --baseline outputs/PROJ-Foo-2024Q1.json
   --current outputs/PROJ-Foo-2025Q4.json --output report.md`.

2. **Team lead, cohort mode.** "Within Q4, did AI-tagged tickets behave
   differently from untagged?"
   `ai-adoption-report cohort --input outputs/PROJ-Foo-2025Q4-with-cohort.json
   --output report.md`. The input must be a `flow-metrics` run that
   was invoked with `--cohort-jql`; the skill reads the existing
   `cohort_breakdown` block.

3. **Program lead, program mode.** "What does Q4 look like across all
   teams in the program?"
   `ai-adoption-report program --inputs outputs/ --window 2025-10-01..2025-12-31
   --output q4-program.md`. Skill globs `*.json` in the input directory,
   filters to those whose `meta.window` matches, aggregates.

## Behavior

### Inputs

```
ai-adoption-report MODE [mode-specific flags] --output FILE [common flags]
```

Modes:

| Mode | Required flags | Optional |
|---|---|---|
| `baseline` | `--baseline PATH` `--current PATH` | `--include-cohort-breakdown` |
| `cohort` | `--input PATH` | — |
| `program` | `--inputs DIR` `--window FROM..TO` | `--include-cohort-breakdown` |

Common flags:

| Flag | Meaning |
|---|---|
| `--output FILE` | Path to Markdown output. JSON sidecar written to the same path with `.md` → `.json` (or `+ .json` if no extension). |
| `--format markdown\|json\|both` | Default `both`. `json` skips Markdown rendering. |
| `--overwrite` | Replace existing output files. Without it, exit 2 on collision. With `both`, the rule applies to both files. |
| `--title TITLE` | Optional title for the Markdown header. Default: `"AI-adoption report — <mode>"`. |
| `--verbose` | Debug logging. |

Path rules:

- All input paths are taken literally. No tilde expansion, no env-var
  expansion, no globbing (except `--inputs DIR` for program mode,
  which globs `*.json` directly in `DIR` — no recursion).
- All paths must be inside the current working directory or its
  descendants. Absolute paths outside CWD exit 2 (same path-safety
  rule as `flow-metrics`).

### Input file validation

Each input file MUST be valid JSON and MUST contain `meta` with at
least: `scope`, `window`, `state_config_sha`, `issuetype_config_sha`,
`schema_version`, `generated_at`. Missing any of these → exit 2 with
a clear error naming the file and the missing field.

The skill does NOT validate the rest of the `flow-metrics` schema. It
trusts `flow-metrics` as the producer. If a downstream metric is
missing from `aggregates` when the report needs it (e.g. computing a
`rework_rate` delta but `rework_rate` is absent because the upstream
run was invoked with `--metrics throughput`), the cell renders as `—`
and a `notes` entry records `"<metric> absent in <file>; cell omitted"`.

`schema_version` is parsed as `"<major>.<minor>"` (two integer parts
separated by `.`). The skill emits a `notes` entry
`"mixed-major-schema-versions: <list of distinct majors and their
input basenames>"` when input files in the same run disagree on the
major component. Mixed minors are silently allowed. Inputs that
cannot be parsed as `<int>.<int>` exit 2 naming the file.

**Window format.** `meta.window.from` and `meta.window.to` MUST be
date strings in `YYYY-MM-DD` form (no time component, no timezone).
This matches the documented `flow-metrics` output shape. Inputs that
fail this format exit 2. `--window FROM..TO` is also parsed as two
`YYYY-MM-DD` dates separated by `..`; the program-mode window filter
compares the two date strings with `==`. Future format changes in
`flow-metrics` (e.g. adding time precision) require a coordinated
spec update.

**Scope shape and `kind` inference.** `flow-metrics` emits `meta.scope`
as a dict with a subset of keys from `{project, team, program_id,
portfolio_id}`. The report infers `kind` from key presence (NOT from
an explicit `meta.scope.kind` field, which `flow-metrics` does not
emit):

- `portfolio_id` present → `kind = portfolio`.
- `program_id` present, no `portfolio_id` → `kind = program`.
- `project` present, no `program_id` and no `portfolio_id`:
  - with `team` → `kind = project+team`.
  - without `team` → `kind = project`.
- Any other key combination (e.g. only `team` without `project`) →
  exit 2 with `"unrecognised scope shape in <file>: <scope dict>"`.

Inferred `kind` is used internally only (overlap detection, canonical
sort key). It is also surfaced in the JSON sidecar's
`meta.inputs[].scope_kind` for downstream consumers.

### Mode: baseline

Compares two `flow-metrics` outputs for the same scope, different
windows.

**Pairing rule.** The skill requires `baseline.meta.scope` ==
`current.meta.scope` (exact dict equality — same set of keys, same
values). Mismatched scope → exit 2 with both scopes printed.

**Window rule.** `baseline.meta.window.to` MUST be <=
`current.meta.window.from`. Overlapping windows → exit 2 with both
windows printed. Equal endpoints (back-to-back windows) are allowed.

**Config-SHA rule.** If `state_config_sha` or `issuetype_config_sha`
differ between baseline and current, emit a `notes` entry
`"config-sha-drift: state_config_sha <a> → <b>"` (similarly for
issuetype). Deltas are still computed; the user is warned that
definitions changed.

**With `--include-cohort-breakdown`:** if both inputs contain a
`cohort_breakdown` block AND both have matching `meta.cohort_jql`
(string equality), the Markdown report appends a section comparing
cohort-vs-control deltas across the two windows. If either input
lacks `cohort_breakdown`, the flag no-ops silently with a `notes`
entry. If both have `cohort_breakdown` but `meta.cohort_jql` differs,
the section is omitted and a `notes` entry records
`"cohort-jql-mismatch: <baseline-jql> vs <current-jql>; cohort
breakdown comparison omitted"`.

**`per_team` in baseline mode.** Baseline mode is a single-scope
comparison; `per_team` arrays (emitted by `flow-metrics` for
program/portfolio scope) are ignored — the comparison runs against
`aggregates` only. A `notes` entry records `"per_team data present in
<file>; ignored in baseline mode (use program mode for multi-team
rollup)"` when either input has a non-empty `per_team`.

### Mode: cohort

Reports the within-window cohort vs control split that `flow-metrics`
already computed.

**Input rule.** The input file MUST contain `cohort_breakdown`.
Missing → exit 2 with `"--input was not produced with --cohort-jql; no
cohort_breakdown block present"`.

**No pairing.** The deltas come from the single file's
`cohort_breakdown.cohort` vs `cohort_breakdown.control`.

### Mode: program

Aggregates across scopes for a single window.

**Input discovery.** Glob `<DIR>/*.json`. Each file must validate
(per §"Input file validation"). Non-JSON or invalid files → exit 2
naming the offender.

**Window filter.** Only files whose `meta.window` exactly equals
`--window FROM..TO` (string equality on the ISO-formatted endpoints)
are included. Files outside the window are silently ignored. If zero
files match → exit 2 with `"no inputs matched --window FROM..TO in
DIR"`.

**Scope overlap.** If the matched set contains overlapping scopes
(see overlap rule below), exit 2 listing the overlapping scopes. The
user must run program mode on a non-overlapping set.

**Overlap rule.** Two scopes overlap iff one is a hierarchical
prefix of the other based on inferred `kind` (see §"Scope shape and
`kind` inference"):

- `portfolio` vs any other kind → overlap.
- `program` vs `project` or `project+team` → overlap.
- `project` (no team) vs `project+team` with the same `project` value
  → overlap. (Different `project` values → no overlap.)
- Two scopes of the same kind with identical scope dicts → exit 2
  with `"duplicate scope in input set: <scope dict> in <basename-a>
  and <basename-b>"` (this is a pre-overlap dedupe; do not silently
  collapse).
- All other same-kind combinations with different identifiers → no
  overlap.

The skill does NOT resolve Jira hierarchy. It uses only declared
`scope` fields.

**Per-team rollup pass-through.** If individual `flow-metrics` JSONs
contain a `per_team` array (because they were `--program-id` or
`--portfolio-id` runs against Jira Align), the program-mode aggregator
flattens those into the per-scope rows. A `per_team` entry becomes a
separate row in the per-scope table with `scope.team = <team name>`
synthesised from the entry and `kind` re-inferred (typically
`project+team`). Per-team flattened rows participate in the
non-cohort aggregation table. They are **excluded from the cohort
breakdown rollup** because `flow-metrics` v1 does not split `per_team`
rows by cohort (see flow-metrics.md §"Cohort behaviour"); a `notes`
entry with the literal form `"per_team-cohort-deferred: N flattened
per-team rows have no cohort_breakdown; excluded from cohort
rollup"` is emitted when `--include-cohort-breakdown` is set and any
per_team flattening occurred. When `meta.per_team_double_counted` is
true in any flattened input, a `notes` entry with the literal form
`"per_team-double-counted: <comma-separated input basenames whose
meta.per_team_double_counted is true, sorted codepoint-ascending>;
flattened per-team rows may double-count issues that span multiple
teams"` is emitted (one entry covering all such inputs).

**With `--include-cohort-breakdown`:** the aggregator rolls up the
cohort-vs-control split across scopes that have `cohort_breakdown`.
**The cohort side and the control side are aggregated independently
of each other.** For each side, the same per-metric aggregation rules
as the non-cohort table apply, using **that side's own denominators**
as weights — never mixing cohort and control numbers into a single
weighted average:

- Throughput: `sum(scope.cohort_breakdown.<side>.throughput)`.
- Distribution percentiles (`cycle_time_hours`, `lead_time_hours`,
  `flow_time_hours`, `flow_efficiency`): median-of-medians across
  scopes, computed separately for cohort and control.
- `rework_rate`: side-throughput-weighted average using each scope's
  `<side>` throughput as weight. Example for cohort:
  `sum(scope.cohort_breakdown.cohort.rework_rate[i] *
  scope.cohort_breakdown.cohort.throughput[i]) /
  sum(scope.cohort_breakdown.cohort.throughput[i])`. Symmetric for
  control. This is algebraically equivalent to
  `sum(cohort_rework_events[i]) / sum(cohort_throughput[i])` because
  `rework_rate[i] × throughput[i] = rework_events[i]` by definition
  (see flow-metrics.md §"Cohort breakdown denominator rule").
- `defect_ratio`: side-`flow_distribution.denominator`-weighted
  average, using each scope's
  `cohort_breakdown.<side>.flow_distribution.denominator` as weight.
  This mirrors the non-cohort defect_ratio rule and is required
  because `defect_ratio` uses the Flow Distribution denominator
  (which includes subtasks regardless of `--include-subtasks`); see
  flow-metrics.md §Decisions item 25. The side's
  `flow_distribution.denominator` is guaranteed to be cohort-restricted
  per flow-metrics.md §"Cohort breakdown denominator rule".
- `flow_distribution` per-bucket: side-denominator-weighted average
  (same rule as non-cohort flow_distribution, but using the side's
  `cohort_breakdown.<side>.flow_distribution.denominator`).

If a scope's `cohort_breakdown.<side>` is missing `flow_distribution`
(because the upstream run was invoked with `--metrics` excluding it),
that scope is dropped from the `defect_ratio` and `flow_distribution`
side-rollups only (other side-metrics still include it). A `notes`
entry records the exclusion with the literal form
`"cohort-flow_distribution-missing: side=<cohort|control> dropped N
of M scopes (basenames: a.json, b.json); defect_ratio and
flow_distribution rollups computed over the remaining M-N"` (one
entry per side; basenames sorted codepoint-ascending).

This independence is required because `flow-metrics` documents that
cohort + control do NOT weighted-average to the global value (see
flow-metrics.md §"Cohort breakdown denominator rule"). The report
never tries to derive a "global from cohort+control" — it presents
cohort and control side-by-side and lets the reader compare.

Scopes without `cohort_breakdown` are silently dropped from that
section with a `notes` entry `"cohort-breakdown-missing: N of M
scopes (basenames: ...); cohort rollup computed over the remaining
M-N"`. If the set of distinct `meta.cohort_jql` values across
contributing scopes has size > 1, an additional `notes` entry records
`"mixed-cohort-jql: <list of distinct JQLs and their input
basenames>; rollup proceeds but cohort definitions differ across
scopes"`. If zero scopes contribute, the cohort section is omitted
entirely and `notes` records `"cohort-breakdown-section-empty"`.

### Delta math

Applied uniformly across modes wherever two numbers are compared
(call them `A` = baseline / control / prior, `B` = current / cohort
/ comparand).

For each metric:

- **Absolute delta:** `B - A`.
- **Percent delta:** `(B - A) / A` rendered as a signed percentage
  with one decimal place (e.g. `+12.5%`, `-3.0%`).
- **Zero baseline:** if `A == 0` and `B == 0`, render percent as `—`
  with a `notes` entry `"<metric> zero on both sides; percent delta
  undefined"`. If `A == 0` and `B > 0`, render percent as `+∞%` (literal
  Unicode `∞`). If `A == 0` and `B < 0` (only possible for signed
  metrics, currently none), render as `−∞%`.
- **Both null:** if a metric is `null` (e.g. `flow_efficiency` for a
  window with no eligible issues) on either side, percent renders as
  `—`; absolute renders as `—`; a `notes` entry records
  `"<metric> null in <which-side> for <scope>"`.

Distribution metrics (`cycle_time_hours`, `lead_time_hours`,
`flow_time_hours`, `flow_efficiency`) compare per-percentile: `p50`
to `p50`, `p75` to `p75`, `p90` to `p90`. Each percentile becomes a
separate row in the Markdown table (e.g. `cycle_time_hours p50`,
`cycle_time_hours p75`, `cycle_time_hours p90`). The percentile
columns are independent — no overall "distribution delta." The `n`
field is reported but not subjected to delta math. A `notes` entry
records the per-side `n` values when they differ by more than 10%
(measured as `abs(n_a - n_b) / max(n_a, n_b) > 0.1`; zero on either
side always triggers the note). In cohort comparisons the rule
applies to the (cohort `n`, control `n`) pair per metric; in
baseline / program-mode aggregate comparisons it applies to the
(A-side `n`, B-side `n`) pair per metric.

Bucket metrics (`flow_distribution`) compare bucket-by-bucket. Each
bucket key becomes a row (e.g. `flow_distribution.feature`,
`flow_distribution.defect`). The `denominator` sub-field is reported
but not subjected to delta math (same `n`-style note rule).

**Metric row order.** The Markdown delta table emits rows in this
fixed canonical order (matching `flow-metrics` `--metrics`
documentation order): `throughput`, `wip`, `flow_load`,
`cycle_time_hours p50`, `cycle_time_hours p75`, `cycle_time_hours
p90`, `lead_time_hours p50`, `lead_time_hours p75`, `lead_time_hours
p90`, `flow_time_hours p50`, `flow_time_hours p75`, `flow_time_hours
p90`, `flow_efficiency p50`, `flow_efficiency p75`, `flow_efficiency
p90`, `rework_rate`, `defect_ratio`, `flow_distribution.feature`,
`flow_distribution.defect`, `flow_distribution.debt`,
`flow_distribution.risk`, `flow_distribution.subtask`,
`flow_distribution.other`. Metrics absent from both sides are
omitted entirely (no row). The JSON sidecar uses the same canonical
key order via the sort rules in §"JSON canonicalization".

### Aggregation math (program mode only)

Per-metric rules for combining per-scope values into a program-wide
cell:

| Metric | Aggregate |
|---|---|
| `throughput` | sum across scopes. Reported as raw count AND as per-week (`sum / (window.days / 7)`) for window-length normalisation. |
| `cycle_time_hours` p50/p75/p90 | NOT aggregated. Render median-of-medians per percentile + min/max across scopes in a separate row. |
| `lead_time_hours`, `flow_time_hours`, `flow_efficiency` p50/p75/p90 | Same as cycle_time. |
| `wip`, `flow_load` | sum across scopes. |
| `rework_rate` | **throughput-weighted average**: `sum(rework_rate[i] * throughput[i]) / sum(throughput[i])`. Zero denominator → `—` with `notes` entry. |
| `defect_ratio` | **flow_distribution-denominator-weighted average**: `sum(defect_ratio[i] * flow_distribution.denominator[i]) / sum(flow_distribution.denominator[i])`. NOT throughput-weighted because `defect_ratio` uses the Flow Distribution denominator (which includes subtasks regardless of `--include-subtasks`), see flow-metrics.md §Decisions item 25. Zero denominator → `—`. |
| `flow_distribution` | per-bucket weighted average using each scope's `flow_distribution.denominator` as the weight: `sum(bucket_share[i] * denominator[i]) / sum(denominator[i])`. The aggregated `flow_distribution.denominator` is `sum(denominator[i])` (integer count). Zero total denominator → all bucket cells `—`. |

The "median-of-medians" representation is explicitly an approximation;
a `notes` entry on program-mode reports records this and points users
to per-scope rows for honest distribution inspection.

### Output: Markdown

Section order fixed. Sections absent for a mode are omitted entirely
(no empty headers).

```markdown
# <title>

**Mode:** <baseline | cohort | program>
**Generated at:** <UTC ISO-8601 from skill run, NOT from input files>
**Inputs:** <count> file(s) — see §Provenance.
<mode-specific header line — see below>

## Summary

<one-line plain-English summary, e.g. "Throughput up 12%, cycle time p50
down 18%, rework rate up 4pp over <baseline-window> → <current-window>.">

## Metric deltas

| Metric | <A-label> | <B-label> | Δ abs | Δ % |
|---|---|---|---|---|
| throughput | 84 | 102 | +18 | +21.4% |
| cycle_time_hours p50 | 38.2 | 31.5 | −6.7 | −17.5% |
| ...

## Per-scope rows   <!-- program mode only -->

| Scope | throughput | cycle_p50 | rework_rate | ... |
| ... |

## Cohort breakdown   <!-- when --include-cohort-breakdown -->

| Metric | cohort | control | Δ abs | Δ % |
| ... |

## Notes

- <notes from validation, config-sha drift, missing metrics, etc.>

## Provenance

- Input files (basename, scope, window, generated_at, state_config_sha,
  issuetype_config_sha, upstream schema_version):
  - PROJ-Foo-2024Q1.json — project=PROJ team=Foo — 2024-01-01..2024-03-31
    — sha state=abc123 issuetype=def456 — generated 2024-04-02T08:00Z
    — upstream schema 1.0
  - ...
```

Mode-specific header line:

- **baseline:** `**Baseline window:** <from..to> | **Current window:** <from..to> | **Scope:** <scope-repr>`
- **cohort:** `**Window:** <from..to> | **Scope:** <scope-repr> | **Cohort JQL:** <jql>`
- **program:** `**Window:** <from..to> | **Scopes:** <N> (project=<i>, program=<j>, portfolio=<k>)`

Markdown rules:

- Numeric cells: integers as integers, floats to 4 decimal places (same
  as `flow-metrics`).
- Hours rendered as raw hours (e.g. `38.2`), not converted to days.
- Percent delta column: always signed (`+0.0%` or `−0.0%` for true
  zero), one decimal place.
- Use `—` (em dash) for absent / undefined cells.
- Use `∞` (Unicode) for infinite percent delta.
- Use `−` (Unicode minus) in numeric cells; `-` (ASCII hyphen) is
  reserved for ranges like `2024-Q1`.
- All Markdown special characters in scope/team names are escaped
  with backslash.

### Output: JSON sidecar

A compact JSON twin of the Markdown report, emitted whenever
`--format` is `both` (default) or `json`. Schema:

```json
{
  "meta": {
    "skill": "ai-adoption-report",
    "skill_version": "1.0",
    "mode": "baseline" | "cohort" | "program",
    "generated_at": "2026-05-19T14:30:00Z",
    "title": "AI-adoption report — baseline",
    "inputs": [
      { "basename": "PROJ-Foo-2024Q1.json",
        "scope": { ... },
        "scope_kind": "project+team",
        "window": { "from": "...", "to": "..." },
        "generated_at": "...",
        "state_config_sha": "...",
        "issuetype_config_sha": "...",
        "schema_version": "1.0" }
    ],
    "options": { "include_cohort_breakdown": false }
  },
  "summary": "Throughput up 12%, ...",
  "deltas": {
    "throughput": { "a": 84, "b": 102, "abs": 18, "pct": 0.2143 },
    "cycle_time_hours": {
      "p50": { "a": 38.2, "b": 31.5, "abs": -6.7, "pct": -0.1754 },
      "p75": { ... }, "p90": { ... }
    },
    ...
  },
  "per_scope": [ ... ],          // program mode only
  "cohort_breakdown": { ... },   // when --include-cohort-breakdown
  "notes": [ "config-sha-drift: ...", "..." ]
}
```

JSON canonicalization:

- Object keys sorted at every level (`json.dumps(sort_keys=True)`).
- Floats rounded to 4 decimal places at serialization time (same rule
  as `flow-metrics`).
- `pct` fields are decimal fractions (`0.2143`, not `21.4`). The
  Markdown rendering multiplies by 100 for display.
- `meta.inputs` sorted by `basename` ascending (Python codepoint
  order via `str.__lt__`; not locale-aware).
- `notes` sorted lexicographically (Python codepoint order; not
  locale-aware — same rule as `flow-metrics`).
- `per_scope` sorted by canonical scope representation (see below).
- `deltas` object keys follow the canonical metric row order from
  §"Metric row order" (NOT lexicographic). This is the one
  intentional exception to the global sort-keys rule.

Scope canonical representation: a stable string built as
`kind=<kind>;project=<v>;team=<v>;program_id=<v>;portfolio_id=<v>`
with absent fields rendered as empty string after the `=`. Used for
sort order and as the Markdown label in per-scope rows. Example:
`kind=project+team;project=PROJ;team=Foo;program_id=;portfolio_id=`.

### Provenance

The report's audit trail is the `meta.inputs` array. It carries
forward, per input file: basename, scope (dict + inferred kind),
window, the two config SHAs, the upstream `generated_at`, and the
upstream `schema_version`. This is the only integrity story.

The skill writes its own `meta.skill_version` (semver pinned in the
skill, bumped on every breaking output-shape change) and its own
`meta.generated_at` (UTC, from the skill's clock at write time).

No SHA-derived envelope ID. No tamper-detection. If the user wants
that, they put the output files in git.

### Errors and exit codes

| Exit | When |
|---|---|
| 0 | Report written. |
| 1 | Bug in the skill (uncaught exception). |
| 2 | Bad input: missing/extra flags, unreadable file, invalid JSON, missing required meta field, scope mismatch (baseline mode), window overlap (baseline mode), missing `cohort_breakdown` (cohort mode), no inputs matched window (program mode), overlapping scopes (program mode), output exists without `--overwrite`. |

Error messages MUST name the offending file (basename) and the
specific field or rule that triggered the exit. No bare "validation
failed" messages.

### Read-only contract

The skill makes no upstream calls. It does not invoke `flow-metrics`,
`jira`, or `jira-align`. Its filesystem writes are limited to
`--output` and its `.json` sidecar.

## Contract tests

### Input validation

- `test_missing_required_meta_field_exits_2` — for each of: `scope`,
  `window`, `state_config_sha`, `issuetype_config_sha`,
  `schema_version`, `generated_at`.
- `test_unreadable_input_file_exits_2_with_basename`.
- `test_invalid_json_input_exits_2_with_basename`.
- `test_absolute_path_outside_cwd_exits_2`.
- `test_window_not_iso_date_exits_2` (e.g. `2026-02-19T00:00:00Z`).
- `test_window_flag_not_two_iso_dates_exits_2`.
- `test_schema_version_unparseable_exits_2`.
- `test_mixed_major_schema_versions_emits_note`.
- `test_unrecognised_scope_shape_exits_2` (e.g. `{team: "Foo"}` alone).
- `test_scope_kind_inferred_correctly` (each of the 4 kinds).

### Baseline mode

- `test_baseline_scope_mismatch_exits_2_with_both_scopes`.
- `test_baseline_window_overlap_exits_2`.
- `test_baseline_back_to_back_windows_allowed`.
- `test_baseline_config_sha_drift_emits_note_and_renders_deltas`.
- `test_baseline_include_cohort_breakdown_without_cohort_noops_with_note`.
- `test_baseline_include_cohort_breakdown_jql_mismatch_omits_section_with_note`.
- `test_baseline_per_team_present_emits_ignored_note`.

### Cohort mode

- `test_cohort_input_without_cohort_breakdown_exits_2`.
- `test_cohort_emits_cohort_vs_control_deltas`.

### Program mode

- `test_program_no_inputs_match_window_exits_2`.
- `test_program_overlapping_scopes_exits_2`.
- `test_program_duplicate_scope_exits_2_with_both_basenames`.
- `test_program_per_team_flattens_into_per_scope_rows`.
- `test_program_per_team_double_counted_input_emits_warning_note`.
- `test_program_throughput_weighted_rework_rate_zero_denom_renders_dash`.
- `test_program_distribution_metric_renders_median_of_medians`.
- `test_program_cohort_breakdown_partial_emits_count_note`.
- `test_program_mixed_cohort_jql_emits_note_and_proceeds`.
- `test_program_no_cohort_inputs_omits_section_with_note`.
- `test_program_cohort_rollup_aggregates_sides_independently` —
  Fixture: 2 scopes; scope 1 cohort=(thru=10, rework=0.5),
  control=(thru=90, rework=0.1); scope 2 cohort=(thru=20, rework=0.4),
  control=(thru=80, rework=0.2). Cohort rollup rework_rate =
  (0.5×10 + 0.4×20) / (10+20) = 13/30 ≈ 0.4333. Control rollup
  rework_rate = (0.1×90 + 0.2×80) / (90+80) = 25/170 ≈ 0.1471. Cohort
  rollup is NOT (0.5×10 + 0.4×20 + 0.1×90 + 0.2×80) / (10+20+90+80).
- `test_program_defect_ratio_weighted_by_distribution_denominator` —
  Fixture: 2 scopes with throughput != flow_distribution.denominator
  (subtasks excluded from throughput but included in denominator).
  Assertion: defect_ratio aggregate uses denominator weights, not
  throughput weights.
- `test_program_cohort_defect_ratio_weighted_by_cohort_denominator` —
  Fixture: same as above but inside cohort_breakdown.cohort. Assertion:
  the cohort-side defect_ratio rollup uses
  `cohort_breakdown.cohort.flow_distribution.denominator` as weight,
  NOT throughput, NOT global `flow_distribution.denominator`.
- `test_program_cohort_missing_flow_distribution_drops_from_distribution_rollup_only`
  — Fixture: scope A has cohort_breakdown with flow_distribution;
  scope B has cohort_breakdown without flow_distribution. Assertion:
  scope B contributes to cohort throughput and rework_rate rollups
  but not to defect_ratio / flow_distribution; notes entry present.
- `test_program_flow_distribution_buckets_sum_to_one_after_aggregation`.
- `test_program_per_team_flattened_rows_excluded_from_cohort_rollup`.

### Delta math

- `test_percent_delta_zero_baseline_zero_current_renders_dash`.
- `test_percent_delta_zero_baseline_positive_current_renders_infinity`.
- `test_percent_delta_null_either_side_renders_dash`.
- `test_percent_delta_one_decimal_place_signed`.
- `test_distribution_metrics_compared_per_percentile`.

### Output

- `test_markdown_sections_omitted_when_empty`.
- `test_markdown_unicode_minus_in_numeric_cells_ascii_hyphen_in_dates`.
- `test_markdown_scope_team_names_escaped`.
- `test_markdown_metric_rows_in_canonical_order`.
- `test_markdown_distribution_metric_one_row_per_percentile`.
- `test_markdown_n_differs_more_than_10pct_emits_note`.
- `test_json_sidecar_keys_sorted_except_deltas_in_canonical_order`.
- `test_json_sidecar_floats_4dp`.
- `test_json_sidecar_inputs_sorted_by_basename`.
- `test_json_sidecar_scope_kind_present_on_inputs`.
- `test_overwrite_collision_exits_2_without_flag`.
- `test_overwrite_collision_with_both_format_checks_both_files`.
- `test_format_json_skips_markdown_render`.
- `test_byte_identical_rerun_modulo_generated_at`.

### Read-only contract

- `test_no_upstream_skill_invocations` (mock `subprocess`, assert none).
- `test_no_filesystem_writes_outside_output_and_sidecar`.

## Non-goals

- **No adversarial flag system.** The skill does not classify deltas
  as concerning. It prints numbers; the reader judges.
- **No baseline integrity envelope.** Baselines are `flow-metrics`
  JSONs sitting in a directory. Git is the integrity layer.
- **No cross-skill schema-version negotiation.** Single repo, single
  schema. Mixed-minor inputs noted; mixed-major inputs noted; nothing
  refuses to render.
- **No explain mode.** All deltas are visible in the table.
- **No path-expansion ceremony.** Paths are literal. `--inputs DIR`
  globs `*.json` directly, no recursion.
- **No multi-window program reports.** Each program-mode run is
  scoped to one `--window`. Time-series across windows is a downstream
  notebook job.
- **No charting.** Markdown tables only.

## Decisions

- **Three modes, one engine.** Baseline, cohort, and program-roll-up
  all reduce to "pair (or aggregate) two sets of numbers, subtract,
  render." A single delta-math layer serves all three.
- **Trust flow-metrics as the producer.** No re-validation of metric
  schemas beyond the `meta` fields the report itself needs. If
  flow-metrics emits bad data, the report renders bad data and the
  fix is upstream.
- **Markdown + JSON, both by default.** Program leads paste the
  Markdown; downstream tools consume the JSON. Generating both is
  free; defaulting to both removes a flag from the common path.
- **Notes block, not flags.** Anomalies (config-sha drift, missing
  metrics, zero denominators) become `notes` entries, not exit codes
  and not "flags." Notes are human-readable; flags are pretend-objective.
- **No `--ai-tag` flag in flow-metrics.** Cohort identity is already
  carried by `flow-metrics`'s `--cohort-jql`. The report reads
  `cohort_breakdown` from upstream output; it does not re-segment.

## Deferred to v2

- **Time-series mode.** "Last 6 quarters of throughput for scope X."
  Useful but downstream — write the notebook first, see if it earns a
  spec.
- **Cross-program comparison.** Comparing two non-overlapping program
  rollups. Not needed for the initial program; revisit when there's a
  second one.
- **Chart export.** PNG/SVG of trend lines. Out of scope for a
  Markdown-first tool.
- **`--baseline-from-directory` autopairing.** Picking the baseline
  file automatically from a directory by scope+earliest-window.
  Convenient but pushes ambiguity into the skill. Manual file paths
  for v1.

## Acceptance criteria

- Three modes work end-to-end against `flow-metrics` JSON fixtures.
- Output is byte-identical when re-run on the same inputs with the
  same skill version (modulo `meta.generated_at`, which is the only
  per-run timestamp).
- All contract tests pass.
- Spec and plan together fit under 800 lines (this spec + its plan
  budget). Anything beyond signals creeping scope.
