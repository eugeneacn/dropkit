# Plan: ai-adoption-baseline

- **Spec:** [`docs/specs/ai-adoption-baseline.md`](ai-adoption-baseline.md)
- **Status:** Approved (ready to execute) <!-- Drafting | Approved | Executing | Done -->
- **Review history:** 3 adversarial review rounds (2026-05-19). Round 1: 2 blockers / 7 majors / 7 minors; round 2: 0 blockers / 3 majors / 10 minors; round 3: 0 blockers / 0 majors / 1 minor. Terminal-clean.

> **Plan contract:** this is the implementation strategy. Unlike the
> spec, this document is allowed to change as you learn. When it
> changes substantially, note why in the changelog at the bottom.

## Approach

Ten sequentially-ordered tasks. The first three (T1 scaffold, T2 config
+ default configs, T3 upstream wrapper) establish the substrate. T4–T6
build the data path: window resolution, snapshot_id derivation, envelope
construction. T7 handles overwrite semantics. T8 wires notes. T9
packages the skill. T10 covers CI and fixtures.

The load-bearing tasks are T3 (subprocess wrapper to `flow-metrics`,
mirroring the architectural pattern flow-metrics itself uses for `jira`
/ `jira-align`) and T5 (snapshot_id derivation — the integrity contract
the cohort skill depends on for tamper detection).

Implementation is **standalone Python ≥ 3.10, stdlib only**. No third-
party deps. All upstream calls go through the existing dropkit
`flow-metrics` skill via subprocess.

## Architectural decisions deferred to this plan

The spec says cross-skill invocation is "by name, not path." For the
Python implementation:

- **Subprocess invocation of `flow-metrics`** via the same discovery
  probe shape `flow-metrics` itself uses for `jira` / `jira-align`.
- **Discovery probe order** (matches the spec exactly — four probe
  steps plus a not-found exit; no ancestor walk):
  1. `$AI_ADOPTION_FLOW_METRICS_SCRIPT` env var (testing override).
  2. `<this-skill-dir>/../flow-metrics/scripts/flow_metrics.py`
     (sibling install layout).
  3. `~/.claude/skills/flow-metrics/scripts/flow_metrics.py`.
  4. `<cwd>/.claude/skills/flow-metrics/scripts/flow_metrics.py`.
  - Not found after all four probes → exit 2 with the discovery
    message naming each tried path.
- **Allowlist enforcement wrapper-side** — the upstream CLI can do
  more than the spec allows; this skill's wrapper refuses to construct
  argv outside the documented forwarded-flags allowlist.
- **flow-metrics subprocess uses `subprocess.run` (not `Popen`)** —
  aggregate JSON output is bounded by issue count × percentile-block
  size, fits in memory. No streaming needed (unlike flow-metrics' own
  `search` call, which streams 10k+ rows from jira).
- **flow-metrics stderr always forwarded** to this skill's stderr,
  even on exit 0, so users see permission-undercount and other notes.

## Constraints

The decisions recorded in the spec's "Decisions" section govern all
ambiguous cases. The most binding for implementation:

- Python floor 3.10.
- UTC throughout; window math is `from = R − timedelta(days=N)` and
  `to = R − timedelta(days=1)` (inclusive).
- Stabilization period 14 days post-rollout unless
  `--accept-recent-rollout`.
- `--baseline-window-days` range `[14, 365]`.
- Canonical envelope serialization via `json.dumps(envelope,
  sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"`.
- `snapshot_id` includes `envelope_schema_version` (this skill's own
  version) so future envelope bumps invalidate downstream caches.
- Output path includes `-cfg<sha8>` suffix iff `--state-config` or
  `--issuetype-config` was passed.
- Stdout is **exactly one line** on success (the absolute path) so
  `$(ai-adoption-baseline ...)` composition works.
- `--verbose` writes to stderr only.
- Exit-code map: 0 success, 1 user-abort, 2 validation, 3 upstream
  error (no `4`).

## Construction tests

Cross-cutting tests spanning multiple tasks.

**Integration tests:**

- `test_full_happy_path` — fixture: a mocked `flow-metrics` CLI that
  returns a canned aggregate JSON. Run end-to-end: `ai-adoption-
  baseline --project PROJ --rollout-date 2026-04-01`. Assert the
  output file matches a checked-in golden JSON byte-for-byte (after
  `meta.generated_at` normalization). Verify (a) the upstream argv
  contains only allowlisted flags, (b) `meta.scope` is the canonical
  5-field dict, (c) `meta.snapshot_id` is a 64-char hex sha, (d) the
  embedded `flow_metrics` block is byte-identical to the canned input.
- `test_overwrite_roundtrip` — write a snapshot, modify the input
  fixture, re-run with `--overwrite --overwrite-snapshot-id <id>`,
  verify the new snapshot replaces the old and the new
  `meta.snapshot_id` differs.
- `test_canonical_byte_equality` — two consecutive runs with identical
  inputs produce byte-identical files (modulo `meta.generated_at`).

**Manual verification gate (before tagging):**

- Run against one real team's project with their actual rollout date.
  Sanity-check that the embedded `flow_metrics` block matches a
  hand-run `flow-metrics` invocation byte-for-byte. The user runs
  this; CI cannot.

## Tasks

### T1: Scaffold — CLI, argparse, exit codes, Python floor

**Depends on:** none

**Tests:**

- `test_python_below_floor_exits_2` — mocked `sys.version_info` to
  `(3, 9)` exits 2 with a clear message.
- `test_help_exits_0` — `--help` exits 0 and lists every flag from
  the spec's Inputs synopsis.
- `test_rollout_date_required` (contract) — invocation without
  `--rollout-date` exits 2.
- `test_exactly_one_scope_required` (contract).
- `test_team_only_valid_with_project` (contract).
- `test_unknown_flag_exits_2`.
- `test_force_without_overwrite_exits_2` — `--force` alone exits 2
  at parse-time (no filesystem state needed).
- `test_overwrite_snapshot_id_without_overwrite_exits_2` — also
  parse-time.

**Approach:**

- Create `skills/workflows/ai-adoption-baseline/scripts/ai_adoption_baseline.py`
  as the CLI entry point. Mirrors the sibling skill layout.
- Version check at module top: `sys.version_info < (3, 10)` → stderr
  + `sys.exit(2)`.
- `build_parser()` configures all flags from the spec's Inputs
  synopsis. Mutex groups for scope flags. `--overwrite` /
  `--overwrite-snapshot-id` / `--force` validation in
  `validate_args()`.
- Stub every command path to print "not yet implemented" and exit 0;
  later tasks fill these in.

**Done when:** all listed tests green on Python 3.10, 3.11, 3.12.

---

### T2: Config loading + window resolution

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_rollout_date_in_future_exits_2`.
- `test_rollout_date_within_stabilization_exits_2`.
- `test_baseline_window_days_below_min_exits_2`.
- `test_baseline_window_days_above_max_exits_2`.
- `test_window_math_leap_year_boundary`.
- `test_canonical_scope_always_five_fields`.
- `test_window_anchors_one_day_before_rollout` — `from = R − N days`,
  `to = R − 1 day` (inclusive math).
- `test_window_inclusive_endpoints` — for the same fixture, both
  endpoints are inclusive per spec's inclusive-inclusive
  convention.
- `test_window_does_not_cross_rollout` — no combination of
  `--baseline-window-days` produces a window that includes the
  rollout date itself.

**Construction tests:**

- `test_default_window_days_is_90` — without `--baseline-window-days`,
  resolved `window.days == 90`.

- `test_scope_normalization_project_key_upper` —
  `--project proj` produces `scope.project_key == "PROJ"`.
- `test_scope_normalization_team_stripped` —
  `--team "  Foo  "` produces `scope.team == "Foo"`.
- `test_today_utc_only_read_via_clock_module` — static check: no
  direct `datetime.now()` calls anywhere except in `clock.py`. The
  seam exists so contract tests like
  `test_rollout_date_in_future_exits_2` can monkeypatch `today_utc`
  deterministically and not flake at midnight UTC boundaries.

**Approach:**

- `ai_adoption_baseline/window.py`:
  - `resolve_window(rollout_date: date, days: int) -> Window` returns
    a dataclass with `from: date, to: date, days: int`.
  - `validate_rollout_date(rollout_date: date, accept_recent: bool,
    today_utc: date) -> None` — raises `ValidationError` with the
    spec-pinned exit-2 message.
- `ai_adoption_baseline/scope.py`:
  - `canonical_scope(args) -> dict` builds the 5-field dict with
    explicit `null` for unused slots.
  - String normalization (uppercase, strip) happens here.
- `today_utc` is taken from `datetime.now(timezone.utc).date()`;
  exposed via a small `clock.py` helper for monkeypatching in tests.

**Done when:** all listed tests green.

---

### T3: Upstream wrapper — discovery, allowlist, subprocess

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_only_flow_metrics_invoked` — wraps `subprocess.run`/`Popen`;
  asserts the only subprocess invoked is the resolved
  `flow_metrics.py`. argv[0] may be `python` / `python3`. No `jira`,
  `jira-align`, `git`, `gh`, `curl`, `wget`, `pip`, `npm`.
- `test_per_issue_never_invoked` — `--per-issue` is never in the
  upstream argv.
- `test_only_allowlisted_upstream_flags_passed` — upstream argv
  contains only `--from`, `--to`, exactly one scope flag, optional
  `--team`, `--state-config`, `--issuetype-config`, `--format json`.
- `test_no_cohort_breakdown_in_output` (contract) — defensive: under
  no scope/flag combination does the wrapped `flow_metrics` JSON
  contain a `cohort_breakdown` key. Any such case exits 3.
- `test_upstream_flow_metrics_failure_exits_3` (contract).
- `test_flow_metrics_not_found_exits_2` (contract) — none of the
  discovery paths exist → exit 2 with each path listed.

**Construction tests:**

- `test_discovery_probes_in_order` — patch each candidate path; assert
  the wrapper picks the first hit (env var > sibling > user-scope >
  cwd-walk).
- `test_discovery_cwd_direct_only` — only the literal
  `<cwd>/.claude/skills/flow-metrics/scripts/flow_metrics.py` is
  checked; an ancestor `<cwd>/../.claude/skills/...` is NOT walked.
  If the user runs from a sub-repo where the canonical install is at
  the parent, they must set the env-var override.
- `test_skill_does_not_read_credentials_file` — monkeypatch
  `builtins.open` **in this skill's process only**, record every
  path opened, assert `~/.config/dropkit/credentials.env` is never
  among them. (The upstream subprocess is invoked via
  `subprocess.run` and runs in a separate process; its file reads
  are not observed by this monkeypatch and are not subject to this
  contract — credential access there is the upstream skill's
  responsibility.)
- `test_subprocess_inherits_full_env` — the subprocess is invoked
  with the parent's full `os.environ` (no `env=` filter applied to
  `subprocess.run`). Necessary because `flow-metrics` reads
  `JIRA_*` / `JIRA_ALIGN_*` and other credential env vars from its
  own process environment; an env filter here would break
  credentials. The test asserts that a sentinel env var set in the
  parent reaches the mocked upstream subprocess unchanged.
- `test_flow_metrics_stderr_forwarded_on_success` — flow-metrics'
  stderr appears on this skill's stderr even on exit 0.
- `test_jira_call_args_quoting` — args with spaces are passed via
  `subprocess.run([argv])` (list form), never `shell=True`.

**Approach:**

- `ai_adoption_baseline/upstream.py`:
  - `discover_flow_metrics() -> Path` implements the 4-step probe.
  - `class FlowMetricsClient`:
    - Constructor takes the discovered script path.
    - One method `run_aggregate(scope_args, from_, to_, state_config,
      issuetype_config) -> dict` builds the argv (validates against
      the allowlist before assembling), runs
      `subprocess.run(argv, capture_output=True, check=False, env=...)`,
      parses stdout as JSON, forwards stderr, returns the dict on
      success or raises `UpstreamError(returncode, stderr)`.
- `UpstreamError` is caught at main → exit 3 with the upstream stderr
  relayed verbatim.

**Done when:** all listed tests green.

---

### T4: Output path resolution + `-cfg<sha8>` suffix

**Depends on:** T2, T3

**Tests (contract tests from spec):**

- `test_output_path_deterministic_project_scope`.
- `test_output_path_includes_team_slug`.
- `test_output_path_program_scope`.
- `test_output_path_portfolio_scope`.
- `test_label_not_in_filename`.
- `test_default_config_filename_has_no_cfg_suffix`.
- `test_non_default_config_includes_cfg_suffix_in_filename` — when
  `--state-config` is passed (flag-presence rule), filename ends in
  `-cfg<8hex>.json`.

**Construction tests:**

- `test_team_slug_collapse_multiple_hyphens` — `--team "Foo  bar/baz"`
  → slug `Foo-bar-baz`.
- `test_team_slug_strip_leading_trailing_hyphens` — `--team "//Foo//"`
  → slug `Foo`.
- `test_cfg_sha_first_8_hex_chars` — fixture: pass `--state-config
  /tmp/x.json`; resolved suffix is the first 8 hex chars of
  `sha256(state_config_canonical + issuetype_config_canonical)`.

**Approach:**

- `ai_adoption_baseline/output_path.py`:
  - `scope_tag(scope: dict, team: Optional[str]) -> str` per the
    spec's scope-tag rules.
  - `cfg_suffix(args, flow_metrics_meta) -> Optional[str]` — returns
    `"-cfg<hex8>"` iff `--state-config` or `--issuetype-config` was
    passed; `None` otherwise. The sha source is **flow-metrics'
    reported shas**: `sha256(flow_metrics_meta["state_config_sha"]
    + flow_metrics_meta["issuetype_config_sha"]).hexdigest()[:8]`.
    This guarantees the filename sha and the envelope sha
    (`snapshot_id` inputs) agree byte-for-byte, since both read the
    same upstream meta. The skill does NOT re-hash the user-supplied
    config files.
  - `resolve_output_path(output_dir, scope_tag, rollout_date,
    window_days, cfg_suffix) -> Path`.

**Done when:** all listed tests green.

---

### T5: `snapshot_id` derivation + envelope construction

**Depends on:** T2, T3

**Tests (contract tests from spec):**

- `test_meta_includes_snapshot_id` — 64-char hex.
- `test_meta_snapshot_id_stable_across_runs`.
- `test_meta_snapshot_id_changes_with_state_config`.
- `test_meta_schema_version_recorded` — `meta.schema_version ==
  "1.0"`.
- `test_meta_upstream_flow_metrics_schema_version_recorded`.
- `test_missing_upstream_state_sha_exits_3`.
- `test_upstream_schema_major_not_allowlisted_exits_3` — fixture
  sets `flow_metrics.meta.schema_version: "2.0"`; this skill exits 3
  with the spec-pinned message `"upstream flow-metrics
  schema_version 2.0 is not supported by this baseline version;
  upgrade ai-adoption-baseline"`.
- `test_flow_metrics_json_passed_through_verbatim`.
- `test_canonical_scope_always_five_fields` (overlap with T2,
  re-verified at envelope-assembly time).

**Construction tests:**

- `test_snapshot_id_includes_envelope_schema_version` — toggling a
  mocked `meta.schema_version` between `"1.0"` and `"1.1"` changes
  `snapshot_id` even when every other input is identical.
- `test_snapshot_id_canonical_json_sorted_keys` —
  `sha256(json.dumps(..., sort_keys=True, separators=(",",":")))`
  matches a hand-computed reference.
- `test_envelope_serialization_sorted_keys` — output file's JSON is
  produced by `json.dumps(envelope, sort_keys=True, separators=
  (",", ":"), ensure_ascii=False) + "\n"`. Verified by re-parsing
  the file and comparing against `json.dumps(parsed, sort_keys=True,
  ...)`.

**Approach:**

- `ai_adoption_baseline/envelope.py`:
  - `compute_snapshot_id(envelope_schema_version, rollout_date,
    baseline_window, scope, state_config_sha, issuetype_config_sha,
    upstream_schema_version) -> str` — exact formula from the spec.
  - `build_envelope(args, window, scope, flow_metrics_json,
    notes_collector) -> dict` constructs the full envelope. Reads
    `state_config_sha`, `issuetype_config_sha`, `schema_version` from
    `flow_metrics_json["meta"]`; missing → `UpstreamError` → exit 3.
  - `serialize_envelope(envelope: dict) -> bytes` does the canonical
    JSON dump.

**Done when:** all listed tests green.

---

### T6: Collision detection + atomic write

**Depends on:** T4, T5

**Tests (contract tests from spec):**

- `test_existing_file_collision_exits_2`.
- `test_overwrite_alone_exits_2` — `--overwrite` without
  `--overwrite-snapshot-id` and without `--force` exits 2 when the
  target file exists; error message includes the existing file's
  `meta.snapshot_id`.
- `test_no_overwrite_without_flag` — even with stdout redirected
  and stdin piped from `/dev/null`, the skill does not overwrite an
  existing file without `--overwrite`.
- `test_overwrite_with_matching_snapshot_id_succeeds`.
- `test_overwrite_with_wrong_snapshot_id_exits_2`.
- `test_overwrite_force_replaces_malformed_existing` — existing file
  is empty or non-JSON; `--overwrite --force` replaces it.
- `test_atomic_temp_unlinked_on_exception` — simulated crash
  mid-write; no `*.tmp` file remains.
- `test_stale_tmp_swept_at_startup` — pre-existing `*.tmp` with mtime
  > 1h is removed at startup.

**Construction tests:**

- `test_overwrite_force_ignores_snapshot_id` — `--overwrite --force
  --overwrite-snapshot-id <wrong>` succeeds with a
  `"force-overwrite: snapshot-id unverified"` notes entry.
- `test_concurrent_writes_pid_suffixed_tmp` — two simultaneous runs
  use distinct `.tmp` filenames (PID-suffixed) and neither sees the
  other's tempfile.
- `test_atomic_write_via_same_directory_tempfile` — verify the
  tempfile is created in the target's parent directory (not
  `/tmp/...`) so `os.replace` is atomic on Windows.
- `test_stale_tmp_sweep_skips_live_pid` — `*.tmp` files containing
  a live PID in their name are not swept even when stale (defensive
  against the spec's concurrent-write race).

**Approach:**

- `ai_adoption_baseline/atomic_write.py`:
  - `def write_atomic(target: Path, payload: bytes) -> None` —
    creates `<target>.<pid>.tmp` in the target's parent dir, writes,
    fsyncs, `os.replace`s. `try/finally` unlinks on any exception
    before re-raise.
  - `def sweep_stale_tmps(directory: Path) -> None` — at startup,
    `directory.glob("*.tmp")`, unlink each with `mtime` > 1 hour
    AND whose `.<pid>.tmp` PID is not alive. PID liveness uses
    **stdlib only**:
    - POSIX: `os.kill(pid, 0)` raises `ProcessLookupError` if the
      PID is dead. (Other errors — e.g. `PermissionError` on a PID
      owned by another user — are treated as "alive", erring on the
      safe side.)
    - Windows: `ctypes.windll.kernel32.OpenProcess(0x0400, False,
      pid)` returns NULL on dead PID.
    If both probes are unavailable (exotic platform), fall back to
    mtime-only sweep and accept the documented rare race. PID is
    extracted from filename via `re.search(r"\.(\d+)\.tmp$",
    name)`; names not matching the pattern are treated as
    non-PID-tagged and swept by mtime alone.
- `ai_adoption_baseline/collision.py`:
  - `def check_collision(target: Path, args) -> None` — if target
    exists, applies the `--overwrite` / `--overwrite-snapshot-id` /
    `--force` logic per spec.

**Done when:** all listed tests green.

---

### T7: Logging + stdout contract + verbose

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_stdout_prints_only_output_path` — stdout contains exactly one
  line (the absolute path), no other content.
- `test_verbose_writes_to_stderr_only` — `--verbose` produces
  diagnostic lines on stderr; stdout is unchanged.
- `test_flow_metrics_stderr_forwarded_on_success` (overlap with T3).

**Construction tests:**

- `test_verbose_logs_resolved_argv` — `--verbose` produces a stderr
  line showing the resolved `flow-metrics` argv (so users can
  reproduce by hand).
- `test_no_stderr_on_quiet_success` — without `--verbose`, the
  successful path produces no stderr from this skill (upstream stderr
  is still forwarded but only if non-empty).

**Approach:**

- `ai_adoption_baseline/logging.py`:
  - `class StreamLogger`: methods `info`, `verbose`, `success`,
    `error`. `success` writes to stdout (exactly one line); the rest
    write to stderr.
- All print calls in the codebase go through this; tests use a
  capsys-like fixture to assert on the streams.

**Done when:** all listed tests green.

---

### T8: Notes generation + low-throughput warning

**Depends on:** T3, T5

**Tests (contract tests from spec):**

- `test_low_throughput_emits_warning_note` — fixture where flow-
  metrics returns `aggregates.throughput < 30`. Snapshot writes
  successfully; `meta.notes` includes `"low-throughput: N delivered
  issues in window; percentile stability not guaranteed"`.
- `test_accept_recent_rollout_allows_recent_date` — fixture:
  `--rollout-date today - 5 --accept-recent-rollout`. Run succeeds
  (exit 0); the written snapshot's `meta.notes` contains an entry
  whose prefix is exactly `"recent-rollout-accepted:"`.
- `test_meta_label_when_set` — `--label "foo"` → `meta.label == "foo"`.
- `test_meta_label_empty_string_exits_2`.
- `test_meta_notes_sorted_lexicographic` — note order in output is
  lexicographic (no insertion-order leakage).

**Construction tests:**

- `test_recent_rollout_accepted_note_prefix` — when
  `--accept-recent-rollout` is used, `notes` contains an entry whose
  prefix is exactly `"recent-rollout-accepted:"`.
- `test_force_overwrite_note_prefix` — when `--overwrite --force`
  is used and `--overwrite-snapshot-id` was ALSO passed, `notes`
  contains an entry whose prefix is exactly `"force-overwrite:"`.
- `test_upstream_schema_minor_drift_note` — when flow-metrics
  returns `meta.schema_version: "1.1"` (allowlist major `"1"`, minor
  drift), `notes` contains `"upstream-schema-minor-drift:
  flow-metrics v1.1"`.
- `test_notes_array_always_present_even_when_empty` — happy path with
  no warnings produces `meta.notes == []`, not absent.

**Approach:**

- `ai_adoption_baseline/notes.py`:
  - `class NotesCollector`: methods like `add_low_throughput(n)`,
    `add_recent_rollout_accepted(days_since_rollout)`,
    `add_force_overwrite()`, `add_upstream_schema_minor_drift(v)`,
    each appending a string with the canonical prefix.
  - `finalize() -> list[str]` returns a sorted list (lexicographic).
- Wired in: T5 (envelope build) calls
  `notes_collector.finalize()` and sets `envelope["meta"]["notes"]`.

**Done when:** all listed tests green.

---

### T9: SKILL.md + manifest + default-config validation policy

**Depends on:** T1–T8 substantive completion (this is packaging)

**Tests:**

- `test_skill_md_lists_all_subcommands_from_spec` — fail if SKILL.md
  is missing any flag from the spec's Inputs synopsis.
- `test_manifest_declares_flow_metrics_dep` —
  `manifest.json` has `deps.skills: [{name: "flow-metrics"}]`.
- `test_manifest_no_pip_deps` — `manifest.json` has no `deps.pip`
  entry (defense against the stdlib-only contract).
- `test_manifest_id_and_version_present` — `id ==
  "ai-adoption-baseline"`, `version == "0.1.0"`.
- `test_skill_md_security_rules_present` — SKILL.md mentions the
  no-credentials-read rule, the read-only contract, the
  no-write-verb posture toward Jira/Jira Align.

**Approach:**

- `skills/workflows/ai-adoption-baseline/SKILL.md` follows the
  `jira-defect-flow` pattern.
- `skills/workflows/ai-adoption-baseline/manifest.json` declares
  `id`, `version: "0.1.0"`, `description`, `category: "workflows"`,
  `deps.skills: [{name: "flow-metrics"}]`, no `deps.pip`.
- `skills/workflows/ai-adoption-baseline/references/baseline.schema.json`
  — JSON Schema for the canonical output envelope. Co-versioned with
  this skill's `meta.schema_version`. Consumed by the cohort and
  value-report skills.
- `skills/workflows/ai-adoption-baseline/requirements.txt` — empty.

**Done when:** all listed tests green.

---

### T10: CI matrix + integration fixtures

**Depends on:** T1–T9

**Tests:**

- All contract + construction tests pass on a GitHub Actions matrix:
  `os × [ubuntu-latest, macos-latest, windows-latest]`,
  `python-version × [3.10, 3.11, 3.12]` (9 combinations).
- Integration tests `test_full_happy_path`, `test_overwrite_roundtrip`,
  `test_canonical_byte_equality` pass against checked-in synthetic
  fixtures.

**Approach:**

- `.github/workflows/test-ai-adoption-baseline.yml` mirrors the
  flow-metrics CI shape.
- `tests/fixtures/baseline/` — synthetic JSON authored by hand:
  - `flow_metrics_canned.json` — a canned aggregate response
    (delivered, cancelled, all the metrics shape).
  - `golden_envelope.json` — expected envelope output.
  - `state_config_default.json` — exact spec default.
  - `issuetype_config_default.json` — exact spec default (needed
    so cfg-sha tests can be reproduced without an installed
    flow-metrics).
- A `tests/regen_goldens.py` helper (optional, not part of contract
  gate) re-runs the implementation and rewrites goldens.

**Done when:** CI matrix green on all 9 combinations.

## Rollout

New skill, no existing behavior changed. Ships as `v0.1.0` under
`skills/workflows/ai-adoption-baseline/`. The cohort and value-report
skills are separate PRs that depend on this skill being installable.

Ship checklist before tagging:

- All tests green across the 9-combo CI matrix.
- One real-team smoke run produces a snapshot whose `flow_metrics`
  sub-object matches a hand-run `flow-metrics` invocation byte-for-byte.
- SKILL.md links back to this spec and plan.
- `manifest.json` declares the flow-metrics dep.

## Risks

- **Discovery probe fails in unusual install layouts.** The 4-step
  probe covers env var, sibling, user-scope, cwd-walk. A user running
  from a non-cwd-rooted install (e.g., a global venv with skills under
  `/opt/dropkit/...`) needs the env-var override. Document this in
  SKILL.md.
- **Test isolation.** Tests must never call real `flow-metrics`. The
  `FLOW_METRICS_SCRIPT` env override MUST be set to a fixture script
  in every test using the upstream wrapper. Flag in code review if
  any test shells out to the real skill.
- **Atomic-write race on Windows.** `os.replace` cross-volume is not
  atomic; the same-directory tempfile pattern (T6) avoids this.
  CI matrix on Windows catches regressions.
- **Discovery resolves a stub or wrong-version `flow-metrics`.** The
  probe finds *a* script; it doesn't verify version *before* spending
  the run. The upstream-schema allowlist (exit 3) catches major drift
  after the call returns, but a stub `flow_metrics.py` that produces
  well-formed but fake data passes silently. Mitigation: `--verbose`
  logs the resolved script's absolute path on stderr before
  invocation, so users can spot a surprise. No CI gate for this
  (CI uses the env-var override on purpose).
- **Stale-tmp sweep races a long-running concurrent run.** If a
  `flow-metrics` call takes >1h and the second invocation sweeps the
  first's tempfile, the first's `os.replace` fails. T6's
  stdlib-only PID liveness check (`os.kill(pid, 0)` on POSIX;
  `ctypes.windll.kernel32.OpenProcess` on Windows) mitigates;
  fallback (exotic platform without either) accepts the rare race
  and documents it.
- **`flow-metrics` schema drift.** When flow-metrics ships v2.0, this
  skill exits 3 per the upstream-schema allowlist. CI matrix can't
  test against a future flow-metrics; document the upgrade procedure
  in SKILL.md.

## Changelog

- 2026-05-19: initial plan
