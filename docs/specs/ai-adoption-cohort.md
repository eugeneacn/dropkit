# Spec: ai-adoption-cohort

- **Status:** Approved
- **Owner:** eugeneacn
- **Plan:** _not yet drafted_
- **Constrained by:** [`flow-metrics.md`](flow-metrics.md) (Approved,
  terminal-clean), [`ai-adoption-baseline.md`](ai-adoption-baseline.md)
  (Approved)
- **Review history:** 5 adversarial review rounds (2026-05-19). Round 1: 3 blockers / 12 majors / 5 minors; round 2: 1 blocker / 6 majors / 5 minors; round 3: 0 blockers / 6 majors / 11 minors; round 4: 1 blocker / 0 majors; round 5: 0 blockers / 0 majors. Terminal-clean.

> **Spec contract:** this document defines what "done" means for the
> `ai-adoption-cohort` workflow skill. The implementing PR must match
> this spec or update it. Tests must be derivable from it.

## What this is

A read-only workflow skill that compares **AI-tagged work** against an
unmarked control population on the same scope, and surfaces three
deltas: cohort vs control (current window), cohort vs baseline
(pre-AI), and control vs baseline. It also emits **adversarial flags**
when the deltas indicate AI is inflating throughput at the cost of
quality (the DORA 2025 finding).

It composes two skills it does not re-implement:

- `flow-metrics` — for the actual cohort-split aggregate, via
  `--cohort-jql`.
- `ai-adoption-baseline` — read-only; if a baseline snapshot is provided
  via `--baseline-file`, the cohort skill reads it and computes the
  cross-time deltas.

The cohort skill's distinctive job is **cohort sourcing** (turning
"AI-assisted" into a verifiable JQL clause), **delta computation** vs
the baseline, and **flag emission** when the deltas look suspicious.

## Why

DORA 2025's central finding: AI coding assistants dramatically boost
individual output (21% more tasks, 98% more PRs) but organizational
delivery metrics stay flat or worse on stability. The cohort comparison
is the only way to see this with a tracker-side toolchain. Without it,
"AI made us 30% faster" claims circulate based on cherry-picked weeks.

The skill is also the canonical place to make the **cohort-sourcing
choice explicit**. The three options (label, custom field, JQL clause)
have very different reliability:

- **Label** (e.g. `ai-assisted`): easy to set but easy to forget;
  human-tagged, drifty.
- **Custom field** (e.g. `AI Usage = High`): authoritative if the
  team disciplines itself to set it at close.
- **JQL clause** (e.g. `description ~ "Generated with Claude"`):
  heuristic, leaky.

The spec forces the user to name which they're using. Mixing them or
inferring is forbidden.

The third distinctive contribution is the **adversarial flag set**.
DORA 2025 explicitly warns about "throughput up + rework up" as the
signature of AI-amplified bad practices. The cohort skill computes both
deltas and raises a flag when the pattern matches. This is the only
defensive signal in the toolchain.

## Users and use cases

In priority order:

1. **Team lead: "Compare AI-assisted-labeled tickets vs unlabeled,
   last 90 days, against the Sept 1 baseline."**
   `ai-adoption-cohort --project PROJ --team Foo --cohort label:ai-assisted --baseline-file .context/ai-baseline/PROJ_Team-Foo-2026-09-01-90d.json`.
2. **RTE: "Same comparison across the Payments ART."**
   `ai-adoption-cohort --program-id 42 --cohort field:AI-Usage=High --baseline-file .context/ai-baseline/program-42-2026-09-01-180d.json`.
3. **Quick check without baseline.** `ai-adoption-cohort --project PROJ
   --cohort label:ai-assisted`. Result: cohort vs control deltas only;
   no cross-time comparison. The `notes` block calls out the
   limitation; flags that require a baseline ("throughput up vs
   baseline + rework up vs baseline") are not emitted.
4. **Cohort prep with explicit JQL.** `ai-adoption-cohort --project
   PROJ --cohort 'jql:labels in (ai-assisted, copilot)
   OR "AI Usage" is not EMPTY'`. The user spelled out exactly what
   counts; the skill records the resolved JQL verbatim in `meta`.
5. **Adversarial-flag triage.** A team got a flag in their last run.
   They re-run with `--explain-flag throughput-up-rework-up` and the
   skill prints which issues drove the cohort's rework count and which
   issues drove its throughput. (See "explain mode" below.)

## Behavior

### Inputs

```
ai-adoption-cohort
    (--project KEY | --program-id ID | --portfolio-id ID)
    [--team NAME]
    --cohort <label:NAME | field:NAME=VALUE | jql:EXPR>
    [--baseline-file PATH]
    [--from YYYY-MM-DD --to YYYY-MM-DD]
    [--output-dir DIR]
    [--state-config FILE]
    [--issuetype-config FILE]
    [--explain-flag NAME]
    [--verbose]
```

| Flag | Meaning |
|---|---|
| `--project / --program-id / --portfolio-id / --team` | Same scope semantics as `flow-metrics` and `ai-adoption-baseline`. Exactly one of the three scope flags is required. |
| `--cohort SPEC` | **Required.** The cohort definition. Exactly one of three forms (the prefix is part of the syntax): `label:<NAME>` resolves to JQL `labels = "<NAME>"`. `field:<NAME>=<VALUE>` resolves to `"<NAME>" = "<VALUE>"`. `jql:<EXPR>` is used verbatim as the cohort clause. Any other form exits 2. |
| `--baseline-file PATH` | Path to a snapshot from `ai-adoption-baseline`. Optional. When provided, the report includes cross-time deltas and baseline-dependent flags. When absent, only cohort-vs-control (within the current window) is emitted. |
| `--from`, `--to` | Window bounds. Default: last 90 days. Must NOT overlap the baseline's window when `--baseline-file` is set — overlap exits 2. |
| `--output-dir DIR` | Where the cohort report JSON is written. Default: `.context/ai-cohort/`. Created if absent (mode 0700). |
| `--state-config FILE`, `--issuetype-config FILE` | Forwarded to `flow-metrics`. When `--baseline-file` is set, these configs MUST match the baseline's (verified by sha); mismatch exits 2. |
| `--explain-flag NAME` | When provided, the skill writes an additional file `<output-path>.explain.jsonl` listing the issues that contributed to the named flag — provided the flag actually triggered. Supported names: `throughput-up-rework-up`, `throughput-up-rework-up-vs-baseline`, `cycle-time-down-defect-ratio-up`, `flow-efficiency-down-cohort`. (`small-cohort` is not explainable — every cohort issue would be in the list, which is identical to the report itself.) Empty / unknown name → exit 2. Flag did not trigger → exit 4 (report still written). |
| `--verbose` | Debug logging including resolved `flow-metrics` invocations. |

### Cohort resolution

The `--cohort` argument is parsed into exactly one JQL clause and
recorded in `meta.cohort` as `{ kind, raw, resolved_jql }`:

- **`label:<NAME>`** → resolved_jql = `labels = "<NAME>"`. NAME is
  stripped of leading/trailing whitespace, then validated against
  `[A-Za-z0-9._:-]+` (Jira's broader label charset — dots and colons
  are allowed because team-namespaced labels like `team.ai-assisted`
  are common). Any other character (including embedded whitespace,
  quotes, backslashes) → exit 2.
- **`field:<NAME>=<VALUE>`** → resolved_jql = `"<NAME>" = "<VALUE>"`.
  Splits on the **FIRST `=`**; everything to the right is the value
  (so `field:URL=http://example.com?x=y` resolves correctly).
  Both NAME and VALUE are stripped of leading/trailing whitespace
  (internal whitespace preserved). Embedded `"` or `\` in either NAME
  or VALUE → exit 2 (escaping JQL strings is out of scope for v1; use
  the `jql:` form for such values).
- **`jql:<EXPR>`** → resolved_jql = `<EXPR>` verbatim, after a
  conservative pre-validation:
  - Strip leading/trailing whitespace.
  - Reject `ORDER BY` (any case) in EXPR — flow-metrics appends
    `ORDER BY key ASC` after composing with scope, and a user-supplied
    `ORDER BY` would produce invalid JQL after paren-wrapping. Exit 2
    with `"cohort jql must not contain ORDER BY; flow-metrics appends
    it"`.
  - Reject trailing semicolons.
  - Reject any unbalanced `(`/`)` or `"` (simple character-count
    parity check; doesn't validate full JQL grammar).
  - Otherwise pass through verbatim. Remaining JQL syntax errors are
    surfaced from Jira via flow-metrics as exit 3.

The resolved JQL is then passed to `flow-metrics --cohort-jql
"<resolved_jql>"`. Per `flow-metrics`' own contract, the underlying
query becomes `(<scope>) AND (<resolved_jql>) ORDER BY key ASC`. The
paren-wrap is therefore safe because the resolved_jql is guaranteed
not to contain top-level `ORDER BY`, and the cohort-resolution rules
above keep the resolved clause parenthesizable.

### Window resolution

- Default: `--to = today_utc`, `--from = today_utc - 90 days`.
- When `--baseline-file` is set, the current window MUST be disjoint
  from the baseline's window. Specifically: the current `--from` must
  be strictly later than the baseline's `--to`. Overlap exits 2 with
  a message naming both windows.
- **Default-window-collision rule.** When the user did NOT pass
  `--from`/`--to` (defaults active) AND `--baseline-file` is set AND
  the default `today_utc - 90 days` falls before `baseline.to`, the
  skill **auto-clamps** `--from` to `baseline.to + 1 day` and records
  a `notes` entry: `"window-auto-clamped: --from clamped to
  <baseline.to + 1 day> (default 90-day lookback overlapped
  baseline)"`. This prevents the confusing "you didn't pick a window
  but it's wrong" failure when the user simply takes defaults right
  after writing a recent baseline. If the user explicitly passed
  `--from` (even to the same value), no clamping occurs and overlap
  exits 2 — explicit user intent wins.
- The baseline's rollout-date is treated informationally only —
  the cohort skill does NOT require the current window to start at the
  rollout-date. (Teams roll out incrementally; the first 60 days post-
  rollout are often unrepresentative, and forcing the cohort window
  to start at rollout-date would dilute the signal.)

### Pipeline

1. **Validate input shape** (scope, cohort syntax, `--explain-flag`
   name is a known flag, window dates parseable). Exit 2 on any
   shape error **before any upstream invocation or file read**.
2. **Load baseline** if `--baseline-file` provided:
   - Read and JSON-parse the file. Exit 2 on parse failure.
   - Validate against `references/baseline.schema.json` (a copy /
     symlink of `ai-adoption-baseline`'s schema). Schema failure → exit
     2.
   - **Scope check:** `baseline.meta.scope` (canonical 5-field dict per
     `ai-adoption-baseline` spec) must equal the current run's
     canonical scope dict exactly. Mismatch → exit 2 naming both
     scopes.
   - **Snapshot-id integrity check:** recompute the snapshot_id from
     baseline contents using the formula in `ai-adoption-baseline`'s
     spec and compare to `baseline.meta.snapshot_id`. Mismatch → exit
     2 (`"baseline file tampered or corrupted; snapshot_id does not
     match contents"`).
   - **Window-disjoint check:** current `--from` must be strictly later
     than `baseline.meta.baseline_window.to`. Overlap → exit 2.
   - **Schema-version check:** `baseline.meta.schema_version` must have
     major version `"1"` (this skill's input contract). Major
     `split('.', 1)[0]` is computed and compared to the allowlist
     `{"1"}`. Other majors → exit 2 (`"baseline schema_version <V>
     not supported; upgrade ai-adoption-cohort"`). Minor drift
     forward within a supported major (e.g. baseline emits `"1.1"`)
     is accepted and recorded in `notes` as
     `"baseline-schema-minor-drift: 1.1"`.
3. **Resolve `flow-metrics` script** via the discovery probe shape
   used by `ai-adoption-baseline`.
4. **Invoke `flow-metrics`** with `--cohort-jql <resolved>`. Stream
   stdout (the full aggregate JSON with `cohort_breakdown`).
5. **Config-sha + upstream-schema check** (when baseline provided),
   performed after step 4 so the fresh flow-metrics output (`current`)
   is in hand:
   - read both `baseline.flow_metrics.meta.state_config_sha` and
     `current.meta.state_config_sha`; must match. Same for
     `issuetype_config_sha`. Mismatch → exit 2 naming which sha
     differs.
   - **Upstream-schema check** (cross-time consistency):
     `current.meta.schema_version` major must equal
     `baseline.flow_metrics.meta.schema_version` major. Major mismatch
     → exit 2 (`"flow-metrics schema_version changed between baseline
     and current run; deltas not comparable"`). Minor drift within a
     major is recorded in `notes`.
6. **Compute deltas:**
   - Cohort vs control (within current window): metric-by-metric, both
     absolute and relative-percent.
   - Cohort vs baseline (if baseline provided): metric-by-metric.
   - Control vs baseline (if baseline provided): metric-by-metric.
7. **Evaluate flags** (see "Adversarial flags" below) — skipping any
   flag whose required metrics are `null` on either side.
8. **Write report** to `<output-dir>/<scope-tag>-<from>-<to>.json`.
   Atomic write via same-directory tempfile + `os.replace` (same
   pattern as `ai-adoption-baseline`). **Silent overwrite is the
   policy:** cohort reports are recomputable from inputs (unlike
   immutable baseline snapshots), so a second run with the same
   inputs simply replaces the previous report. No `--overwrite` flag
   exists.
9. **If `--explain-flag` set and the named flag triggered,** write
   the explain JSONL alongside the report at
   `<report-path>.explain.jsonl`. (See "Explain mode" below for
   per-flag row shape.)

### Adversarial flags

Each flag is a deterministic predicate over the deltas. The flag set
ships with the skill and is fixed in v1; adding flags requires a spec
update. Each flag has a stable name (used in `--explain-flag`) and a
human-readable explanation in the output.

**Threshold semantics — single rule for all metrics:** every threshold
is a **relative-percent** comparison: `cohort > control * 1.10` means
"cohort is at least 10% larger than control on this metric." This rule
holds whether the underlying metric is a count (throughput), a ratio
(rework_rate, defect_ratio), or a percentile (cycle_time_p50,
flow_efficiency_p50). Absolute-point deltas are NOT used. Comparisons
are performed on **un-rounded floats**; the rounded values appear in
`evidence` for human reading but never determine flag emission.

Flag evaluation skips any flag whose required metrics are `null` on
either side (e.g. `rework_rate` is `null` when throughput is 0;
percentile metrics are `null` when n is 0). **Flag evaluation also
skips any flag whose comparator (right-hand-side) metric is exactly
0** — the relative-percent rule has no meaning against a zero
denominator (`X >= 0 * 1.10` is `X >= 0`, vacuously true for any
non-negative metric; `X <= 0 * 0.90` is `X <= 0`, only true at zero).
Skipped flags do not appear in `flags[]`; a `notes` entry records
`"flag-skipped: <name>: zero comparator"` for each. The `small-cohort`
flag is the only one that can emit on a zero-throughput cohort.

| Flag name | Triggers when | Requires baseline? |
|---|---|---|
| `throughput-up-rework-up` | `cohort.throughput_per_week >= control.throughput_per_week * 1.10` AND `cohort.rework_rate >= control.rework_rate * 1.10`. The classic DORA 2025 warning sign — gains in volume bought with quality. | No (within-window). |
| `throughput-up-rework-up-vs-baseline` | `cohort.throughput_per_week >= baseline.throughput_per_week * 1.10` AND `cohort.rework_rate >= baseline.rework_rate * 1.10`. Same shape, cross-time. | Yes. |
| `cycle-time-down-defect-ratio-up` | `cohort.cycle_time_hours.p50 <= control.cycle_time_hours.p50 * 0.90` AND `cohort.defect_ratio >= control.defect_ratio * 1.10`. Faster but worse. | No. |
| `flow-efficiency-down-cohort` | `cohort.flow_efficiency.p50 <= control.flow_efficiency.p50 * 0.90`. AI cohort is spending proportionally more time in wait states than control — possibly stuck in review. | No. |
| `small-cohort` | `cohort.throughput < 30` OR `cohort.throughput < 0.20 * total.throughput`. Statistical-significance hedge: 30 is the smallest cohort size at which `statistics.quantiles(method="exclusive", n=100)` produces stable p90 values across re-samplings; 20% is the smallest share at which the cohort-vs-control denominator on the control side is at least 4× the cohort side (basic sample-size hygiene). Always emitted when applicable; not an "AI is bad" flag. | No. |

The `flags` array in output contains one object per triggered flag:
`{ name, message, evidence }` where `evidence` lists the metric values
that triggered (rounded to 4dp per flow-metrics canonicalization, but
the threshold itself was applied on un-rounded floats).

**Per-week normalization.** `throughput_per_week = throughput /
(window.days / 7)` applies to every throughput comparison, both
within-window and cross-time. Within-window the denominator is the
same on both sides so it's mathematically a no-op for ordering; the
ratio still matters numerically and is shown in `evidence`. Cross-time
(against a baseline with a different window length) the normalization
is load-bearing.

**Cross-time denominator caveat for `cohort_vs_baseline`.** Cohort
metrics in the current window are computed over the cohort *subset* of
delivered-in-window issues. Baseline metrics are computed over the
entire baseline population (the baseline has no cohort split by
design). The `cohort_vs_baseline` deltas therefore compare "cohort-now
vs population-then", NOT "cohort-now vs cohort-then".

**Secular-trend caveat.** A positive `cohort_vs_baseline.rework_rate`
delta could mean "AI causes rework" OR "rework rose generally between
baseline and now." The toolchain emits `control_vs_baseline` as the
secular-trend control: it answers the same delta for the non-AI
subset over the same window pair. Interpretation rule (documented in
`notes` on every baseline-paired run):
`"secular-trend: interpret cohort_vs_baseline.<metric> net of
control_vs_baseline.<metric> — the latter captures secular trend on
the same window pair"`. The literal string `<metric>` is a downstream-
parseable placeholder; per-metric expansion is deferred to v2 (would
require a metric-specific notes line per delta). A "net delta" metric
(cohort_vs_baseline − control_vs_baseline) is also deferred to v2;
v1 leaves the arithmetic to the reader / to `ai-value-report`.

Flag thresholds (10%, 30, 0.20) are **fixed in v1**, not configurable.
Configurability is a v2 concern.

### Output JSON shape

```json
{
  "meta": {
    "skill": "ai-adoption-cohort",
    "schema_version": "1.0",
    "scope": {
      "kind": "project",
      "project_key": "PROJ",
      "team": "Foo",
      "program_id": null,
      "portfolio_id": null
    },
    "window": { "from": "2026-04-01", "to": "2026-06-30" },
    "cohort": {
      "kind": "label",
      "raw": "label:ai-assisted",
      "resolved_jql": "labels = \"ai-assisted\""
    },
    "baseline_file": ".context/ai-baseline/PROJ_Team-Foo-2026-04-01-90d.json",
    "baseline_snapshot_id": "<sha>",
    "generated_at": "2026-07-01T08:00:00Z",
    "upstream_flow_metrics_schema_version": "1.0"
  },
  "current": { /* full flow-metrics aggregate JSON for current window with cohort_breakdown */ },
  "deltas": {
    "cohort_vs_control":   { /* metric → delta */ },
    "cohort_vs_baseline":  { /* metric → delta — omitted when no --baseline-file */ },
    "control_vs_baseline": { /* metric → delta — omitted when no --baseline-file */ }
  },
  "flags": [
    {
      "name": "throughput-up-rework-up",
      "message": "AI cohort delivered 22% more issues per week than control, but reworked 35% more before delivery. DORA 2025 names this pattern as AI inflating short-term volume at the cost of quality. Review the explain output for the issues driving each side.",
      "evidence": {
        "cohort_throughput_per_week": 12.4,
        "control_throughput_per_week": 10.2,
        "cohort_rework_rate": 0.62,
        "control_rework_rate": 0.46
      }
    }
  ],
  "notes": [
    "cohort size: 31 delivered-in-window issues (22% of total throughput).",
    "current window does not overlap baseline window (baseline ended 2026-03-31, current starts 2026-04-01).",
    "state_config_sha and issuetype_config_sha match between baseline and current.",
    "cohort_vs_baseline: cohort subset of current window vs entire baseline population (baseline has no cohort split by design)."
  ]
}
```

Output canonicalization rules (sorted keys, 4-dp floats, fixed bucket
order in any nested `flow_distribution`) inherit from `flow-metrics`.

### Errors and exit codes

- `0` success.
- `1` user aborted.
- `2` **pre-upstream** validation / integrity error: missing
  `--cohort`; bad cohort format; bad scope flags; window overlapping
  baseline; config sha mismatch with baseline; baseline scope mismatch;
  baseline snapshot-id integrity failure; baseline schema version
  mismatch; unknown `--explain-flag` name (the *name* — not whether
  the flag triggered); `flow-metrics` not discoverable.
- `3` upstream skill error: `flow-metrics` returned non-zero. Stderr
  relayed verbatim.
- `4` **post-evaluation** semantic error: `--explain-flag X` was
  passed but flag X did not trigger in this run, so there is nothing
  to explain. The report and JSONL are still written (the report
  unconditionally, the JSONL only if any flag triggered); the exit
  code signals that the user's stated intent (explain a specific
  flag) was not satisfied.

The distinction matters because exit `2` precedes any upstream call
(contract test `test_validation_error_exits_2_before_any_upstream_call`),
whereas exit `4` happens after the full pipeline runs and is therefore
expected to coexist with normal output files on disk.

### Explain-mode row shapes

The explain JSONL contains one row per issue, sorted by `key` ascending
(codepoint). Each row includes a fixed set of fields depending on which
flag is being explained. Common fields on every row: `key`, `summary`,
`delivered_at`, `team`.

| Flag name | Additional fields per row |
|---|---|
| `throughput-up-rework-up` | `cohort: true`, `rework_count`, `cycle_time_hours` |
| `throughput-up-rework-up-vs-baseline` | `cohort: true`, `rework_count`, `cycle_time_hours`, `baseline_rework_rate_overall` (the population-level baseline value, identical across rows — included so each row is self-contained) |
| `cycle-time-down-defect-ratio-up` | `cohort: true`, `issuetype_at_delivery`, `issuetype_bucket`, `cycle_time_hours`, `is_defect` (boolean derived from `issuetype_bucket == "defect"`) |
| `flow-efficiency-down-cohort` | `cohort: true`, `cycle_time_hours`, `flow_efficiency`, `wait_time_hours` (computed from `cycle_time_hours * (1 - flow_efficiency)` for transparency) |

Every row's per-issue fields come from `flow-metrics --per-issue` rows
filtered to the cohort subset. The explain skill therefore invokes
`flow-metrics --per-issue --output <tmp.jsonl>` exactly once when
`--explain-flag` is set and the flag triggered; the report still uses
the aggregate-mode flow-metrics output.

### Read-only contract — upstream-skill allowlist

The skill invokes exactly two `flow-metrics` modes:

- **Aggregate mode** (always): the report's `current` block comes from
  this call. Forwarded flags (exact allowlist):
  - `--from <YYYY-MM-DD>`, `--to <YYYY-MM-DD>` (resolved window).
  - Exactly one scope flag: `--project`, `--program-id`,
    `--portfolio-id`.
  - `--team <NAME>` when this skill received `--team`.
  - `--state-config <FILE>`, `--issuetype-config <FILE>` when passed.
  - `--cohort-jql "<resolved_jql>"`.
  - `--metrics cycle_time,lead_time,throughput,wip,flow_load,rework_rate,flow_time,flow_efficiency,flow_distribution,defect_ratio`
    — the metric *request tokens* per flow-metrics' `--metrics LIST`
    contract (its Inputs table). Each token requests one or more
    fields in the output `aggregates` block (e.g. `cycle_time` produces
    `aggregates.cycle_time_hours`, `flow_time` produces
    `aggregates.flow_time_hours`). Pinning the explicit list locks
    behavior against a future flow-metrics default change. The list
    includes `flow_time` and `flow_load` even though no flag references
    them directly, because `ai-value-report` consumes them downstream
    from the embedded `current` block.
  - `--format json`.
- **Per-issue mode** (only when `--explain-flag` is set AND the named
  flag triggered): same flags as above plus `--per-issue --output
  <tmp.jsonl>`. The cohort skill reads the JSONL, filters to cohort
  rows, computes per-flag-specific fields, then writes the explain
  JSONL.

Explicitly forbidden upstream flags: `--no-cache`, `--align-filter`,
`--jql` (cohort skill's own `--cohort-jql` is forwarded, not the user's
`--jql`), `--verbose` (this skill manages its own stderr forwarding).

It never invokes `jira` / `jira-align` directly. The contract test
records every subprocess invocation and asserts only `flow-metrics`
calls are made, with argv matching this allowlist.

### Snapshot-id recompute (for baseline integrity)

When verifying the loaded baseline's `snapshot_id` (pipeline step 2),
the cohort skill recomputes:

```
expected_snapshot_id = sha256(json.dumps({
  "envelope_schema_version":  baseline.meta.schema_version,
  "rollout_date":             baseline.meta.rollout_date,
  "baseline_window":          baseline.meta.baseline_window,
  "scope":                    baseline.meta.scope,
  "state_config_sha":         baseline.flow_metrics.meta.state_config_sha,
  "issuetype_config_sha":     baseline.flow_metrics.meta.issuetype_config_sha,
  "upstream_schema_version":  baseline.flow_metrics.meta.schema_version
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

`envelope_schema_version` is read from `baseline.meta.schema_version`
(this is the baseline envelope's own version); the upstream version is
read from `baseline.flow_metrics.meta.schema_version` (NOT from
`baseline.meta.upstream_flow_metrics_schema_version` — that field is a
copy with a different key name, used only for compatibility detection).
This matches the formula in `ai-adoption-baseline`'s spec verbatim;
mismatch in either field path is an implementation bug, not a
spec ambiguity.

### `total.throughput` referent for `small-cohort`

The `small-cohort` flag's `cohort.throughput < 0.20 * total.throughput`
clause uses `total.throughput = current.aggregates.throughput`
(top-level flow-metrics aggregate throughput, which is the count of
all delivered-in-window issues — cohort plus control). NOT
`cohort.throughput + control.throughput` (which excludes any
boundary-case items if flow-metrics counts them once at the top level
but differently in the breakdown).

### `wait_time_hours` derivation (cohort-side only)

`wait_time_hours` is not a flow-metrics per-issue field. The cohort
skill derives it from flow-metrics' per-issue rows when emitting the
`flow-efficiency-down-cohort` explain JSONL:

```
wait_time_hours =
  cycle_time_hours * (1 - flow_efficiency)   if both are non-null
  null                                        otherwise
```

(Derivation: `cycle = active + wait` and `flow_efficiency = active /
cycle`, so `wait = cycle * (1 - flow_efficiency)`.) This formula
assumes `flow_efficiency` is a **ratio in `[0, 1]`** per flow-metrics'
contract (its Metric definitions row for Flow Efficiency); if a future
flow-metrics minor version emits a percentage instead, this derivation
breaks and the upstream-schema check would catch a major bump but not
a unit change within a minor. The cohort skill therefore asserts
`0 <= flow_efficiency <= 1` per row and exits 3 on out-of-range
values. This is a cohort-skill-side computation; flow-metrics itself
does not expose `wait_time_hours` in v1.

### Cross-skill invocation — name, not path

Same posture as `ai-adoption-baseline`. The discovery probe locates
`flow-metrics` by name across IDE-specific install paths.

## Contract tests

### Inputs and cohort resolution

- **`test_cohort_required`** — no `--cohort` exits 2.
- **`test_cohort_label_form`** — `--cohort label:foo` resolves to
  `labels = "foo"`.
- **`test_cohort_field_form`** — `--cohort 'field:AI Usage=High'`
  resolves to `"AI Usage" = "High"`.
- **`test_cohort_jql_form`** — `--cohort 'jql:labels in (a, b)'`
  resolves verbatim.
- **`test_cohort_label_with_space_exits_2`** — `--cohort "label:foo bar"`
  exits 2 (Jira label charset).
- **`test_cohort_field_with_embedded_quote_exits_2`** — exits 2.
- **`test_cohort_unknown_prefix_exits_2`** — `--cohort heuristic:foo`
  exits 2.
- **`test_cohort_label_with_dot_and_colon_ok`** — `--cohort
  label:team.ai-assisted` resolves to `labels = "team.ai-assisted"`.
- **`test_cohort_label_with_backslash_exits_2`** — `--cohort
  'label:foo\bar'` exits 2.
- **`test_cohort_field_value_with_equals_in_url`** — `--cohort
  'field:URL=http://example.com?x=y'` resolves to `"URL" =
  "http://example.com?x=y"` (split on FIRST `=`).
- **`test_cohort_field_value_with_comma_safe`** — `--cohort
  'field:Tags=a,b,c'` resolves to `"Tags" = "a,b,c"` (commas inside
  quotes are JQL-safe).
- **`test_cohort_field_value_with_backslash_exits_2`**.
- **`test_cohort_jql_with_order_by_exits_2`** — `--cohort 'jql:labels
  = "foo" ORDER BY created'` exits 2.
- **`test_cohort_jql_with_unbalanced_parens_exits_2`**.
- **`test_cohort_jql_with_trailing_semicolon_exits_2`**.
- **`test_cohort_field_whitespace_stripped`** — `--cohort 'field:
   AI Usage  =  High '` resolves to `"AI Usage" = "High"`.

### Window

- **`test_default_window_last_90_days`** — same shape as `flow-metrics`.
- **`test_window_overlap_with_baseline_exits_2`** — baseline window
  ends 2026-03-31; current `--from 2026-03-15` exits 2 naming both
  windows.
- **`test_window_adjacent_to_baseline_ok`** — baseline ends 2026-03-31;
  current `--from 2026-04-01` is allowed (strictly after).

### Baseline integration

- **`test_no_baseline_omits_cross_time_deltas`** — without
  `--baseline-file`, `deltas.cohort_vs_baseline` and
  `deltas.control_vs_baseline` keys are absent (not null).
- **`test_baseline_config_mismatch_exits_2`** — `state_config_sha`
  in baseline doesn't match current run's → exit 2 naming which sha
  differs.
- **`test_baseline_snapshot_id_recorded`** — `meta.baseline_snapshot_id`
  matches the baseline's `meta.snapshot_id`.
- **`test_baseline_scope_mismatch_exits_2`** — baseline scope is
  `{kind: "project", project_key: "PROJ", team: "Foo", ...}`; current
  invocation is `--project PROJ --team Bar` → exit 2 naming both
  scopes.
- **`test_baseline_tampered_snapshot_id_exits_2`** — hand-edit the
  baseline file to change a number; the recomputed snapshot_id no
  longer matches the recorded one → exit 2.
- **`test_baseline_schema_version_mismatch_exits_2`** — baseline
  with `meta.schema_version: "0.9"` → exit 2.

### Deltas

- **`test_cohort_vs_control_delta_per_metric`** — for each scalar
  metric (throughput, rework_rate, defect_ratio, flow_load), the
  delta is `cohort_value - control_value` and a percent
  `(cohort - control) / control` (null when control is 0).
- **`test_cohort_vs_control_percentile_delta`** — for each
  percentile-bearing metric (cycle_time, lead_time, flow_efficiency),
  the delta is `{ p50_delta, p75_delta, p90_delta }` against control.
- **`test_baseline_delta_throughput_normalized_per_week`** — cross-time
  throughput comparisons divide by window-length-in-weeks (90-day vs
  180-day baselines must be comparable).

### Adversarial flags

- **`test_throughput_up_rework_up_at_exactly_10pct_emits`** —
  fixture: `cohort_throughput_per_week = control_throughput_per_week
  * 1.10` and `cohort_rework_rate = control_rework_rate * 1.10` —
  both equal the threshold exactly. Flag emitted (`>=`).
- **`test_throughput_up_rework_up_just_below_threshold_not_emitted`**
  — `1.099` on either side → not emitted.
- **`test_threshold_evaluated_on_unrounded_floats`** — fixture: raw
  cohort rework rate `0.45000001`, control `0.40909091`. Ratio is
  `1.10000000...` — at threshold. The `evidence` rounds to `0.45`
  and `0.4091` (4dp) which when compared rounded would round-trip to
  exactly 1.10; the rounded comparison is consistent. Different
  fixture: raw `0.45000000`, control `0.41000000`. Ratio is
  `1.0976...` — below threshold; flag NOT emitted, even though
  rounded `evidence` rounding could nudge a reader to expect
  triggering.
- **`test_throughput_up_rework_up_vs_baseline_requires_baseline`** —
  without `--baseline-file`, the cross-time variant is absent from
  flags even if within-window pattern triggers.
- **`test_cycle_time_down_defect_ratio_up_emitted_at_threshold`** —
  cohort p50 = control * 0.90 AND cohort defect_ratio = control *
  1.10 → emitted.
- **`test_flow_efficiency_down_cohort_emitted`** — analogous.
- **`test_small_cohort_emitted_when_under_30`** — cohort throughput
  29. Flag emitted (the threshold is `< 30`, not `< 20`).
- **`test_small_cohort_emitted_when_under_20pct`** — cohort
  throughput 100, total throughput 600. 100/600 ≈ 16.7%. Flag
  emitted.
- **`test_empty_cohort_only_emits_small_cohort`** — cohort throughput
  0. `cohort.rework_rate` is null, `cohort.cycle_time_hours.p50` is
  null. Only `small-cohort` flag emitted; all others skipped (their
  metrics are null on cohort side).
- **`test_zero_control_rework_rate_skips_flag`** — control rework_rate
  = 0.0 (flawless control population). `throughput-up-rework-up` is
  skipped (zero comparator); `notes` records `"flag-skipped:
  throughput-up-rework-up: zero comparator"`.
- **`test_zero_baseline_throughput_skips_cross_time_flag`** — baseline
  throughput_per_week = 0. `throughput-up-rework-up-vs-baseline`
  skipped; recorded in notes.
- **`test_zero_control_cycle_time_does_not_trip_cycle_down_flag`** —
  control p50 = 0. The `<=` comparison against `0 * 0.9 == 0`
  threshold collapses to "cohort p50 <= 0"; spec skips the flag.
- **`test_flag_evidence_uses_4dp_rounding`** — flag's `evidence`
  values are rounded to 4 decimal places (matches flow-metrics
  canonicalization).
- **`test_flag_evidence_threshold_passed_on_unrounded`** — even when
  the rounded evidence would imply not-triggering, the flag fires
  iff the un-rounded inequality holds.

### Explain mode

- **`test_explain_writes_jsonl_file_when_flag_triggers`** —
  `--explain-flag throughput-up-rework-up`, flag triggers. Produces
  `<output-path>.explain.jsonl` with one row per cohort-delivered-in-
  window issue, fields matching the per-flag shape table.
- **`test_explain_unknown_flag_exits_2`** — pre-upstream validation;
  zero upstream invocations recorded.
- **`test_explain_flag_did_not_trigger_exits_4`** — when the named
  flag did NOT trigger in this run, the report is still written and
  the skill exits 4 (NOT 2). The explain JSONL is absent.
- **`test_explain_small_cohort_exits_2`** — `--explain-flag
  small-cohort` exits 2 at pre-upstream validation with message
  `"flag 'small-cohort' is not explainable (every cohort issue would
  be in the list; see report for the cohort size)"`. The flag name
  is recognized as legal-but-non-explainable, distinct from "unknown
  flag" which uses a different message.
- **`test_explain_invokes_flow_metrics_per_issue_once`** — when
  `--explain-flag` triggers, exactly one additional
  `flow-metrics --per-issue` subprocess call occurs (in addition to
  the aggregate-mode call).

### Output canonicalization

- **`test_stable_output_for_same_inputs`** — two runs with identical
  inputs (same flow-metrics fixture, same baseline) produce
  byte-identical JSON output after `generated_at` normalization.
- **`test_flags_sorted_by_name`** — multiple flags emit in
  alphabetical order of `name`.

### Read-only contract

- **`test_only_flow_metrics_invoked`** — only `flow-metrics`
  subprocess calls; no `jira` / `jira-align`.
- **`test_per_issue_only_invoked_with_explain_flag`** — without
  `--explain-flag`, `flow-metrics --per-issue` is not called.

### Errors

- **`test_upstream_flow_metrics_failure_exits_3`**.
- **`test_validation_error_exits_2_before_any_upstream_call`** —
  bad-cohort-format exits 2 with zero upstream invocations.

## Non-goals

- The skill **will not** infer cohort membership from data
  (commit-message heuristics, PR-author rules, etc.). Cohort sourcing
  is always explicit.
- It **will not** propose new flags or adjust thresholds at runtime.
- It **will not** produce Markdown or HTML (`ai-value-report`'s job).
- It **will not** write to Jira / Jira Align (annotate flagged issues,
  add comments, etc.).
- It **will not** retry or escalate on flow-metrics errors.
- It **will not** auto-discover a baseline file. The caller passes it
  explicitly.
- It **will not** support multi-baseline comparison (e.g. comparing
  against both a pre-AI and a mid-rollout baseline simultaneously).
  Deferred to v2.

## Decisions

1. **`--cohort` syntax is prefixed** (`label:`, `field:`, `jql:`). No
   "auto-detect what they meant"; users name the source.
2. **Cohort window must be strictly after baseline window.** Overlap
   pollutes the comparison; the spec refuses to compute it.
3. **State / issuetype config shas must match the baseline.** Without
   this check, the comparison silently uses different canonicalizations.
4. **All flag thresholds are relative-percent** in v1 — `cohort >
   control * 1.10` (or `<= 0.90` for "down" predicates) regardless of
   whether the underlying metric is a count, a ratio, or a percentile.
   Absolute-point thresholds were considered and rejected because
   they don't generalize across metric types (10 percentage points of
   rework_rate vs 10 percentage points of defect_ratio mean different
   things). Configurability is v2.
5. **Per-week normalization** applies to every throughput comparison,
   not just cross-time. `throughput_per_week = throughput / (window.days
   / 7)`. Within-window the denominator is the same on both sides; the
   value is still shown in `evidence` for transparency.
6. **`--explain-flag` accepts exactly one flag name in v1.** A
   multi-flag explain (e.g. `--explain-flag all`) is deferred to v2
   because per-flag explain JSONLs have flag-specific row shapes
   (different field sets per flag); merging shapes into one JSONL
   would either inflate every row to the union or require a discriminator
   column. v1 forces one re-run per flag to keep the row shape stable.
7. **Zero-comparator flag-skip rule** (documented above in
   "Adversarial flags"): any flag whose right-hand-side comparator
   metric is exactly 0 is skipped with a `notes` entry. Prevents
   vacuous flag firing on degenerate control / baseline values.
8. **Upstream-schema check across baseline and current.** Major
   mismatch between `baseline.flow_metrics.meta.schema_version` and
   `current.meta.schema_version` → exit 2; minor drift recorded in
   notes.
9. **`small-cohort` is a hedge, not an indictment.** Always emitted
   when applicable, alphabetized alongside the other flags. Downstream
   `ai-value-report` skill is expected to soften any AI-claim
   conclusion when `small-cohort` is present.
10. **Explain mode is opt-in.** Per-issue JSONL is bigger and slower;
    the default cohort run is aggregate-only.
11. **Flags array is sorted alphabetically by `name`** for stable
    output.
12. **No flag suppression flag in v1.** If a team wants to ignore a
    flag, they ignore it at the report-rendering layer
    (`ai-value-report`).

## Deferred to v2

- **Multi-baseline comparison** for trend lines (e.g., q1-baseline,
  q2-baseline, q3-baseline).
- **Configurable flag thresholds** via a config file.
- **New flag types** for post-delivery rework, deploy-related signals
  (gated on `flow-metrics`'s own post_delivery_rework_rate v2 work).
- **Plug-in flag definitions** loaded from a config (lets teams write
  their own).
- **Multi-cohort comparison** (e.g., `--cohort label:claude` vs
  `--cohort label:copilot`).

## Acceptance criteria

- [ ] All Contract tests pass on macOS and Linux under Python 3.10,
      3.11, 3.12.
- [ ] SKILL.md follows the dropkit pattern.
- [ ] `manifest.json` declares
      `deps.skills: [{name: "flow-metrics"}, {name: "ai-adoption-baseline"}]`
      (the latter is a read-time dep — the cohort skill loads baseline
      files written by it).
- [ ] One real-team run with a real cohort label produces a report
      that matches a hand-computed reference for at least one flag.
- [ ] Output JSON validates against
      `references/cohort.schema.json`.
- [ ] Skill lives at `skills/workflows/ai-adoption-cohort/`.
