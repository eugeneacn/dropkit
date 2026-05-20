# Plan: flow-metrics

- **Spec:** [`docs/specs/flow-metrics.md`](flow-metrics.md)
- **Status:** Approved (ready to execute) <!-- Drafting | Approved | Executing | Done -->
- **Review history:** 3 adversarial review rounds (2026-05-19). Round 1 found 0 blockers / 7 majors / 8 minors; round 2: 0 blockers / 1 major / 8 minors; round 3: 0 blockers / 0 majors / 6 minors (all addressed). Terminal-clean.

> **Plan contract:** this is the implementation strategy. Unlike the spec,
> this document is allowed to change as you learn. When it changes
> substantially (a different approach, not just a re-ordering), note why
> in the changelog at the bottom.

## Approach

Thirteen sequentially-ordered tasks. The first three (T1 scaffold, T2
config + default configs, T3 upstream wrappers) establish the
substrate. T4–T6 build the data pipeline from raw upstream data
through per-issue derivation to aggregation. T7 covers caching of
per-issue rows. T8–T9 add cohort split and Jira Align per-team
rollup. T10 covers output canonicalization (JSON / CSV / per-issue
JSONL). T11 generates `notes` and the `meta` block. T12 packages the
skill (SKILL.md, manifest.json, output.schema.json). T13 wires CI,
integration fixtures, and golden files.

The load-bearing tasks are T4 (changelog pagination — the spec calls out
this Cloud regression explicitly) and T5–T6 (the per-issue → aggregation
pipeline). Caching (T7) gates on T5 only — the cache stores per-issue
derived rows that exist before cohort tagging or aggregation; the spec
explicitly excludes cohort JQL, `--metrics`, and `--include-subtasks`
from the cache key. Cohort split (T8) and per-team rollup (T9) operate
on cached rows.

Implementation is **standalone Python ≥ 3.10, stdlib only in v1**. The
spec allows `numpy.percentile(method="linear")` *or* the equivalent
`statistics.quantiles(..., method="exclusive")`; v1 picks the latter to
avoid a `pip` dependency and the post-install surfacing complexity that
comes with it. If percentile perf becomes a problem at >100k issue scale,
v2 introduces optional `numpy`. No third-party HTTP or Jira clients —
all upstream calls go through the existing dropkit skills via subprocess
(see T3 for the architectural decision the spec defers to this plan).

The spec is uncompromising about correctness invariants — read-only
allowlist, output canonicalization, population predicate consistency. Each
of those gets its own dedicated test surface; the contract tests from the
spec are not optional.

## Architectural decisions deferred to this plan

The spec says "Cross-skill invocation — name, not path" and references "the
IDE's native skill-dispatch mechanism (the Skill tool in Claude Code, the
equivalent elsewhere)." For a Python implementation that processes 10k+
issues, an LLM-mediated dispatch loop per call is impractical. The plan
pins the implementation strategy:

- **Subprocess invocation of the upstream skill's CLI script.** The Python
  CLI locates `<upstream-skill-dir>/scripts/jira.py` (or `jira_align.py`)
  at startup via a discovery probe (see T3), then `subprocess.run`s it for
  each upstream call. The "name, not path" contract is preserved at the
  agent / SKILL.md level — the Python implementation hides the path
  resolution behind a single discovery helper.
- **Discovery probe order:**
  1. `$FLOW_METRICS_JIRA_SCRIPT` env var (testing override).
  2. `<this-skill-dir>/../jira/scripts/jira.py` (sibling install — both
     installed under `~/.claude/skills/` via kit-installer, both under
     `<repo>/skills/integrations/`).
  3. `~/.claude/skills/jira/scripts/jira.py` (user scope).
  4. `<cwd>/.claude/skills/jira/scripts/jira.py` (project scope).
  5. Not found → exit 2 with: `"upstream skill 'jira' not found. Install
     dropkit's jira skill (see <repo URL>). Discovery searched: <paths>."`
- **Allowlist enforcement is wrapper-side.** The upstream CLIs *can* do
  more than the spec allows; flow-metrics' wrapper refuses to call them
  with disallowed verbs / paths. The contract test
  `test_only_allowlisted_jira_verbs_invoked` verifies via a wrapper that
  records calls.
- **Credentials remain with the upstream skill.** flow-metrics never reads
  `~/.config/dropkit/credentials.env`. Upstream auth failures (exit 2 from
  the wrapped CLI) propagate as flow-metrics exit 3, per spec.

## Constraints

No ADRs exist in dropkit yet. The decisions recorded in the spec's
"Decisions" section govern all ambiguous cases. The most binding for
implementation:

- Python floor 3.10 (`match` statement, `zoneinfo`).
- UTC throughout; window is `[from 00:00, (to + 1day) 00:00)`.
- Read-only allowlist is **exact-pattern**, not prefix. `raw GET` paths are
  validated by regex at the wrapper layer (not after the call).
- State-config / issuetype-config sha is
  `sha256(json.dumps(parsed, sort_keys=True, separators=(",",":")).encode())`.
- Cache key includes only fields that affect the fetched data; cohort JQL,
  `--metrics`, `--include-subtasks` are aggregation-only.
- Output canonicalization rules (sorted keys codepoint, 4-dp via
  `json.dumps(round(x,4))`, fixed bucket order in `flow_distribution`,
  `notes` sorted lexicographically) are part of the contract.
- Per-issue rows for non-delivered issues emit `null` for delivery fields;
  `rework_count` is `0`, not `null`.

## Construction tests

Cross-cutting tests spanning multiple tasks. Per-task tests are listed
under each Task below.

**Integration tests:**

- `test_full_happy_path_project_scope` — fixture: a recorded fixture of
  jira responses (issues + per-issue changelog pagination) under
  `tests/fixtures/proj_alpha/`. Run end-to-end:
  `flow-metrics --project ALPHA --from 2026-01-01 --to 2026-03-31`. Assert
  the resulting JSON matches a checked-in golden file byte-for-byte (after
  `generated_at` normalization). The fixture covers: 50 delivered (10
  cancelled, 5 sub-tasks, 8 with rework, 4 with skipped commitment, 3 with
  >100 changelog entries, 2 with mid-flight issuetype change).
- `test_full_happy_path_program_scope` — fixture for `--program-id 42`;
  asserts Jira Align is called for team enumeration, Jira for issue data,
  and `per_team` rows reconcile.
- `test_full_happy_path_cohort_split` — same fixture, `--cohort-jql
  "labels = ai-assisted"`; assert `cohort_breakdown.cohort.throughput +
  cohort_breakdown.control.throughput == aggregates.throughput`, and that
  cohort metrics match a hand-computed reference.
- `test_full_happy_path_per_issue` — `--per-issue --output rows.jsonl`;
  assert N lines = (delivered + cancelled + wip-only) counts; null fields
  match the spec contract for non-delivered rows; line order is by key
  ascending.

**Manual verification gate** (before tagging):

- Run against one real team's project for the last 90 days. Sanity-check
  the numbers against the team's own dashboard (LinearB / Jellyfish / Jira
  built-in) — they won't match exactly (different state mappings) but the
  shape (throughput ±10%, cycle time same order of magnitude) must agree.

## Tasks

### T1: Scaffold — CLI, argparse, Python version guard, exit codes

**Depends on:** none

**Tests:**

- `test_python_below_floor_exits_2` (contract) — Python 3.9 startup exits
  2; tested via mocked `sys.version_info`.
- `test_help_exits_0` — `--help` exits 0 and lists every flag from the
  spec's Inputs table.
- `test_requires_exactly_one_scope` (contract) — no `--project /
  --program-id / --portfolio-id` → exit 2. Two of them → exit 2.
- `test_team_only_valid_with_project` (contract) — `--team Foo
  --program-id 42` → exit 2.
- `test_per_issue_requires_output_flag` (contract) — `--per-issue` without
  `--output` → exit 2.
- `test_unknown_flag_exits_2` — `--bogus` → exit 2.
- `test_default_window_is_last_90_days_utc` (contract) — without
  `--from`/`--to`, the resolved window in `meta.window.from` =
  `today_utc - 90 days`, `meta.window.to` = `today_utc`. (Stubs the
  upstream calls to return empty; just verifies window resolution and
  serialization in meta.)
- `test_to_is_inclusive_of_named_day` (contract) — verified at unit
  level via the window-parsing helper: `--from 2026-04-30 --to
  2026-05-19` resolves to `[2026-04-30 00:00 UTC, 2026-05-20 00:00
  UTC)`. Spec inclusivity: `--from` resolves to `from 00:00 UTC`,
  `--to` resolves to `(to + 1 day) 00:00 UTC` (exclusive).
- `test_validation_error_exits_2_before_any_upstream_call` (contract)
  — a flag-combo validation error (e.g. two scope flags) exits 2 with
  zero upstream invocations recorded.
- `test_rejects_output_in_etc` (contract) — `--output /etc/foo` (or
  `C:\Windows\foo`) exits 2 before any data fetch.
- `test_rejects_output_with_null_byte` (contract) — `--output
  "ok\x00bad"` exits 2.
- `test_rejects_state_config_in_proc` (contract) — `--state-config
  /proc/self/maps` exits 2.
- `test_overwrite_aborts_without_tty` (contract) — `--output
  EXISTING` with no TTY and no `--yes` exits 1 without writing. (T10
  ships the actual write path; T1 ships the prompt + TTY-detection
  helper that this test exercises via a stub.)

**Approach:**

- Create `skills/workflows/flow-metrics/scripts/flow_metrics.py` as the
  CLI entry point. Mirrors the sibling skill layout
  (`scripts/jira.py`, `scripts/jira_align.py`).
- Version check at module top: `sys.version_info < (3, 10)` → stderr +
  `sys.exit(2)`.
- `build_parser()` configures all flags from the spec's Inputs table.
- Mutex groups: scope (`--project`/`--program-id`/`--portfolio-id`).
- `parse_window(args) -> (datetime_utc, datetime_utc)` resolves
  inclusive-of-named-day semantics; UTC throughout. Default: last 90
  days ending today (UTC).
- Stub every command path: print "not yet implemented" + exit 0. Later
  tasks fill these in.
- `if __name__ == "__main__": main()` guard.

**Done when:** all listed tests green on Python 3.10, 3.11, 3.12.

---

### T2: Config loading + default configs ship — state + issuetype + integrity validation

**Depends on:** T1

**Files shipped in this task (in addition to code):**

- `skills/workflows/flow-metrics/references/states.default.json` —
  exact JSON from the spec's State configuration example, including
  the `cancelled` canonical state, `wait_states: [backlog, in_review,
  in_test]`, and the four-row default `rework_signals`.
- `skills/workflows/flow-metrics/references/issuetypes.default.json` —
  five buckets (`feature/defect/debt/risk/subtask`); maps the
  conventional Jira issuetype names per the spec.

These files are part of the substrate that T2's contract tests
validate; T12 (packaging) only adds SKILL.md, manifest.json, and the
output schema.

**Tests (contract tests from spec):**

- `test_default_state_config_loads_at_install_path` — without
  `--state-config`, loads from `__file__`-relative path
  (`references/states.default.json`).
- `test_default_state_config_loads_from_clone_path` — same when run from
  a dropkit clone layout.
- `test_state_config_sha_canonicalized` — three files with same parsed
  JSON but different whitespace / key order produce identical sha; a
  semantic change produces a different sha.
- `test_unmapped_status_exits_2` — at validate-data step (after fetch),
  status `"Blocked"` not in `canonical_states` → exit 2 naming the
  status.
- `test_commitment_equals_delivery_exits_2` — startup exit.
- `test_active_intersects_wait_exits_2` — startup exit.
- `test_delivery_in_active_states_exits_2` — startup exit.
- `test_commitment_in_terminal_non_delivery_exits_2` — startup exit.
- `test_rework_signals_reference_unknown_canonical_exits_2` — startup
  exit.
- `test_delivery_overlapping_cancelled_exits_2` — startup exit.
- `test_unknown_team_field_id_exits_2` (contract) — `team_field.id =
  customfield_99999` not present in Jira's field catalog (mocked
  `jira: raw GET field` returns a list without it) → exit 2 naming
  the id. Test depends on the T3 wrapper. To allow T2 to ship before
  T3 is landed, the test is decorated with
  `@pytest.mark.skipif(not _has_t3(), reason="requires T3 upstream
  wrapper")` and re-enables automatically once T3 lands.
- `test_team_field_override_validated_not_config` (contract) — when
  `--team-field-override customfield_88888` is passed AND the config
  has a valid `team_field.id` but `customfield_88888` is unknown, the
  skill exits 2 naming `customfield_88888` (the override is what's
  validated; the config value is ignored that run). Same `skipif`
  gating as above.

**Construction tests:**

- `test_state_config_resolution_walks_up` — implementation walks up from
  `__file__` until a sibling `references/` is found. Verified by
  symlinking the script under `scripts/scripts/` and confirming the
  walk reaches the skill root.
- `test_canonical_state_lookup_indexed` — building the
  raw-status→canonical lookup is O(1) per query; the dataclass exposes
  a `canonical_for(raw_status) -> Optional[str]` method.
- `test_user_picker_group_kind_rejected` — state config with
  `team_field.kind: "user_picker_group"` exits 2 (round-3 decision:
  deferred to v2).

**Approach:**

- `flow_metrics/config.py`:
  - `@dataclass StateConfig`: canonical_states (Dict[str,
    FrozenSet[str]]), active_states, wait_states,
    terminal_non_delivery_states, rework_signals (List[ReworkSignal]),
    commitment_state, delivery_state, team_field, sha (str),
    align_join_field (Optional[str]).
  - `load_state_config(path: Optional[Path]) -> StateConfig` — resolves
    default if path is None; parses JSON; runs `validate_state_config`;
    computes sha.
  - `validate_state_config(parsed: dict)` — implements the 9 startup
    checks from the spec's State configuration section (1-9). Raises
    `ConfigError(msg, exit_code=2)` on any violation.
  - `IssuetypeConfig` analogous, simpler.
- The data-dependent unmapped-status check is NOT here — it runs in T5
  (per-issue derivation) once the changelog data is in hand.
- sha derivation:
  `sha256(json.dumps(parsed, sort_keys=True, separators=(",",":")).encode()).hexdigest()`.

**Done when:** all listed tests green; running with the shipped default
config produces a valid `StateConfig` with non-empty sha.

---

### T3: Upstream skill wrappers — discovery, allowlist, subprocess

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_only_allowlisted_jira_verbs_invoked` (contract) — the wrapper
  rejects any verb / path not in the allowlist, before any
  `subprocess.run`. Test asserts: trying to call `jira_call("transition",
  ...)` raises `AllowlistError`; trying `jira_raw_get("dashboard")`
  raises; `jira_raw_get("project/PROJ/components")` raises;
  `jira_raw_get("field")` succeeds (subprocess mocked).
- `test_only_allowlisted_jira_align_verbs_invoked` (contract) — same
  shape for jira-align: only `raw GET` with paths matching exactly one
  of the four allowed patterns is invoked.
- `test_raw_get_outside_allowed_patterns_blocked` (contract) — every
  forbidden path from the spec test list raises `AllowlistError`.
- `test_attach_never_invoked` (contract) — no code path calls `attach`.
- `test_upstream_jira_failure_exits_3` (contract) — subprocess returns
  non-zero; `JiraError` raised; caught in main → exit 3; stderr relayed.

**Construction tests:**

- `test_discovery_probes_in_order` — patch each candidate path; assert
  the wrapper picks the first hit (env var > sibling > user-scope >
  project-scope).
- `test_discovery_not_found_exits_2` — none of the candidates exist;
  exit 2 with the discovery message naming each tried path.
- `test_jira_call_args_quoting` — args with spaces / quotes are passed
  via list-form `subprocess.run([argv])` / `subprocess.Popen([argv])`,
  never via `shell=True`.
- `test_jira_call_does_not_read_credentials_file` — flow-metrics' own
  process never opens `~/.config/dropkit/credentials.env`; verified by
  monkeypatching `builtins.open` to record every path opened during a
  full run. Credential access happens inside the upstream subprocess,
  not in flow-metrics. The subprocess env is forwarded unfiltered so
  the upstream skill can find its config (`HOME` and friends).
- `test_search_streams_via_popen_not_run` — `JiraClient.search()` uses
  `subprocess.Popen` (verified by monkeypatching both `subprocess.run`
  and `subprocess.Popen` and asserting only `Popen` was called for
  search). A 10k-row mock stream is consumed without peak memory
  exceeding O(one row).
- `test_search_yields_one_dict_per_line` — given a mock subprocess
  whose stdout is `{"key":"A-1"}\n{"key":"A-2"}\n`, the iterator
  yields exactly two dicts in order.
- `test_no_subprocess_calls_outside_upstream_module` — static AST scan
  of `flow_metrics/` tree fails if any file outside
  `flow_metrics/upstream.py` imports `subprocess` or calls
  `subprocess.*`. Prevents future code from bypassing the allowlist
  wrapper.

**Approach:**

- `flow_metrics/upstream.py`:
  - `discover_skill_path(name: str) -> Path` — implements the 4-step
    probe.
  - `class JiraClient`:
    - Constructor takes the discovered script path.
    - Methods one per allowlisted verb: `check()`, `whoami()`,
      `get_issue(key, fields, expand)`, `search(jql, fields, expand,
      page_size)` (streaming), `get_project(key)`, `raw_get(path,
      params)`.
    - `raw_get` validates the path against three regex patterns; raises
      `AllowlistError` on miss. Patterns:
      - `r"^field$"`
      - `r"^project/[A-Z][A-Z0-9_]+/statuses$"`
      - `r"^issue/[A-Z][A-Z0-9_]+-[0-9]+/changelog$"`
    - **Non-streaming verbs** (`check`, `whoami`, `get_issue`,
      `get_project`, `raw_get`) use
      `subprocess.run(argv, capture_output=True, check=False)`.
      Non-zero → `JiraError(returncode, stderr)`.
    - **Streaming verb `search`** uses `subprocess.Popen` with
      `stdout=PIPE, stderr=PIPE`, args including `--format jsonl
      --output -`. Yields one parsed dict per line via
      `for line in proc.stdout: yield json.loads(line)`. On EOF, calls
      `proc.wait()`; non-zero → drains `proc.stderr` and raises
      `JiraError`. **Never** `subprocess.run(capture_output=True)` for
      `search` — that would buffer all output and defeat the
      bounded-memory streaming contract.
  - `class JiraAlignClient`: same shape; only `raw_get` exposed, with
    four regex patterns from the spec.
- Streaming: `search()` uses `--format jsonl --output -` and yields one
  parsed dict at a time. Memory bounded.
- `--insecure` is NOT forwarded by flow-metrics; users who need it run
  their own upstream-skill `setup_credentials.sh` against an `--insecure`
  base.

**Done when:** all listed tests green; an integration smoke test against
mocked upstream scripts (returning small canned JSON) succeeds.

---

### T4: Per-issue changelog pagination

**Depends on:** T3

**Tests (contract tests from spec):**

- `test_changelog_pagination_drained` — fixture: issue with 150
  transitions, 50 inline + 100 behind `isLast: false`. The wrapper
  issues a follow-up `raw GET issue/PROJ-1/changelog?startAt=50`; the
  resulting `first_in_progress` matches the earliest of all 150, not
  the inline 50.
- `test_no_follow_up_when_changelog_complete` — fixture: 10 inline
  entries, `isLast: true` → no follow-up call (verified by call
  counter).

**Construction tests:**

- `test_changelog_pagination_cloud_format` — Cloud `isLast` /
  `nextPageToken` shape; verifies the wrapper detects and paginates.
- `test_changelog_pagination_server_format` — Server `total` vs
  `histories.length` mismatch; verifies the wrapper detects and
  paginates with `startAt`.
- `test_changelog_pagination_memory_bounded` — issue with 5000
  transitions; peak memory during the walk stays under O(transitions
  per issue), verified by tracking the live-object count after each
  page is processed.
- `test_changelog_pagination_handles_empty_histories` — issue with no
  changelog entries → empty list returned, not None.

**Approach:**

- `flow_metrics/changelog.py`:
  - `def iter_issue_changelog(jira: JiraClient, issue_key: str,
    inline: list[dict]) -> Iterator[ChangelogEntry]`:
    - Yield each entry from `inline`.
    - Detect "more pages" via the three signals from the spec (in
      priority order: Server `total`/`histories.length`, Cloud
      `isLast == False`, Cloud `nextPageToken`).
    - Drain remaining via `jira.raw_get(f"issue/{key}/changelog", ...)`
      until `isLast` or `histories.length` exhausted.
- `ChangelogEntry` dataclass: `timestamp: datetime`, `author: str`,
  `field: str` ("status" | "issuetype"), `from_value: str`, `to_value:
  str`.
- The walker normalizes both Cloud and Server response shapes into the
  same dataclass; downstream consumers never branch on flavour.

**Done when:** all listed tests green.

---

### T5: Per-issue derivation — timeline walk, canonical states, population predicates, per-issue fields

**Depends on:** T2, T3, T4

**Tests (contract tests from spec):**

- `test_cycle_time_first_commitment_to_first_delivery` — fixture issue
  `Backlog → In Progress (t1) → Done (t2)`; per-issue row has
  `cycle_time_hours == (t2 - t1) / 3600` and `cycle_eligible: true`.
- `test_cycle_time_excludes_skipped_commitment` — `Backlog → Done` →
  `cycle_eligible: false`, `cycle_time_hours: null`.
- `test_cycle_time_excludes_issue_delivered_after_to` (contract) —
  issue with first-ever delivery at `--to + 1 hour` → not
  delivered-in-window; per-issue row absent (issue not in scope) and
  aggregate `cycle_time_hours.n` does not include it.
- `test_lead_time_uses_created_to_first_delivery`.
- `test_throughput_first_ever_delivery_in_window` — issue delivered
  before window then redelivered in window → `delivered_in_window:
  false`.
- `test_throughput_reopen_in_window_doesnt_double_count`.
- `test_wip_at_to_inclusive` — issue in `In Progress` at WIP-instant →
  `wip_at_to: true`, `delivered_in_window: false`. Issue in `In Review`
  (default config: wait_state) at WIP-instant → `wip_at_to: false`.
- `test_rework_counts_distinct_backward_edges`.
- `test_rework_pre_delivery_only`.
- `test_default_rework_signals_cover_in_progress_to_backlog`.
- `test_default_rework_signals_cover_in_test_to_in_review`.
- `test_flow_efficiency_active_over_total`.
- `test_flow_efficiency_uses_commitment_to_delivery_interval` —
  `[t1, t3]` interval; pre-commitment time excluded.
- `test_flow_efficiency_ignores_time_before_first_commitment` —
  non-default config where commitment isn't an active state; verifies
  the interval boundary, not the active partition.
- `test_flow_efficiency_done_time_excluded` — `done` in neither
  partition; contributes zero.
- `test_flow_efficiency_zero_denominator_excluded` — `null`
  `flow_efficiency` value; recorded in notes by T11.
- `test_flow_efficiency_default_config_non_degenerate` — realistic
  fixture: 4h in_progress / 16h in_review / 8h in_progress / 4h in_test
  / done. Default config (active=[in_progress], wait=[backlog, in_review,
  in_test]). `flow_efficiency == 12/32 == 0.375`.
- `test_issuetype_at_delivery_used_for_distribution` — issuetype changed
  Story → Bug 1h before delivery; per-issue
  `issuetype_at_delivery: "Bug"`, `issuetype_bucket: "defect"`.
- `test_cancelled_excluded_from_throughput`.
- `test_cancelled_then_reopened_still_cancelled_in_window` —
  `cancelled_in_window: true`, `delivered_in_window: false`,
  `wip_at_to: true` (state at WIP-instant is active).
- `test_subtask_excluded_by_default`.
- `test_subtask_included_with_flag`.
- `test_cycle_time_n_can_differ_from_throughput`.

**Construction tests:**

- `test_unmapped_status_exits_2_at_walk_time` — when the timeline
  walker encounters a raw status not in `canonical_states`, exit 2
  naming the status (data-dependent, not startup).
- `test_status_renamed_mid_window` — both old and new raw names appear
  in the changelog; both must be mapped; if only one is, exit 2.
- `test_per_issue_row_field_shape` — for a delivered row: every field
  in the spec's per-issue example is present and typed correctly
  (`cycle_time_hours: float`, `delivered_in_window: bool`, etc.).
- `test_per_issue_non_delivered_emits_nulls`.
- `test_per_issue_wip_only_emits_nulls`.
- `test_search_jql_ends_with_order_by_key_asc` — every `jira: search`
  invocation emitted by T5 (and by the cohort resolution in T8) has
  JQL ending in `" ORDER BY key ASC"`. Verified via the upstream
  wrapper's recorded calls. Required by spec output canonicalization
  rule 4 for reproducible iteration order. T5 emits the suffix
  inline; T8 extracts the `compose_jql` helper that centralizes the
  suffix once cohort joins the picture.

**Approach:**

- `flow_metrics/timeline.py`:
  - `class Timeline`: built per-issue from changelog + issue
    `created`/`status`/`issuetype` baseline. Methods:
    - `first_canonical_transition_into(canonical_name)` → datetime |
      None.
    - `state_at(instant)` → canonical_name (uses the issue's `created`
      → initial-status mapping + walk).
    - `time_in(canonical_name, interval)` → timedelta.
    - `backward_edges(rework_signals)` → List[(timestamp, from_canon,
      to_canon)].
    - `issuetype_at(instant)` → str.
- `flow_metrics/predicates.py`:
  - `delivered_in_window(timeline, window) -> bool`.
  - `cycle_eligible(timeline, window) -> bool`.
  - `cancelled_in_window(timeline, window) -> bool`.
  - `wip_at_to(timeline, window) -> bool`.
- `flow_metrics/per_issue.py`:
  - `def derive_row(issue, timeline, config, window) -> PerIssueRow`.
- `PerIssueRow` dataclass: every field from the spec's per-issue
  example, typed and nullable where the spec specifies null for
  non-delivered.

**Done when:** all listed tests green; running against the integration
fixture produces per-issue rows matching the golden file.

---

### T6: Aggregation — percentiles, throughput, WIP, flow_load, flow_distribution, defect_ratio, rework_rate, flow_efficiency

**Depends on:** T5

**Tests (contract tests from spec):**

- `test_flow_load_includes_both_endpoints` — window
  `[2026-01-01, 2026-01-05]` → 5 samples, each at `(d+1 day) 00:00 UTC
  - 1µs`.
- `test_flow_load_weekend_inclusion_recorded` — `notes` mentions
  sample count and weekend policy.
- `test_flow_distribution_sums_to_one`.
- `test_flow_distribution_denominator_includes_subtasks` — fixture: 80
  non-subtask + 20 subtask. Default (`--include-subtasks=false`):
  `throughput == 80`, `denominator == 100`, `subtask > 0`. With flag:
  `throughput == 100`, `denominator == 100`.
- `test_defect_ratio_equals_flow_distribution_defect`.
- `test_rework_rate_null_on_zero_throughput`.
- `test_flow_time_alias_equals_lead_time`.
- `test_percentile_computed_at_full_precision` — verifies `round` is
  called exactly once per percentile per metric (via monkey-patching).

**Construction tests:**

- `test_percentile_method_exclusive` — fixture: 4 cycle-eligible
  values `[10, 20, 30, 40]`. p50 via
  `statistics.quantiles([10, 20, 30, 40], n=100, method="exclusive")[49]`
  = `25.0`. The test also asserts byte-equality against the canonical
  fixture's hand-computed p75 (32.5) and p90 (39.0).
- `test_percentile_p75_and_p90_consistent` — p75 ≥ p50, p90 ≥ p75 (sanity).
- `test_throughput_excludes_cancelled`.
- `test_throughput_excludes_subtask_by_default`.
- `test_wip_excludes_cancelled_when_no_reopen` — issue cancelled
  in-window and still cancelled at WIP-instant → `wip == 0`,
  `cancelled count == 1`.
- `test_wip_includes_cancelled_then_reopened` — issue cancelled
  in-window then reopened to in_progress → `wip == 1`,
  `cancelled count == 1`.
- `test_flow_load_sample_count_matches_inclusive_day_count` — uses the
  spec's own contract-test fixture: window `[2026-01-01, 2026-01-05]`
  produces exactly 5 samples (one per calendar day Jan 1, 2, 3, 4, 5,
  each at `(d + 1 day) 00:00 UTC - 1 microsecond`). A
  `--from 2026-01-01 --to 2026-04-01` window (where `to − from = 90
  days`) produces 91 samples (Jan 1 through Apr 1 inclusive). This
  matches the spec's example "90-day window produces 91 samples" —
  "90 days" referring to `to − from` difference, not inclusive-day
  count.
- `test_aggregate_n_per_metric` — fixture: 5 delivered, 1 skipped
  commitment, 1 zero-denominator flow_eff exclusion. `throughput == 5`,
  `cycle_time.n == 4`, `flow_efficiency.n == 3`, `lead_time.n == 5`.
- `test_aggregation_does_not_buffer_full_row_list` — fixture: 10k
  synthetic delivered-in-window issues fed via an iterator (live from
  T5 or replayed from T7's cached `.jsonl`). Aggregation consumes the
  iterator exactly once without materializing the full list in
  memory; verified by tracking peak live-object count during the run.

**Approach:**

- `flow_metrics/aggregate.py`:
  - `def aggregate(rows: Iterator[PerIssueRow], window: Window, config:
    StateConfig) -> AggregateBlock` — consumes the iterator **exactly
    once** in a single pass. Per-metric float lists accumulate as rows
    stream through; counters update for scalars; at end-of-stream,
    percentiles are computed on the float lists.
  - Percentiles: stdlib only in v1 —
    `statistics.quantiles(values, n=100, method="exclusive")` and
    pick indices 49 / 74 / 89 for p50 / p75 / p90 (zero-based).
    Stdlib's `method="exclusive"` is the spec's named equivalent of
    `numpy.percentile(method="linear")`; the two interpolations
    diverge slightly at boundary indices, which is why the spec pins
    one named algorithm (and v1 picks `statistics`) rather than
    asserting cross-implementation numerical equality. Run on
    full-precision floats; do not round inputs.
  - WIP and Flow Load both sample at `(d+1 day) 00:00 UTC - 1µs` for the
    relevant day. Flow Load: `mean([wip_at(d) for d in days_in_window])`.
  - Rework Rate: numerator / denominator; numerator = sum of per-issue
    `rework_count` for delivered-in-window rows; denominator =
    throughput. `null` if throughput == 0.
- `AggregateBlock` is a flat dataclass with one field per metric; the
  serializer (T10) filters to `--metrics` requested.

**Done when:** all listed tests green; running against the integration
fixture produces an aggregate matching the golden file.

---

### T7: Caching — atomic write, key derivation, partial-cache cleanup

**Depends on:** T2 (cache key includes state-config and issuetype-config
sha values), T5 (cache stores per-issue derived rows produced in T5;
cohort tagging and aggregation operate over cached rows downstream)

**Tests (contract tests from spec):**

- `test_cache_hit_skips_upstream_calls`.
- `test_cache_invalidated_on_state_config_semantic_change`.
- `test_cache_stable_under_whitespace_edits`.
- `test_no_cache_bypasses_cache`.
- `test_partial_cache_discarded_on_upstream_failure`.
- `test_cohort_jql_not_in_cache_key`.
- `test_metrics_not_in_cache_key`.
- `test_include_subtasks_not_in_cache_key`.
- `test_align_fields_null_in_cache_key_for_project_scope`.
- `test_align_fields_in_cache_key_for_program_scope`.

**Construction tests:**

- `test_cache_key_canonical_json` — two cache-key dicts that differ
  only in key insertion order produce the same sha. Asserts
  `sort_keys=True, separators=(",",":")` are used.
- `test_cache_dir_mode_0700` — directory created with mode 0700 on
  Unix.
- `test_stale_tmp_cleaned_on_startup` — `.tmp` file older than 1 hour
  in the cache dir is removed at startup. Cleanup glob is `*.tmp`
  (matches both `<key>.jsonl.tmp` and `<key>.jsonl.<pid>.tmp`).
- `test_concurrent_writes_tolerated` — two simultaneous runs with the
  same cache key both succeed; final cache content is identical to
  both runs' outputs (which are identical by construction).

**Approach:**

- `flow_metrics/cache.py`:
  - `def cache_key(scope, window, user_jql, user_align_filter,
    state_config_sha, issuetype_config_sha, team_field_override,
    align_join_field, align_teams_path) -> str` — builds the dict
    exactly as the spec specifies, conditionally nulling
    `align_join_field` / `align_teams_path` for project-scope, then
    `sha256(canonical_json).hexdigest()`.
  - `def read_cache(cache_dir: Path, key: str) -> Optional[Iterator[PerIssueRow]]`
    — returns a streaming reader if `<key>.jsonl` exists; None otherwise.
  - `def write_cache_tee(cache_dir: Path, key: str, source: Iterator[PerIssueRow])
    -> Iterator[PerIssueRow]` — wraps the source iterator with a tee
    that writes each row to `<key>.jsonl.<pid>.tmp` as it passes through.
    On full drain, `os.replace` the tmp to `<key>.jsonl`. On any
    exception, leave the tmp behind (cleanup at next startup) and
    re-raise.
  - `def cleanup_stale_tmps(cache_dir: Path)` — at startup, remove any
    `*.tmp` file with mtime > 1h old.

**Done when:** all listed tests green.

---

### T8: Cohort split — `--cohort-jql` resolution + `cohort_breakdown`

**Depends on:** T6 (aggregator) and T7 (cache; cohort tags are applied
to cached per-issue rows)

**Tests (contract tests from spec):**

- `test_cohort_split_disjoint`.
- `test_empty_cohort_does_not_exit_nonzero`.
- `test_cohort_aggregates_match_subset`.
- `test_cohort_rework_rate_denominator_is_cohort_throughput`.
- `test_per_issue_omits_cohort_breakdown`.
- `test_meta_cohort_jql_omitted_when_absent`.
- `test_cohort_jql_user_clause_parenthesized` — combines with scope as
  `(<scope>) AND (<cohort_jql>)`.
- `test_jql_user_clause_parenthesized`.
- `test_align_filter_user_clause_parenthesized`.

**Construction tests:**

- `test_cohort_resolution_one_query` — cohort issue set is fetched
  exactly once (one `jira: search` call with the composed cohort
  JQL); per-issue rows are tagged from the resulting key set in
  memory.
- `test_cohort_breakdown_flow_distribution_cohort_restricted` —
  cohort's `flow_distribution.denominator` = delivered-in-window
  cohort issues (incl subtasks).

**Approach:**

- `flow_metrics/cohort.py`:
  - `def resolve_cohort_keys(jira: JiraClient, cohort_jql: str,
    scope: JqlClause) -> Set[str]` — issues a single `jira.search`
    with the composed `(scope) AND (cohort_jql) ORDER BY key ASC`,
    returns the key set. (No window clause: cohort membership is
    intersected against the main fetch's in-scope rows at tagging
    time, not at JQL time, per spec.)
  - After per-issue derivation (T5) or cache read (T7), tag each row's
    `cohort: bool` by membership in the resolved set.
  - `def aggregate_cohort(rows: Iterator[PerIssueRow], cohort: bool,
    config: StateConfig, window: Window) -> AggregateBlock` — filters
    rows by `cohort` and runs the T6 aggregator on the subset.
- JQL composition helper: `compose_jql(scope, user, *, order_by_key:
  bool = True) -> str` returns `f"({scope}) AND ({user})"` if user
  non-empty (else `scope`), then appends `" ORDER BY key ASC"` if
  `order_by_key`. Same helper used for scope JQL, cohort JQL, and any
  composed query — the `ORDER BY key ASC` suffix is the canonical
  iteration-order anchor required by the spec's output stability
  contract.

**Done when:** all listed tests green.

---

### T9: Jira Align integration + `per_team` rollup

**Depends on:** T3, T5, T6, T7

**Tests (contract tests from spec):**

- `test_jira_only_run_does_not_call_jira_align`.
- `test_program_scope_uses_raw_get_teams_path`.
- `test_program_scope_teams_intersected_via_jira_team_field`.
- `test_missing_align_join_field_exits_2`.
- `test_align_teams_path_rejects_traversal`.
- `test_align_teams_path_validates_response_shape`.
- `test_per_team_array_kind_double_count_flagged`.
- `test_per_team_single_value_kind_sums_to_throughput`.
- `test_per_team_sort_uses_codepoint_order` — Unicode team names sort
  by codepoint, not locale.
- `test_meta_sources_reflects_skills_called`.

**Construction tests:**

- `test_program_scope_passes_team_field_to_jira_jql` — generated JQL
  has the form `"<team_field.id>" in (<team_a>, <team_b>, ...) ORDER
  BY key ASC` (no `project = ...` clause; one Jira ↔ one Jira Align
  instance pair is assumed in v1).
- `test_program_scope_jql_has_no_project_clause` — explicit anti-test
  for the above: the composed JQL does NOT contain `project = ...`.
- `test_portfolio_scope_walks_programs_then_teams` — call sequence:
  `portfolios/<id>/programs` → for each, `programs/<pid>/teams` →
  then Jira JQL with all team IDs.
- `test_align_teams_path_override_validated_as_exact_pattern` — an
  override of `programs/42/features` is rejected at startup (not at
  call-time) because it's not one of the four allowed patterns.
- `test_field_level_permission_undercount_recorded` — fixture with
  one issue whose `team_field` returns null; the issue goes into a
  synthetic `(no team)` per_team row; `notes` records the count.

**Approach:**

- `flow_metrics/align.py`:
  - `def resolve_teams(align: JiraAlignClient, scope: AlignScope) ->
    list[Team]` — handles `program-id` (one `raw_get
    programs/<id>/teams`) and `portfolio-id` (walk programs first,
    then teams per program). Validates response shape — every element
    has `id`; else `UpstreamError` → exit 3.
- `flow_metrics/per_team.py`:
  - `def bucket_by_team(rows: Iterator[PerIssueRow], team_field:
    TeamFieldConfig) -> dict[str, list[PerIssueRow]]` — handles
    `single_value` and `array` kinds. Returns a `"(no team)"` bucket
    for issues whose `team_field` is null / missing (note: rows must
    be materialized per-bucket for aggregation; the iterator is
    consumed once).
  - `def per_team_rollup(buckets, config, window) -> list[PerTeamRow]`
    — sorts by team name (codepoint order).
- `meta.per_team_double_counted` is set to `true` iff `team_field.kind
  == "array"`. Set in T11 (output rendering).

**Done when:** all listed tests green.

---

### T10: Output rendering — JSON canonicalization, CSV long-form, per-issue JSONL

**Depends on:** T6, T7, T8, T9 (renders `per_team` rows produced by T9)

**Tests (contract tests from spec):**

- `test_stable_output_for_same_inputs`.
- `test_per_team_sort_uses_codepoint_order` (overlap with T9 — covered
  fully here on the serialization side).
- `test_notes_sorted_lexicographically`.
- `test_per_issue_emits_jsonl_sorted_by_key`.
- `test_csv_long_form_columns`.
- `test_metrics_filter_omits_unrequested`.
- `test_flow_distribution_and_defect_ratio_independent`.

**Construction tests:**

- `test_json_keys_sorted_at_every_level_except_bucket_maps` —
  recursive descent into the output; every dict's keys are in
  codepoint order **except** for the explicitly named bucket-order
  maps: `aggregates.flow_distribution`,
  `cohort_breakdown.cohort.flow_distribution`,
  `cohort_breakdown.control.flow_distribution`, and the analogous
  per-team copies. Those follow the fixed canonical bucket order
  (`feature, defect, debt, risk, subtask, other, denominator`).
- `test_floats_rounded_to_4dp` — every float in the output, after
  `json.dumps`, matches `^-?\d+(\.\d{1,4})?$`. No `38.20000` artifacts.
- `test_integer_counts_no_decimal_point` — `throughput`, `n`, `wip`,
  `flow_distribution.denominator` serialize without a `.0`.
- `test_flow_distribution_bucket_order_not_lexicographic` — output
  shows `feature, defect, debt, risk, subtask, other, denominator` in
  that order (canonical, not lexicographic).
- `test_meta_metrics_requested_canonical_order` — order matches
  spec's `--metrics` enumeration.
- `test_meta_sources_sorted_lexicographic` — `["jira", "jira-align"]`.
- `test_csv_scalar_metrics_leave_p75_p90_blank` — throughput row has
  `p50=84` and `p75`, `p90` blank.

**Approach:**

- `flow_metrics/output.py`:
  - `def render_json(report: Report) -> bytes` — builds the dict in
    the canonical shape, applies `--metrics` filtering, pre-walks the
    dict to replace every `float` with `round(x, 4)`, then emits
    bytes via a custom recursive serializer. (`json.dumps`'s
    `default=` hook does not fire on floats — only on types it
    doesn't know — so float rounding must happen before serialization,
    not via a hook.) Tested by `test_floats_rounded_to_4dp`.
  - The recursive serializer sorts dict keys in codepoint order at
    every level **except** the bucket-order maps
    (`flow_distribution` and its cohort / per-team copies). For those,
    the serializer emits the canonical bucket order (`feature, defect,
    debt, risk, subtask, other, denominator`) regardless of insertion
    order. Lists are serialized in input order; the caller is
    responsible for pre-sorting lists that need a canonical order
    (`per_team` by team name; `meta.sources` lexicographic;
    `meta.metrics_requested` in spec-canonical order).
  - `def render_csv(report: Report) -> bytes` — long-form, header
    row, one row per (metric, scope, cohort, team) tuple.
  - `def render_jsonl(rows: Iterator[PerIssueRow]) -> Iterator[bytes]`
    — same canonicalization rules per row; sorted by `key` ascending
    (codepoint).

**Done when:** all listed tests green.

---

### T11: Notes generation + `meta` block

**Depends on:** T3 (`jira.whoami()` populates `meta.caller`), T5
(population predicates increment `NotesCollector` exclusion counters),
T6 (aggregator increments zero-denominator and unmapped-issuetype
counters), T8 (cohort emits its own notes for empty-cohort etc.), T9
(per-team double-count and field-permission notes), T10 (T11 produces
the unsorted `notes` list and feeds it to T10's renderer, which sorts
on emit — T10 owns the wire format)

**Tests (contract tests from spec):**

- `test_caller_in_meta_cloud`.
- `test_caller_in_meta_server`.
- `test_caller_unrecognized_whoami_exits_3`.
- `test_permission_undercount_recorded_in_notes`.
- `test_notes_sorted_lexicographically` (overlap with T10).

**Construction tests:**

- `test_notes_include_window_edge_count` — `notes` says "N issues
  entered in-progress before window start".
- `test_notes_include_unmapped_issuetype_count` — `notes` says "N
  issues had unmapped issuetype 'X'; bucketed as 'other'".
- `test_notes_include_skipped_commitment_count`.
- `test_notes_include_zero_denominator_flow_eff_count`.
- `test_notes_include_cancelled_count` — single line listing all five
  metrics cancelled are excluded from.
- `test_notes_include_defect_ratio_disclaimer`.
- `test_notes_include_flow_load_sample_count_and_weekend_policy`.
- `test_notes_include_field_level_permission_undercount`.

**Approach:**

- `flow_metrics/notes.py`:
  - `class NotesCollector`: methods like `add_cancelled(n)`,
    `add_skipped_commitment(n)`, `add_zero_denominator(n)`,
    `add_permission_undercount(n)`, etc. Each appends a string;
    duplicates are deduped.
  - `def finalize() -> list[str]` — sorts lexicographically and returns.
- Wired into T5/T6 — each population predicate / aggregator increments
  the relevant counter when it excludes a row.
- `meta.caller` is set in T11 after a startup `jira.whoami()`. Cloud:
  `accountId` field; Server: `name` field; both missing → exit 3.

**Done when:** all listed tests green.

---

### T12: SKILL.md + manifest.json + default config files + references/output.schema.json

**Depends on:** T1–T11 substantive completion (this is packaging)

**Tests:**

- `test_skill_md_lists_all_subcommands_from_spec` — fail if SKILL.md
  is missing any flag from the spec's Inputs table.
- `test_manifest_declares_dependencies` — `manifest.json` has
  `deps.skills` listing `jira` and `jira-align` by name.
- `test_default_state_config_passes_validation` —
  `references/states.default.json` loads cleanly and produces a valid
  `StateConfig`.
- `test_default_issuetype_config_passes_validation`.
- `test_output_json_validates_against_schema` — integration golden
  output validates against `references/output.schema.json` using
  stdlib `jsonschema`-equivalent (or a minimal homegrown validator;
  no third-party dep).
- `test_skill_md_security_rules_present` — SKILL.md mentions the
  read-only contract, the credential-isolation rule (never reads
  `credentials.env`), and the no-write-verb posture.

**Approach:**

- `skills/workflows/flow-metrics/SKILL.md` — follows the
  `jira-defect-flow` pattern: `name`/`description` frontmatter,
  cross-skill invocation by name, "Don't" list, security rules, Edge
  cases. Tells the agent how to invoke the CLI for common flows.
- `skills/workflows/flow-metrics/manifest.json` — `id`,
  `version: "0.1.0"`, `description`, `category: "workflows"`,
  `deps.skills: [{name: "jira"}, {name: "jira-align"}]`. **No
  `deps.pip` entry** — v1 is stdlib only (see Approach §). If `numpy`
  is added in v2, `deps.pip: ["numpy"]` lands then.
- `skills/workflows/flow-metrics/references/output.schema.json` — JSON
  Schema for the canonical output. The `unrequested-metrics-are-absent`
  rule lives here (additionalProperties: false on `aggregates`; every
  metric key is optional).
- `skills/workflows/flow-metrics/requirements.txt` — empty in v1 (no
  pip deps).

(The default state and issuetype JSON files ship in T2 — see that
task. T12 only adds packaging artefacts: SKILL.md, manifest.json, and
output.schema.json.)

**Done when:** all listed tests green; running `python install.py --list`
(once kit-installer ships) shows flow-metrics with `deps.skills` listed.

---

### T13: CI matrix + integration fixtures + golden files

**Depends on:** T1–T12

**Tests:**

- All contract tests pass in a GitHub Actions matrix:
  - `os × [ubuntu-latest, macos-latest, windows-latest]`
  - `python-version × [3.10, 3.11, 3.12]`
  - 9 combinations total.
- Integration tests (`test_full_happy_path_*` from the construction
  block) pass against checked-in fixtures + golden files.
- Per-team smoke test passes against one real team's recorded fixture
  with hand-computed reference values for cycle time, lead time,
  throughput, rework rate, cancelled count, to within ±1%.

**Approach:**

- `.github/workflows/test-flow-metrics.yml` mirrors
  kit-installer's CI shape (`python -m pytest`).
- `tests/fixtures/proj_alpha/`: **synthetic JSON authored by hand**
  from the spec's described scenarios (issues page, per-issue
  changelog pagination payloads, state config, expected golden JSON
  output). Not recorded from a real Jira instance — this avoids
  credentialed-data leakage and makes the fixture's invariants
  reviewable line-by-line.
- `tests/fixtures/program_42/`: same plus synthetic Jira Align
  responses.
- Golden files use `generated_at` placeholder; the test harness
  substitutes a fixed timestamp.
- **Optional helper** (not part of the contract gate): a
  `tests/regen_goldens.py` script re-runs the implementation against
  the existing synthetic fixtures and re-writes the golden output
  files when the implementation legitimately changes output. The
  fixtures themselves are hand-edited when scenarios change; the
  helper never regenerates fixtures. Ships if convenient, omitted if
  not — the integration test suite works without it.

**Done when:** CI matrix green on all 9 combinations; integration
smoke against the real-team fixture matches within ±1% on each
contract metric.

## Rollout

New skill, no existing behavior changed. Ships as `v0.1.0` under
`skills/workflows/flow-metrics/`. The downstream `ai-adoption-report`
skill (baseline / cohort / program modes — see
[`docs/specs/ai-adoption-report.md`](ai-adoption-report.md)) is a
separate PR that depends on flow-metrics v0.1.0 being installable.

Ship checklist before tagging:

- All contract tests + construction tests + integration tests green on
  the 9-combo CI matrix.
- Default state config (`references/states.default.json`) passes
  validation with no warnings.
- One real-team smoke run produces numbers within ±1% of the
  hand-computed reference.
- SKILL.md links back to this spec and plan.
- `manifest.json` declares `deps.skills` for `jira` and `jira-align`.
- No `pip install` step in the CI workflow (stdlib only in v1).

## Risks

- **Upstream skill `jira` doesn't expose `raw GET issue/<KEY>/changelog`
  pagination.** Spec calls this out as a pre-implementation gap. T4
  depends on the upstream verb being available. If absent, ship a small
  PR against `jira` first to add it; this plan blocks on T4 until then.
- **Percentile algorithm divergence stdlib vs numpy.** Stdlib
  `statistics.quantiles(method="exclusive")` and `numpy.percentile(method=
  "linear")` use slightly different interpolation rules at the
  boundaries. Pin one in v1 (stdlib; the spec says "or equivalent" so
  we're free to pick) and document. Cross-platform CI catches drift.
- **Cloud changelog regression on long-lived issues.** Real-team
  validation is the only way to be sure pagination drains every entry.
  Smoke against an issue known to have >200 transitions before tagging.
- **`os.replace` on Windows with cross-drive cache paths.** Same risk
  shape as kit-installer; same mitigation (scope roots and cache root
  are under home or cwd, same drive in practice).
- **Test isolation.** Tests must never call real Jira or Jira Align.
  The upstream-skill discovery probe MUST be intercepted in every test
  via `FLOW_METRICS_JIRA_SCRIPT` / `FLOW_METRICS_JIRAALIGN_SCRIPT` env
  vars pointing at fixture scripts. Flag in code review if any test
  shells out to a real skill.
- **Output canonicalization is fragile.** Floats are the highest-risk
  area — a single missed `round` call before `json.dumps` breaks
  `test_stable_output_for_same_inputs` flakily. The canonicalization is
  centralized in `flow_metrics/output.py` to keep the blast radius
  small.
- **Read-only allowlist drift.** A future code change in T8 / T11 could
  add a new upstream call (e.g., a convenience `list-users` lookup).
  The allowlist-enforcement test runs against every supported
  scope/flag combination, so it catches such additions. New verbs
  require a spec update first.

## Changelog

- 2026-05-19: initial plan
- 2026-05-19: update downstream-skill reference — the three original
  AI-adoption specs (baseline, cohort, value-report) were consolidated
  into a single `ai-adoption-report` skill (three modes). No
  flow-metrics technical contract changes; rollout updated to point
  at the new spec.
