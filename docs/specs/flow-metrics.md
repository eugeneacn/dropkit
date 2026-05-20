# Spec: flow-metrics

- **Status:** Approved
- **Owner:** eugeneacn
- **Plan:** _not yet drafted_
- **Constrained by:** none (dropkit has no ADRs yet)
- **Review history:** 6 adversarial review rounds (2026-05-19). Round 1 found 7 blockers / 14 majors; round 2: 4 blockers / 12 majors / 2 minors; round 3: 0 blockers / 5 majors / 8 minors; round 4: 0 blockers / 2 majors / 3 minors; round 5: 0 blockers / 2 majors / 1 minor; round 6: 0 blockers / 0 majors / 1 minor (resolved). Terminal-clean.

> **Spec contract:** this document defines what "done" means for the
> `flow-metrics` workflow skill. The implementing PR must match this spec
> or update it. Tests must be derivable from it.

## What this is

A read-only workflow skill that computes a fixed catalog of DORA and Flow
Framework metrics for a Jira project / team / Jira Align program / Jira Align
portfolio over a time window. It orchestrates the existing `jira` and
`jira-align` skills, walks status-change history to derive time-in-state, and
emits a uniform JSON (or CSV) report.

The skill is the **foundation layer** of the AI-adoption metrics
stack. The downstream `ai-adoption-report` skill consumes
`flow-metrics` JSON outputs and renders deltas across three modes —
`baseline` (one scope, two windows), `cohort` (within-window AI vs
control split), and `program` (rollup across scopes for one window).
`flow-metrics` does all the math; the report pairs files and
subtracts.

## Why

Three reasons, in priority order:

1. **One canonical definition.** Today, teams compute "cycle time" and
   "rework rate" with bespoke Jira filters, vendor dashboards (LinearB,
   Jellyfish, Plandek, Faros), or hand-rolled scripts. Numbers don't
   reconcile across teams because the cohorting and state-mapping rules
   vary. A repo-local, manifest-driven calculation eliminates that drift.
2. **Every downstream AI-adoption metric depends on it.** Without a stable
   flow-metrics layer, baseline-vs-cohort comparisons amount to comparing
   two different black boxes. DORA 2025's central finding — that AI
   inflates individual throughput while *organisational* metrics stay flat
   or get worse on stability — only shows up if rework and defect rate are
   computed the same way before and after.
3. **No new REST clients.** All Jira / Jira Align access goes through the
   existing skills, which already handle auth, pagination, retries, and
   ADF wrapping. This skill is pure choreography on top of those.

## Users and use cases

In priority order — first is the load-bearing one:

1. **Engineering manager wants their team's flow metrics for the last 90 days.**
   `flow-metrics --project PROJ --team "Foo" --from 2026-02-19 --to 2026-05-19`.
   Result: a JSON report with cycle time, lead time, throughput, WIP,
   rework rate, defect ratio, broken down by Jira issuetype. Pure read on Jira.
2. **Cohort prep for `ai-adoption-report cohort`.**
   `flow-metrics --project PROJ --from ... --to ... --cohort-jql "labels = ai-assisted" --output q4.json`.
   Result: aggregate JSON with a `cohort_breakdown` block. The report's
   cohort mode reads that block directly. (Per-issue output via
   `--per-issue --output rows.jsonl` is also supported; consumers that
   need per-issue inspection re-aggregate from the rows.)
3. **Value-stream / ART rollup via Jira Align.**
   `flow-metrics --program-id 42 --from ... --to ...`.
   Result: Flow Distribution, Flow Load, Flow Efficiency, and per-team
   throughput across all teams in program 42. Joins Jira (for time-in-state)
   with Jira Align (for program/team mapping).
4. **Portfolio-level snapshot for `ai-adoption-report baseline`.**
   `flow-metrics --portfolio-id 7 --from 2025-08-19 --to 2025-11-19 --output .context/baseline.json`.
   Result: same metrics, rolled up per team within the portfolio, ready
   to be paired with a later window by the report's baseline mode.
5. **Quick sanity check, one project, default window.**
   `flow-metrics --project PROJ`.
   Result: last-90-days JSON to stdout. Should "just work" with the
   shipped default state config.

## Behavior

### Inputs

CLI flags only — no input files except the optional state-transitions config:

```
flow-metrics --project KEY | --team NAME | --program-id ID | --portfolio-id ID
             [--from ISO --to ISO]
             [--jql "<extra clause>"]
             [--align-filter "<OData expr>"]
             [--cohort-jql "<JQL expr>"]
             [--metrics m1,m2,...]
             [--state-config FILE]
             [--issuetype-config FILE]
             [--team-field-override ID]
             [--align-join-field NAME]
             [--align-teams-path PATH]
             [--include-subtasks]
             [--format json|csv]
             [--output FILE]
             [--per-issue]
             [--no-cache]
             [--verbose]
```

| Flag | Meaning |
|---|---|
| `--project KEY` | Jira project key. Mutually exclusive with `--program-id` / `--portfolio-id`. |
| `--team NAME` | Optional sub-scope within a project. Resolution rule depends on `team_field.kind` (`single_value` or `array`) — adds a JQL clause matching the team field value to the scope query. Mutually exclusive with the other scope flags except `--project`. |
| `--program-id ID` | Jira Align program ID. Triggers a Jira Align join for team mapping. |
| `--portfolio-id ID` | Jira Align portfolio ID. Triggers a rollup across constituent programs/teams. |
| `--from ISO`, `--to ISO` | Window bounds, `YYYY-MM-DD`. **Both inclusive of the named day.** Internally the window is `[from 00:00 UTC, (to + 1 day) 00:00 UTC)`. Default: `--to = today (UTC)`, `--from = today − 90 days`. All Jira / Jira Align timestamps are converted to UTC before comparison. |
| `--jql "<expr>"` | Extra JQL ANDed into the issue query. Always wrapped: the underlying query is `(<scope clause>) AND (<--jql expr>)`. The user's expression is parenthesized verbatim regardless of internal operator precedence. |
| `--align-filter "<expr>"` | Extra OData ANDed into Jira Align queries with the same parenthesization rule. |
| `--cohort-jql "<expr>"` | Issues matching this JQL are marked `cohort: true`. See "Cohort behaviour" below for the exact interaction with `--per-issue`. |
| `--metrics LIST` | Comma list. Default: `all`. Names: `cycle_time, lead_time, throughput, wip, flow_load, rework_rate, flow_time, flow_efficiency, flow_distribution, defect_ratio`. Unrequested metrics are **omitted** from `aggregates` (not emitted as `null`); a `meta.metrics_requested` field records the resolved list. Requesting `flow_distribution` does not auto-include `defect_ratio` and vice versa — they're separate keys. |
| `--state-config FILE` | JSON file mapping the project's raw statuses to canonical states (see "State configuration" below). Defaults to the shipped `references/states.default.json`. |
| `--issuetype-config FILE` | JSON file mapping issuetypes to Flow Distribution buckets (`feature/defect/debt/risk/subtask`). Defaults to `references/issuetypes.default.json`. |
| `--team-field-override ID` | Override `team_field.id` from the state config for this run. Useful when one team uses a non-standard field. |
| `--align-join-field NAME` | Override the Jira ↔ Jira Align join field for this run. Defaults to the `align_join_field` entry in the state config; if neither is set and Jira Align scope is requested, exit 2. |
| `--align-teams-path PATH` | Override the Jira Align endpoint used to enumerate teams in a program. Default: `programs/<id>/teams`. The override must match one of the four allowlisted `jira-align` `raw GET` exact path patterns (`programs/<id>`, `programs/<id>/teams`, `portfolios/<id>`, or `portfolios/<id>/programs`); paths containing `..` or starting with `/` are rejected with exit 2. Response shape is validated after the call: every element must be a JSON object with at least an `id` field; otherwise exit 3 with `"unexpected response shape from <path>"`. |
| `--include-subtasks` | Include issues with `issuetype` in the `subtask` bucket when computing throughput, cycle time, lead time, flow efficiency, rework rate. Default: **false** (subtasks are excluded by all aggregates except Flow Distribution, where their share is reported separately). |
| `--format` | `json` (default) or `csv`. |
| `--output FILE` | Write to file instead of stdout. Required for `--per-issue`. File is path-validated: relative paths resolve against cwd; absolute paths are accepted but cannot escape into `/etc`, `/sys`, `/proc`, or the OS-equivalent system roots (the implementation rejects writes inside any of these roots with exit 2). |
| `--per-issue` | Emit one row per issue with all derived fields, instead of aggregates. JSONL on disk. See "Cohort behaviour" for interaction with `--cohort-jql`. |
| `--no-cache` | Bypass the on-disk cache (see Caching). |
| `--verbose` | Debug logging (state-transition walks, cache hits, upstream skill invocations). |

**Exactly one** of `--project`, `--program-id`, `--portfolio-id` must be
provided. `--team` is only valid with `--project`.

### Cohort behaviour

When `--cohort-jql` is set, the skill runs the cohort query once against
the same scope+window and stores the matching issue-key set in memory.
Every issue in the main result set gets a `cohort` boolean indicating
membership. The two output modes differ:

- **Aggregate mode (default):** emit a `cohort_breakdown` section
  containing `cohort` and `control` sub-objects, each with the same
  metric shape as `aggregates`. `per_team` rows are NOT split by cohort
  in v1 (deferred).
- **Per-issue mode (`--per-issue`):** every JSONL row includes
  `"cohort": true|false`. `cohort_breakdown` is **NOT** emitted in this
  mode — downstream consumers re-aggregate from the per-issue rows.
  This keeps the breakdown logic in exactly one place.

When `--cohort-jql` matches zero issues, the cohort sub-object has
`throughput: 0` and every percentile is `null`; the skill exits 0.

### State configuration

Status names vary per Jira workflow. The skill needs a config mapping the
project's raw statuses to canonical states. Without it, time-in-state math
isn't portable.

Schema (`states.default.json`):

```json
{
  "canonical_states": {
    "backlog":     ["Backlog", "To Do", "Open"],
    "in_progress": ["In Progress", "In Development"],
    "in_review":   ["In Review", "Code Review", "Ready for Review"],
    "in_test":     ["QA", "Testing", "In Test"],
    "done":        ["Done", "Closed", "Resolved"],
    "cancelled":   ["Won't Do", "Won't Fix", "Cancelled", "Duplicate"]
  },
  "active_states":   ["in_progress"],
  "wait_states":     ["backlog", "in_review", "in_test"],
  "terminal_non_delivery_states": ["cancelled"],
  "rework_signals": [
    { "from": ["in_progress", "in_review", "in_test", "done"], "to": ["backlog"] },
    { "from": ["in_review", "in_test", "done"],                "to": ["in_progress"] },
    { "from": ["in_test", "done"],                              "to": ["in_review"] },
    { "from": ["done"],                                          "to": ["in_test"] }
  ],
  "commitment_state": "in_progress",
  "delivery_state":   "done",
  "team_field": {
    "id":   "customfield_10001",
    "kind": "single_value"
  }
}
```

**Why `in_review` and `in_test` are `wait_states`, not `active_states`.**
Flow Framework convention is that "active" means *developer hands on
keyboard*, and "wait" means *blocked on someone else's action* (reviewer,
QA, deploy). In a normal Jira workflow, an issue in `In Review` is waiting
for a reviewer; in `In Test` is waiting for QA. Classifying these as
`active` produces degenerate Flow Efficiency values (always close to 1.0)
because no time is recorded against `wait_states` between commitment and
delivery in non-rework flows. A team that wants the alternative
(developer-collaborates-on-review-time, so `in_review` is active) edits
their config.

- `canonical_states` is the raw-name → canonical-name map. Every raw
  status that appears in the data **must** be mapped.
- `active_states` / `wait_states` partition canonical states for Flow
  Efficiency. States not in either partition (e.g. `done`, `cancelled`)
  contribute zero time to both numerator and denominator.
- `terminal_non_delivery_states` enumerates canonical states that close
  an issue *without* counting as delivery. The formal cancelled-in-window
  predicate (defined under "Core population predicates") is: the issue
  has at least one changelog transition INTO any state in this list
  whose timestamp is in window, AND has no first-ever delivery in
  window. Cancelled-in-window issues are **excluded from throughput,
  cycle time, lead time, flow efficiency, and Flow Distribution**, but
  counted in `notes` (`"N issues cancelled in window"`). A
  cancel-then-reopen-still-active-at-`--to` issue satisfies the predicate
  AND is in WIP — both signals are reported, per Decision #29.
- `rework_signals` enumerates backward transitions that count as rework.
  Each backward *transition edge* (one row in the changelog whose
  canonical `from ∈ entry.from` and canonical `to ∈ entry.to`) counts
  exactly once.
- `commitment_state` is the start anchor for Cycle Time. Exactly one
  canonical state.
- `delivery_state` is the end anchor for Cycle Time, Lead Time, and
  Throughput. Exactly one canonical state. Must be disjoint from
  `terminal_non_delivery_states`.
- `team_field` configures the Jira custom field that maps an issue to a
  team for `--team` and `per_team` rollups.
  - `id` is the Jira customfield id (e.g. `customfield_10001`) or a
    field name. Resolved against `jira: raw GET field` at startup; if
    not found, exit 2.
  - `kind` is one of:
    - `single_value` — field holds a scalar (string or `{value: "..."}`).
      `per_team` rows partition issues exactly: `sum(per_team[*].throughput)
      == aggregates.throughput`.
    - `array` — field holds a list of values; an issue belongs to every
      named team in the list. **`per_team` rows then overlap** — an
      issue with `[Foo, Bar]` is counted in both teams' rollups, so
      `sum(per_team[*].throughput)` ≥ `aggregates.throughput`. The skill
      sets `meta.per_team_double_counted: true` and adds a `notes`
      entry: `"per_team: K issues belong to multiple teams and are
      counted in each (team_field.kind=array)"`.
  - **`user_picker_group` is deferred to v2** — it would require a
    `raw GET group/member/<group>` call (not in the v1 allowlist) and
    has no natural `per_team` partition. Teams that need
    assignee-based team resolution should configure a `single_value`
    or `array` field instead, or use `--team NAME` with the
    `assignee in membersOf("NAME")` clause spelled out via `--jql`.
  - Optional `--team-field-override <id>` flag lets the user point at a
    different field for one invocation. When set, `--team-field-override`
    is what gets validated against `jira: raw GET field` at startup;
    the config's `team_field.id` is not consulted that run.

**Unmapped-status policy:** if the data contains a raw status not listed
under any `canonical_states` entry, the skill exits 2 with the offending
status name and refuses to compute. No silent inference — wrong
canonicalisation breaks every downstream comparison. **Cancelled-but-
unmapped is the most common failure mode**; the shipped default config
deliberately maps "Won't Do" / "Cancelled" / "Duplicate" so first-run
users on a normal Jira workflow get accurate throughput out of the box.

**State-config integrity validation** runs at startup, before any data
fetch. Each violation exits 2 with a specific message naming the
offending field:

1. `commitment_state` must be exactly one canonical state and present in
   `canonical_states`.
2. `delivery_state` must be exactly one canonical state and present in
   `canonical_states`.
3. `commitment_state != delivery_state`.
4. `delivery_state ∉ terminal_non_delivery_states`.
5. `commitment_state ∉ terminal_non_delivery_states`.
6. `active_states ∩ wait_states == ∅` (a state cannot be both active
   and wait).
7. `delivery_state ∉ (active_states ∪ wait_states)` (delivery is a
   terminal anchor, not a duration bucket).
8. Every canonical name referenced by `active_states`, `wait_states`,
   `terminal_non_delivery_states`, `commitment_state`, `delivery_state`,
   and every `rework_signals[i].from` / `to` entry is a key of
   `canonical_states`. Unreferenced canonical states are allowed.
9. `team_field.id`, if set, is checked against `jira: raw GET field` at
   startup; not found → exit 2.

### Issuetype configuration

Schema (`issuetypes.default.json`):

```json
{
  "feature": ["Story", "Task", "Epic", "Feature"],
  "defect":  ["Bug", "Defect"],
  "debt":    ["Tech Debt", "Refactor"],
  "risk":    ["Risk", "Vulnerability"]
}
```

Unmapped issuetypes go into a `"other"` bucket reported in `notes`. They
do not exit 2 — Flow Distribution is descriptive, not load-bearing for the
other metrics.

### Metric definitions

Each definition is fixed and testable. The implementation must not deviate.

**Core population predicates** (used by every metric below):

- An issue is **delivered-in-window** iff its *first-ever* changelog
  transition into `delivery_state` falls within
  `[from 00:00 UTC, (to+1 day) 00:00 UTC)`. Reopen-and-redeliver does
  **not** create a second delivery — the second `done` entry contributes
  to rework, never to throughput.
- An issue is **cycle-eligible** iff it is delivered-in-window AND the
  issue's changelog contains at least one transition into
  `commitment_state` at any time *at or before* its first-ever delivery.
- An issue is **cancelled-in-window** iff (a) its changelog contains at
  least one transition INTO a canonical state in
  `terminal_non_delivery_states` whose timestamp is in window, AND (b)
  the issue has no first-ever delivery in window (i.e. it is NOT
  delivered-in-window). Cancellation followed by reopen-in-window still
  counts as cancelled-in-window — the team's act of cancelling is what
  matters for the `notes` line. Cancelled-in-window issues are
  **excluded from throughput, cycle time, lead time, flow efficiency,
  and Flow Distribution**; their count goes in `notes`. (An issue
  cancelled-then-reopened that is still active at `--to` is also counted
  in WIP — both signals are reported simultaneously.)
- An issue's **issuetype-at-delivery** is whatever `issuetype` it held at
  its first-ever delivery timestamp (from the changelog `issuetype` field
  if it has been changed, else from the issue's current `issuetype`).

| Metric | Definition | `n` semantics |
|---|---|---|
| **Cycle Time** | For each cycle-eligible issue: `(first-ever delivery_state transition) − (first commitment_state transition that precedes that delivery)`. Reported as median, p75, p90 in hours. Delivered-in-window issues that skipped `commitment_state` are excluded; count goes in `notes` as `"N delivered without commitment-state entry"`. | `n` = cycle-eligible count (≤ throughput). |
| **Lead Time** | For each delivered-in-window issue: `(first-ever delivery_state transition) − (issue.created)`. Includes issues that skipped commitment_state (Lead Time is birth-to-delivery, commitment-independent). Median, p75, p90 in hours. | `n` = throughput. |
| **Throughput** | Count of distinct delivered-in-window issues. A reopened-and-redelivered issue contributes 1 (the first-ever delivery defines membership). | scalar count, no `n` separate from value. |
| **WIP** | Count of issues whose canonical state is in `active_states` at the **WIP-instant** = `(to + 1 day) 00:00 UTC − 1 microsecond` (the last representable instant of the inclusive window). Membership predicate (two clauses): state-at-WIP-instant ∈ `active_states` AND issue is NOT delivered-in-window. Cancelled-in-window status is **not** part of the predicate: a cancelled-then-reopened issue whose state at the WIP-instant is in `active_states` IS in WIP (both clauses hold). Such an issue is also cancelled-in-window per its own predicate; both signals are reported simultaneously, per Decision #29. | scalar count. |
| **Flow Load** | Mean of daily WIP-style samples. Sample set: for each calendar day `d` from `from` to `to` *inclusive* (91 samples for a 90-day window), take one sample at `(d + 1 day) 00:00 UTC − 1 microsecond` — i.e., the end-of-day instant matching the WIP sampling convention. The last sample (for day = `to`) is identically the WIP value, so `flow_load` and `wip` use the same anchor and are directly comparable. Weekends and holidays included by default; `notes` records `"flow_load: 91 samples, weekends included"`. | scalar (float). |
| **Rework Rate** | Numerator: count of backward changelog edges (rows whose canonical `from ∈ rework_signals[i].from` AND canonical `to ∈ rework_signals[i].to`) that occur **at or before each delivered-in-window issue's first-ever delivery**, summed over all delivered-in-window issues. Denominator: throughput. Reported as average backward moves per delivered issue. When throughput is 0, value is `null` (not zero, not NaN). | scalar; denominator stated. |
| **Flow Time** | Alias of Lead Time. Emitted with the same value under the `flow_time_hours` key for Flow Framework parlance. Not a separate computation. | `n` = throughput. |
| **Flow Efficiency** | Per cycle-eligible issue: `active_t / (active_t + wait_t)`, where both terms are computed over `[first commitment_state transition, first-ever delivery_state transition]` (the same interval as Cycle Time). `active_t` = sum of time the issue spent in any canonical state listed in `active_states` during that interval; `wait_t` = sum of time in any canonical state in `wait_states` during that interval. Time in canonical states that are in neither partition (e.g. `done`, `cancelled`) is excluded from both terms. Issues whose `(active_t + wait_t) == 0` are excluded; count goes in `notes`. Aggregated as median, p75, p90 across remaining issues. | `n` = cycle-eligible count minus zero-denominator exclusions. |
| **Flow Distribution** | Issuetype-at-delivery split. Numerator and denominator both run over **all delivered-in-window issues including sub-tasks** — Flow Distribution is intentionally insensitive to `--include-subtasks` so that the defect-share of all delivered work is observable regardless of the throughput-counting convention. Buckets: `feature/defect/debt/risk/subtask/other`. Percentages sum to 1.0 (within 4-dp tolerance). `flow_distribution.denominator` (integer) is emitted alongside the buckets so downstream consumers can verify. | denominator is its own integer; not equal to `throughput` when `--include-subtasks=false` and subtasks exist. |
| **Defect Ratio** | `flow_distribution.defect` (same value, separate key for convenience). Defect share of *all delivered work in window* — not of throughput when those diverge. The disambiguation is stated in `notes`: `"defect_ratio uses flow_distribution denominator; throughput excludes subtasks (override: --include-subtasks)"`. | scalar. |

**Out of scope (deliberately):** Deployment Frequency, Failed Deployment
Recovery Time, and Change Failure Rate proper. Those require deploy-event
data the tracker doesn't have. The skill emits `defect_ratio` and
`rework_rate` as the available tracker-side quality signals, and surfaces
that limitation in `notes` as `"defect_ratio is not Change Failure Rate;
see spec §Out of scope"`.

**Cohort breakdown denominator rule.** Every metric inside
`cohort_breakdown.cohort` is computed with **both numerator and
denominator restricted to the cohort subset**. Symmetric for `control`.
Examples:

- `cohort_breakdown.cohort.throughput` = number of delivered-in-window
  issues with `cohort: true`.
- `cohort_breakdown.cohort.rework_rate` = pre-delivery rework edges in
  cohort issues ÷ cohort throughput.
- `cohort_breakdown.cohort.flow_distribution` = bucket shares over
  cohort delivered-in-window issues; `flow_distribution.denominator`
  equals the cohort-restricted denominator.

This means the rework_rate of cohort + control does **not** weighted-
average to the global rework_rate when cohort and control sizes differ;
that's intentional and is the property `ai-adoption-report` (cohort
and program modes) relies on when rolling up cohort and control sides
independently across scopes.

**Population-rule rationale.** Anchoring every metric on "first-ever
delivery falls in window" gives one consistent population. Post-delivery
rework (an issue reopened in window after a prior delivery) is a real
phenomenon but is *not* counted in `rework_rate` v1, because its
denominator (current throughput) doesn't include the issue. A v2 metric
`post_delivery_rework_rate` would address it; see Deferred to v2.

### Outputs

**JSON shape** (aggregate mode, default):

```json
{
  "meta": {
    "scope": { "project": "PROJ", "team": "Foo" },
    "window": { "from": "2026-02-19", "to": "2026-05-19" },
    "cohort_jql": "labels = ai-assisted",
    "metrics_requested": ["cycle_time", "lead_time", "throughput", "wip", "flow_load", "rework_rate", "flow_time", "flow_efficiency", "flow_distribution", "defect_ratio"],
    "state_config_sha": "...",
    "issuetype_config_sha": "...",
    "generated_at": "2026-05-19T14:00:00Z",
    "sources": ["jira"],
    "schema_version": "1.0",
    "caller": "5b10ac8d82e05b22cc7d4ef5",
    "per_team_double_counted": false
  },
  "aggregates": {
    "cycle_time_hours":     { "p50": 38.2,  "p75": 91.0,  "p90": 168.4, "n": 80 },
    "lead_time_hours":      { "p50": 120.5, "p75": 340.0, "p90": 720.0, "n": 84 },
    "throughput":           84,
    "wip":                  17,
    "flow_load":            21.4,
    "rework_rate":          0.42,
    "flow_time_hours":      { "p50": 120.5, "p75": 340.0, "p90": 720.0, "n": 84 },
    "flow_efficiency":      { "p50": 0.58,  "p75": 0.72,  "p90": 0.86,  "n": 76 },
    "flow_distribution":    {
      "feature":     0.4608,
      "defect":      0.1961,
      "debt":        0.1078,
      "risk":        0.0294,
      "subtask":     0.1765,
      "other":       0.0294,
      "denominator": 102
    },
    "defect_ratio":         0.1961
  },
  "cohort_breakdown": {
    "cohort":  {
      "throughput": 31,
      "cycle_time_hours": { "p50": 28.0, "p75": 60.0, "p90": 120.0, "n": 31 },
      "rework_rate": 0.55,
      "flow_distribution": {
        "feature": 0.4054, "defect": 0.2432, "debt": 0.1081,
        "risk": 0.027, "subtask": 0.1892, "other": 0.027,
        "denominator": 37
      },
      "defect_ratio": 0.2432
    },
    "control": {
      "throughput": 53,
      "cycle_time_hours": { "p50": 44.0, "p75": 110.0, "p90": 200.0, "n": 53 },
      "rework_rate": 0.33,
      "flow_distribution": {
        "feature": 0.4923, "defect": 0.1692, "debt": 0.1077,
        "risk": 0.0308, "subtask": 0.1692, "other": 0.0308,
        "denominator": 65
      },
      "defect_ratio": 0.1692
    }
  },
  "per_team": [
    { "team": "Bar",  "aggregates": { } },
    { "team": "Foo",  "aggregates": { } }
  ],
  "notes": [
    "12 issues entered in-progress before window start and are included in lead-time computation.",
    "3 issues had unmapped issuetype 'Spike'; bucketed as 'other'.",
    "4 cycle-eligible issues had zero (active_t + wait_t); excluded from flow_efficiency.",
    "4 delivered without commitment-state entry; excluded from cycle_time.",
    "4 issues cancelled in window; excluded from throughput, cycle_time, lead_time, flow_efficiency, and flow_distribution.",
    "defect_ratio is not Change Failure Rate; see spec §Out of scope.",
    "defect_ratio uses flow_distribution denominator; throughput excludes subtasks (override: --include-subtasks).",
    "flow_load: 91 samples, weekends included.",
    "permissions: 1 issue in scope's JQL was inaccessible to the caller and is silently excluded."
  ]
}
```

- `cohort_breakdown` is omitted when `--cohort-jql` is not provided **or
  when `--per-issue` is set** (see "Cohort behaviour" above).
- `meta.cohort_jql` is **omitted** when `--cohort-jql` is not provided
  (matches the unrequested-metrics rule — absent rather than `null`).
  Downstream consumers must check for key presence, not for a null
  value.
- `per_team` is emitted iff (a) scope is `--program-id` or `--portfolio-id`,
  or (b) scope is `--project` AND `team_field` is configured AND the
  resolved issue set spans more than one distinct team value. Project
  scope without a configured `team_field` never emits `per_team` (no
  attempt is made to infer teams).
- Unrequested metrics (per `--metrics`) are absent from `aggregates`,
  `cohort_breakdown.*`, and every `per_team[].aggregates`. Their keys
  are not emitted as `null`.

**Output canonicalization** — required for the
`test_stable_output_for_same_inputs` invariant. All rules apply at
*serialization time*, after every metric has been computed in full
precision:

1. **Object key order:** keys sorted at every level using Python's
   default codepoint order (`json.dumps(obj, sort_keys=True)` — no
   locale, no ICU collation).
2. **Float precision:** percentile and ratio computations run on
   full-precision in-memory floats. The 4-decimal-place rounding is
   applied **only at serialization time, after every aggregate is
   computed**. The on-wire format is exactly what
   `json.dumps(round(x, 4))` emits in Python — trailing zeros are NOT
   preserved (`38.2` is the wire form, not `38.2000`). Integer-valued
   floats serialize without a decimal point only when their type is
   `int`; floats keep their `.0` if `json.dumps` would emit one (e.g.
   `round(120.0, 4) → 120.0`). Counts (`n`, `throughput`, `wip`,
   `flow_distribution.denominator`) stay as integers (no decimal
   point on the wire). The percentile algorithm is
   `numpy.percentile(values, q, method="linear")` or the equivalent
   `statistics.quantiles(..., method="exclusive")` for stdlib-only
   implementations — the spec pins `method="linear"` (interpolate
   between the two closest ranks).
3. **List ordering, deterministic:**
   - `per_team`: sorted by `team` field using **codepoint order**
     (`str.__lt__`, not locale-aware). Unicode team names sort by
     codepoint, not by `locale.strcoll`.
   - `meta.metrics_requested`: sorted to match the canonical metric-name
     order documented in `--metrics` (NOT lexicographic).
   - `meta.sources`: sorted ascending lexicographic.
   - `notes`: **sorted lexicographically** in the canonical output.
     The notes are descriptive only; chronology is not preserved.
     This eliminates any parallelization-related nondeterminism in
     future implementations.
   - `flow_distribution` and other bucket maps: keys sorted by the
     fixed canonical order `feature, defect, debt, risk, subtask,
     other` (NOT lexicographic). `flow_distribution.denominator`
     follows the bucket keys.
4. **Upstream JQL ordering:** every `jira: search` invocation includes
   `ORDER BY key ASC` so the issue iteration order is reproducible.
5. **`generated_at` normalization in tests only:** the test harness
   substitutes a fixed timestamp before comparing bytes.

**CSV shape** (aggregate mode only): long form — one row per (metric,
scope, cohort, team), columns in this exact order:
`metric, scope, cohort, team, p50, p75, p90, count`. Header row always
emitted. Missing percentiles for scalar metrics (throughput, wip,
flow_load, rework_rate, defect_ratio) emit `p50` only, with `p75` and
`p90` blank.

**Per-issue mode** (`--per-issue`, JSONL):

```jsonl
{"cancelled_in_window":false,"cohort":true,"cycle_eligible":true,"cycle_time_hours":36.1,"delivered_in_window":true,"first_commitment_at":"2026-04-12T09:00:00Z","first_delivery_at":"2026-04-13T21:06:00Z","flow_efficiency":0.61,"issue_created":"2026-04-08T12:00:00Z","issuetype_at_delivery":"Bug","issuetype_bucket":"defect","key":"PROJ-123","lead_time_hours":140.2,"rework_count":1,"team":"Foo","wip_at_to":false}
{"cancelled_in_window":true,"cohort":false,"cycle_eligible":false,"cycle_time_hours":null,"delivered_in_window":false,"first_commitment_at":null,"first_delivery_at":null,"flow_efficiency":null,"issue_created":"2026-03-01T08:00:00Z","issuetype_at_delivery":null,"issuetype_bucket":null,"key":"PROJ-200","lead_time_hours":null,"rework_count":0,"team":"Foo","wip_at_to":false}
```

One row per issue **in scope**, where "in scope" means:
- delivered-in-window (contributes to throughput), OR
- cancelled-in-window (excluded but reported with
  `delivered_in_window: false`, `cancelled_in_window: true`), OR
- in-WIP at `--to` (excluded but reported with `wip_at_to: true`).

Per-issue field-presence rules for non-delivered rows:

- **Cancelled-in-window or WIP-only rows** emit `null` for
  `cycle_time_hours`, `lead_time_hours`, `flow_efficiency`,
  `first_commitment_at`, `first_delivery_at`, `issuetype_at_delivery`,
  and `issuetype_bucket`.
- `rework_count` is `0` for non-delivered rows (no pre-delivery
  rework to count — and post-delivery rework is v2).
- `cycle_eligible` is `false` for non-delivered rows.
- The three boolean flags `delivered_in_window`, `cancelled_in_window`,
  `wip_at_to` are always present on every row.

**Downstream consumers (notably any re-aggregation of `--per-issue`
output) MUST filter on `delivered_in_window: true` before computing
delivery-based metrics (cycle, lead, rework, flow_efficiency,
throughput).** A naive `mean` over the JSONL would incorrectly
include `null` rows or zero-rework rows. This filter is the
documented contract; the skill does not enforce it on consumers.

This is the contract that the downstream `ai-adoption-report` skill
(and any future per-issue inspection tool) consumes. Each row carries
enough fields to re-derive every aggregate without re-querying Jira.

Per-issue rows are also canonicalized: object keys sorted codepoint
order, floats rounded to 4 decimals at serialization. JSONL line order:
sorted by `key` ascending (codepoint).

### Data sources

- **Jira (always)** for status history. Two upstream calls per issue set:
  1. `jira: search "<JQL>" --expand changelog --fields summary,status,issuetype,assignee,created,resolutiondate,labels,<team_field.id>`
     to enumerate issues and inline their first ~100 changelog entries.
  2. **For every issue** whose inline changelog response indicates more
     entries exist (the upstream `jira` skill exposes either a `total`
     vs. `histories.length` mismatch or an `isLast` flag — see "Changelog
     pagination" below), the skill issues a follow-up
     `jira: raw GET issue/<KEY>/changelog --param startAt=N`
     to drain the rest. This is not optional: long-lived issues commonly
     have more than 100 changelog rows, and missing rows silently corrupt
     cycle-time and lead-time math.
  The skill walks `histories[].items[].field == "status"` and
  `field == "issuetype"` to build the per-issue state and issuetype
  timeline.

- **Jira Align (only for `--program-id` / `--portfolio-id`)** — used
  exclusively to resolve team/program/portfolio membership. The actual
  time-in-state numbers always come from Jira's changelog. The upstream
  calls are:
  - **Teams in a program:** `jira-align: raw GET programs/<id>/teams`
    (overridable via `--align-teams-path`). This nested-resource path
    follows the `features/<id>/stories` example documented in the
    `jira-align` SKILL.md. The skill does **not** assume `programID` is
    a filterable property on the `teams` resource — that has not been
    verified across Jira Align versions.
  - **Programs in a portfolio:** `jira-align: raw GET portfolios/<id>/programs`.
  - **Issues belonging to a team:** intersected via the configured Jira
    `team_field` (NOT pulled from Jira Align). The skill collects the
    team-id list from Jira Align, then runs a Jira JQL query like
    `"<team_field.id>" in (<team_a>, <team_b>, ...)` to fetch the
    actual issues.

  If any of these endpoints return non-2xx, exit 3 with the upstream
  response verbatim. Don't try alternative paths silently.

**Joining Jira ↔ Jira Align:** done by an explicit field. Resolution
order:

1. `--align-join-field NAME` on the command line.
2. `align_join_field` entry in the state config.
3. If neither is set and `--program-id` / `--portfolio-id` is requested,
   exit 2 with a clear message.

There is no default — instances vary too much, and silently picking
`customfield_10001` is a wrong-answer risk.

### Changelog pagination (Cloud regression)

Cloud Jira's `/search/jql` endpoint returns *at most the first inlined
batch* of changelog entries when `expand=changelog` is used. The exact
inline cap is unstable across Cloud versions (~100 entries historically).
The implementation therefore **must not** assume a single `search` call
returns complete change history.

Concrete contract:

- After `jira: search ... --expand changelog`, for every returned issue
  the implementation inspects the changelog payload for a "more pages
  exist" signal. The signals the upstream `jira` skill currently exposes
  are (in priority order):
  1. `histories.length < total` (Server / DC).
  2. `isLast == false` in the `changelog` object (Cloud, post-`/search/jql`).
  3. `nextPageToken` present in the response.
- If any of those signals is true, issue a follow-up
  `jira: raw GET issue/<KEY>/changelog --param startAt=<N>` (Server) or
  `--param pageToken=<token>` (Cloud) until drained.
- If the upstream `jira` skill does not yet expose `raw GET issue/<KEY>/changelog`
  or its response shape doesn't surface one of the signals above, this
  spec **requires extending the `jira` skill before implementing
  flow-metrics**. Don't shim the REST call here.

### Permission undercounting

Jira silently omits issues the caller's account lacks browse permission
on. There is no count of "you matched N issues but lack permission to
see K of them". This is a fundamental tracker limitation; flow-metrics
mitigates rather than solves it:

- The skill runs `jira: whoami` at startup and records the calling
  account in `meta.caller`. The field used:
  - **Cloud:** `accountId` (24-char opaque identifier).
  - **Server / Data Center:** `name` (username).
  - If both are present, prefer `accountId`. If neither, exit 3
    (`whoami` returned an unrecognized shape).
- For project-scope runs, the skill compares the total issue count from
  `jira: get-project <KEY>` (when available) against the JQL count over
  the entire project. If they differ, a `notes` entry records the delta:
  `"permissions: K issues in project are inaccessible to the caller and
  are silently excluded"`.
- For broader scopes, the skill emits a softer `notes` line:
  `"permissions: this report reflects only issues visible to <caller>;
  cross-team comparisons with reports from other accounts may differ"`.
- **Field-level permission undercount.** Jira instances with
  field-level security may return null / missing values for the
  configured `team_field.id` on some issues even when the issue
  itself is readable. The skill detects this by counting how many
  in-scope issues return null / missing for the team field and emits
  `"per_team: N issues had no readable team_field value; bucketed
  as '(no team)'"`. Such issues are gathered into a synthetic
  `(no team)` row in `per_team` rather than dropped, so global
  aggregates still reconcile with the per-team sum (for the
  `single_value` kind).
- The skill does **not** retry as a different user or escalate.

### Cross-skill invocation — name, not path

Same posture as `jira-defect-flow`. This skill names sibling skills
(`jira`, `jira-align`) by their `name:` field and uses the IDE's native
skill-dispatch mechanism (the Skill tool in Claude Code, the equivalent
elsewhere). It never reads `~/.config/dropkit/credentials.env`, never
hard-codes installer paths, and never re-implements REST calls.

If a verb this skill needs is missing from `jira` or `jira-align`, the fix
is to extend that skill — not to shim around it here.

### Caching

Per-issue derived rows are cached on disk under
`.context/flow-metrics/cache/<cache-key>.jsonl`. Re-runs read the cache
unless `--no-cache` is passed.

**Cache key derivation** — pinned exactly so two runs with semantically
equivalent inputs hit the same cache. Fields that affect *which issues
and changelogs are fetched* are in the key; fields that affect only
*post-fetch aggregation* are not.

```
cache_key = sha256(json.dumps({
  "schema_version":         "1.0",
  "scope_kind":             "project" | "program" | "portfolio",
  "scope_value":            <KEY or ID, as string>,
  "team":                   <NAME or null>,
  "from":                   "<YYYY-MM-DD>",
  "to":                     "<YYYY-MM-DD>",
  "user_jql":               normalize_jql(<--jql or "">),
  "user_align_filter":      normalize_odata(<--align-filter or "">),
  "state_config_sha":       <hash of canonical state config — see below>,
  "issuetype_config_sha":   <hash of canonical issuetype config — see below>,
  "team_field_override":    <ID or null>,
  "align_join_field":       <NAME or null, only when scope_kind ∈ {"program","portfolio"}; else null>,
  "align_teams_path":       <PATH or default-string, only when scope_kind ∈ {"program","portfolio"}; else null>
}, sort_keys=True, separators=(",", ":")).encode())
```

Notes on this shape:

- **Cohort JQL is not in the key.** Cohort is applied at aggregation
  time, after per-issue derivation; the same cache feeds multiple
  cohort runs over the same underlying data.
- **`--metrics` is not in the key.** Per-issue rows always carry all
  derivable fields; aggregation honors `--metrics` afterward.
- **`--include-subtasks` is not in the key.** Subtasks are always
  fetched (they're needed for Flow Distribution regardless of the
  flag); the flag is applied at aggregation time. Implementations
  must not tighten the underlying JQL with `issuetype != Sub-task`.
- **`scope_kind` is keyed separately from `scope_value`** so a
  `--project PROJ` run cannot collide with a `--program-id PROJ` run.
- **`align_join_field` and `align_teams_path` are pinned to `null`
  for project-scope runs** — they have no effect on what's fetched,
  so changing them should not invalidate the cache. The Jira-Align-
  scope runs include them in the key.

**Canonical config sha** (`state_config_sha`, `issuetype_config_sha`):

```
sha256(
  json.dumps(parsed_config, sort_keys=True, separators=(",", ":"))
  .encode()
)
```

This makes whitespace-only edits invariant (`jq .` round-trips produce
the same sha) and pure key-reordering invariant. Any *semantic* change
(adding a status mapping, renaming a canonical state) changes the sha
and invalidates downstream caches.

**`normalize_jql` and `normalize_odata`:**

v1 normalization is conservative — no clause re-ordering, because a
correct JQL parser is out of scope. The functions:

1. Strip leading/trailing whitespace.
2. Collapse internal whitespace runs to a single space.
3. Treat empty/whitespace-only input as `""`.

This means `labels = foo AND assignee = bar` and `assignee = bar AND
labels = foo` produce **different** cache files. That is an acceptable
v1 trade — the user-visible failure mode is wasted recomputation, not
wrong answers. Semantic-equivalence normalization is deferred to v2.

**Atomic cache writes** (matches `kit-installer.md`'s `installed.json.tmp`
pattern):

1. Aggregate-mode runs write per-issue derivation rows to
   `<cache-key>.jsonl.tmp`, then `os.replace()` to `<cache-key>.jsonl`
   only after the full upstream fetch completes. Partial fetches
   (Ctrl-C, network error, upstream non-2xx) leave the `.tmp` file
   behind and never produce a readable cache entry.
2. On startup, the implementation removes any stale `.tmp` files older
   than 1 hour in the cache directory. (Concurrent fresh runs are
   protected by the .tmp name including the PID.)
3. The cache directory itself is created with mode 0700.

**Concurrent invocations** writing the same cache key are tolerated:
each writes its own PID-suffixed `.tmp`, and whichever finishes last
"wins" the final filename via `os.replace`. The cache content is a pure
function of the cache key, so the winner is content-identical to the
loser.

**Aggregation pass always runs** (cheap, in-memory); only the Jira /
Jira Align fetch and the per-issue derivation are cached.

### Read-only contract — upstream-skill allowlist

The skill **invokes only** the following upstream subcommands. Any other
invocation (including the `raw POST/PUT/PATCH/DELETE` escape hatches,
`attach`, and `raw GET` to paths outside the allowed prefixes) is
forbidden and enforced by a contract test that wraps the upstream skills
and fails on any out-of-allowlist call.

**`jira` allowlist** (verbs):
- `check`, `whoami`
- `get-issue`, `search`, `get-project`
- `raw GET` restricted to **exactly** these path patterns (regex-style;
  `<KEY>` matches `[A-Z][A-Z0-9_]+-[0-9]+` for issue keys or
  `[A-Z][A-Z0-9_]+` for project keys):
  - `field` (exact match; custom-field catalog)
  - `project/<KEY>/statuses` (exact, with project-key validation)
  - `issue/<KEY>/changelog` (exact, with issue-key validation)

Every other `jira` verb is forbidden, including: `create-issue`,
`update-issue`, `delete-issue`, `transition`, `comment`, `attach`,
`list-transitions`, `get-user`, `list-users`, `list-projects`, and
`raw POST`/`PUT`/`PATCH`/`DELETE`. Any `raw GET` whose path does not
exactly match one of the three patterns above is also forbidden —
e.g. `project/PROJ/components`, `issue/PROJ-1/comments`, and
`dashboard` are all rejected by the contract test even though the verb
is `raw GET`.

**`jira-align` allowlist** (verbs):
- `raw GET` restricted to **exactly** these path patterns (regex-style;
  `<id>` matches `[0-9]+`):
  - `programs/<id>` (program metadata)
  - `programs/<id>/teams` (program team enumeration; overridable via
    `--align-teams-path`, but the override must match one of the four
    patterns in this list)
  - `portfolios/<id>` (portfolio metadata)
  - `portfolios/<id>/programs` (portfolio program enumeration)

The current spec body uses `jira-align` only for these four
nested-resource reads. If a future v2 needs `check`, `whoami`, `get`,
`list`, or `search`, this allowlist is extended at that time. Every
other `jira-align` verb is forbidden, including: `create`, `update`,
`delete`, and `raw POST`/`PUT`/`PATCH`/`DELETE`. Any `raw GET` whose
path does not exactly match one of the four patterns above is also
forbidden.

The allowlist is the canonical statement; any future upstream verb is
denied by default until this spec is updated. The contract test
`test_only_allowlisted_jira_verbs_invoked` enforces this for both
skills.

### Errors and exit codes

- `0` success (including empty result sets, empty cohorts, all-cancelled
  result sets)
- `1` user aborted (Ctrl-C; `--output FILE` overwrite confirmation
  declined; no-TTY environment where confirmation is needed)
- `2` validation error: bad flag combo, missing required scope, unmapped
  raw status in data, `delivery_state` overlapping
  `terminal_non_delivery_states`, missing `align_join_field` when Jira
  Align scope is requested, `--per-issue` without `--output`, path
  escape on `--output` / `--state-config` / `--issuetype-config`, Python
  version below the floor, configured `team_field.id` not found in
  Jira's field catalog.
- `3` upstream skill error: `jira` or `jira-align` returned non-zero.
  Upstream stderr is relayed verbatim; this skill adds no interpretation.
  Distinct from `2` — `3` always means "the data layer failed", `2`
  always means "the user's invocation was rejected before any data
  call".

### Edge cases

- **Issue spans the window edge.** Started before `--from`, delivered
  inside the window: delivered-in-window = true; cycle time computed
  from the actual start timestamp (which is outside the window). Counted
  in `notes`.
- **Issue with no `commitment_state` transition** (e.g. closed directly
  from backlog): delivered-in-window = true; cycle-eligible = false.
  Contributes to throughput and lead time. Excluded from cycle time
  (`cycle_time_hours.n` decrements; counted as "N delivered without
  commitment-state entry" in `notes`). Not cycle-eligible, therefore
  also not in `flow_efficiency`'s denominator — but that exclusion is
  not a separate `notes` entry; it's a consequence of the same skip.
- **Issue reopened and re-delivered.** Throughput uses the first-ever
  delivery only; a redelivery does not increment throughput. The
  backward transition that triggered the reopen counts in rework iff
  it occurs at or before the first-ever delivery (it does not, by
  definition — reopen happens *after* delivery, so it's
  post-delivery rework, which v1 does not count). v2 will add a
  `post_delivery_rework_rate` metric.
- **Cancelled issue.** Issue has at least one changelog transition
  INTO a canonical state in `terminal_non_delivery_states` whose
  timestamp is in window, AND no first-ever delivery in window.
  Cancelled-in-window = true; excluded from throughput, cycle time,
  lead time, flow efficiency, and Flow Distribution; counted in
  `notes`. If the cancellation was followed by a reopen still in
  window, the issue may *also* be in WIP at `--to` — both signals
  are reported.
- **Sub-task.** Bucketed as `subtask` in Flow Distribution. Excluded
  from throughput/cycle/lead/flow_efficiency/rework_rate unless
  `--include-subtasks` is set.
- **Issuetype changed mid-flight.** Flow Distribution and per-issue
  `issuetype_at_delivery` use the issuetype at the first-ever delivery
  timestamp, derived from the changelog `issuetype` field history.
  Pre-delivery issuetype changes do not retroactively re-bucket.
- **Custom field with team membership not found.** If the `team_field.id`
  (or `--team-field-override`) is not present in Jira's field catalog,
  exit 2 with the missing id named and `notes` pointing at
  `jira: raw GET field`.
- **`--team` with non-existent team value.** Resolves to zero issues
  matched. Empty result, exit 0; not a validation error.
- **Cohort-jql matches zero issues.** `cohort_breakdown.cohort.throughput`
  is 0; metric percentiles are `null`. Exit 0.
- **Status renamed mid-window.** Show up as two distinct raw statuses
  in the changelog. Both must be mapped in the state config; if only
  one is, exit 2 naming the unmapped one.
- **Jira Cloud vs Server changelog format.** Both flavours return
  `histories[].items[].field == "status"`. The skill consumes the
  uniformly-shaped output from the `jira` skill and does not branch on
  flavour. Per-issue changelog pagination (see "Changelog pagination"
  above) is the one place flavour-specific handling is required, and
  it goes through `jira: raw GET issue/<KEY>/changelog`.
- **Issue with thousands of transitions** (rare; happens with bots).
  Per-issue changelog pagination drains all of them. No upper bound is
  imposed. Memory is `O(transitions per issue)` during walk; freed once
  the per-issue row is emitted.
- **Project with >50k issues in window.** The implementation streams
  per-issue rows to the `.jsonl.tmp` cache file rather than buffering
  in memory. Aggregation re-reads the JSONL once. This keeps memory
  bounded at one issue's changelog. Streaming-streaming aggregation
  (no full re-read) is deferred to v2.
- **`--output FILE` already exists.** Without `--yes`, prompt
  `overwrite / abort`. Without a TTY, treat as abort → exit 1. With
  `--yes`, overwrite atomically (temp file + rename).
- **No TTY for prompts.** The skill's only prompts are `--output FILE`
  overwrite. Treat as aborted (exit 1) unless `--yes`.
- **Python version.** Floor: 3.10 (needed for `match` statement,
  type aliases, and `zoneinfo`). Detect at startup; exit 2 with a
  clear message if below.
- **Time zones.** All timestamps are converted to UTC before any
  subtraction. Window bounds (`--from`, `--to`) are interpreted as
  per-day UTC bounds (see Inputs).
- **Path safety for file flags.** `--output`, `--state-config`,
  `--issuetype-config`: resolved with `pathlib.Path.resolve()`. Reject
  paths under `/etc`, `/sys`, `/proc`, `/dev`, `/boot`, or the Windows
  equivalents (`C:\Windows`, `C:\Program Files`). Reject any path
  containing a null byte. Exit 2.
- **Default config resolution.** The shipped
  `references/states.default.json` and
  `references/issuetypes.default.json` are read relative to the
  skill's install root, located by walking up from `__file__` until a
  directory containing both `SKILL.md` and `references/` is found
  (typically `__file__.parent` if the entry point is `flow-metrics.py`
  at the skill root, or `__file__.parent.parent` if it lives under
  `scripts/`). This resolves correctly when the skill is installed
  under `~/.claude/skills/flow-metrics/` (kit-installer layout) AND
  when run directly from a dropkit clone at
  `<repo>/skills/workflows/flow-metrics/`. Both paths are tested.

## Contract tests

The gate for "done". Black-box; any valid implementation must pass all of
these. Each bullet is one test.

### Inputs, scope, window

- **`test_requires_exactly_one_scope`** — Passing none of `--project /
  --program-id / --portfolio-id` exits 2. Passing two exits 2.
- **`test_team_only_valid_with_project`** — `--team Foo --program-id 42`
  exits 2.
- **`test_default_window_is_last_90_days_utc`** — Without
  `--from`/`--to`, `meta.window.from` equals `today_utc - 90 days` and
  `meta.window.to` equals `today_utc`.
- **`test_to_is_inclusive_of_named_day`** — An issue delivered at
  `--to 23:59:59 UTC` is in scope; an issue delivered at `(--to + 1
  day) 00:00:00 UTC` is not.
- **`test_jql_user_clause_parenthesized`** — `--jql "a OR b"` results
  in the underlying `jira: search` receiving `(<scope>) AND (a OR b)`,
  not `<scope> AND a OR b`.
- **`test_align_filter_user_clause_parenthesized`** — Same, for
  `--align-filter`, against `jira-align`.

### State configuration

- **`test_unmapped_status_exits_2`** — Given changelog data containing
  status `"Blocked"` not present in the state config, the skill exits
  2 and names `"Blocked"` in the error.
- **`test_default_state_config_loads_at_install_path`** — Without
  `--state-config`, the shipped default loads from
  `__file__.parent / references / states.default.json` and
  `meta.state_config_sha` is non-empty.
- **`test_default_state_config_loads_from_clone_path`** — Same, when
  the skill is run from a dropkit clone at
  `<repo>/skills/workflows/flow-metrics/`.
- **`test_state_config_sha_canonicalized`** — Three files that parse to
  the same JSON object (whitespace differs, key order differs) produce
  the same `state_config_sha`. A semantic change produces a different
  one.
- **`test_delivery_overlapping_cancelled_exits_2`** — A state config
  where `delivery_state == "done"` and `"done"` is also listed in
  `terminal_non_delivery_states` exits 2 at startup.
- **`test_unknown_team_field_id_exits_2`** — `team_field.id =
  customfield_99999` that's not in Jira's field catalog exits 2 with
  the id named.
- **`test_team_field_override_validated_not_config`** — When
  `--team-field-override customfield_88888` is passed AND the config
  has a *valid* `team_field.id` but `customfield_88888` is unknown,
  the skill exits 2 naming `customfield_88888` (the override is what
  gets validated; the config value is ignored that run).
- **`test_commitment_equals_delivery_exits_2`** — State config with
  `commitment_state == delivery_state` exits 2 at startup.
- **`test_active_intersects_wait_exits_2`** — State config where a
  canonical state appears in both `active_states` and `wait_states`
  exits 2.
- **`test_delivery_in_active_states_exits_2`** — `delivery_state` in
  `active_states` exits 2.
- **`test_commitment_in_terminal_non_delivery_exits_2`** —
  `commitment_state` in `terminal_non_delivery_states` exits 2.
- **`test_rework_signals_reference_unknown_canonical_exits_2`** —
  `rework_signals[0].from` containing a canonical name not in
  `canonical_states` exits 2.

### Metric correctness (per-issue)

Fixture: a JSON file of synthetic Jira responses with hand-computed
expected values. Tests load the fixture, run the metric, and assert.

- **`test_cycle_time_first_commitment_to_first_delivery`** — Issue with
  transitions `Backlog → In Progress (t1) → Done (t2)` has
  `cycle_time_hours == (t2 − t1) / 3600`.
- **`test_cycle_time_excludes_skipped_commitment`** — Issue with
  `Backlog → Done` (no `In Progress`) is in throughput, in lead time,
  and **not** in cycle time; `notes` records "N delivered without
  commitment-state entry".
- **`test_cycle_time_excludes_issue_delivered_after_to`** — Issue
  delivered after `--to` is excluded from cycle time AND throughput.
- **`test_lead_time_uses_created_to_first_delivery`** — Issue with
  `created=t0`, first-ever `done=t2` has `lead_time_hours ==
  (t2 − t0) / 3600`.
- **`test_throughput_first_ever_delivery_in_window`** — Issue delivered
  before window, reopened, redelivered in window: NOT counted in
  throughput.
- **`test_throughput_reopen_in_window_doesnt_double_count`** — Issue
  delivered in window, reopened in window, redelivered in window:
  counted once.
- **`test_wip_at_to_inclusive`** — Default config (active_states =
  [in_progress]). Issue whose canonical state at the WIP-instant
  (`(to+1day) 00:00 UTC − 1µs`) is `in_progress` IS in WIP. Issue
  moved to `Done` one second before the WIP-instant is NOT in WIP
  (delivered-in-window predicate excludes it). Issue in `In Review`
  at the WIP-instant is NOT in WIP under the default config (in_review
  is a wait_state), establishing that WIP membership tracks
  `active_states`, not just "not-yet-delivered".
- **`test_flow_load_includes_both_endpoints`** — Window
  `[2026-01-01, 2026-01-05]` produces 5 samples, not 4 and not 6.
- **`test_flow_load_weekend_inclusion_recorded`** — `notes` always
  records the sample count and weekend policy.
- **`test_rework_counts_distinct_backward_edges`** — Issue with
  `Done → In Progress → Done` cycle has rework_count == 1 (one
  backward edge). Issue with two separate `In Review → In Progress`
  moves has rework_count == 2.
- **`test_default_rework_signals_cover_in_progress_to_backlog`** —
  Under the shipped default state config, an issue with `In Progress
  → Backlog → In Progress → Done` has `rework_count == 1`.
- **`test_default_rework_signals_cover_in_test_to_in_review`** —
  Under the shipped default, an issue with `In Test → In Review →
  In Test → Done` has `rework_count == 1`.
- **`test_rework_pre_delivery_only`** — Issue delivered in window,
  then reopened and redelivered in window: only the rework edges
  before the *first* delivery count. The reopen-after-first-delivery
  edge does not increment rework_count in v1.
- **`test_rework_rate_null_on_zero_throughput`** — When throughput is
  0, `aggregates.rework_rate` is `null`, not 0 and not NaN.
- **`test_flow_time_alias_equals_lead_time`** — `flow_time_hours`
  values match `lead_time_hours` byte-for-byte.
- **`test_flow_efficiency_active_over_total`** — Issue with 8h in
  active states and 4h in wait states (between commitment and
  delivery) has `flow_efficiency == 8/12`.
- **`test_flow_efficiency_uses_commitment_to_delivery_interval`** —
  Default config (commitment_state=in_progress). Issue history:
  `Backlog (t0) → In Progress (t1, 8h) → In Review (t2, 4h) → Done
  (t3)`. The "first commitment" is t1; the interval is `[t1, t3]`;
  active_t = 8h in in_progress; wait_t = 4h in in_review (under
  default wait_states); `flow_efficiency == 8 / (8 + 4) == 8/12 ≈
  0.667`. Pins the formula's interval and the active/wait partition.
- **`test_flow_efficiency_ignores_time_before_first_commitment`** —
  Non-default config required: `active_states = ["in_progress",
  "in_review"]`, `wait_states = ["in_test"]`, `commitment_state =
  "in_review"`. Issue history: `In Progress (t0, 2h) → In Review (t1,
  8h) → In Test (t2, 4h) → Done (t3)`. The first commitment (entry
  into in_review) is t1; the interval is `[t1, t3]`. The 2h spent in
  `in_progress` before t1 is OUTSIDE the interval and contributes
  zero to both `active_t` and `wait_t`. Expected: `active_t = 8h
  (in_review only, within interval) + 0h (in_progress, outside)`,
  `wait_t = 4h`, `flow_efficiency == 8/12 ≈ 0.667` — not `10/14` as a
  buggy "whole-issue active time" implementation would produce.
- **`test_flow_efficiency_zero_denominator_excluded`** — Issue
  delivered the same second as committed (no recorded time in active
  or wait) is excluded; `notes` records the exclusion count.
- **`test_flow_efficiency_done_time_excluded`** — Issue in `done` for
  3 days (e.g. before being reopened-then-redelivered): the time in
  `done` is excluded from both `active_t` and `wait_t` since `done`
  is in neither partition.
- **`test_flow_efficiency_default_config_non_degenerate`** — Realistic
  fixture: issue spends 4h in `In Progress`, 16h in `In Review`, 8h
  in `In Progress` (after review feedback), 4h in `In Test`, then
  `Done`. Under the shipped default (active = [in_progress], wait =
  [backlog, in_review, in_test]), `flow_efficiency == 12/32 = 0.375`,
  which is in the non-degenerate range. Verifies that the shipped
  default doesn't produce ~1.0 for normal flows.
- **`test_flow_distribution_sums_to_one`** — Sum of all bucket
  percentages in `aggregates.flow_distribution` (excluding the
  `denominator` integer) equals 1.0 within 4-dp tolerance.
- **`test_flow_distribution_denominator_includes_subtasks`** —
  Fixture: 80 non-subtask deliveries + 20 subtask deliveries.
  Default run (`--include-subtasks=false`): `throughput == 80` but
  `flow_distribution.denominator == 100` and `flow_distribution.subtask
  > 0`. With `--include-subtasks`: `throughput == 100` and
  `flow_distribution.denominator == 100`.
- **`test_defect_ratio_equals_flow_distribution_defect`** —
  `defect_ratio` is always equal to `flow_distribution.defect`, even
  when `throughput != flow_distribution.denominator`.
- **`test_issuetype_at_delivery_used_for_distribution`** — Issue
  created as `Story`, changed to `Bug` 1 hour before delivery: counted
  in `defect` bucket.
- **`test_cancelled_excluded_from_throughput`** — Issue with a
  transition INTO `Won't Do` in window AND no first-ever delivery in
  window: NOT in throughput; counted in `notes` as cancelled.
- **`test_cancelled_then_reopened_still_cancelled_in_window`** —
  Issue moved to `Won't Do` mid-window, then back to `In Progress`
  before `--to`: `cancelled_in_window == true`, NOT in throughput,
  AND in WIP at `--to`. Both signals reported.
- **`test_cycle_time_n_can_differ_from_throughput`** — Fixture: 5
  delivered-in-window issues, 1 skipped commitment_state.
  `throughput == 5`, `cycle_time_hours.n == 4`. Same shape:
  `flow_efficiency.n` reflects the zero-denominator exclusion.
- **`test_subtask_excluded_by_default`** — Issue with `issuetype:
  Sub-task` delivered in window: NOT in throughput, IS in
  `flow_distribution.subtask`.
- **`test_subtask_included_with_flag`** — Same fixture run with
  `--include-subtasks`: throughput increments and the subtask appears
  in cycle/lead time aggregates.

### Cohort behaviour

- **`test_cohort_split_disjoint`** — For any issue in scope, `cohort`
  is either true or false; never both, never missing.
- **`test_empty_cohort_does_not_exit_nonzero`** — `--cohort-jql`
  matching zero issues produces `cohort_breakdown.cohort.throughput ==
  0`, percentiles `null`, and exits 0.
- **`test_cohort_aggregates_match_subset`** — Aggregates of the
  cohort=true subset of per-issue rows equal
  `cohort_breakdown.cohort`.
- **`test_cohort_rework_rate_denominator_is_cohort_throughput`** —
  Fixture: cohort throughput = 10 with 5 backward edges; control
  throughput = 90 with 9 backward edges.
  `cohort_breakdown.cohort.rework_rate == 0.5` (5/10), NOT
  `(5+9) / (10+90) == 0.14`. Symmetric for control.
- **`test_per_issue_omits_cohort_breakdown`** — `--per-issue
  --cohort-jql ...` produces JSONL with `cohort` field on every row
  and **no** `cohort_breakdown` in any output. (Per-issue mode has no
  aggregate object.)
- **`test_meta_cohort_jql_omitted_when_absent`** — Without
  `--cohort-jql`, `meta` has no `cohort_jql` key (not present, not
  null). With `--cohort-jql`, the key is present and the value
  matches the input.

### `--metrics` filtering

- **`test_metrics_filter_omits_unrequested`** — `--metrics
  throughput,wip` produces `aggregates` with **only** those two keys
  and `meta.metrics_requested == ["throughput", "wip"]`.
- **`test_flow_distribution_and_defect_ratio_independent`** —
  `--metrics flow_distribution` does NOT auto-include `defect_ratio`,
  and vice versa.

### Jira Align integration

- **`test_jira_only_run_does_not_call_jira_align`** — With `--project
  KEY` scope, the mocked `jira-align` skill records zero invocations.
- **`test_program_scope_uses_raw_get_teams_path`** — With
  `--program-id 42`, the mocked `jira-align` records a call to
  `raw GET programs/42/teams` (or the `--align-teams-path` override).
- **`test_program_scope_teams_intersected_via_jira_team_field`** —
  After resolving team ids via Jira Align, the issue fetch goes to
  `jira: search` with the configured `team_field.id` in the JQL.
- **`test_missing_align_join_field_exits_2`** — `--program-id 42` with
  no `align_join_field` in state config and no `--align-join-field`
  exits 2.
- **`test_align_teams_path_rejects_traversal`** —
  `--align-teams-path "../admin/users"` exits 2 before any upstream
  call. `--align-teams-path "/programs/42/teams"` (leading slash)
  exits 2.
- **`test_align_teams_path_validates_response_shape`** — When the
  mocked `jira-align` returns a list of items missing the `id` field,
  the skill exits 3 with `"unexpected response shape from <path>"`.

### Changelog pagination

- **`test_changelog_pagination_drained`** — Issue fixture with 150
  changelog entries (50 inline, 100 behind `isLast: false`). The
  skill issues a follow-up `jira: raw GET issue/<KEY>/changelog` and
  the resulting `first_in_progress` matches the earliest of the 150
  transitions, not the earliest of the inline 50.
- **`test_no_follow_up_when_changelog_complete`** — Issue with
  `isLast: true` and 10 inline entries: no follow-up changelog call.

### Output

- **`test_per_issue_emits_jsonl_sorted_by_key`** — `--per-issue
  --output rows.jsonl` produces a file whose `key` field sequence is
  ascending (codepoint).
- **`test_per_issue_requires_output_flag`** — `--per-issue` without
  `--output` exits 2.
- **`test_per_issue_non_delivered_emits_nulls`** — A cancelled-in-
  window row has `delivered_in_window: false`,
  `cancelled_in_window: true`, and `null` for
  `cycle_time_hours`, `lead_time_hours`, `flow_efficiency`,
  `first_commitment_at`, `first_delivery_at`, `issuetype_at_delivery`,
  `issuetype_bucket`. `rework_count` is `0`.
- **`test_per_issue_wip_only_emits_nulls`** — A WIP-only row (in
  scope solely because it's active at `--to`) has the same null
  pattern as cancelled rows, with `wip_at_to: true` instead.
- **`test_per_team_array_kind_double_count_flagged`** — Fixture with
  `team_field.kind: array` and one issue assigned to two teams: the
  issue appears in two `per_team` rows;
  `meta.per_team_double_counted == true`; `notes` records the count.
- **`test_per_team_single_value_kind_sums_to_throughput`** —
  Default `single_value` kind: `sum(per_team[*].throughput) ==
  aggregates.throughput`.
- **`test_csv_long_form_columns`** — `--format csv` produces a header
  row with exactly the columns
  `metric,scope,cohort,team,p50,p75,p90,count` in that order. Scalar
  metrics fill `p50` and leave `p75`/`p90` blank.
- **`test_meta_sources_reflects_skills_called`** — Project-scope run
  has `meta.sources == ["jira"]`; program-scope run has
  `meta.sources == ["jira", "jira-align"]` (sorted).
- **`test_stable_output_for_same_inputs`** — Two runs with identical
  inputs produce byte-identical JSON output after
  `generated_at` normalization. Floats are rounded to 4dp; object
  keys are sorted; `per_team` and bucket maps follow the documented
  canonical orders.
- **`test_per_team_sort_uses_codepoint_order`** — Fixture with team
  names `"Zebra"`, `"Über-team"`, `"alpha"`. `per_team` rows are in
  codepoint order (`Zebra`, `Über-team`, `alpha`) — uppercase before
  lowercase, ASCII before non-ASCII Latin-1 supplement.
- **`test_percentile_computed_at_full_precision`** — Two cycle-
  eligible issues with cycle times `1.55554` and `1.55556` hours.
  Spec-compliant path (percentile-then-round): full-precision p50 =
  `(1.55554 + 1.55556) / 2 = 1.55555`, then `round(1.55555, 4) =
  1.5556`. Wrong path (round-then-percentile): round inputs first to
  `1.5555` and `1.5556`, then p50 = `1.55555`, rounded = `1.5556` —
  agrees here. Stronger fixture distinguishing the two: `1.5555444`
  and `1.5555556`. Spec-compliant: full-precision p50 = `1.5555500`,
  rounded = `1.5556`. Wrong path: round inputs to `1.5555` and
  `1.5556`, p50 = `1.55555`, rounded = `1.5556` — still agrees due
  to symmetric rounding. The pinning value is computational order,
  not numerical divergence: the test asserts the implementation calls
  `round` exactly once per percentile, on the percentile output, not
  on each input. The test harness verifies this by monkey-patching
  `round` and counting calls per metric (`round` called once for p50,
  once for p75, once for p90 — three total per percentile-bearing
  metric, never N times for N inputs).
- **`test_notes_sorted_lexicographically`** — Notes in output are in
  lexicographic order regardless of computation order. (Inject a
  note from each metric computation and assert sorted output.)

### Read-only contract

- **`test_only_allowlisted_jira_verbs_invoked`** — Run every supported
  scope/flag combination through a wrapper that records each upstream
  invocation. Assert that the set of unique `jira` subcommands used is
  a subset of `{check, whoami, get-issue, search, get-project, raw}`
  AND that every `raw` invocation has `method == "GET"` AND its path
  matches **exactly** one of: `field`, `project/<KEY>/statuses`,
  `issue/<KEY>/changelog` (with `<KEY>` matching the documented
  key regex).
- **`test_only_allowlisted_jira_align_verbs_invoked`** — Same for
  `jira-align` with allowlist `{raw}`, `raw` method `"GET"` only,
  and path matching exactly one of: `programs/<id>`,
  `programs/<id>/teams`, `portfolios/<id>`, `portfolios/<id>/programs`
  (with `<id>` matching `[0-9]+`).
- **`test_attach_never_invoked`** — Explicit anti-test: `attach` (file
  upload) is in neither allowlist and is never invoked.
- **`test_raw_get_outside_allowed_patterns_blocked`** — Each of these
  hypothetical paths is detected by the test wrapper and fails the
  test even though the verb is `raw GET`: `jira: raw GET dashboard`,
  `jira: raw GET project/PROJ/components` (wrong sub-path),
  `jira: raw GET issue/PROJ-1/comments` (wrong sub-path),
  `jira-align: raw GET features/123`,
  `jira-align: raw GET programs/123/features` (wrong sub-path).

### Caching

- **`test_cache_hit_skips_upstream_calls`** — Run twice with identical
  inputs; the second run records zero `jira` invocations.
- **`test_cache_invalidated_on_state_config_semantic_change`** —
  Editing the state config to add a new status mapping forces a
  re-fetch.
- **`test_cache_stable_under_whitespace_edits`** — Reformatting the
  state config with `jq .` (different whitespace, same semantics)
  does NOT invalidate the cache.
- **`test_no_cache_bypasses_cache`** — `--no-cache` re-fetches even
  when a matching cache file exists.
- **`test_partial_cache_discarded_on_upstream_failure`** — Mock
  `jira: search` to fail mid-pagination. After the failed run, no
  `.jsonl` file exists in the cache dir; a `.jsonl.tmp` may exist
  but is removed on next startup.
- **`test_cohort_jql_not_in_cache_key`** — Two runs with same inputs
  except `--cohort-jql` produce one cache file (second reads from
  cache).
- **`test_metrics_not_in_cache_key`** — Two runs with same inputs
  except `--metrics` produce one cache file.
- **`test_include_subtasks_not_in_cache_key`** — Two runs with same
  inputs except `--include-subtasks` produce one cache file (second
  reads from cache).
- **`test_align_fields_null_in_cache_key_for_project_scope`** — For
  `--project KEY` runs, changing `--align-join-field` or
  `--align-teams-path` does NOT invalidate the cache.
- **`test_align_fields_in_cache_key_for_program_scope`** — For
  `--program-id` runs, changing `--align-teams-path` DOES invalidate
  the cache.

### Permission undercounting

- **`test_caller_in_meta_cloud`** — When `jira: whoami` returns
  `{accountId: "abc", name: "alice"}`, `meta.caller == "abc"`.
- **`test_caller_in_meta_server`** — When `jira: whoami` returns
  `{name: "alice", key: "JIRAUSER123"}` (no `accountId`),
  `meta.caller == "alice"`.
- **`test_caller_unrecognized_whoami_exits_3`** — When `jira: whoami`
  returns an object with neither `accountId` nor `name`, exit 3.
- **`test_permission_undercount_recorded_in_notes`** — When
  `jira: get-project` reports a higher total than the in-scope JQL,
  `notes` records the delta.

### Path safety and Python floor

- **`test_python_below_floor_exits_2`** — When invoked under Python
  3.9 or below, the skill exits 2 with a clear message.
- **`test_rejects_output_in_etc`** — `--output /etc/foo` (or
  `C:\Windows\foo`) exits 2.
- **`test_rejects_output_with_null_byte`** — `--output "ok\x00bad"`
  exits 2.
- **`test_rejects_state_config_in_proc`** — `--state-config
  /proc/self/maps` exits 2.

### Errors

- **`test_upstream_jira_failure_exits_3`** — When the mocked `jira`
  skill exits non-zero, this skill exits 3 and relays the stderr.
- **`test_validation_error_exits_2_before_any_upstream_call`** — A
  flag-combo validation error exits 2 with **zero** upstream
  invocations recorded.
- **`test_overwrite_aborts_without_tty`** — Given `--output EXISTING`
  with no TTY and no `--yes`, exit 1 without writing.

## Non-goals

Explicit anti-scope — the skill **will not**:

- Write to Jira or Jira Align in any form (no `transition`, `comment`,
  `update-issue`, `create-issue`, `delete-issue`). Pure read.
- Compute Deployment Frequency, Failed Deployment Recovery Time, or
  Change Failure Rate proper. Those need deploy data not in the tracker.
- Pull data from git, PRs, CI, or any non-tracker source.
- Pair JSON outputs across windows, scopes, or cohorts and render
  deltas — that's `ai-adoption-report` (baseline / cohort / program
  modes).
- Generate Markdown reports or charts — also `ai-adoption-report`.
- Make claims about *causes* of metric movement. The output is
  descriptive; interpretation is downstream.
- Run SPACE or DevEx surveys, store survey data, or join with HRIS data.
- Manage `~/.config/dropkit/credentials.env` (`jira` and `jira-align`
  already own it).
- Auto-discover team membership without a configured join field.
- Apply semver or recency weighting to metrics. Median/p75/p90 only.

## Decisions

These are the resolved answers to design questions raised during drafting
and the round-1 adversarial review. Each became part of Behavior or
Contract tests above.

1. **State config format: JSON** (not YAML). Stdlib-only parsing,
   matches `manifest.json` style. YAML deferred to v2.
2. **Unmapped statuses are fatal**, not soft-warned. Silent
   canonicalisation drift breaks every comparison downstream. The shipped
   default config maps "Won't Do" / "Cancelled" / "Duplicate" to a new
   `cancelled` canonical state so first-run users on a normal Jira
   workflow get accurate numbers out of the box.
3. **Cycle Time anchors are configurable** (`commitment_state` /
   `delivery_state` in state config). Default is `in_progress → done`.
   Some teams will want `in_review → done`; the config allows that
   without a code change.
4. **Unmapped issuetypes go to `"other"`, not fatal.** Flow Distribution
   is descriptive; an unknown issuetype shouldn't block a report.
5. **One scope per invocation.** No multi-project queries in v1.
   Aggregate via a wrapper script that calls `flow-metrics` N times.
6. **No Markdown output.** Downstream `ai-adoption-report` owns
   presentation.
7. **No change-failure-rate proxy.** The skill emits `defect_ratio` and
   `rework_rate` and explicitly notes in output that these are *not*
   CFR. Inviting users to interpret defect ratio as CFR would be worse
   than omitting it.
8. **Caching key excludes cohort-jql, `--metrics`, and aggregation
   options.** Cohort and metric filtering are post-hoc; the same fetch
   serves multiple cohort/metric runs.
9. **Time zones: UTC throughout.** No per-team TZ. Window bounds are
   per-day UTC; `--to` is inclusive of the named day (window is
   `[from 00:00, to+1day 00:00)` internally).
10. **Population semantics anchored on "first-ever delivery in window".**
    A reopen-then-redeliver event never creates a second throughput.
    Post-delivery rework (an issue reopened in window after a prior
    delivery) is **not** counted in `rework_rate` v1; a v2
    `post_delivery_rework_rate` will address it.
11. **`cancelled` is a first-class canonical state**, not "done". Issues
    that transitioned INTO `terminal_non_delivery_states` in window AND
    had no first-ever delivery in window (the formal cancelled-in-window
    predicate) are excluded from throughput, cycle, lead, and flow
    efficiency, but counted in `notes`. A cancel-then-reopen issue still
    satisfies this and is also in WIP if active at the WIP-instant.
12. **Sub-tasks are excluded from throughput by default.** Toggleable
    via `--include-subtasks`. Flow Distribution always reports the
    subtask share separately.
13. **Issuetype-at-delivery wins** when an issue's type changed
    mid-flight. Pre-delivery type changes do not retroactively
    re-bucket.
14. **Read-only is an allowlist, not a deny list.** Specific upstream
    subcommands enumerated; `raw` accepted only when `method == "GET"`.
15. **JQL parenthesization is always-on.** Both scope clause and user
    clause are wrapped in parens before AND.
16. **Cloud changelog pagination is mandatory.** The implementation
    drains per-issue changelogs via `jira: raw GET
    issue/<KEY>/changelog` whenever the inline payload signals more
    pages. Skipping this silently corrupts cycle/lead time.
17. **Jira Align team enumeration uses `raw GET programs/<id>/teams`**
    (nested resource path), overridable via `--align-teams-path`. No
    assumption that `programID` is filterable on the `teams` resource.
18. **`align_join_field` has no default.** Explicit configuration is
    required when Jira Align scope is used. Silently picking a custom
    field is a wrong-answer risk.
19. **Output canonicalization is part of the contract**, not a polish
    item. Sorted keys, 4-dp float rounding, sorted `per_team` and
    `sources`, fixed bucket order in `flow_distribution`. Without
    canonicalization, `test_stable_output_for_same_inputs` is
    impossible to keep green.
20. **Python floor: 3.10.** `match` statements and `zoneinfo` are used.
21. **Path safety applies to `--output`, `--state-config`, and
    `--issuetype-config`.** System roots rejected; null bytes rejected.
22. **Default config files are resolved relative to the script's own
    install location** (`pathlib.Path(__file__).parent / "references"`).
    Works for both kit-installer layout and dropkit-clone direct run.
23. **Default `wait_states` include `in_review` and `in_test`.** Flow
    Framework convention: "active" = developer hands-on-keyboard;
    "wait" = blocked on reviewer / QA. Without this, default Flow
    Efficiency would degenerate to ~1.0 on every non-rework flow.
24. **Default `rework_signals` cover four backward shapes:** any
    forward-of-backlog state → backlog; in_review/in_test/done →
    in_progress; in_test/done → in_review; done → in_test.
    Pre-round-2 default missed `in_progress → backlog` (the canonical
    "we gave up on this approach" signal).
25. **Flow Distribution is throughput-independent.** Numerator and
    denominator both run over delivered-in-window issues *including
    subtasks*, regardless of `--include-subtasks`. Throughput, cycle,
    lead, rework, flow_efficiency honor the flag; Flow Distribution
    does not. `flow_distribution.denominator` (integer) is emitted so
    downstream consumers can see the difference. `defect_ratio` uses
    the Flow Distribution denominator, not throughput.
26. **`n` per metric is the metric's own sample size**, not
    throughput. Cycle Time `n` may be less than throughput when issues
    skipped commitment_state. Flow Efficiency `n` may be less than
    cycle-eligible count when zero-denominator exclusions apply.
27. **Cohort breakdown denominators are cohort-restricted.** Each
    metric in `cohort_breakdown.cohort` uses only the cohort subset
    for both numerator and denominator; symmetric for `control`.
    Cohort + control do NOT weighted-average to the global value when
    sizes differ.
28. **Per-issue rows for non-delivered issues emit `null`** for
    delivery-based fields (`cycle_time_hours`, `lead_time_hours`,
    `flow_efficiency`, `first_commitment_at`, `first_delivery_at`,
    `issuetype_at_delivery`, `issuetype_bucket`). `rework_count` is
    `0`. Downstream consumers must filter on `delivered_in_window:
    true`.
29. **Cancelled-then-reopened is cancelled-in-window AND in WIP.**
    Both signals are reported. Throughput excludes it; WIP includes
    it (since the issue is active at `--to`).
30. **`--include-subtasks` is NOT in the cache key.** Subtasks are
    always fetched (needed for Flow Distribution). The flag is
    aggregation-only.
31. **`align_join_field` and `align_teams_path` are null in the cache
    key for project-scope runs.** They have no effect on what's
    fetched; including them would cause spurious cache misses.
32. **Read-only allowlist enumerates exact `raw GET` path patterns,**
    not prefixes. `jira`: `field`, `project/<KEY>/statuses`,
    `issue/<KEY>/changelog` only (three patterns, `<KEY>` validated by
    regex). `jira-align`: `programs/<id>`, `programs/<id>/teams`,
    `portfolios/<id>`, `portfolios/<id>/programs` only (four patterns,
    `<id>` validated by regex). Any other `raw GET` path is denied —
    defense in depth against future plugin endpoints that mutate via
    GET. Pattern-not-prefix matters: `project/PROJ/components` is
    rejected even though it starts with `project/`.
33. **`--align-teams-path` is validated.** Must match an allowlisted
    prefix; no `..`; no leading `/`. Response shape (every element
    has `id`) is validated; bad shape exits 3.
34. **`meta.caller` uses `accountId` on Cloud, `name` on Server.** If
    both are present, prefer `accountId`. If neither, exit 3.
35. **`per_team` for `team_field.kind == "array"` overlaps.** Issues
    assigned to multiple teams are counted in each team's row.
    `meta.per_team_double_counted` and a `notes` line surface this
    so downstream summers don't double-count silently.
36. **`notes` is sorted lexicographically** in canonical output. No
    chronological ordering preserved (avoids parallelization
    nondeterminism in future implementations).
37. **`per_team` and `key` sort orders use codepoint comparison**, not
    locale. ASCII before non-ASCII; uppercase before lowercase.
38. **Percentiles computed at full precision; rounded only at
    serialization.** Algorithm: `numpy.percentile(method="linear")`
    or equivalent. Implementers must not round per-issue values
    before computing percentiles.
39. **State-config integrity validation runs at startup** with nine
    distinct exit-2 conditions enumerated under "State configuration".
    The shipped default passes all checks.

## Deferred to v2

Captured here so design context isn't lost:

- **Deploy-event integration.** Reading deploy events (from a CI tool,
  a Confluence release log, or a manifest of `gh release` tags) to
  enable proper Deployment Frequency, Failed Deployment Recovery Time,
  and Change Failure Rate. Spec separately; this is a bigger fetch.
- **PR / git source signals.** Joining the tracker view with PR data
  (lead time to PR merge, review-cycle time) for a fuller SPACE-style
  picture. Best done as a separate skill that consumes flow-metrics
  output and adds the PR-side columns.
- **`post_delivery_rework_rate` metric.** Counts backward transitions
  on issues that have already been delivered (reopen-then-redeliver).
  v1 deliberately scopes rework to pre-first-delivery only so the
  denominator (throughput) is consistent. v2 adds the post-delivery
  view as a separate metric with `throughput_ever_delivered` as
  denominator.
- **Streaming-streaming aggregator.** v1 streams per-issue rows to
  disk and re-reads them once for aggregation (bounded memory per
  issue). v2 could keep running aggregates in memory and avoid the
  re-read for very large scopes (>100k issues).
- **Semantic JQL / OData normalization** for cache-key derivation.
  Today `"a AND b"` and `"b AND a"` produce different cache files.
  Wasted recomputation, not wrong answers. v2 with a real parser.
- **YAML state config.** If hand-editing turns out to be the
  bottleneck.
- **Per-team timezone handling.** If distributed teams want their
  "business hours cycle time" computed locally.
- **Statistical significance markers on cohort breakdown.** Today the
  output is descriptive — p50/p75/p90 with counts. A v2 could flag
  when the cohort sample is too small to claim a real delta
  (Mann-Whitney U, bootstrap CI).
- **Business-day-only Flow Load.** `--business-days-only` to exclude
  weekends and configured holidays from the daily sample set.
- **Per-team cohort breakdown.** v1's `cohort_breakdown` is global;
  v2 could split `per_team` rows into `cohort`/`control` columns.
- **Total accessible-issue audit.** Today permission undercount is a
  best-effort note from comparing JQL count to `get-project` total.
  A v2 could enumerate accessible vs inaccessible issue keys for an
  explicit reconciliation report.

## Acceptance criteria

The non-test checklist for "done":

- [ ] All Contract tests above pass on macOS and Linux under Python
      3.10, 3.11, 3.12.
- [ ] SKILL.md follows the dropkit pattern from `jira-defect-flow`:
      cross-skill calls by name, security rules, "Don't" list, Edge
      cases section. No raw REST.
- [ ] Default state config (`references/states.default.json`) maps
      "Won't Do" / "Cancelled" / "Duplicate" to a `cancelled` canonical
      state and ships the `team_field` schema commented for the user
      to fill in.
- [ ] Default issuetype config (`references/issuetypes.default.json`)
      ships with `feature/defect/debt/risk/subtask` buckets.
- [ ] `manifest.json` declares `deps.skills: [{name: "jira"}, {name:
      "jira-align"}]`.
- [ ] One real-team smoke run produces numbers that match a
      hand-computed reference for cycle time, lead time, throughput,
      rework rate, and cancelled count to within ±1%.
- [ ] Output JSON is documented with a schema file at
      `references/output.schema.json`, including the
      `unrequested-metrics-are-absent` rule.
- [ ] Upstream-skill verb usage matches the allowlist; the read-only
      contract test exercises every supported scope/flag combination.
- [ ] No new top-level repo dirs. Skill lives at
      `skills/workflows/flow-metrics/` matching the existing layout.
- [ ] README or skill SKILL.md links to this spec.
- [ ] Pre-implementation gap: if `jira: raw GET
      issue/<KEY>/changelog` is not yet supported by the upstream
      `jira` skill or its response shape doesn't surface a "more pages"
      signal, the upstream skill is extended first (separate PR
      against the `jira` skill).
