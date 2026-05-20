# How to run flow-metrics

Compute DORA and Flow Framework metrics for a Jira project, team,
Jira Align program, or Jira Align portfolio over a time window. The
output is JSON (or CSV); downstream skills like
[`ai-adoption-report`](run-ai-adoption-report.md) consume it.

This guide gets you from "I have Jira credentials" to "I have a
report-ready JSON file." The full contract lives in
[`docs/specs/flow-metrics.md`](../../specs/flow-metrics.md).

## Before you start

If this is your team's first run, work through
[Prepare Jira for flow-metrics](prepare-jira-for-flow-metrics.md)
first — it covers the status audit, team-field validation, and
cohort-label decision that this page assumes are already done.

1. **Install dropkit** and the `jira` skill, and configure credentials
   for it. The `jira` skill owns `~/.config/dropkit/credentials.env`;
   `flow-metrics` never reads that file itself, it just calls the
   skill. Step-by-step:
   [Set up the jira skill](set-up-jira-skill.md). If
   `python skills/integrations/jira/scripts/jira.py check` doesn't
   exit 0, every `flow-metrics` run exits 3 — fix this first.
2. **Jira Align scopes (`--program-id`, `--portfolio-id`) only:** also
   install and configure `jira-align`. Step-by-step:
   [Set up the jira-align skill](set-up-jira-align-skill.md), which
   also covers the
   [`align_join_field` wiring](set-up-jira-align-skill.md#wiring-up-flow-metrics-jira-align-scopes)
   you'll need before program / portfolio runs work.
3. **Pick or write a state config.** The shipped default at
   `references/states.default.json` maps six canonical states:
   `backlog` (raw: "Backlog", "To Do", "Open"); `in_progress` ("In
   Progress", "In Development"); `in_review` ("In Review", "Code
   Review", "Ready for Review"); `in_test` ("QA", "Testing", "In
   Test"); `done` ("Done", "Closed", "Resolved"); `cancelled` ("Won't
   Do", "Won't Fix", "Cancelled", "Duplicate"). If your project uses
   any status name not in those lists, jump to
   [Customising the state config](#customising-the-state-config)
   first — an unmapped status exits 2 and refuses to compute.
4. **Confirm your team field (only if slicing by team).** The shipped
   default sets `team_field.id: customfield_10001`. If your instance
   uses a different custom field, override it per-run via
   `--team-field-override` or edit the config — see
   [Slicing by team](#slicing-by-team).

The skill never writes to Jira. Browse permission on the project is
sufficient.

## Quick start: one project, last 90 days

```bash
flow-metrics --project PROJ
```

This emits aggregate JSON to stdout: cycle time, lead time, throughput,
WIP, rework rate, defect ratio, Flow Distribution, broken down nowhere.
Default window is `today − 90 days` through `today` (UTC, inclusive of
both named days).

To write to a file instead of stdout:

```bash
flow-metrics --project PROJ --output PROJ-last-90d.json
```

## Scope a run

Pick exactly one scope flag — `--project`, `--program-id`, or
`--portfolio-id`. `--team` is only valid with `--project`.

| Goal | Command |
|---|---|
| One project | `flow-metrics --project PROJ` |
| One team in a project | `flow-metrics --project PROJ --team "Foo"` |
| Everything in a Jira Align program | `flow-metrics --program-id 42` |
| Everything in a Jira Align portfolio | `flow-metrics --portfolio-id 7` |

Add `--from YYYY-MM-DD --to YYYY-MM-DD` to override the default
90-day window. Both dates are inclusive of the named day. Times are
always UTC.

```bash
flow-metrics --project PROJ --from 2025-10-01 --to 2025-12-31 \
  --output PROJ-2025Q4.json
```

### Slicing by team

`--team NAME` adds a JQL clause on the configured team custom field.
The shipped default is `customfield_10001` (set in
`states.default.json` under `team_field.id`). Two ways to point at a
different field:

- **One-off:** `--team-field-override customfield_12345`. Validated
  against Jira's field catalog at startup; unknown → exit 2. When
  this flag is set, the config's `team_field.id` is **ignored
  entirely for that run** — including the catalog-validation step.
- **Persistent:** edit `team_field.id` in your state config (see
  below).

If your team field holds an array (one issue can belong to multiple
teams), set `team_field.kind: "array"` in the state config. The
`per_team` rollup rows then overlap on purpose, and the output sets
`meta.per_team_double_counted: true` plus a `notes` line of the form
`"per_team: K issues belong to multiple teams and are counted in each
(team_field.kind=array)"`.

### Jira Align scope (program / portfolio)

`--program-id` and `--portfolio-id` add a Jira Align join for team
mapping. You **must** also provide a join field — there's no default,
because picking one wrong is a wrong-answer risk:

- **Persistent:** add `"align_join_field": "customfield_12345"` to
  the state config.
- **One-off:** `--align-join-field customfield_12345`.

Forgetting both exits 2 with a clear message. Jira Align is used only
to resolve which teams belong to the program/portfolio; the actual
time-in-state numbers still come from Jira changelogs.

If your Jira Align instance enumerates teams under a non-default
path, override with `--align-teams-path PATH`. The override must
match one of the allowlisted patterns
(`programs/<id>`, `programs/<id>/teams`, `portfolios/<id>`,
`portfolios/<id>/programs`) — paths containing `..` or starting with
`/` are rejected with exit 2; response shapes missing an `id` field
exit 3.

To narrow further, `--align-filter "<OData>"` ANDs an extra OData
clause into Jira Align queries — symmetrical to how `--jql` extends
the Jira clause.

## Cohort breakdown (AI vs control split)

This is the load-bearing input for
[`ai-adoption-report cohort`](run-ai-adoption-report.md#mode-cohort).

The skill does **not** auto-detect AI-assisted work. You tag the
issues yourself in Jira — typically with a label like `ai-assisted` —
then pass a JQL expression that identifies them. For the rationale
behind manual labelling and the denominator behaviour that surprises
most first-time readers, see
[Explanation: the cohort model](../explanation/cohort-model.md).

```bash
flow-metrics --project PROJ --from 2025-10-01 --to 2025-12-31 \
  --cohort-jql "labels = ai-assisted" \
  --output PROJ-2025Q4-with-cohort.json
```

The output gains a `cohort_breakdown` block with `cohort` and
`control` sub-objects. Each side's metrics are computed using **only
that side's issues** as both numerator and denominator — cohort +
control will not weighted-average back to the global figure when
sizes differ. That's intentional.

Empty cohorts are not an error: the cohort sub-object reports
`throughput: 0` and `null` percentiles. Exit 0.

**On Jira Align scopes (`--program-id`, `--portfolio-id`), `per_team`
rows are not split by cohort in v1** — only the top-level
`cohort_breakdown` reflects the cohort/control split. Per-team cohort
breakdown is deferred to v2.

If you need per-issue inspection instead of a single aggregate, see
[Per-issue output](#per-issue-output) — the rules differ.

## Customising the state config

The shipped default lives at one of two paths depending on how you
installed the skill:

- Dropkit clone:
  `skills/workflows/flow-metrics/references/states.default.json`
- Kit-installer layout:
  `~/.claude/skills/flow-metrics/references/states.default.json`

If your project uses status names not covered by the default — say
"Backlog Refined", "Dev Complete", "Awaiting Test" — copy the
default, edit, and pass `--state-config`:

```bash
# from a dropkit clone:
cp skills/workflows/flow-metrics/references/states.default.json \
   my-team-states.json
# edit my-team-states.json
flow-metrics --project PROJ --state-config my-team-states.json
```

**Rules to keep in mind:**

- Every raw status that appears in the changelog **must** be mapped
  under some `canonical_states` entry. Unmapped → exit 2 naming the
  offender. The most common cause of this is a project-specific
  "Cancelled-equivalent" status; map it under `cancelled`.
- `commitment_state` and `delivery_state` must each be exactly one
  canonical state, must differ from each other, and **neither** may
  appear in `terminal_non_delivery_states`.
- `active_states` and `wait_states` must be disjoint. The shipped
  default has `active_states = ["in_progress"]` and
  `wait_states = ["backlog", "in_review", "in_test"]`. Moving review
  and test states into `active_states` (a common misconfiguration)
  produces degenerate Flow Efficiency ≈ 1.0 for non-rework flows
  because almost no time gets recorded against wait states. See
  [spec §State configuration](../../specs/flow-metrics.md#state-configuration)
  for the full rationale.
- The full integrity check has nine distinct exit-2 conditions; all
  run at startup before any data fetch.

A semantic edit to the state config (adding a status mapping,
renaming a canonical state) **invalidates the cache automatically** —
the next run re-fetches from Jira. Whitespace-only edits (e.g.
re-running `jq .`) do not invalidate. You generally do not need
`--no-cache` after editing the config.

## Issuetype config (Flow Distribution buckets)

The defaults at `references/issuetypes.default.json` map:

| Bucket | Default issuetypes |
|---|---|
| `feature` | Story, Task, Epic, Feature |
| `defect` | Bug, Defect |
| `debt` | Tech Debt, Refactor |
| `risk` | Risk, Vulnerability |
| `subtask` | Sub-task, Subtask |

Anything else (Spike, Incident, …) falls into `other` and is recorded
in `notes`. That's deliberately non-fatal — Flow Distribution is
descriptive. Override with `--issuetype-config FILE` if you want a
custom bucketing.

## Per-issue output

For consumers that need to re-aggregate or inspect individual issues:

```bash
flow-metrics --project PROJ --from 2025-10-01 --to 2025-12-31 \
  --per-issue --output rows.jsonl
```

- JSONL on disk; one row per issue **in scope** (delivered-in-window,
  cancelled-in-window, or WIP at `--to`).
- `--output` is **required**.
- `cohort_breakdown` is **not** emitted; instead every row carries a
  `cohort` boolean. Re-aggregate downstream.
- Cancelled-in-window and WIP-only rows have `null` for every
  delivery-based field (`cycle_time_hours`, `lead_time_hours`, etc.).
  **Always filter `delivered_in_window == true` before computing
  delivery-based metrics from this file.**

For the full per-row field list (booleans, derived hours, issuetype
bucket, etc.) see
[spec §Outputs / Per-issue mode](../../specs/flow-metrics.md#outputs).

## Filtering metrics

By default the skill emits every metric. To narrow:

```bash
flow-metrics --project PROJ --metrics throughput,wip,cycle_time
```

Unrequested metrics are **absent** from `aggregates` (not emitted as
`null`). The list of computed metrics appears in
`meta.metrics_requested`.

Note: `flow_distribution` and `defect_ratio` are independent —
requesting one does not pull in the other. `flow_time` is an alias of
`lead_time` (same values, different key), but they are separate names
in `--metrics` — request both if you want both keys present.

## Including sub-tasks

By default sub-tasks are excluded from throughput, cycle time, lead
time, Flow Efficiency, and rework rate. They always appear separately
in `flow_distribution.subtask`.

To include them in the other metrics:

```bash
flow-metrics --project PROJ --include-subtasks
```

## Output formats

| Flag | Output |
|---|---|
| (default) | JSON, aggregate mode, to stdout |
| `--format csv` | Long-form CSV: `metric,scope,cohort,team,p50,p75,p90,count` |
| `--output FILE` | Write to file (atomic temp-then-rename) |
| `--per-issue --output FILE.jsonl` | One row per issue (JSONL) |

`--output` paths are validated: relative paths resolve against cwd;
absolute paths cannot escape into `/etc`, `/sys`, `/proc`, `/dev`,
`/boot`, or Windows system roots. Paths containing a null byte are
also rejected.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Exit 2, message names an unmapped raw status | Project uses a status name not in the state config. | Add the raw name to a `canonical_states` entry — `cancelled` is the most common omission. |
| Exit 2, message says the join field is missing | `--program-id` / `--portfolio-id` without a configured join field. | Add `align_join_field` to the state config or pass `--align-join-field`. |
| Exit 2, message names a customfield ID that isn't in Jira's field catalog | Configured team field doesn't exist on this instance. | Run `jira: raw GET field` to list the real custom field IDs, then update the config or use `--team-field-override`. |
| Exit 3, upstream stderr relayed verbatim | The data layer failed — auth, rate limit, network, etc. Exit 3 always means upstream. | Read the relayed stderr. Re-run `jira: check` to verify auth before re-trying. |
| `notes` line about permission undercount (e.g. `"permissions: K issues in project are inaccessible to the caller and are silently excluded"`) | Caller lacks browse permission on some issues in scope. | Not an error — but cross-account comparisons may differ. Either re-run as a service account with full access, or accept the partial coverage. |
| Cache seems stale | The cache key includes scope, window, the user `--jql` clause, the user `--align-filter` OData clause, team selection, both configs (state and issuetype, semantic SHAs — whitespace-only edits don't invalidate), the team-field override, and the Jira-Align join/teams paths. Several inputs are **post-fetch only** and never affect the cache: `--metrics`, `--include-subtasks`, and `--cohort-jql`. | For a one-off bypass: `--no-cache`. Cache lives at `.context/flow-metrics/cache/`. |
| Hard to tell what's happening (no upstream calls visible, mysterious wait) | Default output is terse. | Add `--verbose` to log state-transition walks, cache hits, and upstream skill invocations. |

## Inspecting output

A run produces (aggregate mode):

```jsonc
{
  "meta": {
    "scope":       { "project": "PROJ", "team": "Foo" },
    "window":      { "from": "2025-10-01", "to": "2025-12-31" },
    "cohort_jql":  "labels = ai-assisted",        // omitted if --cohort-jql absent
    "state_config_sha":     "...",
    "issuetype_config_sha": "...",
    "schema_version":       "1.0",
    "generated_at": "2026-05-19T14:00:00Z",
    "caller":      "5b10ac8d82e05b22cc7d4ef5",
    "metrics_requested": ["..."],
    "sources":     ["jira"],
    "per_team_double_counted": false
    // serialised keys are sorted at every level; shown loosely here for readability
  },
  "aggregates":        { /* cycle_time_hours, throughput, wip, ... */ },
  "cohort_breakdown":  { "cohort": {}, "control": {} },        // when --cohort-jql
  "per_team":          [],                                     // program/portfolio scope
  "notes":             []
}
```

Always read the `notes` array — population caveats, permission
undercount warnings, and config-drift signals all surface there. The
skill never silently drops data without recording a note.

## Saving a baseline for future comparison

The baseline mode of `ai-adoption-report` pairs a pre-AI window
against a current window. If you want that comparison later, generate
the baseline JSON **now** and keep it. Concretely:

```bash
flow-metrics --project PROJ --team "Foo" \
  --from 2024-01-01 --to 2024-03-31 \
  --output baselines/PROJ-Foo-2024Q1.json
```

Commit `baselines/PROJ-Foo-2024Q1.json` to git. The skill writes no
tamper-detection envelope; **git history is the integrity layer.**
Months later, generate the current window's JSON and run
`ai-adoption-report baseline` against the pair (see
[Run ai-adoption-report](run-ai-adoption-report.md)).

## Next step

If you're computing flow metrics to feed an AI-adoption report:

1. Generate the **baseline** window's JSON (pre-AI period). Commit it.
2. Generate the **current** window's JSON with the same scope and a
   non-overlapping window. Back-to-back windows (baseline `to` ==
   current `from`) are allowed.
3. (Optional) Tag your AI-assisted stories in Jira and re-run the
   current window with `--cohort-jql`.
4. Run [`ai-adoption-report`](run-ai-adoption-report.md) against the
   files.
