# How to run ai-adoption-report

Pair (or aggregate) one or more `flow-metrics` JSON files and emit a
Markdown delta report (with a JSON sidecar). The skill makes no
upstream calls — it reads JSON, subtracts numbers, and renders a
table.

Three modes share one engine:

| Mode | Question it answers | Inputs |
|---|---|---|
| `baseline` | "How are our metrics now vs. pre-AI?" | Two JSONs, same scope, non-overlapping windows. |
| `cohort` | "Within this window, did AI-tagged tickets differ from untagged?" | One JSON that was produced with `--cohort-jql`. |
| `program` | "What does this window look like across all teams in the program?" | A directory of JSONs for the same window, non-overlapping scopes. |

The full contract lives in
[`docs/specs/ai-adoption-report.md`](../../specs/ai-adoption-report.md).
This guide assumes you've already produced the `flow-metrics` JSONs —
if not, start with
[Run flow-metrics](run-flow-metrics.md). That, in turn, depends on
the `jira` skill being set up; see
[Set up the jira skill](set-up-jira-skill.md) if you've never run
any of this before.

Because this skill makes no upstream calls, no Jira credentials are
needed to run it — only the JSON files produced by upstream
`flow-metrics` runs.

## Before you start

1. **Generate the input JSONs with `flow-metrics`.** Each input must
   carry `meta.scope`, `meta.window`, `state_config_sha`,
   `issuetype_config_sha`, `schema_version`, and `generated_at`. Any
   `flow-metrics` v1 output qualifies. **Caveat:** if the upstream
   run was invoked with `--metrics` to filter, missing metrics in the
   input render as `—` cells in the report rather than failing — see
   [Reading delta cells](#reading-delta-cells).
2. **Keep the inputs inside your working directory.** All paths must
   resolve under CWD; absolute paths that escape exit 2.
3. **Decide your output path.** The skill writes Markdown to
   `--output` and a JSON sidecar to the same name with `.md → .json`
   (or `+ .json` if no extension). Both files refuse to overwrite
   unless you pass `--overwrite`.

## Mode: baseline

Compare one scope across two windows.

```bash
ai-adoption-report baseline \
  --baseline outputs/PROJ-Foo-2024Q1.json \
  --current  outputs/PROJ-Foo-2025Q4.json \
  --output   reports/baseline-PROJ-Foo.md
```

**Pairing rules:**

- `baseline.meta.scope` must equal `current.meta.scope` exactly (same
  keys, same values). Mismatched scopes exit 2.
- `baseline.meta.window.to` must be ≤ `current.meta.window.from`.
  Overlapping windows exit 2. Back-to-back windows (equal endpoints)
  are allowed.

**Drift signals (warnings, not errors):**

- If `state_config_sha` or `issuetype_config_sha` differ between
  inputs, a `config-sha-drift` note is added. Deltas still render —
  but be aware that a status was remapped between runs.
- If either input has a non-empty `per_team` array (it came from a
  `--program-id`/`--portfolio-id` run), it's ignored with a note.
  Baseline is a single-scope comparison; use program mode for
  per-team rollups.

### Including cohort breakdown in baseline

```bash
ai-adoption-report baseline \
  --baseline outputs/PROJ-2024Q1-with-cohort.json \
  --current  outputs/PROJ-2025Q4-with-cohort.json \
  --include-cohort-breakdown \
  --output   reports/baseline-PROJ.md
```

Both inputs must:

- carry a `cohort_breakdown` block (i.e. were produced with
  `--cohort-jql`), and
- share the same `meta.cohort_jql` string.

If either condition fails, the cohort section is silently omitted and
the reason is recorded in `notes`. Deltas still render.

## Mode: cohort

Report the AI-vs-control split that `flow-metrics` already computed
for a single window.

```bash
ai-adoption-report cohort \
  --input  outputs/PROJ-Foo-2025Q4-with-cohort.json \
  --output reports/cohort-PROJ-Foo-2025Q4.md
```

The input **must** contain a `cohort_breakdown` block. If it doesn't,
the skill exits 2 with the literal message
`"--input was not produced with --cohort-jql; no cohort_breakdown
block present"`. Fix by re-running `flow-metrics` with `--cohort-jql`
and a label-based filter (e.g. `"labels = ai-assisted"`).

**Important — read this if your cohort numbers look surprising:**

The cohort and control sides are computed against **their own
denominators**. A cohort rework rate of 0.5 over 10 issues and a
control rework rate of 0.1 over 90 issues does **not** weighted-
average to the global 0.14. For the worked example and rationale see
[Explanation: the cohort model](../explanation/cohort-model.md#why-cohort--control-dont-average-to-global);
the formal rule is in
[flow-metrics §Metric definitions](../../specs/flow-metrics.md#metric-definitions).

## Mode: program

Roll up many scopes for a single window.

```bash
ai-adoption-report program \
  --inputs outputs/2025Q4/ \
  --window 2025-10-01..2025-12-31 \
  --output reports/program-2025Q4.md
```

**Discovery:** the skill globs `<DIR>/*.json` non-recursively. Every
JSON file in `outputs/2025Q4/` is considered.

**Window filter:** only files whose `meta.window.from` and
`meta.window.to` exactly match `--window` are included. Files outside
the window are silently dropped. Zero matches → exit 2.

**Scope overlap is a hard error.** The skill exits 2 if any two
scopes in the matched set overlap:

| Scope A | Scope B | Overlap? |
|---|---|---|
| portfolio | anything | yes |
| program | project / project+team | yes |
| project (no team) | project+team with same project | yes |
| project PROJ-A | project PROJ-B | no |
| project+team Foo | project+team Bar (same project) | no |
| identical scope dicts (any kind) | | yes — distinct exit-2 message: `"duplicate scope in input set: <scope> in <basename-a> and <basename-b>"` |

The skill does **not** resolve Jira hierarchy. Overlap is determined
solely from the `meta.scope` dicts. If you accidentally have a
project-wide JSON sitting next to its per-team JSONs, you'll get an
overlap error — move the project-wide file out of the input directory
and re-run.

**Per-team rollup pass-through:** if individual JSONs came from
`--program-id`/`--portfolio-id` runs and carry a non-empty `per_team`
array, the program-mode aggregator flattens those into the per-scope
table (one row per `(scope, team)` pair). Flattened per-team rows are
**excluded from the cohort rollup** in v1 — `flow-metrics` doesn't
split `per_team` by cohort yet. If any input has
`meta.per_team_double_counted: true` (i.e. came from an array-kind
team field), a `per_team-double-counted` note records the
contributing basenames so downstream summers know to expect
overlapping team counts.

### Including cohort breakdown in program mode

```bash
ai-adoption-report program \
  --inputs outputs/2025Q4/ \
  --window 2025-10-01..2025-12-31 \
  --include-cohort-breakdown \
  --output reports/program-2025Q4.md
```

Scopes without `cohort_breakdown` are silently dropped from the
cohort section with a `notes` line counting them. If the contributing
scopes don't share a single `meta.cohort_jql`, a `mixed-cohort-jql`
note records the distinct values — the rollup still proceeds, but
"cohort" means different things across scopes. If **zero** scopes
carry `cohort_breakdown` after filtering, the cohort section is
omitted entirely and `notes` records `cohort-breakdown-section-empty`.

Scopes whose `cohort_breakdown.<side>` is missing `flow_distribution`
(because the upstream run filtered metrics) are dropped from the
`defect_ratio` and `flow_distribution` side-rollups only, not from
throughput or rework rate. A `cohort-flow_distribution-missing` note
records this per side.

## Common output (all modes)

By default the skill writes both formats:

- **Markdown** at the literal `--output` path you pass.
- **JSON sidecar** derived by swapping `.md → .json`, or by appending
  `.json` if `--output` has no extension.

To skip one:

```bash
# Markdown only — no JSON sidecar written:
ai-adoption-report cohort --input ... --output report.md --format markdown

# JSON only — pass a base name (no .md) so the resolved path is
# unambiguous; the JSON file is written to <base>.json:
ai-adoption-report cohort --input ... --output report --format json
```

The Markdown report has a fixed section order:

1. Header (mode, generated_at, input count, mode-specific scope/window line)
2. Summary (one-line plain-English)
3. Metric deltas (one row per metric, percentiles broken out)
4. Per-scope rows (program mode only)
5. Cohort breakdown (when `--include-cohort-breakdown`)
6. Notes
7. Provenance — basename, scope, window, config SHAs, upstream
   `generated_at` for every input file. This is the audit trail; keep
   it.

### Reading delta cells

| Cell content | Meaning |
|---|---|
| `+12.5%` / `−3.0%` | Signed percent change to one decimal. |
| `—` (em dash) | Undefined: both sides zero, either side `null`, or a metric absent from the upstream JSON. |
| `+∞%` | Baseline was zero; current is positive. (`−∞%` is reserved for signed metrics; flow-metrics v1 emits none, so you will not see it in practice.) |
| Numeric cells use Unicode `−` | ASCII `-` is reserved for date ranges (`2024-Q1`). |

A `notes` entry always explains a `—`. Read the notes.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Exit 2, message about missing `cohort_breakdown` block | Cohort mode requires a `cohort_breakdown` block. | Re-run `flow-metrics` with `--cohort-jql "labels = ai-assisted"` (or whatever label your team uses). |
| Exit 2, scope mismatch (baseline) | Baseline and current JSONs report different scopes. | Confirm both runs used the same `--project` / `--team` / program / portfolio flags. The scope dicts must be **equal** (same keys, same values — content-equality, not byte-equality of the serialised JSON). |
| Exit 2, window overlap (baseline) | `baseline.window.to > current.window.from`. | Pick non-overlapping windows. Back-to-back (`baseline.to == current.from`) is fine. |
| Exit 2, no inputs matched `--window` (program) | No file's `meta.window` equals the `--window` you passed. | Open one input and check `meta.window` — `flow-metrics` writes the window you passed it. Match exactly. |
| Exit 2, overlapping scopes (program) | The matched set contains a portfolio + program, or a project + project+team, etc. | Remove the broader scope from the input directory or move it out before running. |
| Exit 2, duplicate scope (program) | Two input files have byte-identical scope dicts. | The skill won't silently collapse them. Decide which one to keep and remove the other. |
| `notes: config-sha-drift` | State or issuetype config changed between the two `flow-metrics` runs. | Inspect the configs — a remapped status can shift cycle time materially. Decide whether the comparison is honest. |
| `notes: per_team-cohort-deferred` | Program mode flattened `per_team` rows but skipped them in the cohort rollup. | v1 limitation. Run cohort mode per-scope if you need per-team cohort numbers. |
| `notes: mixed-major-schema-versions` | Inputs were produced by different major versions of `flow-metrics`. | The report still renders, but verify the metric definitions match. Re-running every input under one version is safer. |
| Hard to tell what's happening | Default output is terse. | Add `--verbose` to log validation steps, pairing decisions, and file writes. |

## End-to-end example: baseline-then-cohort

A team lead wants both views for one project, one team, Q4 2025 vs.
Q1 2024.

```bash
mkdir -p outputs reports

# Baseline window — pre-AI period, no cohort tagging needed:
flow-metrics --project PROJ --team "Foo" \
  --from 2024-01-01 --to 2024-03-31 \
  --output outputs/PROJ-Foo-2024Q1.json

# Current window — with cohort tagging via Jira labels:
flow-metrics --project PROJ --team "Foo" \
  --from 2025-10-01 --to 2025-12-31 \
  --cohort-jql "labels = ai-assisted" \
  --output outputs/PROJ-Foo-2025Q4.json

# Baseline report (no --include-cohort-breakdown — the 2024Q1 file
# lacks a cohort_breakdown block):
ai-adoption-report baseline \
  --baseline outputs/PROJ-Foo-2024Q1.json \
  --current  outputs/PROJ-Foo-2025Q4.json \
  --output   reports/baseline-PROJ-Foo.md

# Cohort report (within Q4 only):
ai-adoption-report cohort \
  --input  outputs/PROJ-Foo-2025Q4.json \
  --output reports/cohort-PROJ-Foo-2025Q4.md
```

Two Markdown files, two JSON sidecars, one audit trail per report.
