# Spec: ai-value-report

- **Status:** Approved
- **Owner:** eugeneacn
- **Plan:** _not yet drafted_
- **Constrained by:** [`flow-metrics.md`](flow-metrics.md) (Approved),
  [`ai-adoption-baseline.md`](ai-adoption-baseline.md) (Approved),
  [`ai-adoption-cohort.md`](ai-adoption-cohort.md) (Approved)
- **Review history:** 5 adversarial review rounds (2026-05-19). Round 1: 7 blockers / 11 majors / 3 minors; round 2: 5 blockers / 8 majors / 3 minors; round 3: 2 blockers / 4 majors / 4 minors; round 4: 0 blockers / 1 major / 5 minors; round 5: 0 blockers / 0 majors / 3 minors. Terminal-clean.

> **Spec contract:** this document defines what "done" means for the
> `ai-value-report` workflow skill. The implementing PR must match this
> spec or update it. Tests must be derivable from it.

## What this is

A read-only workflow skill that **renders** an AI-adoption value report
from a set of `ai-adoption-baseline` snapshots and
`ai-adoption-cohort` reports. It produces a board-ready Markdown
document (and a JSON twin for machine consumers) following the DORA
2025 three-layer framing: Utilization, Impact, Value.

It is a **pure renderer** — the only inputs are pre-computed files
from the two skills above. No upstream calls to `flow-metrics`,
`jira`, or `jira-align`. The numbers in the report are exactly the
numbers in the input files.

## Why

Engineering managers, RTEs, and portfolio owners need a single artifact
that combines per-team baseline + cohort outputs into one cross-team
narrative for review meetings. Today this is done by hand in slides,
which (a) drifts from the underlying numbers, (b) takes hours to
build, and (c) typically omits the adversarial flags from the cohort
skill because they undermine the narrative.

The skill exists to make the rollup **fast, reproducible, and
adversarially honest**. Specifically:

- Same inputs → same Markdown bytes (canonicalization).
- If any input cohort flagged "throughput up + rework up" or any of
  the other DORA-2025 warning patterns, the report cannot suppress
  that flag at render time.
- The report is human-readable but the JSON twin enables CI-driven
  monitoring and inclusion in a dashboard.

DORA 2025's seven-archetype finding is also baked into the per-team
table: the report shows per-team distribution (median + IQR across
teams) so aggregate claims don't hide the spread.

## Users and use cases

In priority order:

1. **RTE: build the Q2 AI-value report for the Payments ART.**
   `ai-value-report --baselines '.context/ai-baseline/program-42-*.json'
   --cohorts '.context/ai-cohort/program-42-*.json'
   --output .context/ai-value-reports/payments-q2-2026.md`.
   Result: a Markdown document with utilization %, impact deltas per
   metric, per-team table, flagged-team callouts, value-stream
   summary.
2. **Portfolio owner: cross-portfolio rollup for the May board.**
   `ai-value-report --baselines '.context/ai-baseline/portfolio-*.json'
   --cohorts '.context/ai-cohort/portfolio-*.json'`. Result: report
   covering the listed portfolios with per-scope rows. (Note: explicit
   portfolio→ART→team grouping is deferred to v2 — see Decision #11;
   the v1 report shows each input file as its own row.)
3. **Repeated render after data refresh.** The user re-runs cohorts,
   then re-runs the report; same inputs → byte-identical output. CI
   diff confirms no drift.
4. **Machine-consumer feed.** `ai-value-report ... --format json`.
   The JSON twin feeds a wiki page or a dashboard.

## Behavior

### Inputs

```
ai-value-report
    --baselines <PATH | GLOB> [--baselines <PATH | GLOB> ...]
    --cohorts <PATH | GLOB> [--cohorts <PATH | GLOB> ...]
    --output <FILE>
    [--format markdown | json | both]
    [--include-per-scope]
    [--overwrite]
    [--title TITLE]
    [--as-of YYYY-MM-DD]
    [--verbose]
```

| Flag | Meaning |
|---|---|
| `--baselines PATH-or-GLOB` | One or more paths or shell globs that resolve to baseline snapshots from `ai-adoption-baseline`. Repeatable. At least one match required. Patterns are passed through `os.path.expanduser` then `os.path.expandvars` then `glob.glob(pattern, recursive=True)`. Only files ending in `.json` are matched; anything else with a `.json` suffix is rejected at validate-time. |
| `--cohorts PATH-or-GLOB` | One or more paths or shell globs to cohort reports from `ai-adoption-cohort`. Repeatable. Same expansion rules. |
| `--output FILE` | Path to the Markdown output file. For `--format both`, the JSON twin is written to `<FILE>` with `.md` (or no extension) replaced by `.json`. Rules: if FILE ends in `.md`, JSON twin = `re.sub(r'\\.md$', '.json', FILE)`. If FILE has no extension, JSON twin = `FILE + '.json'`. If FILE ends in `.json`, exit 2 — `--format both` requires the Markdown file to be named distinctly. |
| `--format` | One of `markdown` (default), `json`, `both`. |
| `--include-per-scope` | Include a per-scope table in the Markdown output (section V). Without it, only the aggregate rollup is rendered. JSON output always includes the `per_scope` array regardless of this flag (the flag is recorded in JSON `meta.flags.include_per_scope` so consumers know the intent). The previous name `--include-per-team` is rejected with a clear "renamed to --include-per-scope" error. |
| `--overwrite` | Replace an existing `--output` file. Without this flag, exit 2 on collision. With `--format both`, the rule applies to BOTH files: exit 2 if either `<FILE>` or its `.json` twin exists; with `--overwrite`, both files are atomically replaced. |
| `--title TITLE` | Optional title string for the Markdown document. Default: `"AI-adoption value report"`. |
| `--as-of YYYY-MM-DD` | Override the "report date" line in the Markdown header. Default: `today_utc`. Useful for reproducibility — the same `--as-of` two days in a row produces byte-identical output. |
| `--verbose` | Debug logging. |

### Input file matching

Each baseline and cohort file's `meta.scope` is the canonical 5-field
dict defined by `ai-adoption-baseline`:

```json
{ "kind": "project"|"program"|"portfolio",
  "project_key": "<UPPER>" | null,
  "team": "<stripped>" | null,
  "program_id": <int> | null,
  "portfolio_id": <int> | null }
```

**Pairing rule.** Baseline ↔ cohort by **exact equality** of these
five fields. The fields are already canonicalized at write-time by the
sister skills (uppercase project keys, stripped teams, integer IDs),
so the value-report skill performs no further normalization. A baseline
with `{kind: "project", team: null, ...}` is NOT paired with a cohort
that has `{kind: "project", team: "Foo", ...}` — they are different
scopes by construction.

**Cross-scope state-config check.** Every paired (baseline, cohort)
must have matching `state_config_sha` and `issuetype_config_sha` (the
cohort spec already enforces this within a pair). Across different
scopes in the same report, mixing canonicalizations is allowed but
recorded: if the set of `state_config_sha` values across all input
files has size > 1, a `notes` entry lists every distinct sha and the
scopes using each, and a `meta.warnings` field includes
`mixed_state_config_shas: true`. Aggregate cells are still computed,
but the user is informed that cross-team comparison may be misleading.

**Pairing resolution order:**

1. **Dedupe per scope first.** For each input side (baselines, cohorts),
   group by canonical scope dict, then collapse each group to one
   representative using the tie-breakers below. Ignored files are
   recorded in `notes`.
2. **Then pair across sides** by exact scope-dict equality.

This order matters: if a baseline scope X has 2 baseline files and a
cohort scope X has 2 cohort files, the skill picks one baseline + one
cohort and pairs them — it does NOT consider any of the 4 pairings.

**Pairing edge cases:**

- A baseline without any matching cohort is **skipped** with a `notes`
  entry: `"baseline for scope <scope> has no matching cohort; impact
  section for that scope is omitted"`. The baseline still appears in
  the per-scope table with cohort columns blank.
- A cohort without a matching baseline is **included** with its
  cohort-vs-control deltas only (no cross-time data). `notes` records
  `"cohort for scope <scope> has no matching baseline; value section
  for that scope is omitted"`.
- Multiple cohorts for the same scope: pick the one with the latest
  `meta.window.to`. Tie on `window.to`: prefer larger `window.days`
  (`to - from`). Tie on both: prefer later `meta.generated_at`. Tie on
  all three: prefer the lexicographically-first basename (absolute
  paths never enter sort order; the duplicate-basename collision rule
  makes this tiebreaker effectively unreachable but it is pinned for
  total ordering).
  Ignored cohorts noted.
- Multiple baselines for the same scope: same tie-breaker hierarchy
  but anchored on `meta.rollout_date` first, then
  `meta.baseline_window.days`, then `meta.generated_at`, then the
  lexicographically-first basename (absolute paths never enter sort
  order; the duplicate-basename collision rule makes this tiebreaker
  effectively unreachable but it is pinned for total ordering).

### Aggregation math (across scopes)

Aggregate cells in sections I, II, III have one definition per metric.
Aggregates run over the **paired (baseline, cohort) tuples** unless
otherwise noted; an unpaired cohort still contributes to section II
(impact, within-window) but not section III (value, vs baseline).

**Scope-overlap rule.** Heterogeneous-granularity scope sets cause
double-counting (a portfolio-scope cohort plus a team-scope cohort
inside that portfolio counts the team twice). The skill **refuses** to
aggregate if the input set contains overlapping scopes — exit 2 with a
message naming the overlapping scopes. The user must pass a
non-overlapping set. Detection rule:

- Two scopes overlap iff one is a prefix of the other under the scope
  hierarchy: `portfolio_id` contains its `program_id`s contains its
  `project_key`s contains their `team`s.
- The skill does NOT resolve hierarchy from Jira / Jira Align (no
  upstream calls). It only refuses based on declared scope kinds: a
  `portfolio` scope plus any other scope in the same input set →
  exit 2. A `program` scope plus a `project` scope → exit 2. Mixed
  `project` and `project+team` for the same project key → exit 2.
- All scopes of the same kind (e.g. five project-scope cohorts for
  five different projects) → no overlap, allowed.

**Per-metric aggregation:**

| Metric | Within-window aggregate (sec. II) | Cross-time aggregate (sec. III) |
|---|---|---|
| Throughput | sum(throughput) across scopes, normalized per-week by dividing each scope's count by `window.days / 7` before summing. | same, against per-week baseline values. |
| Cycle time p50/p75/p90 | NOT aggregated — show median-of-medians across scopes and per-scope distribution (min/max). | same. |
| Rework rate | **throughput-weighted average**: `sum(rework_rate[i] * throughput[i]) / sum(throughput[i])`. | same denominator on each side. |
| Defect ratio | throughput-weighted average. | same. |
| Flow efficiency p50 | NOT aggregated — show median and per-scope range. | same. |
| Utilization (% AI-tagged) | `sum(cohort_throughput[i]) / sum(total_throughput[i])` across scopes after the overlap rule. | n/a (this is a within-window measure). |

Distribution stats (`p25, p50, p75, min, max`) are computed across
scopes with explicit n-branching (because
`statistics.quantiles(method="exclusive")` raises on n < 2):

- **n == 1:** `p25 = p50 = p75 = min = max = <the single value>`.
- **n == 2:** `min = a`, `max = b`, `p50 = (a + b) / 2`, `p25 = min`,
  `p75 = max` (simplest defensible interpolation for two points).
- **n == 3:** `statistics.quantiles([a,b,c], n=4, method="exclusive")`
  produces three cut-points which are used as `p25, p50, p75`;
  `min` and `max` are the input extremes.
- **n >= 4:** `statistics.quantiles(values, n=4, method="exclusive")`
  → `[p25, p50, p75]`; `min` and `max` from the input extremes.

Empty input set is impossible (at least one input file is required).

**Zero-denominator aggregation rules.** When the throughput-weighted
aggregates have a zero denominator:

- `rework_rate`: render as `null` (Markdown: `—`); add a `notes` entry
  `"aggregate-rework-rate-undefined: sum(throughput) == 0 across N
  paired scopes"`.
- `defect_ratio`: same.
- `utilization.ai_tagged_share_aggregate`: same; note as
  `"aggregate-utilization-undefined: ..."`.
- Throughput per-week aggregate: sum is 0, rendered as `0` (this case
  is mathematically valid, not undefined).

### Output structure (Markdown)

Roman-numeral section order is fixed; section content is filled in
from the input files.

```markdown
# <title>

**As of:** <as-of date>
**Scopes:** N teams / M programs / K portfolios
**Window comparison:** baseline windows (<oldest>..<newest>) vs cohort windows (<oldest>..<newest>)

## I. Utilization

- % of completed work tagged AI-assisted, aggregate across all scopes.
- Per-team distribution: median / p25 / p75 / min / max.

## II. Impact (cohort vs control, in current window)

| Metric | Cohort | Control | Delta | Flagged teams |
|---|---|---|---|---|
| Throughput per week | ... | ... | +X% | (none / list) |
| Cycle Time p50 (h)  | ... | ... | -X% | ... |
| Rework Rate         | ... | ... | +X% | (DORA-2025 warning: see flags) |
| Defect Ratio        | ... | ... | +X% | ... |
| Flow Efficiency p50 | ... | ... | -X% | ... |

## III. Value (cross-time, vs baseline)

| Metric                | Pre-AI baseline | Current control | Current cohort | Cohort delta vs baseline |
|---|---|---|---|---|
| Lead Time p50 (h)     | ... | ... | ... | ... |
| Flow Distribution     | (feature/defect/debt/risk/subtask/other) | | | |

(rendered only when at least one baseline + cohort pair is available)

## IV. Adversarial flags

<one subsection per flag name>

### `throughput-up-rework-up`

DORA 2025 warning. Triggered for: <scope list>.

| Scope | Cohort throughput/wk | Control throughput/wk | Cohort rework rate | Control rework rate |
|---|---|---|---|---|
| <scope-label> | ... | ... | ... | ... |

Where `<scope-label>` is rendered from the canonical scope dict:
- project + team → `<project_key> / <team>`
- project (no team) → `<project_key>`
- program → `program <program_id>`
- portfolio → `portfolio <portfolio_id>`

When the rendered label appears in a Markdown table cell, literal `|`
characters in `<project_key>` or `<team>` are escaped to `\|`. Literal
newlines (rare in team names) → `<br>`. The same escaping applies to
every user-derived value in any table cell across the report.

Each row is one input cohort that emitted the flag. Program- and
portfolio-scope cohorts produce one row per cohort, not one row per
team — the cohort skill emits flags at the scope of its input, not
per team. (To get per-team attribution for a program, the user runs
the cohort skill on each team scope separately and supplies those
cohort files instead.)

<repeat for each flag triggered in any input cohort>

If a flag triggered in zero input cohorts, the subsection is omitted.
If the entire flag set is empty (no input cohort had any flag),
section IV is rendered with the single line `No adversarial flags
triggered.` to keep section presence stable.

**Forward compatibility with unknown flag names.** If an input cohort
file emits a flag with a `name` this skill version doesn't recognize,
the report renders the subsection with the cohort's own `message`
field and a `notes` entry: `"unknown-flag: '<name>' from cohort spec
schema_version <X>; rendering with cohort-supplied message"`. The
skill does not refuse to render — that would suppress the very
adversarial signal the report exists to surface.

**Flag-name and message sanitization.** Both `flag.name` and
`flag.message` come from input cohort files; the renderer must defend
against pipe / backtick / newline content that would corrupt the
Markdown:

- `flag.name` validated against `^[a-z0-9-]+$` at input time
  (post-load, pre-render). Any other character → exit 2 naming the
  offending name. (Established cohort flag names — `throughput-up-
  rework-up`, `cycle-time-down-defect-ratio-up`, `flow-efficiency-
  down-cohort`, `small-cohort`, `throughput-up-rework-up-vs-baseline`
  — all match this regex; future cohort flags are expected to follow
  the same convention, and this skill enforces it defensively.)
- `flag.message` is rendered as a Markdown paragraph below the
  subsection heading (NOT inside a table cell). Newlines in the
  message are preserved as paragraph breaks (`\n\n` rendered as the
  separator between paragraphs; literal `\n` collapsed to single
  spaces). Pipe `|` and backtick `` ` `` are kept verbatim (allowed
  in paragraph context). The flag's `evidence` is rendered separately
  in a fixed-column table; user-supplied content does not appear in
  table cells.
- All user-derived strings appearing in any table cell (notes lines,
  scope labels, flag names, team names, project keys) are escaped:
  `|` → `\|`, literal `\n` → `<br>`. Tested by
  `test_scope_label_with_pipe_escaped_in_markdown`.

## V. Per-scope table  <!-- only when --include-per-scope is set -->

| Team | Cohort size | Throughput delta | Rework delta | Flags |
|---|---|---|---|---|
| ... | ... | ... | ... | (list) |

## VI. Notes

- N pairing notes (baseline-only, cohort-only, multiple-files-collapsed).
- Cohort sourcing methods used across inputs (label / field / jql),
  per spec §"Cohort sourcing" of `ai-adoption-cohort`.
- Aggregate denominators (total throughput, total cohort throughput).
- Boilerplate: "defect_ratio is not Change Failure Rate; see flow-metrics
  spec §Out of scope" if any input cohort emits this.
```

### Output structure (JSON twin)

Same content as Markdown, structured for machine consumers:

```json
{
  "meta": {
    "skill": "ai-value-report",
    "schema_version": "1.0",
    "title": "...",
    "as_of": "2026-05-19",
    "scopes": {
      "scopes_total": 15,
      "with_pair": 12,
      "baseline_only": 1,
      "cohort_only": 2
    },
    "//": "scopes_total == with_pair + baseline_only + cohort_only; every input scope (canonical 5-field dict) appears in exactly one of the three subcounts. Adding new categories requires a major schema_version bump.",
    "baseline_window_range": { "from": "2025-12-01", "to": "2026-03-31" },
    "cohort_window_range":   { "from": "2026-04-01", "to": "2026-05-19" },
    "input_files": {
      "baselines": [
        { "name": "PROJ_Team-Foo-2026-04-01-90d.json", "sha256": "<hex>" }
      ],
      "cohorts": [
        { "name": "PROJ_Team-Foo-2026-04-01-2026-06-30.json", "sha256": "<hex>" }
      ]
    },
    "flags": { "include_per_scope": false },
    "warnings": { "mixed_state_config_shas": false },
    "generated_at": "2026-05-19T00:00:00Z"
  },
  "utilization": {
    "ai_tagged_share_aggregate": 0.18,
    "per_scope_distribution": { "p50": 0.20, "p25": 0.12, "p75": 0.34, "min": 0.05, "max": 0.61 }
  },
  "impact": {
    "throughput_per_week":    { "cohort": ..., "control": ..., "delta_pct": ..., "flagged_teams": [...] },
    "cycle_time_hours_p50":   { ... },
    "rework_rate":            { ... },
    "defect_ratio":           { ... },
    "flow_efficiency_p50":    { ... }
  },
  "value": { /* same shape, vs baseline; omitted when no pair available */ },
  "flags": [
    {
      "name": "throughput-up-rework-up",
      "scopes": [
        {
          "scope": { "kind": "project", "project_key": "PROJ", "team": "Foo", "program_id": null, "portfolio_id": null },
          "scope_label": "PROJ / Foo",
          "evidence": { "cohort_throughput_per_week": ..., "control_throughput_per_week": ..., "cohort_rework_rate": ..., "control_rework_rate": ... }
        }
      ]
    }
  ],
  "per_scope": [
    {
      "scope": { ... },
      "scope_label": "...",
      "cohort_size": ...,
      "throughput_delta_pct": ...,
      "rework_delta_pct": ...,
      "flags": [...]
    }
  ],
  "notes": [ "...", ... ]
}
```

### Determinism contract

Two runs with identical inputs and the same `--as-of` produce
byte-identical Markdown AND byte-identical JSON. This relies on:

- `meta.generated_at` is pinned to `<as_of>T00:00:00Z` (NOT
  `datetime.now(UTC)`). With `--as-of 2026-05-19`,
  `generated_at = "2026-05-19T00:00:00Z"`. Default `--as-of` is
  `today_utc`, so an unparameterized run is byte-identical with any
  other run on the same UTC day (and differs from runs on a different
  day only in `meta.as_of` and `meta.generated_at`).
- `meta.input_files.baselines` and `cohorts` record file **basenames**
  plus a `sha256` of file content — not absolute paths. The `sha256`
  is computed over **raw file bytes** (not parsed-then-canonicalized);
  re-formatting an input file with `jq` therefore changes its
  recorded sha. The basename + content sha pair is enough to
  fingerprint the input without leaking machine-specific paths.
- **Duplicate-basename collision.** If two input files (across all
  `--baselines` and `--cohorts` patterns combined) share a basename,
  exit 2 with `"duplicate input basename: '<name>' (paths: A, B);
  rename one or pass through a single glob"`. This keeps the
  basename-sorted `input_files` deterministic across machines.
- Float rounding: `json.dumps(round(x, 4))` for the JSON twin (matches
  flow-metrics).
- Markdown rounding for displayed percents: `f"{round(value * 100,
  1):.1f}%"` applied to the **un-rounded** value. Note that JSON
  4-dp and Markdown 1-dp-percent of the same datum can read
  differently (e.g. 0.12349 → JSON 0.1235, Markdown 12.3%); both are
  consistent representations of the same number, computed
  independently from the source.
- Markdown table column padding: **single space** on either side of
  each cell (no max-cell alignment). Separator row: exactly three
  dashes per column (`|---|---|...`). One trailing newline at EOF.
- Null cell rendering: `—` (em-dash) in Markdown; `null` in JSON.
- Lists sorted: `input_files.baselines` by `name` (basename) in
  codepoint order; `input_files.cohorts` by `name` (basename) in
  codepoint order; `flags` by `name`; `per_scope` by scope-label
  codepoint; flag-section rows by scope-label codepoint. **The
  basename-by-codepoint rule is the single source of truth for
  `input_files` ordering — no absolute paths are sorted, recorded, or
  considered anywhere.**
- `notes` sorted lexicographically (inherits the
  flow-metrics-canonicalization rule).

### Read-only contract

The skill invokes **no upstream skills**. It reads only:

- Files matched by `--baselines` (read-only).
- Files matched by `--cohorts` (read-only).

It writes only:

- `--output FILE` (Markdown or JSON, depending on `--format`).
- `<FILE>.json` when `--format both`.

It never invokes `jira`, `jira-align`, `flow-metrics`,
`ai-adoption-baseline`, `ai-adoption-cohort`, git, curl, or any other
subprocess. The contract test enforces this with a wrapper that fails
on any subprocess call.

### Errors and exit codes

- `0` success.
- `1` user aborted.
- `2` validation error:
  - no `--baselines` matches; no `--cohorts` matches;
  - input path does not end in `.json`;
  - malformed input file (not JSON; missing `meta.scope`; wrong
    `meta.skill`; missing `meta.schema_version`);
  - `meta.schema_version` major is not `"1"` on any input file
    (i.e. `version.split('.', 1)[0] != "1"`). Major-version mismatch
    exits 2 with `"input file <path> has schema_version <V>; this
    skill supports major 1.x"`. Minor drift forward (e.g. `"1.2"`) is
    accepted and recorded in `notes` as `"input-schema-minor-drift:
    <path> uses schema_version <V>"`. This allows the unknown-flag
    forward-compat path (see "Forward compatibility with unknown
    flag names") to be reachable: a cohort schema_version 1.1 emitting
    a new flag still loads;
  - state-config sha mismatch within a paired (baseline, cohort);
  - overlapping scopes in the input set (per "Aggregation math");
  - output file exists without `--overwrite`;
  - `--format both` with FILE ending in `.json`.
- `3` not used (no upstream skills).

**Input schema validation.** Every baseline file is validated against
`references/baseline.schema.json`; every cohort file against
`references/cohort.schema.json`. Both schemas ship with this skill (as
copies of the sister skills' schemas, kept in sync via CI). Schema
validation failure → exit 2 naming the file and the failing field.

### Output canonicalization

Same rules as `flow-metrics`:

1. JSON object keys sorted codepoint order at every level.
2. Floats rounded to 4 decimals at serialization via
   `json.dumps(round(x, 4))`.
3. Lists sorted: `meta.input_files.baselines` and `cohorts` are
   sorted by `name` (basename) in codepoint order — never by absolute
   path; `flags` sorted by `name`; `flags[].scopes` sorted by
   `scope_label` codepoint; `per_scope` sorted by `scope_label`
   codepoint.
4. Markdown rendering is deterministic: same input files + same
   `--as-of` → byte-identical Markdown output. Tables use a fixed
   column ordering and a fixed delimiter style.

### Markdown content rules

The Markdown is generated, not user-edited:

- Tables use GitHub-flavored Markdown pipe syntax (`| col | col |`)
  with single-space padding and exactly-three-dash separator rows
  (see "Determinism contract" above).
- Numeric cells: throughput counts as integers, ratios as percent
  with one decimal place (`12.3%`), durations as hours with one
  decimal place. Null values render as `—` (em-dash).
- **Flag messages come from the cohort file's own `flags[].message`
  field**, not from a table baked into this skill. The cohort spec
  ships the canonical text per flag name; this skill renders verbatim.
  Unknown flag names (forward-compat) still render with the cohort's
  message and a notes-line acknowledgement. This means a v2 cohort
  flag like `post-delivery-rework-up` lands in v1 reports without a
  skill update.
- The `## VI. Notes` section is always present, even when empty
  ("No notes." line). This keeps the section order stable.

JSON output: `notes` is always an array (possibly empty `[]`).
`flags` is always an array (possibly empty `[]`). `value` is **omitted
entirely** (not present as `{}` or `null`) when no paired
(baseline, cohort) exists. `per_scope` is always an array (possibly
empty `[]`).

## Contract tests

### Input validation

- **`test_no_baselines_match_exits_2`** — `--baselines '/tmp/nope/*.json'`
  matching zero files exits 2.
- **`test_no_cohorts_match_exits_2`** — same, for cohorts.
- **`test_malformed_baseline_exits_2`** — baseline file is not JSON
  → exit 2 naming the path.
- **`test_baseline_missing_meta_scope_exits_2`** — baseline file's
  `meta.scope` field absent → exit 2.
- **`test_wrong_skill_in_meta_exits_2`** — baseline file's `meta.skill`
  is not `"ai-adoption-baseline"` → exit 2.
- **`test_cohort_baseline_state_config_mismatch_exits_2`** — paired
  baseline and cohort have different `state_config_sha` values → exit
  2 naming the scope.

### Pairing

- **`test_canonical_scope_exact_match_required`** — `{kind: "project",
  project_key: "PROJ", team: null}` baseline does NOT pair with
  `{kind: "project", project_key: "PROJ", team: "Foo"}` cohort; both
  appear in the report as "unpaired" with notes entries.
- **`test_baseline_without_cohort_skipped_with_note`** — note records
  the skipped scope; impact section omits it.
- **`test_cohort_without_baseline_included_no_baseline_delta`** —
  cohort's within-window deltas appear; cross-time deltas absent.
- **`test_multiple_cohorts_per_scope_latest_window_to_wins`** — older
  cohorts noted; newer one used.
- **`test_multiple_cohorts_tie_breaker_window_days`** — same
  `window.to`, different `window.days`: larger wins.
- **`test_multiple_cohorts_tie_breaker_generated_at_then_path`** —
  all primary keys equal; later `generated_at` wins; full tie
  resolves to lexicographically-first basename.
- **`test_multiple_baselines_per_scope_latest_rollout_wins`** —
  analogous.
- **`test_overlapping_scopes_exit_2`** — input set contains
  `{kind: "portfolio", portfolio_id: 7}` AND `{kind: "project",
  project_key: "PROJ"}`. Exit 2 with both scopes named.

### Aggregation math

- **`test_aggregate_throughput_normalized_per_week`** — fixture: scope
  A has throughput 100 over 60 days, scope B has 200 over 90 days.
  Aggregate per-week throughput = `(100/(60/7) + 200/(90/7))`.
- **`test_aggregate_rework_rate_throughput_weighted`** — fixture:
  scope A rework_rate=0.30 with throughput 100, scope B rework_rate=
  0.50 with throughput 50. Aggregate = `(0.30*100 + 0.50*50) / 150 ==
  0.367`.
- **`test_aggregate_cycle_time_not_aggregated`** — output shows
  median-of-medians and per-scope distribution; aggregate cell is the
  median across scopes, NOT a throughput-weighted percentile.
- **`test_aggregate_utilization_correct_denominator`** — sum of
  cohort throughput divided by sum of total throughput across paired
  scopes; single-scope input gives that scope's own utilization
  exactly.

### Cross-scope state-config

- **`test_mixed_state_config_shas_recorded`** — input set has two
  baselines with different `state_config_sha` values. Aggregation
  proceeds; `meta.warnings.mixed_state_config_shas == true`; `notes`
  lists distinct shas with their scopes.
- **`test_uniform_state_config_no_warning`** — all inputs share one
  sha. `meta.warnings.mixed_state_config_shas == false`; no notes
  entry about it.

### Rendering — Markdown

- **`test_markdown_section_order_stable`** — sections appear in roman-
  numeral order regardless of input order.
- **`test_markdown_byte_identical_for_same_inputs`** — same inputs +
  same `--as-of` → byte-identical Markdown.
- **`test_per_scope_table_only_when_flag_set`** — without
  `--include-per-scope`, section V is absent; JSON output always
  contains the `per_scope` data.
- **`test_flags_subsection_per_unique_flag_name`** — three teams with
  `throughput-up-rework-up`, two teams with `small-cohort` → exactly
  two subsections under `## IV. Adversarial flags`.
- **`test_dora_attribution_present_when_flag_triggers`** — when
  `throughput-up-rework-up` is in the report, the flag's section
  text contains the DORA-2025 attribution string verbatim.

### Rendering — JSON twin

- **`test_json_keys_sorted`** — at every level.
- **`test_floats_rounded_to_4dp`** — same rule as flow-metrics.
- **`test_input_files_listed_as_basenames_with_sha`** —
  `meta.input_files.baselines` and `cohorts` contain
  `{name: basename, sha256: hex}` objects, sorted by `name` codepoint
  (NOT by absolute path). No absolute paths anywhere in the output.
- **`test_duplicate_input_basename_exits_2`** — two input files
  sharing a basename across the input set → exit 2.
- **`test_generated_at_pinned_to_as_of_midnight`** — `--as-of
  2026-05-19` produces `meta.generated_at == "2026-05-19T00:00:00Z"`.
- **`test_byte_identical_across_machines`** — two runs of the same
  inputs from two different working directories with `--as-of` set
  produce byte-identical JSON and Markdown.
- **`test_format_both_writes_both`** — `--format both` produces
  `<FILE>` and the resolved JSON twin path per the documented rule.
- **`test_format_both_existing_twin_exits_2_without_overwrite`** —
  existing JSON twin but missing Markdown: exit 2 without
  `--overwrite`; with `--overwrite`, both are replaced.
- **`test_format_both_json_named_file_exits_2`** — `--format both
  --output report.json` exits 2.
- **`test_meta_flags_include_per_scope_records_actual_value`** —
  whether `--include-per-scope` is passed (true) or omitted (false),
  the resulting `meta.flags.include_per_scope` records the actual
  parsed value.
- **`test_legacy_include_per_team_flag_rejected`** —
  `--include-per-team` exits 2 with a clear "renamed to
  --include-per-scope" message; user error is easy to fix.
- **`test_unknown_flag_renders_cohort_message_with_notes_entry`** —
  cohort input emits flag `name: "future-flag-name"` this skill
  version doesn't know. Section IV renders the subsection with the
  cohort's `message`; notes includes the unknown-flag entry.
- **`test_flag_name_invalid_charset_exits_2`** — cohort input emits
  flag `name: "Bad Name!"` violating `^[a-z0-9-]+$`. Exit 2.
- **`test_scope_label_with_pipe_escaped_in_markdown`** — team name
  `"Foo|Bar"` renders as `PROJ / Foo\|Bar` inside table cells.

### Aggregation math — utilization

- **`test_utilization_aggregate_equals_total_cohort_div_total_throughput`**
  — `utilization.ai_tagged_share_aggregate ==
  sum(cohort_throughput) / sum(total_throughput)`.
- **`test_utilization_per_scope_distribution_uses_percentiles`** — same
  algorithm as flow-metrics (`statistics.quantiles(method=
  "exclusive")`), p25 / p50 / p75.
- **`test_impact_delta_per_metric_signs_consistent`** — positive
  delta means cohort is larger than control; this convention is the
  same across every metric (including the ones where "larger" is
  worse like rework_rate).

### Read-only contract

- **`test_no_subprocess_invocations`** — test wrapper monkeypatches
  `subprocess.run`/`Popen` and asserts zero calls.
- **`test_no_writes_outside_output_path`** — file-system writes are
  exactly the `--output` file (and its `.json` twin under
  `--format both`); no other paths touched. The user is trusted to
  choose a sensible `--output` location (no sandbox check on system
  roots — this is a local read-only-input renderer, not a security
  boundary).

### Errors

- **`test_validation_error_exits_2_before_any_read`** — flag-combo
  validation runs before any file read; zero file reads recorded on
  exit-2 path.

## Non-goals

- The skill **will not** call any upstream skill. Pure renderer.
- It **will not** mutate any input file.
- It **will not** suppress adversarial flags. If the input cohorts
  flagged, the report says so.
- It **will not** propose recommendations ("you should slow down AI
  adoption"). Recommendation is a human judgment; the report is the
  evidence.
- It **will not** send the report anywhere (Slack, email, wiki). The
  report is a local file; humans share it.
- It **will not** generate charts / plots / images. Markdown tables
  only; rendering to a dashboard is out of scope.
- It **will not** support partial rendering (only `## I.
  Utilization`). The structure is fixed.
- It **will not** support multi-window comparison (`pre-AI baseline`
  vs `mid-rollout snapshot` vs `current cohort`). v1 is two-window:
  baseline → cohort.

## Decisions

1. **The skill is a pure renderer.** No upstream calls; same inputs
   produce same bytes.
2. **Markdown is the default format**, JSON is the twin. Both are
   first-class outputs.
3. **Adversarial flags cannot be suppressed** at render time. If you
   want to ignore a flag, ignore it in conversation; the document
   records it.
4. **Pairing is by exact scope match.** No fuzzy matching across
   project keys or team names.
5. **Per-scope table is opt-in** in Markdown (to keep the default
   document board-friendly), always-on in JSON.
6. **Sections are roman-numeraled and fixed order.** Partial rendering
   not supported.
7. **`--as-of` allows reproducibility** by pinning the "as of"
   header line; without it, defaults to `today_utc`.
8. **Glob expansion is performed by the skill**, not by the shell.
   This avoids surprises on Windows where `cmd.exe` doesn't expand
   globs.
9. **Output JSON canonicalization rules** match `flow-metrics`'.
   Markdown canonicalization is also pinned (column orders, delimiter
   style, null renderer).
10. **Defect-ratio-not-CFR boilerplate** is propagated from any input
    cohort's notes verbatim; the report does not add or remove the
    disclaimer.
11. **`--portfolio-grouping` is deferred to v2.** v1 baseline/cohort
    scopes don't carry portfolio metadata (the baseline skill never
    resolves portfolio membership). v2 either adds a sidecar map file
    or extends the baseline scope to carry resolved portfolio
    metadata.
12. **Cross-scope state-config heterogeneity is allowed but flagged**,
    not refused. Refusing would block legitimate cross-team rollups
    where teams legitimately use different state configs. The flag
    (`meta.warnings.mixed_state_config_shas`) lets consumers soften
    aggregate claims.
13. **Overlapping scopes are refused** at validate-time. Mixing
    portfolio-level and project-level cohorts double-counts and the
    aggregate math becomes meaningless. The user must pick one
    granularity per report.
14. **Flag messages come from the cohort file's own `message`
    field**, not from a baked-in table in this skill. Forward-compat
    with new cohort flags requires no skill update; the cohort spec
    is the source of truth for flag text.
15. **`meta.generated_at` is pinned to `<as_of>T00:00:00Z`** for
    cross-machine reproducibility. Default `--as-of` is `today_utc`.
16. **`input_files` records basenames + content shas**, never
    absolute paths. PII and machine-specific paths never appear in
    the output.
17. **JSON empty-vs-omitted policy:** `notes`, `flags`, `per_scope`
    are always arrays (possibly empty). `value` is omitted entirely
    when no paired (baseline, cohort) exists.

## Deferred to v2

- **Charts and plots** (matplotlib, mermaid, etc.).
- **Multi-window comparison** (3+ time periods).
- **Wiki / Confluence / Slack adapters.**
- **Custom flag suppression** with audit trail (defensible: an exec
  reviewing v1 in a board meeting may want to suppress noise; v1
  forbids it on principle).
- **Per-flag drill-down** linking to the originating cohort's
  `--explain-flag` JSONL when present.
- **Localization / non-English templates.**

## Acceptance criteria

- [ ] All Contract tests pass on macOS and Linux under Python 3.10,
      3.11, 3.12.
- [ ] SKILL.md follows the dropkit pattern.
- [ ] `manifest.json` declares
      `deps.skills: [{name: "ai-adoption-baseline"}, {name: "ai-adoption-cohort"}]`.
      No dep on `flow-metrics` (the cohort and baseline skills depend
      on it transitively, but this skill never invokes it directly).
- [ ] Output JSON validates against
      `references/value-report.schema.json`.
- [ ] Output Markdown validates against the canonical structure
      (section order, table column order) via a snapshot test.
- [ ] Skill lives at `skills/workflows/ai-value-report/`.
