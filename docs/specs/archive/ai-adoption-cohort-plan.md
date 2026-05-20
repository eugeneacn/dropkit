# Plan: ai-adoption-cohort

- **Spec:** [`docs/specs/ai-adoption-cohort.md`](ai-adoption-cohort.md)
- **Status:** Approved (ready to execute) <!-- Drafting | Approved | Executing | Done -->
- **Review history:** 3 adversarial review rounds (2026-05-19). Round 1: 1 blocker / 5 majors / 8 minors; round 2: 0 blockers / 3 majors / 10 minors; round 3: 0 blockers / 0 majors / 1 minor. Terminal-clean.

> **Plan contract:** this is the implementation strategy. Unlike the
> spec, this document is allowed to change as you learn. When it
> changes substantially, note why in the changelog at the bottom.

## Approach

Eleven sequentially-ordered tasks. The first four (T1 scaffold, T2
cohort SPEC parsing, T3 upstream wrapper, T4 baseline loader) establish
the substrate. T5–T7 build the data path: default-window resolution,
delta computation, flag evaluation. T8 implements explain-mode. T9
handles output rendering. T10 packages. T11 wires CI.

The load-bearing tasks are T4 (baseline integrity checks — snapshot_id
recompute, scope match, schema-version compatibility — all of which
must produce exit 2 *before any upstream call* to satisfy the
pre-upstream-validation contract) and T7 (flag evaluation, where the
zero-comparator skip rule and relative-percent semantics live).

**Spec pipeline steps → tasks:**

| Spec pipeline step | Task |
|---|---|
| 1. Validate input shape | T1 |
| 2. Load baseline (parse, schema, integrity checks) | T4 |
| 3. Resolve flow-metrics script | T3 |
| 4. Invoke flow-metrics (aggregate) | T3 |
| 5. Config-sha + upstream-schema check | T4 + T9 |
| 6. Compute deltas | T6 |
| 7. Evaluate flags | T7 |
| 8. Write report | T9 |
| 9. Explain JSONL (when triggered) | T8 |
| (across) Window resolution + auto-clamp | T5 |

Implementation is **standalone Python ≥ 3.10, stdlib only**. No
third-party deps. All upstream calls go through `flow-metrics` via
subprocess.

## Architectural decisions deferred to this plan

The spec says cross-skill invocation is "by name, not path." The
Python implementation:

- **Subprocess invocation of `flow-metrics`** via the same discovery
  probe shape `ai-adoption-baseline` uses (env var → sibling →
  user-scope → cwd-walk).
- **Two `flow-metrics` invocation modes:**
  1. **Aggregate mode** (always): `subprocess.run(... capture_output=
     True)`. JSON output bounded; no streaming needed.
  2. **Per-issue mode** (only when `--explain-flag` is set AND the
     named flag triggered): `flow-metrics --per-issue --output
     <tmpfile>`. The cohort skill reads the JSONL from the tmpfile,
     filters to cohort rows, derives per-flag fields, writes the
     explain JSONL. Tmpfile is cleaned up in `try/finally`.
- **Per-flag explain row shapes are coded as a per-flag function
  table.** Adding a new explainable flag requires (a) adding the row
  shape to the spec, (b) adding the function. No plugin mechanism in
  v1.
- **Cohort tagging is read off `flow-metrics --per-issue`'s `cohort`
  field**, not re-computed by re-running JQL. The cohort skill
  trusts flow-metrics' own cohort-membership determination.

## Constraints

The decisions recorded in the spec's "Decisions" section govern all
ambiguous cases. The most binding for implementation:

- Python floor 3.10.
- Cohort SPEC validation runs BEFORE any upstream call (pre-upstream
  exit 2; matches the contract test).
- All flag thresholds are relative-percent (`>= * 1.10` for "up",
  `<= * 0.90` for "down"); zero comparator → skip with notes entry.
- Cohort vs baseline = "cohort-now vs population-then" (documented in
  notes every run with baseline).
- `--explain-flag` accepts exactly one flag name. Flag not triggered
  → exit 4 (post-evaluation), distinct from exit 2 (pre-upstream).
- Silent overwrite of cohort report (no `--overwrite` flag — cohort
  reports are recomputable from inputs, unlike immutable baseline
  snapshots).
- `wait_time_hours` assumes `flow_efficiency` is a ratio in `[0, 1]`;
  out-of-range → exit 3.

## Construction tests

Cross-cutting tests spanning multiple tasks.

**Integration tests:**

- `test_full_happy_path_with_baseline` — fixture: a mocked
  `flow-metrics` (aggregate mode) returning canned cohort/control
  breakdown; a checked-in baseline file from
  `ai-adoption-baseline`. Run end-to-end:
  `ai-adoption-cohort --project PROJ --team Foo --cohort label:ai-assisted
  --baseline-file .context/baseline.json --from 2026-04-01 --to
  2026-06-30`. Assert (a) deltas match hand-computed reference, (b)
  flags triggered match expected set, (c) `meta.baseline_snapshot_id`
  equals baseline's `meta.snapshot_id`, (d) byte-identical re-runs
  produce byte-identical outputs.
- `test_full_happy_path_no_baseline` — same fixture without
  `--baseline-file`. Assert `deltas.cohort_vs_baseline` and
  `deltas.control_vs_baseline` keys are absent.
- `test_explain_flag_round_trip` — fixture where
  `throughput-up-rework-up` triggers. Run with `--explain-flag
  throughput-up-rework-up`. Assert
  `<output>.explain.jsonl` contains the expected per-issue rows.
- `test_canonical_byte_equality` — two runs with identical inputs
  produce byte-identical JSON output (after `meta.generated_at`
  normalization).

**Manual verification gate (before tagging):**

- Run against one real team's cohort label (e.g.,
  `label:ai-assisted`) using a real baseline snapshot. Verify (a) the
  deltas pass a sanity check against the team's own dashboard, (b)
  at least one flag's evidence values match a hand-computed reference,
  (c) the explain JSONL for that flag lists the expected issue keys.

## Tasks

### T1: Scaffold — CLI, argparse, exit codes, Python floor

**Depends on:** none

**Tests:**

- `test_python_below_floor_exits_2`.
- `test_help_exits_0`.
- `test_cohort_required`.
- `test_exactly_one_scope_required`.
- `test_team_only_valid_with_project`.
- `test_unknown_flag_exits_2`.
- `test_explain_unknown_flag_exits_2` — `--explain-flag foo` exits 2
  pre-upstream.
- `test_explain_small_cohort_exits_2` — recognized-but-not-explainable
  flag name; exits 2 with the spec-pinned message
  `"flag 'small-cohort' is not explainable..."`.
- `test_validation_error_exits_2_before_any_upstream_call` — any
  flag-shape validation error (bad cohort prefix, two scope flags,
  unknown `--explain-flag` name) exits 2 with **zero** subprocess
  invocations recorded by the test harness.

**Approach:**

- Create `skills/workflows/ai-adoption-cohort/scripts/ai_adoption_cohort.py`.
- Python version check; argparse with all flags from the spec's
  Inputs synopsis.
- `--explain-flag` validation:
  - Empty / not in the recognized list → exit 2 (unknown).
  - `small-cohort` → exit 2 (recognized-not-explainable, different
    message).
  - Any of the four explainable names → accept; trigger check
    deferred to T8.
- Stub the data-path commands; later tasks fill in.

**Done when:** all listed tests green on Python 3.10, 3.11, 3.12.

---

### T2: Cohort SPEC parsing + JQL composition

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_cohort_label_form`.
- `test_cohort_field_form`.
- `test_cohort_jql_form`.
- `test_cohort_label_with_space_exits_2`.
- `test_cohort_field_with_embedded_quote_exits_2`.
- `test_cohort_unknown_prefix_exits_2`.
- `test_cohort_label_with_dot_and_colon_ok`.
- `test_cohort_label_with_backslash_exits_2`.
- `test_cohort_field_value_with_equals_in_url`.
- `test_cohort_field_value_with_comma_safe`.
- `test_cohort_field_value_with_backslash_exits_2`.
- `test_cohort_jql_with_order_by_exits_2`.
- `test_cohort_jql_with_unbalanced_parens_exits_2`.
- `test_cohort_jql_with_trailing_semicolon_exits_2`.
- `test_cohort_field_whitespace_stripped`.
- `test_jql_user_clause_parenthesized` — composed query passes
  parenthesized cohort clause to flow-metrics.

**Construction tests:**

- `test_cohort_field_internal_whitespace_preserved` —
  `--cohort "field:Multi Word=Has Spaces"` produces
  `"Multi Word" = "Has Spaces"`.
- `test_label_regex_exact` — characters `^[A-Za-z0-9._:-]+$` accepted;
  anything else (whitespace, `/`, `=`, `<`, `>`, control chars)
  rejected with exit 2.
- `test_field_split_on_first_equals_only` —
  `"a=b=c"` splits to `"a"` and `"b=c"`.

**Approach:**

- `ai_adoption_cohort/cohort_spec.py`:
  - `parse_cohort(arg: str) -> CohortClause` returns
    `{kind, raw, resolved_jql}`.
  - Dispatch table by prefix; each branch validates and resolves.
  - Raises `ValidationError(msg)` on any rule violation; caller
    converts to exit 2.

**Done when:** all listed tests green.

---

### T3: Upstream wrapper — discovery, allowlist, aggregate mode

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_only_flow_metrics_invoked` — wraps subprocess; asserts only
  `flow_metrics.py` is called (no jira/jira-align/git/curl).
- `test_only_allowlisted_upstream_flags_passed` — upstream argv
  contains only the allowlist from the spec.
- `test_per_issue_only_invoked_with_explain_flag` — without
  `--explain-flag`, `flow-metrics --per-issue` is never called. With
  `--explain-flag` AND the flag triggered, exactly one
  `--per-issue` call occurs (verified at T8's integration).
- `test_upstream_flow_metrics_failure_exits_3`.

**Construction tests:**

- `test_discovery_probes_in_order`.
- `test_discovery_cwd_direct_only` — only the literal
  `<cwd>/.claude/skills/flow-metrics/scripts/flow_metrics.py` is
  checked (no ancestor walk-up); matches `ai-adoption-baseline-plan`'s
  identical decision for consistency across the two skills.
- `test_subprocess_uses_run_not_popen_for_aggregate` — aggregate-mode
  output is bounded and fits in `subprocess.run`'s capture; no
  streaming.
- `test_metrics_flag_pins_all_relevant_metrics` — upstream argv
  always includes `--metrics cycle_time,lead_time,throughput,wip,
  flow_load,rework_rate,flow_time,flow_efficiency,flow_distribution,
  defect_ratio`.
- `test_cohort_jql_passed_to_upstream` — upstream argv contains
  `--cohort-jql "<resolved>"`.
- `test_flow_metrics_stderr_forwarded_on_success`.

**Approach:**

- `ai_adoption_cohort/upstream.py`:
  - `discover_flow_metrics() -> Path` (same probe as
    ai-adoption-baseline; consider extracting to a shared helper
    later — v1 duplicates).
  - `class FlowMetricsClient`:
    - `run_aggregate(scope_args, window, cohort_clause, state_config,
      issuetype_config) -> dict` builds argv (allowlist-validated),
      runs `subprocess.run`, returns the parsed JSON.
    - `run_per_issue(...) -> Path` — runs `flow-metrics --per-issue
      --output <tmpfile>`, returns the tmpfile path (caller is
      responsible for cleanup).
- T3 covers aggregate-mode only; per-issue mode lands in T8.

**Done when:** all listed tests green.

---

### T4: Baseline loader + integrity checks

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_baseline_config_mismatch_exits_2`.
- `test_baseline_snapshot_id_recorded`.
- `test_baseline_scope_mismatch_exits_2`.
- `test_baseline_tampered_snapshot_id_exits_2`.
- `test_baseline_schema_version_mismatch_exits_2`.

**Construction tests:**

- `test_baseline_minor_drift_accepted_with_note` — baseline
  `meta.schema_version: "1.1"`; load succeeds; `notes` contains
  `"baseline-schema-minor-drift: 1.1"`.
- `test_baseline_malformed_json_exits_2`.
- `test_baseline_missing_meta_scope_exits_2`.
- `test_baseline_wrong_skill_in_meta_exits_2` — `meta.skill !=
  "ai-adoption-baseline"` → exit 2.
- `test_snapshot_id_recompute_uses_envelope_schema_version` —
  recompute formula reads `baseline.meta.schema_version` (the
  envelope) plus `baseline.flow_metrics.meta.{state_config_sha,
  issuetype_config_sha, schema_version}`.
- `test_snapshot_id_recompute_matches_baseline_formula` — fixture
  baseline produced by a known-good baseline skill; recompute matches
  `meta.snapshot_id` exactly.
- `test_baseline_load_raises_before_upstream_call` — at the unit
  level: `load_baseline()` raises on malformed input directly,
  before any caller has a chance to invoke flow-metrics. The
  integration assertion ("zero `flow-metrics` invocations") lives
  in T11 as `test_validation_error_exits_2_before_any_upstream_call`
  where the full pipeline is wired and the upstream wrapper can be
  observed.

**Approach:**

- `ai_adoption_cohort/baseline_loader.py`:
  - `def load_baseline(path: Path) -> Baseline` — opens, parses,
    validates against `references/baseline.schema.json` (a copy of
    the baseline skill's schema), runs the four integrity checks
    (scope match against args, snapshot_id recompute, schema_version
    major check). Each failure raises a distinct exception caught at
    main with the spec-pinned message.
- `Baseline` is a dataclass exposing `meta`, `flow_metrics`,
  `snapshot_id_expected` (the recomputed value, for comparison).
- This task runs at pipeline step 2 of the spec (BEFORE any upstream
  call), so the contract test
  `test_validation_error_exits_2_before_any_upstream_call` keeps
  green.

**Done when:** all listed tests green.

---

### T5: Window resolution + auto-clamp

**Depends on:** T4

**Tests (contract tests from spec):**

- `test_default_window_last_90_days`.
- `test_window_overlap_with_baseline_exits_2`.
- `test_window_adjacent_to_baseline_ok`.

**Construction tests:**

- `test_window_auto_clamp_when_defaults_overlap` — user passes no
  `--from`/`--to`; baseline ends today − 30 days; the default
  90-day lookback would overlap. Skill auto-clamps `--from` to
  `baseline.to + 1 day`; `notes` contains
  `"window-auto-clamped:..."`.
- `test_explicit_from_no_auto_clamp` — user passes `--from
  <same-date-as-default>` explicitly; still exits 2 on overlap
  (explicit intent wins).
- `test_window_no_baseline_no_auto_clamp` — without
  `--baseline-file`, no clamp logic runs; defaults `today − 90d`
  to `today`.

**Approach:**

- `ai_adoption_cohort/window.py`:
  - `resolve_window(args, baseline: Optional[Baseline], today_utc:
    date) -> Window` returns `Window(from, to, user_set_from: bool)`.
  - **Argparse sentinel pattern:** `--from` and `--to` use
    `default=None` (argparse omits the default substitution). After
    parsing, `args.from is None` means the user did not pass the
    flag; any other value is explicit user intent. This is the only
    reliable way for argparse to distinguish "not passed" from
    "passed equal to today's default value." Same pattern for `--to`.
  - When `args.from is None` AND baseline is provided AND the
    resolved default would overlap: auto-clamp + emit a notes entry.
    Otherwise: standard resolution + overlap check + exit 2 on
    overlap.
  - The `user_set_from` flag in the returned `Window` is set to
    `args.from is not None`; downstream code reads this when
    deciding whether overlap-detection should suppress
    auto-clamp.

**Done when:** all listed tests green.

---

### T6: Delta computation — within-window + cross-time

**Depends on:** T3, T4, T5

**Tests (contract tests from spec):**

- `test_cohort_split_disjoint`.
- `test_cohort_aggregates_match_subset`.
- `test_cohort_rework_rate_denominator_is_cohort_throughput`.
- `test_no_baseline_omits_cross_time_deltas`.
- `test_cohort_vs_control_delta_per_metric`.
- `test_cohort_vs_control_percentile_delta`.
- `test_baseline_delta_throughput_normalized_per_week`.

**Construction tests:**

- `test_throughput_per_week_normalization_formula` —
  `throughput_per_week = throughput / (window.days / 7)` applied to
  both sides, both within-window and cross-time.
- `test_percentile_delta_p50_p75_p90` — each percentile metric's
  delta block has three sub-deltas keyed `p50_delta, p75_delta,
  p90_delta`.
- `test_delta_null_when_either_side_null` — when cohort `rework_rate`
  is null (zero throughput), `cohort_vs_control.rework_rate` is null
  (not 0, not NaN).

**Approach:**

- `ai_adoption_cohort/deltas.py`:
  - `def compute_deltas(current: dict, baseline: Optional[Baseline],
    window: Window) -> dict` returns `{cohort_vs_control,
    cohort_vs_baseline?, control_vs_baseline?}`.
  - Per-metric resolution: scalar metrics produce
    `{delta_abs, delta_pct}`; percentile metrics produce
    `{p50_delta, p75_delta, p90_delta}`.
  - `normalize_per_week(throughput, window_days) -> float` is a
    pure helper.

**Done when:** all listed tests green.

---

### T7: Flag evaluation + zero-comparator skip

**Depends on:** T6

**Tests (contract tests from spec):**

- `test_throughput_up_rework_up_at_exactly_10pct_emits`.
- `test_throughput_up_rework_up_just_below_threshold_not_emitted`.
- `test_threshold_evaluated_on_unrounded_floats`.
- `test_throughput_up_rework_up_vs_baseline_requires_baseline`.
- `test_cycle_time_down_defect_ratio_up_emitted_at_threshold`.
- `test_flow_efficiency_down_cohort_emitted`.
- `test_small_cohort_emitted_when_under_30`.
- `test_small_cohort_emitted_when_under_20pct`.
- `test_empty_cohort_only_emits_small_cohort` — cohort throughput
  is 0; all percentiles null. Skill exits 0; only `small-cohort`
  flag emitted; all other flags skipped (their cohort-side metrics
  are null).
- `test_flag_evidence_uses_4dp_rounding`.
- `test_flag_evidence_threshold_passed_on_unrounded`.
- `test_zero_control_rework_rate_skips_flag`.
- `test_zero_baseline_throughput_skips_cross_time_flag`.
- `test_zero_control_cycle_time_does_not_trip_cycle_down_flag`.

**Construction tests:**

- `test_flag_set_fixed_in_v1` — `flag_definitions` registry contains
  exactly five entries: `throughput-up-rework-up`,
  `throughput-up-rework-up-vs-baseline`,
  `cycle-time-down-defect-ratio-up`, `flow-efficiency-down-cohort`,
  `small-cohort`.
- `test_flags_sorted_alphabetically_by_name`.
- `test_flag_skipped_zero_comparator_note_emitted` — when a flag is
  skipped due to zero comparator, `notes` contains
  `"flag-skipped: <name>: zero comparator"`.
- `test_small_cohort_total_throughput_is_current_aggregates_throughput`
  — verified by fixture: cohort 100, total (from
  `current.aggregates.throughput`) 600 → `small-cohort` flag fires
  via the 20% disjunct.

**Approach:**

- `ai_adoption_cohort/flags.py`:
  - `class Flag(Protocol)`: `name: str`, `requires_baseline: bool`,
    `evaluate(deltas, current, baseline) -> Optional[FlagResult]`.
  - Each of the five flags is a dataclass implementing the protocol.
  - `evaluate_all(deltas, current, baseline, notes) -> list[FlagResult]`
    iterates all flags, applies the null-side skip and the
    zero-comparator skip (recording notes for skips), and returns
    triggered results in alphabetical name order.
- Threshold helpers (`relative_up`, `relative_down`) operate on
  un-rounded floats; rounding happens later at evidence-emit time.

**Done when:** all listed tests green.

---

### T8: Explain mode — per-issue fetch + per-flag row shapes

**Depends on:** T3, T7, T9 (report-path resolution lives in T9; T8
needs `<report-path>.explain.jsonl` to be derivable from T9's output
path. To avoid an actual cycle, T9 exposes a small
`compute_report_path(args) -> Path` helper consumed by both itself and
T8; that helper has no dependency on T7 or T8 so it can be implemented
within T9 first.)

**Tests (contract tests from spec):**

- `test_explain_writes_jsonl_file_when_flag_triggers`.
- `test_explain_flag_did_not_trigger_exits_4`.
- `test_explain_invokes_flow_metrics_per_issue_once`.

**Construction tests:**

- `test_explain_row_shape_throughput_up_rework_up` — each row
  contains `key, summary, delivered_at, team, cohort: true,
  rework_count, cycle_time_hours`.
- `test_explain_row_shape_cycle_time_down_defect_ratio_up` —
  contains `..., issuetype_at_delivery, issuetype_bucket,
  cycle_time_hours, is_defect`.
- `test_explain_row_shape_flow_efficiency_down_cohort` —
  contains `..., cycle_time_hours, flow_efficiency,
  wait_time_hours`.
- `test_wait_time_hours_derived_from_cycle_and_efficiency` —
  `wait = cycle * (1 - flow_efficiency)` per row.
- `test_wait_time_hours_null_when_either_input_null`.
- `test_flow_efficiency_out_of_range_exits_3` — fixture: per-issue
  row has `flow_efficiency: 1.5`. Skill exits 3 naming the issue.
- `test_explain_jsonl_sorted_by_key_codepoint` —
  `PROJ-1, PROJ-10, PROJ-2` order (codepoint, not natural).
- `test_explain_tmpfile_cleaned_on_success` — no leftover tmp.
- `test_explain_tmpfile_cleaned_on_exception` — simulated parse
  failure mid-stream; no leftover tmp.

**Approach:**

- `ai_adoption_cohort/explain.py`:
  - `EXPLAIN_ROW_BUILDERS: dict[str, Callable[[dict], dict]]` — one
    builder per explainable flag name. Each takes a flow-metrics
    per-issue row, returns the trimmed-down explain row.
  - `def write_explain(flag_name, per_issue_path, output_jsonl_path)
    -> None` reads the JSONL line-by-line, filters to `cohort: true`,
    applies the builder, sorts by `key` codepoint, writes.
- `wait_time_hours` derivation lives in the
  `flow-efficiency-down-cohort` builder. Per-issue
  `flow_efficiency` range check happens during builder call.
- `try / finally` cleanup of the tmpfile.

**Done when:** all listed tests green.

---

### T9: Output rendering + canonicalization

**Depends on:** T4 (baseline meta → `meta.baseline_snapshot_id`), T5
(window → `meta.window`), T6 (deltas), T7 (flags). The report-path
helper used by T8 also lives here.

**Tests (contract tests from spec):**

- `test_stable_output_for_same_inputs`.
- `test_flags_sorted_by_name` (overlap with T7).

**Construction tests:**

- `test_meta_schema_version_recorded` — `meta.schema_version == "1.0"`.
- `test_meta_upstream_flow_metrics_schema_version_recorded`.
- `test_meta_scope_is_canonical_5_field`.
- `test_meta_cohort_block_records_resolved_jql`.
- `test_meta_baseline_file_path_recorded_when_provided`.
- `test_output_json_canonicalized_sorted_keys` — every dict's keys
  in codepoint order; `json.dumps(parsed, sort_keys=True) ==
  file_bytes_minus_trailing_newline`.
- `test_floats_rounded_to_4dp` — every float in the output, after
  `json.dumps`, has at most 4 decimal digits.
- `test_notes_lexicographic_order`.

**Approach:**

- `ai_adoption_cohort/output.py`:
  - `build_report(args, current, deltas, flags, baseline, notes) ->
    dict` constructs the full report.
  - `serialize_report(report) -> bytes` does the canonical JSON
    dump.
  - **Pre-walk float rounding ordering:** `pre_walk_round_floats(
    report, 4)` runs BEFORE `json.dumps(report, sort_keys=True,
    separators=(",",":"), ensure_ascii=False)`. Rounding via a
    `default=` hook does NOT fire on floats (Python's `json.dumps`
    invokes `default=` only on types it doesn't know natively;
    `float` is native). The pre-walk replaces every float in-place
    with `round(x, 4)` so the subsequent `json.dumps` emits the
    rounded form. Floats inside the embedded `current` block are
    already rounded by flow-metrics; the pre-walk is idempotent on
    those. The report dict is then discarded — no other code reads
    it post-rounding, so in-place mutation is safe.
- Atomic write via the same-directory tempfile + `os.replace`
  pattern.

**Done when:** all listed tests green.

---

### T10: SKILL.md + manifest + cohort.schema.json

**Depends on:** T1–T9

**Tests:**

- `test_skill_md_lists_all_subcommands_from_spec`.
- `test_manifest_declares_dependencies` — `manifest.json` has
  `deps.skills: [{name: "flow-metrics"}, {name:
  "ai-adoption-baseline"}]`.
- `test_skill_md_security_rules_present`.

**Approach:**

- `skills/workflows/ai-adoption-cohort/SKILL.md`.
- `skills/workflows/ai-adoption-cohort/manifest.json` —
  `id: "ai-adoption-cohort"`, `version: "0.1.0"`, deps.skills as
  above, no deps.pip.
- `skills/workflows/ai-adoption-cohort/references/cohort.schema.json`
  — JSON Schema for output. Co-versioned with `meta.schema_version`.
- `skills/workflows/ai-adoption-cohort/references/baseline.schema.json`
  — copy of `ai-adoption-baseline`'s schema, used by T4 for input
  validation. Co-versioning: bump both when the baseline format
  changes.

**Done when:** all listed tests green.

---

### T11: CI matrix + integration fixtures + golden files

**Depends on:** T1–T10

**Tests:**

- All contract + construction tests pass on the 9-combo CI matrix
  (os × python).
- Integration tests `test_full_happy_path_with_baseline`,
  `test_full_happy_path_no_baseline`, `test_explain_flag_round_trip`,
  `test_canonical_byte_equality` pass against synthetic fixtures.

**Approach:**

- `.github/workflows/test-ai-adoption-cohort.yml`.
- `tests/fixtures/cohort/`:
  - `flow_metrics_aggregate_canned.json` — flow-metrics aggregate
    response with `cohort_breakdown`.
  - `flow_metrics_per_issue_canned.jsonl` — per-issue rows.
  - `flow_metrics_per_issue_malformed.jsonl` — partial / truncated
    rows for `test_explain_tmpfile_cleaned_on_exception`.
  - `baseline_canned.json` — a baseline file produced by
    ai-adoption-baseline (or hand-authored to match the schema).
  - `golden_report.json` — expected cohort output.
  - `golden_explain_throughput_up_rework_up.jsonl`.

**Done when:** CI matrix green on all 9 combinations.

## Rollout

New skill, no existing behavior changed. Ships as `v0.1.0`. Depends on
`flow-metrics` and `ai-adoption-baseline` being installable.

Ship checklist:

- All tests green across the 9-combo CI matrix.
- One real-team smoke run produces a report whose flags match a
  hand-computed reference.
- SKILL.md links spec + plan.

## Risks

- **Cohort sourcing reliability.** `label:` cohorts are easy to set
  but easy to forget. The skill cannot detect "should have been
  tagged but wasn't" cases. Documented in SKILL.md; users should be
  warned that a small cohort might mean low AI adoption OR low
  tagging discipline.
- **`small-cohort` threshold drift.** v1 pins 30 and 20% with
  documented rationale. Teams whose workflows differ will want
  config. v2 work; document the limitation.
- **Cross-time secular trend.** Even with `control_vs_baseline` as a
  trend control, attributing a delta to "AI" requires the user to
  reason about confounders. The spec's notes line documents this;
  this skill cannot enforce interpretation discipline.
- **Per-issue mode tmpfile location.** `flow-metrics --per-issue`
  writes to a file we name. v1 uses `tempfile.NamedTemporaryFile(
  dir=<output-dir>, suffix=".<pid>.per-issue.tmp", delete=False)` —
  same directory as the cohort report. No cross-volume `os.replace`
  risk because the tmpfile is read-then-deleted (no rename). No
  spec-unauthorized `tmp/` subdirectory needed; `<output-dir>` is
  the only path the user asked for. `try/finally` unlinks the
  tmpfile on success and exception alike.
- **`flow_efficiency` unit drift.** Spec asserts the cohort skill
  exits 3 if any per-issue `flow_efficiency` is outside `[0, 1]`.
  This catches a future flow-metrics minor that emits percentages.
- **Test isolation.** Tests must never call real `flow-metrics`. The
  env-var override MUST be set to a fixture script in every test.

## Changelog

- 2026-05-19: initial plan
