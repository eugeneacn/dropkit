# Plan: ai-value-report

- **Spec:** [`docs/specs/ai-value-report.md`](ai-value-report.md)
- **Status:** Approved (ready to execute) <!-- Drafting | Approved | Executing | Done -->
- **Review history:** 3 adversarial review rounds (2026-05-19). Round 1: 0 blockers / 6 majors / 7 minors; round 2: 0 blockers / 3 majors / 10 minors; round 3: 0 blockers / 0 majors / 1 minor. Terminal-clean.

> **Plan contract:** this is the implementation strategy. Unlike the
> spec, this document is allowed to change as you learn. When it
> changes substantially, note why in the changelog at the bottom.

## Approach

Eleven sequentially-ordered tasks. Because this skill is a **pure
renderer** (zero subprocess calls), the implementation is the
simplest of the three downstream skills. The first three (T1
scaffold, T2 glob expansion + input validation, T3 pairing) establish
the substrate. T4–T6 build the data path: aggregation math, flag
aggregation, notes aggregation. T7 covers the JSON twin; T8 covers
Markdown rendering. T9 handles overwrite. T10 packages. T11 wires CI.

The load-bearing tasks are T4 (aggregation math with n-branching for
percentiles and zero-throughput rules) and T8 (Markdown rendering with
the determinism contract — basename-only sort, single-space padding,
exact escape rules for user-supplied text in table cells).

Implementation is **standalone Python ≥ 3.10, stdlib only**. No
third-party deps. No subprocess calls of any kind (enforced by a
contract test).

## Architectural decisions deferred to this plan

The spec is unambiguous about the "pure renderer" contract; few
decisions remain:

- **Glob expansion is performed by `glob.glob(pattern,
  recursive=True)`** preceded by `os.path.expanduser` then
  `os.path.expandvars`. The shell never sees the pattern (Windows
  cmd.exe doesn't expand globs).
- **`statistics.quantiles(method="exclusive")` is the percentile
  algorithm** (matches flow-metrics and ai-adoption-cohort); n=1, 2,
  3 cases get explicit hand-coded branches per the spec.
- **Schema validation** is hand-coded (recursive walk against
  per-skill schemas), not third-party `jsonschema`. The schemas
  shipped by the sister skills are simple enough to validate without
  a library.
- **Markdown table cell escaping** is implemented as a single helper
  `escape_md_cell(s) -> str`: `s.replace("|", "\\|").replace("\n",
  "<br>")`. Applied to every user-derived value in every table cell.

## Constraints

The decisions recorded in the spec's "Decisions" section govern all
ambiguous cases. The most binding for implementation:

- Python floor 3.10.
- No subprocess invocations of any kind.
- Pairing is exact scope-dict equality, dedupe-per-scope-first then
  pair across sides.
- Scope-overlap rule refuses heterogeneous-granularity input sets
  with exit 2.
- `meta.generated_at` is pinned to `<as_of>T00:00:00Z` for cross-
  machine reproducibility.
- `input_files` records basenames + content-sha pairs, never
  absolute paths.
- Duplicate basename across input set → exit 2.
- JSON: `notes`, `flags`, `per_scope` always present (possibly `[]`);
  `value` omitted when no paired (baseline, cohort) exists.
- Flag messages come verbatim from cohort `flag.message`; unknown
  flag names render with the cohort's message + a notes-line.
- Flag `name` validated against `^[a-z0-9-]+$` at input.

## Construction tests

Cross-cutting tests spanning multiple tasks.

**Integration tests:**

- `test_full_happy_path_three_scopes` — fixture: three baseline +
  three cohort files (each canonical 5-field scope = one project +
  team). Run `ai-value-report --baselines '<fixture>/baseline-*.json'
  --cohorts '<fixture>/cohort-*.json' --output /tmp/report.md
  --format both --as-of 2026-05-19`. Assert (a) Markdown matches a
  checked-in golden file byte-for-byte, (b) JSON twin matches its
  golden, (c) every aggregate is reproducible from the input files
  by hand.
- `test_full_happy_path_mixed_scopes` — fixture: one program-scope,
  one project-scope (non-overlapping; different project keys). Both
  appear as `per_scope` rows; aggregates are computed.
- `test_full_happy_path_unknown_flag_forward_compat` — fixture cohort
  emits flag `name: "future-flag-name"` with a `message`. Report
  renders the flag's subsection using the cohort's message; notes
  contains `"unknown-flag: 'future-flag-name'..."`.
- `test_byte_identical_across_machines` — same inputs run from two
  different working directories produce byte-identical JSON and
  Markdown.

**Manual verification gate (before tagging):**

- Run against a real team's actual baseline + cohort output. Read
  the rendered Markdown; verify it reads as a coherent board-ready
  artifact (subjective; user assesses).

## Tasks

### T1: Scaffold — CLI, argparse, exit codes, Python floor

**Depends on:** none

**Tests:**

- `test_python_below_floor_exits_2`.
- `test_help_exits_0`.
- `test_baselines_required` — no `--baselines` exits 2.
- `test_cohorts_required` — no `--cohorts` exits 2.
- `test_output_required`.
- `test_unknown_flag_exits_2`.
- `test_legacy_include_per_team_flag_rejected` (contract) —
  `--include-per-team` exits 2 with the spec-pinned "renamed to
  --include-per-scope" message.
- `test_validation_error_exits_2_before_any_read` (contract) —
  a flag-combo validation error exits 2 with zero file reads
  recorded by the test wrapper. Specifically: bad-flag combos run
  parse-time validation (T1's `validate_args`) before T2's glob
  expansion / file opens.

**Approach:**

- Create `skills/workflows/ai-value-report/scripts/ai_value_report.py`.
- Python version check; argparse with all flags from the spec's
  Inputs synopsis. `--baselines` and `--cohorts` are `action=
  "append"` (repeatable).
- `validate_args(args)` runs the pre-data checks (legacy flag,
  format-both-collides-with-json output extension).
- Stub the data path; later tasks fill in.

**Done when:** all listed tests green on Python 3.10, 3.11, 3.12.

---

### T2: Glob expansion + input file load + schema validation

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_no_baselines_match_exits_2`.
- `test_no_cohorts_match_exits_2`.
- `test_malformed_baseline_exits_2`.
- `test_baseline_missing_meta_scope_exits_2`.
- `test_wrong_skill_in_meta_exits_2`.
- `test_duplicate_input_basename_exits_2`.

**Construction tests:**

- `test_glob_expands_tilde` — `--baselines '~/.context/*.json'`
  expands via `os.path.expanduser`.
- `test_glob_expands_env_vars` — `--baselines '$HOME/.context/*.json'`
  expands via `os.path.expandvars`.
- `test_glob_recursive` — `--baselines '**/*.json'` finds files in
  subdirectories.
- `test_only_json_files_matched` — fixture dir with `foo.json`,
  `bar.txt`, `baz.json.bak`; glob matches only `foo.json` and
  `baz.json` (extension-based; `.json.bak` is not matched if the
  pattern is `*.json`).
- `test_schema_major_version_strict` — input file with
  `meta.schema_version: "2.0"` exits 2 with version named.
- `test_schema_minor_drift_accepted_with_note` — input with `"1.1"`
  loads; `notes` contains `"input-schema-minor-drift: <path> uses
  schema_version 1.1"`.
- `test_schema_subset_only` — each shipped schema
  (`baseline.schema.json`, `cohort.schema.json`) is scanned at
  startup; any unsupported keyword (`$ref`, `oneOf`, etc.) exits 2
  with the offending keyword named.
- `test_schema_parity_with_sister_schemas` — the shipped baseline
  and cohort schemas are byte-identical to the sister skills'
  source schemas (CI fixture: compare bytes of
  `references/baseline.schema.json` against
  `<sister-skill-path>/references/baseline.schema.json`). Catches
  drift between this skill's copies and the source.
- `test_recursion_depth_cap_exits_2` — input file nested 1001 levels
  deep exits 2 naming the file and depth.
- `test_literal_path_not_ending_in_json_exits_2` —
  `--baselines /tmp/foo.json.bak` (literal, not glob) exits 2.

**Approach:**

- `ai_value_report/input_load.py`:
  - `expand_inputs(patterns: list[str]) -> list[Path]` —
    `os.path.expanduser` → `os.path.expandvars` → `glob.glob(...,
    recursive=True)`. Filters to `*.json` extension. Literal paths
    not ending in `.json` exit 2 (not silently dropped). Detects
    duplicate basenames across all patterns and exits 2.
  - `load_baseline(path: Path) -> dict` — open, parse, validate
    `meta.skill == "ai-adoption-baseline"`, validate
    `meta.schema_version` major == "1", validate against
    `references/baseline.schema.json` (hand-coded recursive
    validator).
  - `load_cohort(path: Path) -> dict` — analogous with
    `references/cohort.schema.json`.

**Hand-coded schema validator** supports the JSON Schema subset
actually used by the sister skills' schemas: `type`, `properties`,
`required`, `additionalProperties: false`, `items`, `enum`, `const`,
`pattern` (compiled via `re`), `minimum`, `maximum`. Other JSON
Schema features (`$ref`, `oneOf`, `anyOf`, `allOf`,
`patternProperties`) are NOT supported in v1; the sister skills'
schemas (authored alongside the sister specs in their packaging
tasks) are constrained to this subset. CI gate
`test_schema_subset_only` scans each shipped schema and exits 2 if
any unsupported keyword appears.

**Recursion-bounded walking.** Both the schema validator and the
`pre_walk_round_floats` helper (T7) are converted to iterative form
(explicit stack of `(value, schema_node)` tuples) to avoid stack
overflow on deeply-nested JSON inputs. v1 caps depth at 1000 levels
and exits 2 on overflow with `"input file <path> nested deeper than
1000 levels; refusing to render"`.

**Done when:** all listed tests green.

---

### T3: Pairing + state-config sha cross-check

**Depends on:** T2

**Tests (contract tests from spec):**

- `test_canonical_scope_exact_match_required`.
- `test_baseline_without_cohort_skipped_with_note`.
- `test_cohort_without_baseline_included_no_baseline_delta`.
- `test_multiple_cohorts_per_scope_latest_window_to_wins`.
- `test_multiple_cohorts_tie_breaker_window_days`.
- `test_multiple_cohorts_tie_breaker_generated_at_then_path` —
  tie-breaker on `generated_at`, then on **basename** (NOT absolute
  path).
- `test_multiple_baselines_per_scope_latest_rollout_wins`.
- `test_overlapping_scopes_exit_2`.
- `test_mixed_state_config_shas_recorded`.
- `test_uniform_state_config_no_warning`.
- `test_cohort_baseline_state_config_mismatch_exits_2`.

**Construction tests:**

- `test_dedupe_then_pair_order` — fixture: scope X has 2 baselines
  and 2 cohorts. Skill picks one of each (per tie-breakers), then
  pairs them. Does not consider the other three baselines/cohorts.
- `test_scope_overlap_portfolio_plus_project_exits_2`.
- `test_scope_overlap_portfolio_plus_program_exits_2`.
- `test_scope_overlap_program_plus_project_exits_2`.
- `test_scope_overlap_project_plus_project_team_exits_2`.
- `test_scope_non_overlap_multiple_projects_ok` — five
  project-scope cohorts for five different project keys → no overlap
  exit; aggregated.

**Approach:**

- `ai_value_report/pairing.py`:
  - `dedupe_per_scope(files: list[dict], side: "baseline" | "cohort")
    -> list[dict]` — groups by canonical scope dict; collapses each
    group to one representative via the tie-breakers; emits notes
    for ignored files.
  - `pair(baselines: list[dict], cohorts: list[dict]) ->
    PairedScopes` — exact dict equality; populates `with_pair`,
    `baseline_only`, `cohort_only`.
  - `check_scope_overlap(scopes: list[dict]) -> None` — exits 2 if
    any portfolio+other / program+other / project+project-with-team
    combination is present.

**Done when:** all listed tests green.

---

### T4: Aggregation math — per-metric

**Depends on:** T3

**Tests (contract tests from spec):**

- `test_aggregate_throughput_normalized_per_week`.
- `test_aggregate_rework_rate_throughput_weighted`.
- `test_aggregate_cycle_time_not_aggregated`.
- `test_aggregate_utilization_correct_denominator`.
- `test_utilization_aggregate_equals_total_cohort_div_total_throughput`
  — same property, asserted under the spec's named test:
  `utilization.ai_tagged_share_aggregate == sum(cohort_throughput) /
  sum(total_throughput)` across paired scopes.
- `test_utilization_per_scope_distribution_uses_percentiles`.
- `test_impact_delta_per_metric_signs_consistent`.

**Construction tests:**

- `test_percentile_n_one` — input distribution of one value `x`;
  result is `{p25: x, p50: x, p75: x, min: x, max: x}`.
- `test_percentile_n_two` — input `[a, b]` with `a <= b`; result is
  `{min: a, p25: a, p50: (a+b)/2, p75: b, max: b}`.
- `test_percentile_n_three` — input `[a, b, c]`; result uses
  `statistics.quantiles([a,b,c], n=4, method="exclusive")` for
  `p25, p50, p75`.
- `test_percentile_n_ge_four_uses_stdlib` — input of 10 values;
  `p25, p50, p75` come from `statistics.quantiles(values, n=4,
  method="exclusive")`.
- `test_zero_throughput_rework_rate_null` — when sum of throughput
  across paired scopes is 0, aggregate `rework_rate` is `null` and
  `notes` contains `"aggregate-rework-rate-undefined:..."`.
- `test_zero_throughput_defect_ratio_null` — same shape.
- `test_zero_throughput_utilization_null` — same shape.
- `test_zero_throughput_throughput_per_week_is_zero_not_null` —
  zero per-week throughput is mathematically valid, rendered as `0`.

**Approach:**

- `ai_value_report/aggregation.py`:
  - `def aggregate_impact(paired: PairedScopes) -> dict` — for each
    metric, produces a cell `{cohort, control, delta_pct,
    flagged_scopes}`.
  - `def aggregate_value(paired: PairedScopes) -> dict` — for each
    metric, cross-time delta block. Omitted when no paired (baseline,
    cohort) exists.
  - `def percentile_distribution(values: list[float]) -> dict` —
    n-branching per spec.
  - `def weighted_average(pairs: list[tuple[float, float]]) ->
    Optional[float]` — `sum(value * weight) / sum(weight)`; returns
    `None` (later serialized as `null`) when `sum(weight) == 0`.

**Done when:** all listed tests green.

---

### T5: Flag aggregation + forward-compat

**Depends on:** T2, T4

**Tests (contract tests from spec):**

- `test_flag_name_invalid_charset_exits_2` — input cohort with
  `flag.name` violating `^[a-z0-9-]+$` exits 2 (validated at load
  time in T5; pre-rendering).
- `test_unknown_flag_data_carries_notes_entry` — when an input
  cohort emits a flag with unknown name, the T5-produced data
  structure includes a notes entry; T8 verifies the rendered
  output (Markdown + JSON) carries this note.

**Construction tests:**

- `test_flag_aggregation_collects_one_row_per_cohort_input` —
  fixture: 3 cohorts, each emitting `throughput-up-rework-up`.
  Output `flags[].scopes` has 3 entries.
- `test_flag_aggregation_omits_unflagged_scopes` — fixture: 3
  cohorts, 1 emitting a flag. The flag's `scopes` list has 1 entry.
- `test_flag_set_unioned_across_inputs` — fixture: cohort A emits
  `flag-X`, cohort B emits `flag-Y`. Output `flags` has both,
  alphabetized.
- `test_flag_name_charset_rejects_pipe` — fixture cohort emits
  `flag.name: "bad|flag"`. Exit 2.
- `test_flag_name_charset_rejects_uppercase` — `"BadFlag"` → exit 2.
- `test_flag_name_charset_accepts_known_flags` — all five canonical
  flag names match the regex (defensive: ensures the charset isn't
  accidentally too strict).
- `test_divergent_flag_messages_first_wins_with_note` — fixture: two
  cohorts emit `throughput-up-rework-up` with different `message`
  text. Output renders the basename-first cohort's message; notes
  contains a `flag-message-conflict:` entry.

**Approach:**

- `ai_value_report/flag_aggregation.py`:
  - `def aggregate_flags(paired: PairedScopes) -> list[dict]` —
    walks every cohort input, validates each `flag.name` against the
    charset (exit 2 on violation), groups by name, sorts
    alphabetically. Each group emits one `{name, message, scopes:
    [{scope, scope_label, evidence}]}` entry.
  - The `message` is taken from the first cohort that emits this
    flag, where "first" is defined as
    `input_files.cohorts` order (basename codepoint ascending).
    When two cohorts emit divergent messages for the same flag, a
    notes entry is emitted: `"flag-message-conflict: '<name>' has
    divergent messages across cohorts; using basename-first
    '<chosen-message>'"`. (The cohort spec does not constrain
    `flag.message` text to be canonical; divergent messages are
    legal but should be surfaced.)
  - Unknown flag names (not in the known-five set) emit a notes
    entry but still render.

**Done when:** all listed tests green.

---

### T6: Notes aggregation + warnings + meta.scopes accounting

**Depends on:** T3, T4, T5

**Tests (contract tests from spec):**

- `test_meta_flags_include_per_scope_records_actual_value` — T6
  builds the `meta.flags.include_per_scope` value (records whether
  `--include-per-scope` was passed); T7 (JSON) and T8 (Markdown)
  verify it round-trips into the rendered output.

**Construction tests:**

- `test_meta_scopes_accounting_invariant` — `scopes_total ==
  with_pair + baseline_only + cohort_only` for any input set.
- `test_notes_sorted_lexicographically`.
- `test_notes_dedup` — same note string from two cohorts → emitted
  once.
- `test_meta_warnings_mixed_state_config_shas_true_when_distinct` —
  fixture: two paired scopes with different `state_config_sha`
  values. `meta.warnings.mixed_state_config_shas == true`.
- `test_meta_warnings_mixed_state_config_shas_false_when_uniform` —
  same → false.
- `test_baseline_window_range_records_min_max_across_inputs` —
  `meta.baseline_window_range = {from: min(baseline.window.from),
  to: max(baseline.window.to)}` across paired baselines.
- `test_cohort_window_range_records_min_max` — analogous.

**Approach:**

- `ai_value_report/notes_meta.py`:
  - `class NotesCollector` — same shape as the cohort skill's;
    `add_baseline_only(scope)`, `add_cohort_only(scope)`,
    `add_mixed_state_config(shas)`, `add_input_schema_minor_drift(
    path, ver)`, etc.
  - `finalize() -> list[str]` returns sorted, deduplicated list.
  - `build_meta(args, paired, notes_collector, today_utc) -> dict`
    — assembles the `meta` block.

**Done when:** all listed tests green.

---

### T7: JSON twin rendering + canonicalization

**Depends on:** T4, T5, T6

**Tests (contract tests from spec):**

- `test_json_keys_sorted` — recursive descent into the rendered
  JSON output; every dict's keys in codepoint order.
- `test_floats_rounded_to_4dp`.
- `test_integer_counts_no_decimal_point`.
- `test_input_files_listed_as_basenames_with_sha`.
- `test_generated_at_pinned_to_as_of_midnight`.
- `test_byte_identical_across_machines`.
- `test_format_both_writes_both`.
- `test_format_both_existing_twin_exits_2_without_overwrite`.
- `test_format_both_json_named_file_exits_2`.

**Construction tests:**

- `test_input_file_sha_is_file_content_bytes_not_canonical_json` —
  fixture: two semantically-identical baseline files differing only
  in whitespace produce different sha values in `meta.input_files`.
  (This is the spec's pinned choice; the test enforces it.)
- `test_json_keys_sorted_at_every_level` — recursive descent
  validates ordering at every dict.
- `test_value_block_omitted_when_no_paired_scope` — fixture: all
  inputs are baseline-only OR cohort-only. JSON has no `value` key.

**Approach:**

- `ai_value_report/render_json.py`:
  - `def build_report_dict(meta, utilization, impact, value, flags,
    per_scope, notes) -> dict`.
  - `def serialize_json(report: dict) -> bytes` —
    `pre_walk_round_floats(copy.deepcopy(report), 4)` then
    `json.dumps(rounded, sort_keys=True, separators=(",", ":"),
    ensure_ascii=False).encode() + b"\n"`.
  - **`pre_walk_round_floats` operates on a deep copy**, not the
    original report dict. This is the load-bearing invariant: the
    Markdown renderer (T8) reads the un-rounded source values to
    compute percent displays (`round(value * 100, 1)`) independently
    from JSON rounding, per spec. Mutating the original would
    conflate the two rounding paths and break the spec-pinned
    property "JSON 4-dp and Markdown 1-dp-percent of the same datum
    computed independently from the source." Markdown and JSON
    rendering may run in any order so long as both read from the
    un-rounded source (Markdown directly; JSON via a fresh deep
    copy that gets pre-walked and rounded).

**Done when:** all listed tests green.

---

### T8: Markdown rendering + escape rules

**Depends on:** T4, T5, T6

**Tests (contract tests from spec):**

- `test_markdown_section_order_stable`.
- `test_markdown_byte_identical_for_same_inputs`.
- `test_per_scope_table_only_when_flag_set`.
- `test_dora_attribution_present_when_flag_triggers` — when a known
  flag is in the report, the rendered message contains the
  attribution text (sourced from cohort's `flag.message`).
- `test_unknown_flag_renders_cohort_message_with_notes_entry` —
  flag with name unknown to this skill version still renders the
  cohort's `message` verbatim; section IV subsection appears;
  `notes` carries the spec-pinned `"unknown-flag: ..."` entry.
- `test_flags_subsection_per_unique_flag_name` — three distinct
  flag names across inputs → three subsections under section IV
  (alphabetical by name).
- `test_scope_label_with_pipe_escaped_in_markdown`.

**Construction tests:**

- `test_markdown_table_single_space_padding` — every cell starts and
  ends with exactly one space inside the pipes.
- `test_markdown_separator_row_three_dashes` — every separator row
  is `|---|---|...` (exactly three dashes).
- `test_markdown_eof_single_trailing_newline`.
- `test_null_cell_renders_as_em_dash`.
- `test_percent_cell_renders_with_one_decimal` —
  `f"{round(value * 100, 1):.1f}%"`.
- `test_flag_message_paragraph_not_table_cell` — fixture cohort
  message contains a literal `|`. The pipe is preserved (no escape)
  in the paragraph rendering, would corrupt a table cell. Test
  verifies the message is in paragraph context.
- `test_table_cell_escape_pipe_backslash` — fixture team name
  `"Foo|Bar"` → `"Foo\|Bar"` in any table cell.
- `test_table_cell_escape_newline` — newline in user value →
  `<br>`.
- `test_section_iv_present_with_placeholder_when_zero_flags` —
  fixture with no flagged input → section IV is **present**
  rendering `No adversarial flags triggered.` (single line, NOT
  omitted; the section header itself remains so section order
  stays stable).
- `test_section_v_omitted_without_include_per_scope` —
  Markdown has no section V when flag is unset; JSON still has
  `per_scope`.

**Approach:**

- `ai_value_report/render_md.py`:
  - `def render_markdown(report: dict, args) -> bytes` —
    section-by-section rendering. Each section is its own function
    returning a list of strings; final join + EOF newline.
  - `def escape_md_cell(s: str) -> str` — single helper applied to
    every user-derived value in table cells.
  - `def format_percent(v: float) -> str` and `def
    format_hours(v: float) -> str` — display rules.
  - Determinism: no `datetime.now()` calls; everything keys off
    `meta.as_of`. List iteration follows the sorted orders from T6.

**Done when:** all listed tests green.

---

### T9: Atomic write + overwrite logic

**Depends on:** T7, T8

**Tests (contract tests from spec):**

- (overlap with T7: `test_format_both_existing_twin_exits_2_without_overwrite`).

**Construction tests:**

- `test_overwrite_replaces_atomically` — same pattern as
  baseline-skill T6: same-directory tempfile + `os.replace`.
- `test_overwrite_format_both_replaces_both` — `--overwrite
  --format both` replaces both files atomically (independently, not
  as a single transaction — but each individually atomic).
- `test_overwrite_with_no_existing_file_ok` — `--overwrite` with no
  existing file succeeds (overwrite is permissive: it doesn't require
  a file to actually be overwritten).
- `test_no_writes_outside_output_path` — verified via the no-
  subprocess contract test + a file-handle tracker that asserts
  only `--output` and its `.json` twin are written.
- `test_no_subprocess_invocations` (contract) — wrap
  `subprocess.run/Popen`; assert zero calls.

**Approach:**

- `ai_value_report/atomic_write.py`:
  - Same pattern as the other skills: same-directory tempfile +
    `os.replace`. PID-suffixed `.tmp` name; stale-tmp sweep on
    startup.
- `ai_value_report/main.py` — orchestrates: load inputs → validate
  schema → pair → aggregate → render → atomic write. Catches
  `ValidationError`, `SchemaError`, `PathError` and emits the
  appropriate exit code.

**Done when:** all listed tests green.

---

### T10: SKILL.md + manifest + co-versioned schemas

**Depends on:** T1–T9

**Tests:**

- `test_skill_md_lists_all_subcommands_from_spec`.
- `test_manifest_declares_dependencies` —
  `deps.skills: [{name: "ai-adoption-baseline"}, {name:
  "ai-adoption-cohort"}]`. No direct `flow-metrics` dep.
- `test_skill_md_security_rules_present`.
- `test_no_subprocess_static_check` — AST-scan the `ai_value_report/`
  tree; fail if any file imports `subprocess`, `pty`,
  `multiprocessing`, or calls any of the following process-spawning
  functions: `subprocess.run`, `subprocess.Popen`, `subprocess.call`,
  `subprocess.check_call`, `subprocess.check_output`,
  `os.system`, `os.popen`, `os.spawnl`, `os.spawnle`,
  `os.spawnlp`, `os.spawnlpe`, `os.spawnv`, `os.spawnve`,
  `os.spawnvp`, `os.spawnvpe`, `os.execl`, `os.execle`,
  `os.execlp`, `os.execlpe`, `os.execv`, `os.execve`,
  `os.execvp`, `os.execvpe`, `os.forkpty`, `os.fork`,
  `pty.spawn`. Defense in depth against the "no subprocess of any
  kind" claim — `subprocess` is the most common but not the only
  way to spawn.

**Approach:**

- `skills/workflows/ai-value-report/SKILL.md`.
- `skills/workflows/ai-value-report/manifest.json`.
- `skills/workflows/ai-value-report/references/value-report.schema.json`
  — JSON Schema for output.
- `skills/workflows/ai-value-report/references/baseline.schema.json`
  — copy of ai-adoption-baseline's schema for input validation.
- `skills/workflows/ai-value-report/references/cohort.schema.json` —
  copy of ai-adoption-cohort's schema. All three schemas are
  co-versioned with their producing skill's `meta.schema_version`;
  CI fails if the copies drift from source.

**Done when:** all listed tests green.

---

### T11: CI matrix + integration fixtures + golden files

**Depends on:** T1–T10

**Tests:**

- All contract + construction tests pass on the 9-combo CI matrix
  (os × python).
- Integration tests
  (`test_full_happy_path_three_scopes`,
   `test_full_happy_path_mixed_scopes`,
   `test_full_happy_path_unknown_flag_forward_compat`,
   `test_byte_identical_across_machines`) pass against synthetic
  fixtures.

**Approach:**

- `.github/workflows/test-ai-value-report.yml`.
- `tests/fixtures/value_report/`:
  - `inputs/baseline-PROJ_Team-Foo.json` (and several more,
    hand-authored to canonical-5-field-scope shape).
  - `inputs/cohort-PROJ_Team-Foo.json`.
  - `golden_report_three_scopes.md` and `.json`.
  - `golden_report_mixed_scopes.md` and `.json`.
  - `golden_report_unknown_flag.md` and `.json`.

**Done when:** CI matrix green on all 9 combinations.

## Rollout

New skill, no existing behavior changed. Ships as `v0.1.0`. Depends on
`ai-adoption-baseline` and `ai-adoption-cohort` being installable.

Ship checklist:

- All tests green across the 9-combo CI matrix.
- One real-team smoke run produces a report that reads as a coherent
  board-ready artifact (subjective; PI / RTE assesses).
- SKILL.md links spec + plan.

## Risks

- **Schema drift between sister skills and this renderer's copies.**
  The renderer ships copies of `baseline.schema.json` and
  `cohort.schema.json`. If a sister skill bumps schema_version
  without bumping this skill, the renderer rejects valid input. CI
  job verifies the copies are byte-identical to the source
  schemas; both bump in lockstep.
- **Forward-compat for unknown flag names.** Render-time renders the
  cohort's own message verbatim. A malicious cohort with a hostile
  message (Markdown injection) would corrupt the report. The escape
  rules apply to table cells, but flag-message paragraphs accept
  pipes and backticks. Documented as a trust boundary: the cohort
  spec already constrains flag names to a charset; if a future cohort
  emits a hostile message, that's a cohort-spec problem.
- **Determinism fragility.** Floats are the highest-risk area. The
  `pre_walk_round_floats` helper must be idempotent and complete
  (no float leaks into `json.dumps` unrounded). The
  `test_byte_identical_across_machines` test in CI catches
  regressions.
- **Markdown ambiguity in cohort messages.** A cohort message
  containing `*emphasis*` renders as italics; the spec accepts this
  (cohort messages are trusted authors' prose). Documented.
- **Deep-nesting DoS via malformed inputs.** A hostile input file
  with 10k-deep nesting would overflow the schema validator and the
  float-rounding walker if either is naive recursive. T2's spec
  pins iterative walking with a 1000-level depth cap; T7's
  `pre_walk_round_floats` follows the same pattern. CI fixture
  `deeply_nested_input.json` covers the regression.
- **Glob expansion on Windows.** Python's `glob.glob` is OS-agnostic
  but path separators differ. CI matrix covers Windows.
- **No subprocess invocations** is enforced by both a static AST
  check (T10) and a runtime test wrapper (T9). Two layers, because
  this is the load-bearing security property of the skill.

## Changelog

- 2026-05-19: initial plan
