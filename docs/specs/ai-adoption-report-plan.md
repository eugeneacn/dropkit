# Plan: ai-adoption-report

- **Spec:** [`docs/specs/ai-adoption-report.md`](ai-adoption-report.md)
- **Status:** Approved (ready to execute) <!-- Drafting | Approved | Executing | Done -->
- **Review history:** 3 adversarial review rounds (2026-05-19). Round 1: 1 blocker / 2 majors / 2 minors; round 2: 0 blockers / 1 major / 2 minors; round 3: terminal-clean.

> **Plan contract:** this is the implementation strategy. Unlike the
> spec, this document is allowed to change as you learn. When it
> changes substantially (a different approach, not just a re-ordering),
> note why in the changelog at the bottom.

## Approach

Nine sequentially-ordered tasks. T1 establishes the CLI scaffold. T2
ships the input-loading + meta-validation pipeline shared by all three
modes. T3 implements `baseline` and `cohort` modes — both are simple
file consumers that share T5's delta engine. T4 implements `program`
mode's discovery + overlap + flattening pipeline (the heaviest task).
T5 ships the per-mode delta engine that produces the `deltas` dict
all three modes consume. T6 ships the program-mode aggregation engine
(non-cohort + cohort-rollup, both sides handled by the same "by-side"
core). T7 renders Markdown + JSON sidecar. T8 covers the write path
(atomic, collision detection, `--overwrite`, both-format checks). T9
packages the skill.

The load-bearing tasks are T4 (program discovery — overlap detection
and per_team flattening have the most edge cases) and T6 (aggregation
math — the spec pins distinct weighting rules for `rework_rate`,
`defect_ratio`, and `flow_distribution`, plus cohort/control
independence). T5 looks small but is shared by all three modes; its
contract tests gate T3, T4, and T6.

Implementation is **standalone Python ≥ 3.10, stdlib only** — same
floor and constraints as flow-metrics. The skill makes no upstream
calls (read-only contract; spec §"Read-only contract"). All inputs
are local JSON files; all outputs are local Markdown + JSON.

## Architectural decisions deferred to this plan

The spec does not pin these implementation choices:

- **No per-issue cache.** Unlike flow-metrics, the report reads
  already-aggregated JSON; nothing to cache.
- **In-memory aggregation.** Inputs are bounded (one JSON per scope
  per window; program mode caps at ~hundreds of scopes for a single
  program). No streaming pipeline. Load every input, hold every
  derived value, render once, write.
- **One CLI binary, three subcommand dispatchers.** `baseline`,
  `cohort`, `program` are argparse subcommands; common flags
  (`--output`, `--format`, `--overwrite`, `--title`, `--verbose`) live
  on the top-level parser. This is the cleanest argparse pattern for
  mutually-exclusive mode flag-sets.
- **Atomic write via `tempfile.NamedTemporaryFile` + `os.replace`.**
  Same pattern flow-metrics uses for its output. Both files
  (Markdown + JSON sidecar) write to the same parent directory.
- **Percentile / aggregation library: stdlib only.** Use
  `statistics.median` for median-of-medians; explicit n-branching for
  min/max (no percentiles are aggregated across scopes per the spec).

## Constraints

- Python ≥ 3.10 (matches flow-metrics).
- Stdlib only. No `pip install` step.
- Read-only contract: zero subprocess invocations; zero filesystem
  writes outside `--output` and its `.json` sidecar.
- Tests gated by the spec's "Contract tests" section. Every test
  named in the spec MUST exist as a real test before the task that
  introduces its surface is considered Done.

## Task graph

```
T1 → T2 → T3 (baseline + cohort)
        ↘ T4 (program discovery) → T6 (aggregation)
        ↘ T5 (delta math) ──────────┘
                ↘──────────────────→ T7 (rendering) → T8 (write) → T9 (packaging)
```

T5 is consumed by T3, T6. T7 is consumed by all three modes. T8 and
T9 are the tail. T2 unblocks everything past the scaffold.

---

### T1: Scaffold — CLI, argparse subcommands, Python version guard, path safety, exit codes

**Depends on:** none

**Tests:**

- `test_python_below_floor_exits_2` — Python 3.9 startup exits 2.
- `test_help_exits_0` — `--help` and each subcommand's `--help` exit 0
  and list every flag from the spec's Inputs table.
- `test_unknown_subcommand_exits_2` — `ai-adoption-report frobnicate
  --foo` exits 2.
- `test_missing_subcommand_exits_2` — bare invocation exits 2.
- `test_unknown_flag_exits_2` per subcommand.
- `test_absolute_path_outside_cwd_exits_2` parameterised across
  every input-path flag in every mode (`baseline --baseline`,
  `baseline --current`, `cohort --input`, `program --inputs`, plus
  `--output` in all three modes) — points outside CWD exit 2 before
  any file read.
- `test_baseline_requires_baseline_and_current` — missing either flag
  exits 2.
- `test_cohort_requires_input` — missing `--input` exits 2.
- `test_program_requires_inputs_and_window` — missing either exits 2.
- `test_window_flag_not_two_iso_dates_exits_2` (contract, spec
  §"Input validation").
- `test_validation_error_exits_2_before_any_file_read` — flag-combo
  validation error exits 2 with zero filesystem reads. Verified via
  a fixture that monkey-patches `pathlib.Path.read_text` to raise.

**Approach:**

- Create `skills/workflows/ai-adoption-report/scripts/ai_adoption_report.py`
  as the CLI entry point. Layout mirrors flow-metrics
  (`scripts/flow_metrics.py`).
- Version check at module top: `sys.version_info < (3, 10)` → stderr
  + `sys.exit(2)`.
- `build_parser()` configures a top-level parser plus three
  subparsers (`baseline`, `cohort`, `program`) per the spec's Inputs
  table.
- Path-safety helper `validate_local_path(path: str, *, role: str) ->
  pathlib.Path`: resolves the path, asserts it's inside `Path.cwd()`,
  raises a `ValidationError` with `role` in the message otherwise.
  Reused in every mode.
- Stub every subcommand body to print "not yet implemented" + exit 0.
  Later tasks fill these in.
- `--window FROM..TO` parser: split on `..`, validate each side as
  `YYYY-MM-DD` via `datetime.date.fromisoformat`, reject anything
  else (including `T00:00:00` suffix). Returns the two strings
  verbatim (no normalization — string equality is the spec's match
  rule).
- `if __name__ == "__main__": main()` guard.

**Done when:** all listed tests green on Python 3.10, 3.11, 3.12.

---

### T2: Input loading + meta validation + scope kind inference

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_missing_required_meta_field_exits_2` parameterised across
  `scope`, `window`, `state_config_sha`, `issuetype_config_sha`,
  `schema_version`, `generated_at`.
- `test_unreadable_input_file_exits_2_with_basename`.
- `test_invalid_json_input_exits_2_with_basename`.
- `test_window_not_iso_date_exits_2` (e.g. value `2026-02-19T00:00:00Z`
  in `meta.window.from`).
- `test_schema_version_unparseable_exits_2` (e.g. `"1"` or `"1.0.0"`).
- `test_mixed_major_schema_versions_emits_note` — two inputs with
  `1.0` and `2.1` produce a notes entry with the literal
  `"mixed-major-schema-versions: ..."` prefix.
- `test_unrecognised_scope_shape_exits_2` — e.g. `{team: "Foo"}`
  alone, or `{project: "P", program_id: 42}` (program_id forbids
  project).
- `test_scope_kind_inferred_correctly` parameterised across the four
  kinds: `portfolio`, `program`, `project`, `project+team`.

**Approach:**

- Module `inputs.py`. Functions:
  - `load_input(path: Path) -> InputFile` — reads JSON, validates
    meta keys, parses `schema_version` as `(major:int, minor:int)`,
    infers `kind`. Raises `ValidationError` with file basename in
    every message.
  - `infer_scope_kind(scope: dict) -> str` — implements the spec's
    inference table. Unrecognised shapes raise.
- Dataclass `InputFile` with fields: `path`, `basename`, `scope`,
  `scope_kind`, `window_from`, `window_to`, `meta` (raw dict),
  `aggregates` (raw dict), `cohort_breakdown` (Optional[dict]),
  `per_team` (Optional[list]), `schema_version` (tuple), `notes_from_upstream`
  (list of strings, may be empty).
- A small `Note` helper that produces the literal-form strings from
  the spec — every notes entry the report emits goes through one of
  the helper's factory methods (`Note.mixed_major_schema_versions(...)`,
  etc.). Centralising the formatter prevents wording drift across
  the codebase.
- Window-format validation: `datetime.date.fromisoformat` rejects
  time components in Python 3.10 — but we explicitly verify with a
  regex `^\d{4}-\d{2}-\d{2}$` to avoid accepting partial parses.

**Done when:** tests green and `InputFile` round-trips every fixture
in `tests/fixtures/inputs/*.json` (a small set of canonical
flow-metrics outputs across all four scope kinds).

---

### T3: Baseline mode + cohort mode (file consumers)

**Depends on:** T2, T5 (delta math)

**Tests (contract tests from spec):**

Baseline:
- `test_baseline_scope_mismatch_exits_2_with_both_scopes`.
- `test_baseline_window_overlap_exits_2`.
- `test_baseline_back_to_back_windows_allowed`.
- `test_baseline_config_sha_drift_emits_note_and_renders_deltas`.
- `test_baseline_include_cohort_breakdown_without_cohort_noops_with_note`.
- `test_baseline_include_cohort_breakdown_jql_mismatch_omits_section_with_note`.
- `test_baseline_per_team_present_emits_ignored_note`.

Cohort:
- `test_cohort_input_without_cohort_breakdown_exits_2`.
- `test_cohort_emits_cohort_vs_control_deltas`.

**Approach:**

- Module `modes.py`. Two functions: `run_baseline(args) -> ReportData`
  and `run_cohort(args) -> ReportData`. Both return a `ReportData`
  dataclass that T7 renders.
- `ReportData` fields: `mode`, `header_line` (the mode-specific
  string in spec §"Output: Markdown"), `inputs` (list of
  `InputFile`), `deltas` (dict from T5), `cohort_deltas`
  (Optional[dict], same shape), `per_scope_rows` (None for baseline
  and cohort), `notes` (sorted list of strings via T2's `Note`
  helper).
- Baseline: load A and B via T2, validate scope equality, validate
  window order, emit drift / per_team / cohort-jql notes per spec.
  Call into T5 for the delta computation. **Concatenate the returned
  `DeltaResult.notes` onto `ReportData.notes`** (see T5's "Notes merge
  contract"). For `--include-cohort-breakdown`, repeat with the
  cohort/control pair and concatenate again.
- Cohort: load single input, assert `cohort_breakdown` present, pass
  cohort vs control through T5's engine with side A=control, B=cohort.
  **Concatenate the returned `DeltaResult.notes` onto
  `ReportData.notes`.**
- Both modes assemble `header_line` per the spec's mode-specific
  rules.

**Done when:** tests green; running each mode against fixtures
produces the `ReportData` shape T7 expects.

---

### T4: Program mode — input discovery, dedupe, overlap, per_team flattening

**Depends on:** T2

**Tests (contract tests from spec):**

- `test_program_no_inputs_match_window_exits_2`.
- `test_program_overlapping_scopes_exits_2`.
- `test_program_duplicate_scope_exits_2_with_both_basenames`.
- `test_program_per_team_flattens_into_per_scope_rows`.
- `test_program_per_team_double_counted_input_emits_warning_note` —
  asserts the literal `"per_team-double-counted: ..."` form, with
  basenames sorted codepoint-ascending.
- `test_program_per_team_flattened_rows_excluded_from_cohort_rollup`.
- `test_program_per_team_flattened_collides_with_explicit_project_team_exits_2`
  — fixture: one program-scope input with `per_team` containing
  `team=Foo`, plus an explicit `project+team` input with the same
  `project` and `team=Foo`. Asserts exit 2 with the duplicate-scope
  error naming both basenames.

**Approach:**

- Module `program_discovery.py`. Function `discover_inputs(dir: Path,
  window_str: str) -> ProgramInputs`.
- Discovery:
  1. `Path(dir).glob("*.json")` — no recursion.
  2. Load each via T2's `load_input`. Failures exit 2 naming the
     basename.
  3. Filter to those whose `meta.window.from` + `meta.window.to` ==
     parsed `--window` endpoints (string equality).
  4. Empty result → exit 2 with `"no inputs matched --window
     FROM..TO in <DIR>"`.
- Overlap detection over the filtered set:
  - Group by `scope_kind`. Pre-dedupe pass: two inputs with the same
    canonical scope dict and same `scope_kind` exit 2 with
    `"duplicate scope in input set: <scope> in <a> and <b>"`.
  - Cross-kind overlap rule per spec — implemented as a small
    pairwise check (the set is bounded; no need for trees).
- `per_team` flattening: for each loaded input, if `per_team` is
  present and non-empty, synthesise additional `ProgramScope`
  records carrying:
  - Original scope's `project` / `program_id` / `portfolio_id`.
  - The team value from the per_team entry as `scope.team`.
  - Re-inferred kind (typically `project+team`).
  - The per_team entry's `aggregates` as the row's metrics.
  - **No** `cohort_breakdown` (per spec — flow-metrics v1 doesn't
    split per_team by cohort). A flag `from_per_team: True` on the
    `ProgramScope` so T6 can exclude them from cohort rollups.
  - The original `meta.per_team_double_counted` value propagates.
- After flattening, **re-run the duplicate-scope check on the
  combined set** as a defensive safeguard. The spec is silent on
  whether the duplicate-scope rule applies post-flattening, but the
  rule's intent ("never silently collapse duplicate scopes; report
  both basenames") would otherwise produce an asymmetric outcome
  where pre-existing duplicates raise and flattening-induced
  duplicates double-count. If it raises, exit 2 with the
  duplicate-scope error naming both the program-mode input that
  produced the flattened row and the explicit input. Cross-kind
  overlap (e.g. portfolio vs project) is detected in the first pass
  and need not re-run because flattening can only produce
  finer-grained rows, not coarser. If this safeguard proves wrong in
  practice (e.g. a legitimate workflow surfaces), update the spec
  before relaxing the check — do not silently weaken the plan.
- Output is `ProgramInputs(scopes: list[ProgramScope],
  source_inputs: list[InputFile])` — `source_inputs` is what T7's
  provenance reads.

**Done when:** tests green and `ProgramInputs` carries enough fields
for T6 to drive aggregation without re-reading files.

---

### T5: Delta math engine — absolute, percent, distribution per-percentile, n-rule, edge cases

**Depends on:** none (pure math over dict shapes)

**Tests (contract tests from spec):**

- `test_percent_delta_zero_baseline_zero_current_renders_dash`.
- `test_percent_delta_zero_baseline_positive_current_renders_infinity`.
- `test_percent_delta_null_either_side_renders_dash`.
- `test_percent_delta_one_decimal_place_signed`.
- `test_distribution_metrics_compared_per_percentile`.
- `test_markdown_n_differs_more_than_10pct_emits_note` (the formula
  itself; the rendering verification lives in T7).

**Approach:**

- Module `delta.py`. Function
  `compute_deltas(a: dict, b: dict, *, side_labels: tuple[str, str])
  -> DeltaResult`.
- `a` and `b` are aggregate-shaped dicts (the same shape flow-metrics
  emits in `aggregates` or in `cohort_breakdown.<side>`). The
  function knows nothing about modes — it just compares two
  dicts of the same shape.
- For each metric in the canonical row order (spec §"Metric row
  order"): if absent in both, skip; if absent in one, render as `—`
  with a note; if scalar, compute `abs` and `pct`; if distribution,
  iterate per-percentile `p50, p75, p90`; if bucket
  (`flow_distribution`), iterate per-bucket in flow-metrics's fixed
  bucket order.
- Percent formula: `(b - a) / a`. Special cases per spec:
  - `a == 0 and b == 0` → `pct = None`, note.
  - `a == 0 and b > 0` → `pct = math.inf`, no note (the `∞` renders
    in T7).
  - `a == 0 and b < 0` → `pct = -math.inf` (currently unreachable
    given flow-metrics emits no negative metrics; coded but not
    exercised).
  - `a is None or b is None` → `pct = None`, `abs = None`, note.
- N-rule: when both sides expose `n`, compute `abs(n_a - n_b) /
  max(n_a, n_b)` (guard `max == 0` → always note). Emit a note when
  > 0.1.
- Return a `DeltaResult` with: `rows` (list of `(metric_label,
  a_value, b_value, abs_delta, pct_delta)` tuples in canonical
  order), `notes` (list of strings — unsorted; T7 sorts the final
  merged list).
- **Notes merge contract.** Notes from T5 are *separate* from the
  notes T2 and T4 populate. T3 and T6 are responsible for
  concatenating T5's notes onto `ReportData.notes` before passing
  the report to T7. T7 deduplicates and sorts. The contract test
  `test_notes_from_all_sources_merged_and_sorted` (T7) verifies the
  merge: a fixture that triggers a T2 note (mixed-major-schema), a
  T4 note (per_team-double-counted), and a T5 note (null-on-one-side)
  must produce all three in the final output, sorted lexicographically.

**Done when:** tests green; T3 and T6 can drive T5 without
re-implementing any formula.

---

### T6: Program-mode aggregation — non-cohort + cohort rollup

**Depends on:** T4, T5

**Tests (contract tests from spec):**

- `test_program_throughput_weighted_rework_rate_zero_denom_renders_dash`.
- `test_program_distribution_metric_renders_median_of_medians`.
- `test_program_cohort_breakdown_partial_emits_count_note`.
- `test_program_mixed_cohort_jql_emits_note_and_proceeds`.
- `test_program_no_cohort_inputs_omits_section_with_note`.
- `test_program_cohort_rollup_aggregates_sides_independently`
  (fixture in spec — verifies the cohort-side weighting math).
- `test_program_defect_ratio_weighted_by_distribution_denominator`.
- `test_program_cohort_defect_ratio_weighted_by_cohort_denominator`.
- `test_program_flow_distribution_buckets_sum_to_one_after_aggregation`.
- `test_program_cohort_missing_flow_distribution_drops_from_distribution_rollup_only`.

**Approach:**

- Module `aggregation.py`. Two entry points:
  - `aggregate_non_cohort(scopes: list[ProgramScope]) -> dict` —
    produces an `aggregates`-shaped dict.
  - `aggregate_cohort_side(scopes: list[ProgramScope], side:
    Literal["cohort", "control"]) -> dict | None` — produces a
    `cohort_breakdown.<side>`-shaped dict, or `None` if zero scopes
    contribute.
- Shared core: `weighted_sum_and_average(values, weights) -> tuple
  (sum_weights, weighted_mean | None)`. `weighted_mean` is `None`
  when `sum_weights == 0`.
- Per-metric handlers (one dispatch table; same code path for
  cohort-side and non-cohort, differing only in which weight source
  to use):
  - `throughput`, `wip`, `flow_load` → simple sum.
  - `rework_rate` → throughput-weighted (cohort uses cohort
    throughput; non-cohort uses scope throughput).
  - `defect_ratio` → `flow_distribution.denominator`-weighted (cohort
    uses cohort denominator).
  - `flow_distribution` per-bucket → denominator-weighted; aggregated
    denominator is the sum.
  - Distribution metrics (`cycle_time_hours`, `lead_time_hours`,
    `flow_time_hours`, `flow_efficiency`) → median-of-medians per
    percentile + min/max across scopes; `n` is the sum across
    contributing scopes.
- Cohort rollup exclusions:
  - Scopes with `from_per_team: True` excluded from both cohort and
    control sides (per spec — flow-metrics v1 doesn't split per_team
    by cohort).
  - Scopes missing `cohort_breakdown` excluded from both sides; note
    emitted.
  - Scopes missing `cohort_breakdown.<side>.flow_distribution` excluded
    from that side's `defect_ratio` and `flow_distribution` rollups
    only; note emitted.
- Mixed-cohort-jql note: collect every `meta.cohort_jql` across
  contributing scopes; emit note if `len(set) > 1`.
- Zero-contribution note: if `aggregate_cohort_side` returns `None`,
  emit `"cohort-breakdown-section-empty"`.
- **Notes merge.** Program mode runs T5 once for each comparison
  pair (non-cohort across scopes is not a pair — no T5 invocation;
  cohort rollup vs control rollup IS a pair, runs T5). Every
  `DeltaResult.notes` returned by T5 is concatenated onto
  `ReportData.notes` before the report is passed to T7 (see T5's
  "Notes merge contract").

**Done when:** tests green; the cohort fixture in the spec
(`test_program_cohort_rollup_aggregates_sides_independently`)
produces the exact decimal values pinned.

---

### T7: Output rendering — Markdown + JSON sidecar

**Depends on:** T3, T6

**Tests (contract tests from spec):**

- `test_markdown_sections_omitted_when_empty`.
- `test_markdown_unicode_minus_in_numeric_cells_ascii_hyphen_in_dates`.
- `test_markdown_scope_team_names_escaped`.
- `test_markdown_metric_rows_in_canonical_order`.
- `test_markdown_distribution_metric_one_row_per_percentile`.
- `test_markdown_n_differs_more_than_10pct_emits_note`.
- `test_json_sidecar_keys_sorted_except_deltas_in_canonical_order`.
- `test_json_sidecar_floats_4dp`.
- `test_json_sidecar_inputs_sorted_by_basename`.
- `test_json_sidecar_scope_kind_present_on_inputs`.
- `test_byte_identical_rerun_modulo_generated_at`.
- `test_notes_from_all_sources_merged_and_sorted` — fixture-driven
  test that triggers a T2 note (mixed-major-schema), a T4 note
  (per_team-double-counted), and a T5 note (null-on-one-side); all
  three must appear in the rendered Markdown `## Notes` section and
  in the JSON sidecar's `notes` array, sorted lexicographically and
  deduplicated.

**Approach:**

- Module `render.py`. Two functions: `render_markdown(report:
  ReportData, title: str, generated_at: str) -> str` and
  `render_json(report: ReportData, title: str, generated_at: str) ->
  dict`.
- Markdown:
  - Walk the canonical section order; skip sections whose data is
    empty (no header emitted).
  - Numeric cell formatter:
    - Integers → bare integer.
    - Floats → rounded to 4dp at format time (`format(v, ".4g")` is
      wrong — use `round(v, 4)` then `str(...)`; trailing zeros
      stripped via the JSON-style rule).
    - `None` → `—` (em dash, U+2014).
    - `math.inf` → `∞` (U+221E); `-math.inf` → `−∞` (U+2212 then
      `∞`).
    - Negative numerics → `−<value>` (U+2212), positive → unsigned.
    - Percent column → `<+|−><value>%`, one decimal place. True zero
      → `+0.0%` (sign chosen deterministically to avoid `−0.0`).
  - Markdown escape rule for scope/team names: backslash-escape the
    characters pinned in the module constant
    `` _MARKDOWN_ESCAPE_CHARS = '|`*_[]\\#+' ``. Rationale per
    character: `|` is the table separator; `` ` `` starts code spans;
    `*` and `_` start emphasis; `[` `]` start links; `\` is the
    escape character itself; `#` starts headings if at line start
    (cell content normally isn't, but defensive); `+` can start a
    list item if at line start. **ASCII hyphen `-` is NOT in the
    set** because date strings like `2024-Q1` and team names like
    `Mobile-Web` are common in scope labels, and `-` only acquires
    list-item meaning at line start. Implementation: a `str.maketrans`
    table built once at module load mapping each character `c` to
    `'\\' + c`, applied via `str.translate`. The constant lives next
    to the helper with a comment pointing at this rationale so a
    future contributor can audit it against CommonMark without
    spelunking.
  - Numeric cells inside table rows use the U+2212 minus
    consistently; date strings like `2024-Q1` use ASCII hyphen.
- JSON:
  - Build the dict in canonical order. `meta.inputs` sorted by
    basename via `str.__lt__`. `notes` sorted via `str.__lt__`.
  - `deltas` is *not* sorted by key — its key order follows the
    canonical metric row order. Implementation: build it as a
    regular `dict` (insertion-ordered in 3.7+) and serialize with
    `json.dumps(..., sort_keys=False)` for that subtree, then merge
    with the rest of the object which uses `sort_keys=True`. Cleanest
    approach: serialise the top-level object manually as a sorted
    OrderedDict where the `deltas` value is a pre-serialised JSON
    fragment. Or simpler: emit the whole document via a custom
    encoder that overrides `_sort_keys` for the `deltas` subtree.
    The plan picks the second: a thin `CanonicalEncoder(json.JSONEncoder)`
    subclass that re-orders nested dicts on encode.
  - Floats: pre-walk the dict and round every float to 4dp before
    `json.dumps` — same approach as flow-metrics.
- `generated_at` is set by the caller (T8 passes it; tests stub it).
  The renderer never reads the clock.

**Done when:** tests green; running each mode end-to-end on a fixture
produces byte-identical output across two consecutive runs with the
same `generated_at`.

---

### T8: Output write — atomic, collision detection, `--overwrite`, both-format checks

**Depends on:** T7

**Tests (contract tests from spec):**

- `test_overwrite_collision_exits_2_without_flag`.
- `test_overwrite_collision_with_both_format_checks_both_files`.
- `test_format_json_skips_markdown_render`.

**Approach:**

- Module `write.py`. Function `write_outputs(markdown_path: Path,
  markdown: str | None, json_path: Path | None, json_obj: dict |
  None, overwrite: bool) -> None`.
- Pre-flight check: build the list of target paths (markdown,
  optional sidecar). If any exists and `overwrite=False`, exit 2
  with a message naming all colliding paths. Pre-flight runs *before*
  any write so the `both` mode never half-writes on collision.
- Atomic write: for each non-None target, write to a sibling
  `tempfile.NamedTemporaryFile(dir=target.parent, delete=False)`,
  flush, fsync, `os.replace(tmp.name, target)`. Failure cleanup via
  `try / finally` removing the tempfile.
- Sidecar path derivation: `<output>` ending in `.md` →
  `re.sub(r'\\.md$', '.json', output)`. Output with no extension →
  `output + '.json'`. Output ending in `.json` → exit 2 with
  `"--format both requires the Markdown file to be named distinctly
  from .json"`.
- `--format` dispatch:
  - `markdown`: write markdown only.
  - `json`: write json only; do NOT call T7's `render_markdown` at
    all.
  - `both` (default): render both, write both.

**Done when:** tests green; manual sanity check that an interrupted
write (SIGTERM mid-stream) leaves either both originals intact or
both targets fully replaced.

---

### T9: Packaging — SKILL.md, manifest.json, fixtures, golden files

**Depends on:** T8

**Files shipped:**

- `skills/workflows/ai-adoption-report/SKILL.md` — usage doc with
  three mode examples drawn from spec §"Users and use cases".
- `skills/workflows/ai-adoption-report/manifest.json` — registration
  for the kit-installer (same shape as flow-metrics' manifest).
- `skills/workflows/ai-adoption-report/scripts/ai_adoption_report.py`
  — finished CLI from T1–T8.
- `skills/workflows/ai-adoption-report/tests/fixtures/` — canonical
  flow-metrics fixtures used across the test suite (small, hand-curated
  JSONs covering each scope kind, both with and without
  `cohort_breakdown`, both with and without `per_team`).
- `skills/workflows/ai-adoption-report/tests/golden/` — byte-fixed
  expected Markdown + JSON outputs for one fixture per mode.

**Tests:**

- `test_skill_md_lists_every_flag_from_spec` — parses SKILL.md and
  diffs the flag set against `build_parser().format_help()`.
- `test_manifest_registers_under_workflows` — verifies
  `manifest.json.category == "workflow"` and the entry point matches
  the script path.
- `test_no_upstream_skill_invocations` — runs each mode against a
  fixture under a `subprocess.run` monkey-patch that records every
  call; asserts zero invocations.
- `test_no_filesystem_writes_outside_output_and_sidecar` — same shape,
  monkey-patches `pathlib.Path.write_*` and `open(..., "w")`.
- Golden-file diff tests, one per mode.

**Approach:**

- SKILL.md mirrors flow-metrics' SKILL.md structure: 1-paragraph
  pitch, "When to use," "Inputs," "Outputs," "Examples," "Exit
  codes." Each example uses the literal commands from spec §"Users
  and use cases".
- manifest.json registers under `category: workflow`, lists no
  upstream skill dependencies (the skill is read-only; it consumes
  files, not skills).
- Golden files generated by running the CLI against fixtures with a
  pinned `generated_at` (env var `AI_ADOPTION_REPORT_GENERATED_AT`
  for test reproducibility — same pattern flow-metrics uses for
  determinism).

**Done when:** all listed tests green; running `ai-adoption-report
baseline --baseline tests/fixtures/baseline.json --current
tests/fixtures/current.json --output /tmp/report.md` from a clean
working tree produces the golden output byte-for-byte.

---

## Test inventory cross-check

The spec lists ~40 contract tests. Coverage map:

| Spec section | Tests | Lands in task |
|---|---|---|
| Input validation | 10 tests | T1 (path), T2 (meta) |
| Baseline mode | 7 tests | T3 |
| Cohort mode | 2 tests | T3 |
| Program mode | 10 tests | T4, T6 |
| Delta math | 5 tests | T5 |
| Output | 11 tests | T7, T8 |
| Read-only contract | 2 tests | T9 |

Every spec contract test maps to exactly one task. If
implementation discovers a missing contract test, **update the spec
first** (per spec contract), then add the test to the appropriate
task here.

## Risks

- **Per-team flattening + overlap interaction** (T4): the spec
  doesn't explicitly require re-running overlap detection after
  flattening. The plan adds this defensively. If the re-run rule
  proves wrong (e.g. legitimately running program mode on a portfolio
  that contains program+team detail), revisit and either remove the
  re-run or update the spec.
- **Markdown determinism under Unicode collation** (T7): the spec
  pins codepoint order (`str.__lt__`), not locale. Python defaults
  to codepoint, so this is free — but a future Python change or a
  test environment with non-default `LC_COLLATE` could surface
  divergence. The test suite explicitly sets `LC_ALL=C` for the
  byte-identical-rerun test.
- **JSON `deltas` key order** (T7): the canonical-encoder approach
  requires a small amount of subclassing of `json.JSONEncoder`. The
  fallback is two-pass serialisation (sorted everywhere first, then
  re-order the `deltas` subtree in a post-process). Both are
  acceptable; T7 picks the encoder approach for cleanliness, falls
  back to two-pass if the encoder approach proves brittle.

## Non-goals (this plan only)

- No CI matrix work — spec doesn't require multi-OS testing; CI is
  whatever the surrounding repo already has.
- No integration test against a live Jira instance — the skill
  doesn't talk to Jira.
- No notebook templates for downstream rollup beyond what fits in
  SKILL.md examples.

## Changelog

- 2026-05-19: initial draft.
