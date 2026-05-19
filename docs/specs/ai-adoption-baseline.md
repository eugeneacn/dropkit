# Spec: ai-adoption-baseline

- **Status:** Approved
- **Owner:** eugeneacn
- **Plan:** _not yet drafted_
- **Constrained by:** [`flow-metrics.md`](flow-metrics.md) (Approved, terminal-clean)
- **Review history:** 5 adversarial review rounds (2026-05-19). Round 1: 3 blockers / 11 majors / 8 minors; round 2: 1 blocker / 5 majors / 7 minors; round 3: 1 blocker / 3 majors / 6 minors; round 4: 0 blockers / 1 major / 5 minors; round 5: 0 blockers / 0 majors / 3 minors. Terminal-clean.

> **Spec contract:** this document defines what "done" means for the
> `ai-adoption-baseline` workflow skill. The implementing PR must match this
> spec or update it. Tests must be derivable from it.

## What this is

A read-only workflow skill that snapshots a team's / value stream's
**pre-AI** flow metrics for a fixed window before an AI-tooling rollout
date, and writes the snapshot to `.context/ai-baseline/` as an immutable
reference for later comparison.

It is a thin choreography layer on top of `flow-metrics`: same inputs,
same scope flags, same upstream skills. The only new things it adds are
(a) the rollout-date anchor, (b) the snapshot naming + immutability
contract, and (c) the refusal-to-claim-baseline-without-anchor posture.

## Why

DORA's 2025 State of AI-Assisted Software Development report's central
finding — AI inflates individual throughput while organizational delivery
metrics stay flat or get worse on stability — only shows up when there's
a stable comparison point *before* AI adoption. Every AI-impact claim
downstream (cohort comparisons, ROI reports, board updates) needs to
compare against numbers that everyone agrees were "the pre-AI normal".

Today, teams either skip the baseline (so every claim is "compared to
my dashboard last quarter" — non-reproducible) or hand-roll one in a
spreadsheet (so the math drifts across teams and rebuts itself in
review). A dedicated snapshot skill, anchored on an explicit rollout
date, eliminates both failure modes.

The skill is also the first place where the "AI rollout date" becomes a
load-bearing fact in the toolchain. By forcing the user to name it on
the command line, the skill creates a paper trail nobody has today.

## Users and use cases

In priority order — the first one is load-bearing:

1. **Engineering manager snapshots their team's last 90 days before AI
   rollout.** `ai-adoption-baseline --project PROJ --team Foo --rollout-date 2026-04-01`.
   Result: `.context/ai-baseline/PROJ-Foo-2026-04-01.json` containing
   the full `flow-metrics` output for window `[2026-01-01, 2026-03-31]`.
2. **Portfolio-level baseline for an executive review.**
   `ai-adoption-baseline --portfolio-id 7 --rollout-date 2026-04-01 --label "pre-Q2-rollout"`.
   Result: one snapshot per team in the portfolio, with per-team and
   rolled-up aggregates.
3. **Re-snapshot with a longer window** (e.g., to smooth out a noisy
   90-day baseline). Same command with `--baseline-window-days 180`.
   The output path encodes the window so re-runs don't collide.
4. **Refusal flow.** A user passes `--rollout-date` in the future
   (rollout hasn't happened yet) or omits it entirely. The skill exits
   2 with a clear message rather than silently snapshotting the wrong
   window.

## Behavior

### Inputs

```
ai-adoption-baseline
    --rollout-date YYYY-MM-DD
    (--project KEY | --program-id ID | --portfolio-id ID)
    [--team NAME]
    [--baseline-window-days N]
    [--accept-recent-rollout]
    [--label NAME]
    [--output-dir DIR]
    [--overwrite [--overwrite-snapshot-id ID | --force]]
    [--state-config FILE]
    [--issuetype-config FILE]
    [--verbose]
```

| Flag | Meaning |
|---|---|
| `--rollout-date YYYY-MM-DD` | **Required.** The date AI tooling was rolled out to this team / scope. The baseline window ends one day before this. Must satisfy `rollout_date + stabilization_days <= today_utc` where `stabilization_days = 14` by default — runs closer to the rollout silently undercount throughput because of in-flight tickets that haven't yet transitioned to `done`. Override with `--accept-recent-rollout` if the user knowingly accepts the bias. |
| `--accept-recent-rollout` | Allow `--rollout-date` within the last 14 days. The resulting snapshot's `notes` records the bias warning. |
| `--project / --program-id / --portfolio-id / --team` | Same scope semantics as `flow-metrics`. Exactly one of the three scope flags is required. `--team` is only valid with `--project`. |
| `--baseline-window-days N` | Length of the baseline window in calendar days. Default: 90. Range: `[14, 365]`. Throughput-stability is the consumer's concern, not the snapshot skill's — the skill prints a `notes` warning when `aggregates.throughput < 30` so downstream `ai-adoption-cohort` and `ai-value-report` can soften their conclusions. (The earlier 30-day floor has been replaced by a throughput-based warning.) |
| `--label NAME` | Optional human label included in the snapshot file's `meta.label` field. Does **not** appear in the filename — filenames are deterministic and label-independent so re-runs collide on filename. |
| `--output-dir DIR` | Where snapshot JSON files are written. Default: `.context/ai-baseline/`. The directory is created if absent (mode 0700). |
| `--overwrite` | Allow overwriting an existing snapshot file at the resolved path. Without this flag, a collision exits 2. Snapshots are immutable by convention; overwrites are explicit user action. Must be combined with `--overwrite-snapshot-id` OR `--force` (see "Collision behavior"); `--overwrite` alone exits 2. |
| `--overwrite-snapshot-id ID` | Name the existing file's `meta.snapshot_id` to be replaced. Required with `--overwrite` unless `--force` is used. Mismatched ID → exit 2. Passed without `--overwrite` → exit 2. |
| `--force` | With `--overwrite`, bypass the snapshot-id check. Use only when the existing file is malformed JSON or missing `meta.snapshot_id`. Passed without `--overwrite` → exit 2. |
| `--state-config FILE`, `--issuetype-config FILE` | Forwarded verbatim to `flow-metrics`. Must match the configs the downstream cohort/value-report skills will use; mismatched state configs invalidate the comparison. |
| `--verbose` | Debug logging including the resolved `flow-metrics` invocation. |

### Window resolution

Given `--rollout-date R` (a UTC date) and `--baseline-window-days N`:

- `from = R − timedelta(days=N)` (UTC date).
- `to   = R − timedelta(days=1)` (UTC date).
- The inclusive-inclusive window `[from, to]` is exactly N calendar
  days long, regardless of leap years. Forwarded to flow-metrics as
  `--from <from> --to <to>`; flow-metrics applies its own
  inclusive-window expansion `[from 00:00 UTC, (to + 1 day) 00:00 UTC)`.
- The day of rollout (R) and later are NEVER in the baseline.
- Worked example with a leap-year boundary: `--rollout-date 2025-03-01
  --baseline-window-days 90` → `from = 2025-03-01 − 90 days =
  2024-12-01`, `to = 2025-02-28`. The window contains 31 (Dec) + 31
  (Jan) + 28 (Feb) = 90 days. (A naïve `R − timedelta(days=N-1)` would
  produce `from = 2024-12-02` and N-1 = 89 days; this is the off-by-one
  error the formula guards against.)

### Output path

The snapshot is written to a deterministic path:

```
<output-dir>/<scope-tag>-<rollout-date>-<window-days>d[-cfg<sha8>].json
```

Where `<scope-tag>` is:
- `--project KEY` → `KEY` (or `KEY_Team-Foo` when `--team Foo` is set;
  team name is slugified — non-alphanumeric → `-`, multiple `-`
  collapsed).
- `--program-id N` → `program-N`.
- `--portfolio-id N` → `portfolio-N`.

The optional `-cfg<sha8>` suffix is the first 8 hex chars of
`sha256(state_config_canonical_json + issuetype_config_canonical_json)`
**when the user passed `--state-config` or `--issuetype-config` on the
command line** (flag-presence rule, not content-comparison). The
shipped default configs produce clean filenames; any explicit
`--state-config` / `--issuetype-config` flag produces the suffix even
if the file happens to be byte-identical to the shipped default. This
decouples filename determinism from any future flow-metrics
default-config bumps.

Examples:
- `.context/ai-baseline/PROJ-2026-04-01-90d.json` (default configs)
- `.context/ai-baseline/PROJ_Team-Foo-2026-04-01-90d-cfgab12cd34.json`
  (custom state config)
- `.context/ai-baseline/program-42-2026-04-01-180d.json`

**Collision behavior.** If the target file exists:
- Without `--overwrite`: exit 2.
- With `--overwrite` alone: the implementation reads the existing file
  enough to extract its `meta.snapshot_id`, then refuses to overwrite
  if that ID is not also passed via `--overwrite-snapshot-id <ID>`.
  This forces the user to name what they're replacing — accidentally
  blowing away another team's snapshot requires two flags, not one.
- With `--overwrite --overwrite-snapshot-id <ID>` matching the existing
  file's `meta.snapshot_id`: atomic replace via the tempfile pattern
  above.
- With `--overwrite --force`: bypass the `--overwrite-snapshot-id`
  check entirely. Use only when the existing file is malformed JSON
  or missing `meta.snapshot_id`. If `--overwrite-snapshot-id` is also
  passed alongside `--force`, it is ignored and a `meta.notes`
  warning records `"force-overwrite: snapshot-id unverified"`.

### Behavior — pipeline

1. **Validate inputs** (window not in future, scope flags consistent,
   `--baseline-window-days` in `[14, 365]`).
2. **Resolve `flow-metrics` script** via the same discovery probe shape
   `flow-metrics` itself uses for `jira`/`jira-align`:
   1. `$AI_ADOPTION_FLOW_METRICS_SCRIPT` env var (testing override).
   2. `<this-skill-dir>/../flow-metrics/scripts/flow_metrics.py`
      (sibling install).
   3. `~/.claude/skills/flow-metrics/scripts/flow_metrics.py`.
   4. `<cwd>/.claude/skills/flow-metrics/scripts/flow_metrics.py`.
   5. Not found → exit 2 with a clear message naming each tried path.
3. **Invoke `flow-metrics`** as a subprocess with the resolved
   `--from`/`--to`, the user's scope flags, and the user's
   `--state-config`/`--issuetype-config` if provided. Stream stdout
   (the full aggregate JSON).
4. **Wrap the flow-metrics output** in a baseline envelope (see
   "Output JSON shape" below).
5. **Atomic write** to the resolved output path. The implementation
   creates a tempfile in the same directory as the target via
   `tempfile.NamedTemporaryFile(dir=<output-dir>, suffix=".<pid>.tmp",
   delete=False)`, writes the canonical JSON to it, then
   `os.replace(tmp, target)`. Same-directory tempfile guarantees
   same-volume rename on Windows (where cross-volume `os.replace` is
   copy-then-delete, not atomic). On Ctrl-C / any uncaught exception,
   `try / finally` unlinks the temp file. Stale `*.tmp` files in the
   output directory older than 1 hour are swept at startup (mirrors
   flow-metrics' cache cleanup pattern).
6. **Print** the absolute output path to stdout for downstream
   composition (`ai-adoption-cohort --baseline-file $(ai-adoption-baseline ...)` works).

### Output JSON shape

```json
{
  "meta": {
    "skill": "ai-adoption-baseline",
    "schema_version": "1.0",
    "rollout_date": "2026-04-01",
    "baseline_window": { "from": "2026-01-01", "to": "2026-03-31", "days": 90 },
    "scope": {
      "kind": "project",
      "project_key": "PROJ",
      "team": "Foo",
      "program_id": null,
      "portfolio_id": null
    },
    "label": "pre-Q2-rollout",
    "snapshot_id": "<sha256 hex — see below>",
    "generated_at": "2026-04-02T08:00:00Z",
    "upstream_flow_metrics_schema_version": "1.0",
    "notes": []
  },
  "flow_metrics": { /* full flow-metrics aggregate JSON, verbatim */ }
}
```

**Scope canonicalization.** `meta.scope` is always the five-field dict
above, regardless of which CLI flag was used. The five fields are
always present (no key omission). Normalization rules:

- `kind` ∈ `{"project", "program", "portfolio"}` — exactly one.
- `project_key`: stripped, uppercased; `null` when `kind != "project"`.
- `team`: stripped (leading/trailing whitespace removed); `null` when
  `--team` is not provided.
- `program_id`: integer; `null` when `kind != "program"`.
- `portfolio_id`: integer; `null` when `kind != "portfolio"`.

This canonical shape is the single source of truth for downstream scope
matching across `ai-adoption-cohort` and `ai-value-report`.

**`snapshot_id` derivation.** After `flow-metrics` returns, read its
`meta.state_config_sha` and `meta.issuetype_config_sha`. Both fields MUST
be present and non-empty; missing → exit 3
(`"flow-metrics meta is missing required field <name>"`). Then:

```
snapshot_id = sha256(json.dumps({
  "envelope_schema_version": "<this skill's meta.schema_version, e.g. '1.0'>",
  "rollout_date":            "<YYYY-MM-DD>",
  "baseline_window":         { "from": "...", "to": "...", "days": N },
  "scope":                   <canonical scope dict>,
  "state_config_sha":        <from flow_metrics.meta>,
  "issuetype_config_sha":    <from flow_metrics.meta>,
  "upstream_schema_version": <from flow_metrics.meta.schema_version>
}, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
```

The inclusion of `envelope_schema_version` means a future bump of this
skill's own `meta.schema_version` changes every `snapshot_id` produced
under the new envelope — so downstream skills that use `snapshot_id`
for drift detection (per Decisions) will correctly see the bump even
if every other input is identical.

Two snapshots with identical inputs (and identical upstream flow-metrics
schema_version) are byte-identical bar `generated_at` and `label`.

- `meta.schema_version` is **this skill's** output-format version (bumped
  if the envelope shape changes).
- `meta.upstream_flow_metrics_schema_version` is read from the embedded
  flow-metrics output and lets downstream skills detect upstream-schema
  drift independently from this skill's envelope.

**Upstream schema-version compatibility policy.** This skill accepts
any flow-metrics output whose `meta.schema_version` major matches a
hard-coded allowlist (initially `{"1"}`). A non-allowlisted major
exits 3 with `"upstream flow-metrics schema_version <V> is not
supported by this baseline version; upgrade ai-adoption-baseline"`.
Minor-version drift within an allowed major proceeds normally and is
recorded in `meta.notes` as `"upstream-schema-minor-drift: flow-metrics
v<X.Y>"`.
- `flow_metrics` is the verbatim output of `flow-metrics` JSON mode —
  the baseline skill does not transform, filter, or reorder any field.
- `meta.notes` is always an array (possibly empty). Each note is a
  self-contained string with a stable lower-case-hyphenated prefix
  followed by a colon (e.g., `"low-throughput: 12 delivered issues
  in window; percentile stability not guaranteed"`,
  `"recent-rollout-accepted: 5 days post-rollout, throughput may
  undercount in-flight issues"`,
  `"force-overwrite: snapshot-id unverified"`). Downstream skills
  pattern-match by prefix, not by full text. Notes are sorted
  lexicographically in the canonical output.

**Canonical envelope serialization.** The output JSON is written via
`json.dumps(envelope, sort_keys=True, separators=(",", ":"),
ensure_ascii=False) + "\n"`. Keys at every level appear in codepoint
order. The envelope examples in this spec are illustrative
(insertion-order for human readability), not byte-canonical. Two runs
with identical inputs (and matching upstream `schema_version`) produce
byte-identical files modulo `meta.generated_at` and `meta.label`.

**Schema-version bumping policy.** Bump `meta.schema_version` major
when removing or renaming a `meta.*` field, changing the `snapshot_id`
derivation, or changing the canonical `scope` shape. Bump minor for
purely additive `meta.*` fields. Downstream consumers (cohort,
value-report) MUST treat major mismatch as exit 2 and SHOULD accept
minor drift forward (recording it in their own `notes`).

### Errors and exit codes

- `0` success (including the print of the output path).
- `1` user aborted (Ctrl-C; overwrite confirmation declined when
  stdin is a TTY but not for the overwrite case which is `--overwrite`-only).
- `2` validation error: missing `--rollout-date`; rollout-date in the
  future; window-end in the future; `--baseline-window-days` out of
  `[14, 365]`; bad scope flag combo; output-path collision without
  `--overwrite`; `flow-metrics` script not discoverable.
- `3` upstream skill error: `flow-metrics` returned non-zero. The
  upstream stderr is relayed verbatim; this skill adds no
  interpretation.

### Read-only contract — upstream-skill allowlist

The skill invokes exactly one upstream verb: `flow-metrics` (aggregate
mode, full output).

**Forwarded `flow-metrics` flags allowlist** (exact set; any other
upstream flag is forbidden):

- `--from <YYYY-MM-DD>`, `--to <YYYY-MM-DD>` (resolved by this skill
  from `--rollout-date` and `--baseline-window-days`).
- Exactly one scope flag: `--project <KEY>` or `--program-id <ID>` or
  `--portfolio-id <ID>`.
- `--team <NAME>` (when `--team` was passed to this skill).
- `--state-config <FILE>` (when passed to this skill).
- `--issuetype-config <FILE>` (when passed to this skill).
- `--format json` (always; the baseline reads JSON from stdout).

Explicitly forbidden upstream flags (any of these → exit 2 at startup
if a future user attempts to construct an invocation that requires
them): `--per-issue`, `--cohort-jql`, `--jql`, `--align-filter`,
`--metrics`, `--no-cache`, `--output`, `--verbose` (this skill manages
its own stderr forwarding; see "Logging" below).

The contract test verifies these are the only flags ever appearing in
the upstream argv across every supported scope/flag combination of this
skill's own inputs.

**Defensive output check.** After parsing flow-metrics' JSON, the
baseline skill verifies the embedded `flow_metrics` object contains
**no `cohort_breakdown` key**. Its presence indicates a contamination
bug; exit 3 with `"baseline output unexpectedly contains
cohort_breakdown; this skill must not forward --cohort-jql"`.

### Logging

- `--verbose`, when set, writes diagnostic lines to **stderr**.
  flow-metrics' stderr is always forwarded to this skill's stderr,
  regardless of exit code (so users see permission-undercount notes
  even on a successful run).
- **stdout is reserved** for exactly one line on success: the absolute
  path of the written snapshot file. No other stdout content under any
  flag, so `--baseline-file $(ai-adoption-baseline ...)` composition
  works.

### Cross-skill invocation — name, not path

Same posture as `jira-defect-flow` and `flow-metrics`. This skill names
`flow-metrics` by its `name:` field and uses the IDE's native
skill-dispatch mechanism. At the Python-implementation level, the
subprocess discovery probe documented above translates the name into
the actual script location. It never reads
`~/.config/dropkit/credentials.env` (`flow-metrics` and its upstream
skills own that).

## Contract tests

The gate for "done". Black-box; any valid implementation must pass all
of them.

### Inputs and validation

- **`test_rollout_date_required`** — invocation without `--rollout-date`
  exits 2.
- **`test_rollout_date_in_future_exits_2`** — `--rollout-date today + 1`
  exits 2.
- **`test_rollout_date_within_stabilization_exits_2`** —
  `--rollout-date today - 13` exits 2 (default 14-day stabilization).
- **`test_accept_recent_rollout_allows_recent_date`** —
  `--rollout-date today - 5 --accept-recent-rollout` succeeds; the
  resulting snapshot's `notes` records the bias warning.
- **`test_baseline_window_days_below_min_exits_2`** —
  `--baseline-window-days 13` exits 2 (minimum is 14).
- **`test_baseline_window_days_above_max_exits_2`** —
  `--baseline-window-days 400` exits 2.
- **`test_low_throughput_emits_warning_note`** — fixture: window has
  fewer than 30 delivered issues. Snapshot writes successfully (exit
  0) but `meta.notes` includes a `"low-throughput: N delivered issues
  in window; percentile stability not guaranteed"` entry. Threshold
  matches the cohort skill's `small-cohort` flag floor (both 30) so
  the two skills' "small population" framings agree.
- **`test_exactly_one_scope_required`** — same as flow-metrics: zero
  or two scope flags exits 2.
- **`test_team_only_valid_with_project`** — same shape.
- **`test_window_math_leap_year_boundary`** — `--rollout-date 2025-03-01
  --baseline-window-days 90` produces `--from 2024-12-01 --to
  2025-02-28` (exactly 90 inclusive calendar days).
- **`test_canonical_scope_always_five_fields`** — for each scope flag
  combination, `meta.scope` contains exactly the five fields (`kind`,
  `project_key`, `team`, `program_id`, `portfolio_id`) with `null`
  in unused slots.

### Window resolution

- **`test_window_anchors_one_day_before_rollout`** — `--rollout-date
  2026-04-01 --baseline-window-days 90` resolves to `--from 2026-01-01
  --to 2026-03-31` for the underlying flow-metrics call.
- **`test_window_inclusive_endpoints`** — for the same fixture, the
  in-flight flow-metrics window is `[from 00:00 UTC, (to+1 day) 00:00
  UTC)` per flow-metrics' own inclusive contract.
- **`test_window_does_not_cross_rollout`** — no possible
  `--baseline-window-days` value produces a window that includes the
  rollout date itself.

### Output path

- **`test_output_path_deterministic_project_scope`** — same scope +
  rollout-date + window-days → same output filename.
- **`test_output_path_includes_team_slug`** — `--team "Foo Bar"`
  produces `PROJ_Team-Foo-Bar-...`.
- **`test_output_path_program_scope`** — `--program-id 42` produces
  `program-42-...json`.
- **`test_output_path_portfolio_scope`** — `--portfolio-id 7` produces
  `portfolio-7-...json`.
- **`test_label_not_in_filename`** — `--label "Q2"` does NOT change
  the output filename.
- **`test_existing_file_collision_exits_2`** — second run with same
  inputs but no `--overwrite` exits 2.
- **`test_overwrite_alone_exits_2`** — `--overwrite` without
  `--overwrite-snapshot-id` exits 2 with a message naming the
  existing file's `meta.snapshot_id`.
- **`test_overwrite_with_matching_snapshot_id_succeeds`** —
  `--overwrite --overwrite-snapshot-id <existing-id>` replaces the
  file atomically.
- **`test_overwrite_with_wrong_snapshot_id_exits_2`** — wrong ID
  exits 2 without writing.
- **`test_overwrite_force_replaces_malformed_existing`** — existing
  file is empty or non-JSON; `--overwrite --force` replaces it.
- **`test_atomic_temp_unlinked_on_exception`** — simulated crash
  mid-write; no `*.tmp` file remains in the output dir after the
  process exits.
- **`test_stale_tmp_swept_at_startup`** — pre-existing `*.tmp` with
  mtime > 1h is removed at startup.
- **`test_non_default_config_includes_cfg_suffix_in_filename`** —
  fixture: a state config with one extra raw status mapping. Output
  filename ends in `-cfg<8hex>.json`.
- **`test_default_config_filename_has_no_cfg_suffix`** — shipped
  default configs produce a clean filename.

### Output content

- **`test_flow_metrics_json_passed_through_verbatim`** — the
  `flow_metrics` subobject is byte-identical to what `flow-metrics`
  would have produced for the same window/scope (the baseline skill
  does not transform it).
- **`test_meta_includes_snapshot_id`** — `meta.snapshot_id` is a
  64-char hex sha256.
- **`test_meta_snapshot_id_stable_across_runs`** — two runs with
  identical inputs produce identical `snapshot_id` values.
- **`test_meta_snapshot_id_changes_with_state_config`** — changing
  the state-config sha changes `snapshot_id`.
- **`test_meta_schema_version_recorded`** — `meta.schema_version ==
  "1.0"`.
- **`test_meta_upstream_flow_metrics_schema_version_recorded`** —
  `meta.upstream_flow_metrics_schema_version` equals the wrapped
  `flow_metrics.meta.schema_version`.
- **`test_missing_upstream_state_sha_exits_3`** — when the mocked
  flow-metrics returns JSON missing `meta.state_config_sha`, this
  skill exits 3 with a clear message.
- **`test_no_cohort_breakdown_in_output`** — defensive: under no
  scope/flag combination does the wrapped `flow_metrics` contain a
  `cohort_breakdown` key. Any such case exits 3.
- **`test_meta_label_when_set`** — `--label "foo"` → `meta.label ==
  "foo"`. Without label, the key is absent (not null) — matches the
  flow-metrics convention. `--label ""` (empty) exits 2.
- **`test_stdout_prints_only_output_path`** — stdout contains exactly
  one line (the absolute path), no other content. With `--verbose`,
  stdout still contains exactly one line (verbose logs go to
  stderr).
- **`test_verbose_writes_to_stderr_only`** — `--verbose` produces
  diagnostic lines on stderr; stdout is unchanged.
- **`test_flow_metrics_stderr_forwarded_on_success`** — flow-metrics'
  stderr (e.g. permission-undercount note) appears on this skill's
  stderr even on a successful run.

### Read-only contract

- **`test_only_flow_metrics_invoked`** — the test wrapper records
  every subprocess invocation; argv[1] (the resolved script path)
  must match the discovered `flow_metrics.py`. argv[0] may be
  `python` / `python3`. No `jira`, `jira-align`, `git`, `gh`, `curl`,
  `wget`, `pip`, `npm` invocations occur.
- **`test_per_issue_never_invoked`** — `flow-metrics --per-issue` is
  never invoked.
- **`test_only_allowlisted_upstream_flags_passed`** — the argv to
  the flow-metrics invocation contains only the allowlisted flags
  from this spec (`--from`, `--to`, scope flags, `--team`,
  `--state-config`, `--issuetype-config`, `--format json`). Any
  other flag is a test failure.
- **`test_no_overwrite_without_flag`** — even when stdout is
  redirected and stdin is `/dev/null`, the skill does not overwrite
  an existing file without `--overwrite`.

### Errors

- **`test_upstream_flow_metrics_failure_exits_3`** — when the mocked
  `flow-metrics` exits non-zero, this skill exits 3 and relays the
  stderr verbatim.
- **`test_flow_metrics_not_found_exits_2`** — when no discovery
  probe matches, exit 2 with a message naming each tried path.

## Non-goals

Explicit anti-scope — the skill **will not**:

- Compute any metric itself; all math is `flow-metrics`'.
- Tag issues as AI-assisted or otherwise (`ai-adoption-cohort`'s job).
- Render Markdown, HTML, or charts (`ai-value-report`'s job).
- Auto-discover the rollout date from any source (Jira labels, CI
  timestamps, calendar invites). The user always names it.
- Mutate Jira / Jira Align in any way. Pure read via flow-metrics.
- Snapshot a window that includes or follows the rollout date.
- Re-snapshot automatically. Each run is one explicit user action; cron
  / scheduled snapshots are not in v1 (would invalidate the "explicit
  rollout-date" posture).
- Send the snapshot anywhere (Slack, email, S3). The snapshot is a
  local file; humans copy it where it needs to go.

## Decisions

These are the resolved answers to design questions; each becomes part of
Behavior or Contract tests.

1. **`--rollout-date` is always required.** The skill never infers it
   from data. Rollouts vary by team/tool; inference would be wrong half
   the time and not auditable.
2. **`--baseline-window-days` defaults to 90, range `[14, 365]`.**
   The lower bound is permissive (some teams have fast rollouts);
   throughput stability is handled separately by emitting a
   `low-throughput` note when `throughput < 30` (matches the cohort
   skill's `small-cohort` flag floor so the two skills agree). Longer
   windows mix pre-pre-AI eras and dilute the signal.
3. **Stabilization period: 14 days post-rollout** before a baseline
   can be snapshotted. Override with `--accept-recent-rollout`. Reason:
   in-flight tickets at the rollout date may not have transitioned to
   `done` yet; snapshotting too early undercounts late-window
   throughput and biases the comparison.
4. **Forwarded `flow-metrics` flag allowlist is exact** — see "Read-
   only contract". Future flag additions require a spec update.
5. **Output path is deterministic and label-independent.** Two runs
   with the same scope + rollout-date + window collide on filename. The
   collision is a feature: it forces explicit `--overwrite`.
6. **Snapshot is immutable by convention, mutable by explicit flag.**
   `--overwrite` is the only path to a new write at an existing path.
7. **Snapshot contains the full flow-metrics JSON verbatim**, not a
   filtered subset. The baseline skill must not editorialize.
8. **`snapshot_id` is a content sha** over the inputs (not over the
   output) and includes the envelope's own `schema_version`.
   Downstream tools detect baseline drift by comparing `snapshot_id`,
   not by reading the whole snapshot.
9. **No `--per-issue` mode.** The cohort skill is the consumer of
   per-issue data and runs its own flow-metrics call. Baselines are
   aggregate-only.
10. **No `--cohort-jql`.** Baselines are the *control* by definition —
    they have no AI cohort. Asking for one is a category error; the
    cohort lives in `ai-adoption-cohort`.

## Deferred to v2

- **Multi-team batch mode.** `ai-adoption-baseline --batch <YAML>`
  taking a list of `(scope, rollout_date, window_days, label)` rows
  and producing N snapshots in one invocation. v1 is one-snapshot-per-
  invocation; a shell loop covers the bulk case.
- **Snapshot comparison helper** (`ai-adoption-baseline --diff
  <snapshot-a> <snapshot-b>`). Useful for spotting baseline drift
  caused by state-config edits, but separable from the snapshot
  itself.
- **Remote storage** (S3 / GCS / Confluence attachment) of snapshots.
  Adds dependency surface; users today copy snapshots into their team
  wiki manually.
- **Time-zone-aware rollout dates.** v1 uses UTC throughout (matches
  flow-metrics). A distributed-team-friendly mode that takes a TZ-
  aware ISO timestamp could ship later.

## Acceptance criteria

- [ ] All Contract tests above pass on macOS and Linux under Python
      3.10, 3.11, 3.12.
- [ ] SKILL.md follows the dropkit pattern: cross-skill calls by
      name, "Don't" list, security rules, Edge cases.
- [ ] `manifest.json` declares `deps.skills: [{name: "flow-metrics"}]`.
- [ ] One real-team smoke run produces a snapshot whose
      `flow_metrics` sub-object matches a hand-run `flow-metrics`
      invocation byte-for-byte.
- [ ] Output JSON validates against
      `references/baseline.schema.json`.
- [ ] No new top-level repo dirs. Skill lives at
      `skills/workflows/ai-adoption-baseline/`.
- [ ] README or skill SKILL.md links to this spec.
