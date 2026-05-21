# ai-adoption-report — worked example

A demo-quality walkthrough of the `ai-adoption-report` skill against
plausible (but fully fabricated) `flow-metrics` outputs from a
fictional engineering organisation, **ACME Inc.**

Use this directory to see what the three modes produce *before* you
wire the skill up against your own data. Everything here is checked
in and reproducible — running the commands below regenerates the
files in `outputs/` byte-for-byte.

> ⚠ **The numbers in this directory are fabricated.** Every input
> JSON was hand-curated to tell a coherent story. Do not infer that
> AI pairing produces "+23% throughput, −21% cycle time" in real
> organisations — the demo shows what the *report* looks like, not
> what AI adoption produces. The §"What this demo is NOT" section
> at the bottom of this file restates the disclaimer.

## The story

ACME's Checkout team (project key `CHECKOUT`, team `Foo`) was a
representative pilot site for an AI-pairing rollout in mid-2025. By
Q4 2025 the program lead wanted to answer three questions:

1. **Did Checkout's flow metrics actually move year-on-year?**
   → `baseline` mode against the team's 2024 Q1 numbers.
2. **Within Q4 2025, did tickets tagged `labels = ai-assisted`
   behave differently from untagged tickets on the same team?**
   → `cohort` mode against a `flow-metrics` run invoked with
   `--cohort-jql 'labels = ai-assisted'`.
3. **What does Q4 2025 look like across all four engineering
   teams in the program — Checkout, Search, Billing, Risk?**
   → `program` mode across the four teams' JSONs.

The numbers tell an honest, mixed story: Checkout's cycle time
dropped sharply but rework went *up* (engineers iterate more when
the tool makes it cheap); within Q4, AI-tagged tickets shipped
faster than untagged ones but rework climbed harder; across the
program, Risk regressed while Checkout, Search and Billing all
improved on different dimensions. The report does NOT classify any
of this as good or bad — it lays out the numbers and lets the
reader decide.

## Directory layout

```
examples/ai-adoption-report/
├── README.md                              ← you are here
├── inputs/
│   ├── baseline/
│   │   ├── CHECKOUT-Foo-2024Q1.json       ← pre-AI baseline
│   │   └── CHECKOUT-Foo-2025Q4.json       ← post-AI current
│   ├── cohort/
│   │   └── CHECKOUT-Foo-2025Q4-with-cohort.json
│   │                                      ← same Q4 but produced by
│   │                                        flow-metrics with --cohort-jql
│   └── program/
│       ├── CHECKOUT-2025Q4.json           ← team Foo's project rollup
│       ├── SEARCH-2025Q4.json
│       ├── BILLING-2025Q4.json
│       └── RISK-2025Q4.json
└── outputs/
    ├── baseline-report.md   + baseline-report.json
    ├── cohort-report.md     + cohort-report.json
    └── program-report.md    + program-report.json
```

## Running the demo

**Prerequisites:** Python ≥ 3.10 (the skill's runtime floor; see
`skills/workflows/ai-adoption-report/manifest.json`'s `deps.system`).
Run every command **from the repository root** — the skill rejects
`--output` paths outside the current working directory.

```bash
export PYTHONPATH="$(pwd)/skills/workflows/ai-adoption-report/scripts:$PYTHONPATH"

# Pin generated_at so the outputs match the checked-in versions
# byte-for-byte (and LC_ALL=C is a deterministic-collation safeguard).
export AI_ADOPTION_REPORT_GENERATED_AT=2026-01-15T09:00:00Z
export LC_ALL=C

# Baseline: pre-AI Q1 2024 vs post-AI Q4 2025 for one team.
python -m ai_adoption_report baseline \
  --baseline examples/ai-adoption-report/inputs/baseline/CHECKOUT-Foo-2024Q1.json \
  --current  examples/ai-adoption-report/inputs/baseline/CHECKOUT-Foo-2025Q4.json \
  --output   examples/ai-adoption-report/outputs/baseline-report.md \
  --overwrite

# Cohort: within Q4 2025, ai-assisted vs everything else.
python -m ai_adoption_report cohort \
  --input  examples/ai-adoption-report/inputs/cohort/CHECKOUT-Foo-2025Q4-with-cohort.json \
  --output examples/ai-adoption-report/outputs/cohort-report.md \
  --overwrite

# Program: Q4 2025 across all four teams.
python -m ai_adoption_report program \
  --inputs examples/ai-adoption-report/inputs/program \
  --window 2025-10-01..2025-12-31 \
  --output examples/ai-adoption-report/outputs/program-report.md \
  --overwrite
```

Each invocation writes a Markdown report **and** a JSON sidecar
(`.json` next to the `.md`). With the env vars above set, the
generated files are byte-identical to the ones checked in.

Drop the `AI_ADOPTION_REPORT_GENERATED_AT` env var to see what a
real run looks like — the only difference will be the
`**Generated at:**` line at the top of each report.

### Why byte-identity holds

The demo regression tests (`tests/test_t9_packaging.py`'s
`test_demo_*` family) assert byte-identity against the checked-in
outputs. The contract:

- `AI_ADOPTION_REPORT_GENERATED_AT=2026-01-15T09:00:00Z` pins the
  only per-run timestamp.
- `LC_ALL=C` pins string-sort collation (the spec mandates codepoint
  order; `LC_ALL=C` is the belt-and-braces).
- Python ≥ 3.10 is the runtime floor; older minor versions would
  exit 2 at startup with a clear message.
- Float rendering is hand-controlled in `render.py` (4 dp, trailing
  zeros stripped). No locale-dependent formatting.
- The report's `notes` array is lex-sorted on serialisation;
  `PYTHONHASHSEED` does not matter.

If the skill's renderer changes in a way that updates the wire
format, the demo outputs must be regenerated. The commands above
ARE the regenerate recipe; run them after a renderer change and
commit the updated `outputs/`.

## Reading the demo outputs

### `baseline-report.md` — Checkout team, 2024 Q1 → 2025 Q4

The headline: throughput **up 23%**, cycle time p50 **down 21%**,
but rework rate **up 21%**. The report surfaces all three movements
in the Metric deltas table; it makes no editorial judgment about
whether "more iterations to ship faster" is good or bad.

Flow efficiency improved at every percentile. Defect ratio dropped.
The `notes` block records that the `n` (issue count) per
distribution metric differs by more than 10% between the two
windows — useful context when reading the percentile shifts.

### `cohort-report.md` — within Q4 2025, ai-assisted vs not

A vs B is `control` (untagged) on the left, `cohort` (ai-assisted)
on the right. Cohort tickets shipped with **cycle time p50 29% lower**
and **flow efficiency p50 24% higher** than control. They also
showed **rework rate 62% higher** (0.13 → 0.21) — the same "iterate
more, ship faster" pattern visible in the baseline report, now
isolated to the AI-tagged subset.

Throughput is lower on the cohort side simply because fewer tickets
were tagged; this is expected and not a sign of slower delivery.

### `program-report.md` — Q4 2025 across four teams

Per-scope rows show:

- **CHECKOUT** — strongest cycle-time, healthy throughput.
- **SEARCH** — lowest defect ratio, moderate cycle time.
- **BILLING** — lowest rework rate; defect ratio mid-pack.
- **RISK** — slowest cycle, highest rework AND defect ratio.

The Aggregate row at the bottom is a program-wide rollup using
the spec's documented weighting rules (throughput sum, distribution
median-of-medians, throughput-weighted rework rate,
flow-distribution-denominator-weighted defect ratio). The `notes`
block records the median-of-medians approximation so readers know
to consult per-scope rows for true distribution detail.

## What this demo is NOT

- **Not real data.** Every number was hand-curated to tell a
  coherent story. Realistic ranges; fictional source.
- **Not a benchmark.** Do not infer that AI pairing produces
  "+23% throughput, −21% cycle time" in real organisations.
- **Not a validation set.** The byte-identity tests live in
  `skills/workflows/ai-adoption-report/tests/fixtures/golden/`,
  not here. This directory is a docs artefact.

## Plugging in your own data

When you have real `flow-metrics` outputs, the same three
invocations work — point `--baseline`, `--current`, `--input`, or
`--inputs` at your files. The skill validates the `meta` block and
exits 2 with a basename-named message if anything is missing; see
`skills/workflows/ai-adoption-report/SKILL.md` for the full input
contract.
