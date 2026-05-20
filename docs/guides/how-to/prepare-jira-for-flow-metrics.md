# How to prepare Jira for flow-metrics

A preflight checklist for a team running `flow-metrics` for the first
time. Work through this once per project. After completing it you'll
be able to run `flow-metrics --project PROJ` without exit-2s and get
numbers that match what your team actually does.

Allow about 30 minutes. You'll need browse access to the Jira project
and edit access to a local config file.

**Before you start: the `jira` skill must be set up.** `flow-metrics`
makes every Jira call through it; an unconfigured `jira` skill means
exit 3 on every run. If
`python skills/integrations/jira/scripts/jira.py check` doesn't exit
0, finish [Set up the jira skill](set-up-jira-skill.md) first. If
you plan to run `--program-id` or `--portfolio-id` scopes, also
finish [Set up the jira-align skill](set-up-jira-align-skill.md) —
otherwise the program / portfolio scopes exit 2 regardless of how
clean your state config is.

This is task-oriented. For the *why* behind the cohort decision in
step 4, see
[Explanation: the cohort model](../explanation/cohort-model.md).

## Step 1: list the statuses your project actually uses

Open Jira and identify every status that appears in your project's
workflow (not just the ones currently in use — every status an issue
could be in, historically). Most projects have 5–10.

For each, decide which canonical state it maps to:

| Canonical state | Meaning |
|---|---|
| `backlog` | Not yet committed. Includes any "to do" / "open" / "refined" buckets. |
| `in_progress` | Developer hands-on-keyboard. The active state. |
| `in_review` | Waiting for a reviewer. Code review, ready-for-review. |
| `in_test` | Waiting for QA. Testing, in test, QA-pending. |
| `done` | Successfully delivered. The terminal anchor for throughput. |
| `cancelled` | Closed without delivery. Won't Do, Won't Fix, Duplicate. |

Write the mapping down. You'll convert it into JSON in step 2.

Two pitfalls:

- **Missing a "cancelled-equivalent" status is the most common failure.**
  If your project uses "Won't Do" or "Cancelled", make sure it's in
  the list. An issue closed via one of these and not mapped → exit 2
  on first run.
- **Don't classify `in_review` or `in_test` as `in_progress`.** Flow
  Framework convention is active = hands-on-keyboard, wait =
  blocked-on-someone-else. Misclassifying review/test as active makes
  Flow Efficiency degenerate to ≈1.0 on every non-rework flow.

## Step 2: produce your state config

If the shipped default at
`skills/workflows/flow-metrics/references/states.default.json` (or
`~/.claude/skills/flow-metrics/references/states.default.json` if
installed via the kit-installer) already covers every status from
step 1, you can skip ahead — `flow-metrics` will use it by default.

Otherwise, copy and edit:

```bash
cp skills/workflows/flow-metrics/references/states.default.json \
   my-team-states.json
$EDITOR my-team-states.json
```

Add your raw status names under the right `canonical_states` entry.
Everything else (`commitment_state`, `delivery_state`,
`active_states`, `wait_states`, `rework_signals`) can stay at the
defaults unless your team genuinely deviates from the Flow Framework
convention.

You'll pass this file to `flow-metrics` via `--state-config
my-team-states.json` on every run. Consider committing it to your
repo so the whole team uses the same definitions.

## Step 3: decide and validate your team custom field

Skip this step if you don't plan to slice by team (`--team`) or run
program/portfolio scopes.

The shipped default points at `customfield_10001`. Run a quick check:

```bash
jira: raw GET field
```

Search the response for the team-tracking custom field your project
uses (commonly labelled "Team" or "Squad"). Note its `id` (looks like
`customfield_NNNNN`).

If it isn't `customfield_10001`, edit the `team_field.id` in your
state config. Also decide the kind:

- `single_value` — one team per issue. The `per_team` rollup
  reconciles exactly with `aggregates` (issues count once).
- `array` — one issue can belong to multiple teams. `per_team` rows
  overlap on purpose; the output flags this with
  `meta.per_team_double_counted: true`.

Pick the kind that matches how your Jira instance is configured. If
unsure, ask: "Can one issue be assigned to two teams at once?"

## Step 4: pick a cohort-label convention (only for AI-adoption tracking)

Skip this step if you're not measuring AI adoption.

`flow-metrics` reads cohort identity from a JQL clause you supply via
`--cohort-jql`. The tool does not auto-detect AI-assisted work — your
team must mark issues somehow. Most teams use a Jira label.

Decide three things and write them in your team's runbook:

1. **The label name.** Common choice: `ai-assisted`. The spec uses
   this as its example, but you can pick a different value (`ai`,
   `claude-assisted`). Whatever you choose, make sure it
   doesn't collide with another label your team already uses.
2. **What qualifies.** When does a story get the label? The honest
   threshold is "AI materially contributed to the implementation."
   Vaguer thresholds produce noisy data.
3. **When the label gets applied.** Best: at story-close, by the
   developer who did the work. Retro-labelling at sprint end is OK
   but more error-prone.

The JQL clause you'll pass becomes
`--cohort-jql "labels = ai-assisted"` (or whatever you picked).

For the rationale behind manual labelling, the denominator rule, and
the failure modes when labels are inconsistent, see
[Explanation: the cohort model](../explanation/cohort-model.md).

## Step 5: smoke run

Run with the smallest meaningful window to confirm everything is
wired up:

```bash
flow-metrics --project PROJ \
  --state-config my-team-states.json \
  --from 2025-04-19 --to 2025-05-19 \
  --output smoke.json
```

(Adjust dates to a recent 30 days.)

Check the output:

- **Exit 0.** No unmapped statuses, no missing fields.
- **`meta.state_config_sha`** is non-empty.
- **`aggregates.throughput`** is a sensible non-zero count.
- **`notes`** is empty or only contains explanatory entries — read
  every line.

If you get exit 2 with an unmapped status, go back to step 1, add the
missing status, and re-run. If you get exit 3, the failure is in the
data layer (`jira` skill) — check auth and connectivity, not your
config.

## You're ready

You can now follow:

- [Run flow-metrics](run-flow-metrics.md) for day-to-day measurement.
- [Run ai-adoption-report](run-ai-adoption-report.md) once you have
  two windows worth of JSON to compare.

If your team is committing to AI-adoption measurement, generate a
**baseline** window's JSON now and commit it to your repo. Months
later you can pair it with a current window. See
[Saving a baseline for future comparison](run-flow-metrics.md#saving-a-baseline-for-future-comparison).
