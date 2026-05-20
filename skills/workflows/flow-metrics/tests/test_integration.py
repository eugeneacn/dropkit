"""T13 integration tests — drive the wired CLI against synthetic fixtures.

Each ``test_full_happy_path_*`` test invokes ``flow_metrics.main`` end-to-end
against a fixture directory under ``tests/fixtures/`` and asserts the rendered
output byte-equals a checked-in golden file (after a single
``__GENERATED_AT__`` placeholder substitution).

The fixture-replay harness — set up in ``conftest.py``'s
``integration_sandbox`` fixture — points
``FLOW_METRICS_JIRA_SCRIPT`` / ``FLOW_METRICS_JIRAALIGN_SCRIPT`` at shim
scripts under ``fixtures/_replay/`` and unsets every credential-bearing
env var so no test ever reaches a real upstream instance. The test-isolation
contract (plan line 1029-1033) is what these fixtures lock in.

Goldens use a literal ``__GENERATED_AT__`` placeholder where ``meta.generated_at``
would appear; the test substitutes the actual rendered timestamp before the
byte-compare. The clock is pinned by the ``integration_sandbox`` fixture so
every run produces the same instant — the placeholder substitution is
defensive rather than load-bearing today, but it lets a future test that
exercises an unpinned ``generated_at`` reuse the same golden.

Stdlib only — no third-party deps (no jsonschema / freezegun / pyyaml).
"""
from __future__ import annotations

import io
import json
import re
import sys
from contextlib import redirect_stderr
from pathlib import Path

import pytest

from flow_metrics import main as cli_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_GENERATED_AT_PLACEHOLDER = "__GENERATED_AT__"

# The integration_sandbox fixture pins flow_metrics.clock.today_utc() to
# 2026-05-19T14:00:00 UTC; meta.generated_at renders as the ISO string
# below (build_meta._iso_generated_at coerces +00:00 to "Z"). We
# substitute *only* this exact byte string so the golden's per-issue
# timestamps (issue_created / first_commitment_at / first_delivery_at)
# remain real timestamps, not the placeholder. A naive
# "match any ISO timestamp" regex would silently mask regressions
# where the implementation corrupted those per-issue fields.
_PINNED_GENERATED_AT_BYTES = b"2026-05-19T14:00:00Z"


def _run_cli(argv: list) -> tuple[int, bytes, str]:
    """Run ``flow_metrics.main`` capturing rc, stdout (bytes), stderr (text).

    Stdout is captured as bytes because the renderer emits UTF-8 bytes
    directly via ``sys.stdout.buffer.write`` for canonical byte-equality.
    Stderr stays text — it's diagnostic only.
    """
    stdout_buf = io.BytesIO()
    stderr_buf = io.StringIO()

    class _BytesStdout(io.TextIOBase):
        """Substitute ``sys.stdout`` so the renderer's
        ``sys.stdout.buffer.write`` lands in our buffer.
        """

        def __init__(self, buf):
            self._buf = buf

        @property
        def buffer(self):
            return self._buf

        def write(self, s):
            if isinstance(s, str):
                self._buf.write(s.encode("utf-8"))
            else:
                self._buf.write(s)
            return len(s)

        def flush(self):
            pass

    real_stdout = sys.stdout
    sys.stdout = _BytesStdout(stdout_buf)
    try:
        with redirect_stderr(stderr_buf):
            try:
                rc = cli_main(argv)
            except SystemExit as e:
                rc = e.code if isinstance(e.code, int) else 0
    finally:
        sys.stdout = real_stdout

    return rc, stdout_buf.getvalue(), stderr_buf.getvalue()


def _substitute_generated_at(payload: bytes) -> bytes:
    """Replace the pinned ``meta.generated_at`` timestamp with the literal
    placeholder. Scoped to that exact byte string so per-issue JSONL
    timestamps (issue_created, first_commitment_at, first_delivery_at)
    survive the substitution and stay locked in by the byte-compare.
    """
    return payload.replace(
        _PINNED_GENERATED_AT_BYTES,
        _GENERATED_AT_PLACEHOLDER.encode("ascii"),
    )


def _load_golden(golden_path: Path) -> bytes:
    """Load a golden file as bytes.

    For ``.json`` outputs (which carry ``meta.generated_at``), assert the
    placeholder is present so a regeneration that forgot substitution
    surfaces immediately rather than silently locking in the current
    wall-clock value. CSV and per-issue JSONL outputs have no meta
    block, so the check doesn't apply.
    """
    raw = golden_path.read_bytes()
    if golden_path.suffix == ".json":
        assert _GENERATED_AT_PLACEHOLDER.encode("ascii") in raw, (
            "golden {} is missing the {} placeholder — did you regenerate "
            "without substitution? Re-run tests/regen_goldens.py.".format(
                golden_path, _GENERATED_AT_PLACEHOLDER
            )
        )
    return raw


def _assert_byte_equal(actual: bytes, golden_path: Path) -> None:
    """Byte-compare ``actual`` (post-substitution) against ``golden_path``.

    On mismatch, the assertion message prints the first diverging byte
    offset plus a short snippet either side — enough to diagnose a
    canonicalisation regression without a full diff tool.
    """
    actual_normalised = _substitute_generated_at(actual)
    expected = _load_golden(golden_path)
    if actual_normalised == expected:
        return
    # Find the first divergence for a helpful failure message.
    n = min(len(actual_normalised), len(expected))
    diverge = next((i for i in range(n) if actual_normalised[i] != expected[i]), n)
    snippet = max(0, diverge - 40)
    pytest.fail(
        "byte-equal mismatch against {}\nfirst divergence at offset {}\n"
        "actual   ...{!r}...\nexpected ...{!r}...".format(
            golden_path,
            diverge,
            actual_normalised[snippet : diverge + 40],
            expected[snippet : diverge + 40],
        )
    )


def _allowlisted_calls(call_log: list) -> None:
    """Walk the call log and assert every (skill, verb, path) tuple is in
    the read-only allowlist.

    Plan line 1039: regression check that no future code change introduces
    a new upstream verb without a spec update. The check is conservative —
    it lists exactly what the wired pipeline emits today.
    """
    jira_allowed = {"check", "whoami", "get-issue", "search", "get-project", "raw"}
    align_allowed = {"raw"}
    jira_raw_patterns = (
        re.compile(r"^field$"),
        re.compile(r"^project/[A-Z][A-Z0-9_]+/statuses$"),
        re.compile(r"^issue/[A-Z][A-Z0-9_]+-[0-9]+/changelog$"),
    )
    align_raw_patterns = (
        re.compile(r"^programs/[0-9]+$"),
        re.compile(r"^programs/[0-9]+/teams$"),
        re.compile(r"^portfolios/[0-9]+$"),
        re.compile(r"^portfolios/[0-9]+/programs$"),
    )

    for entry in call_log:
        skill = entry["skill"]
        verb = entry["verb"]
        args = entry["args"]
        if skill == "jira":
            assert verb in jira_allowed, "non-allowlisted jira verb: {}".format(verb)
            if verb == "raw":
                method = args[0] if args else ""
                path = args[1] if len(args) > 1 else ""
                assert method == "GET", "non-GET jira raw method: {}".format(method)
                assert any(p.match(path) for p in jira_raw_patterns), (
                    "non-allowlisted jira raw path: {}".format(path)
                )
        elif skill == "jira-align":
            assert verb in align_allowed, "non-allowlisted jira-align verb: {}".format(verb)
            method = args[0] if args else ""
            path = args[1] if len(args) > 1 else ""
            assert method == "GET", "non-GET jira-align raw method: {}".format(method)
            assert any(p.match(path) for p in align_raw_patterns), (
                "non-allowlisted jira-align raw path: {}".format(path)
            )
        else:
            pytest.fail("unknown skill in call log: {}".format(skill))


# ---------------------------------------------------------------------------
# proj_alpha — project scope
# ---------------------------------------------------------------------------
PROJ_ALPHA = Path(__file__).resolve().parent / "fixtures" / "proj_alpha"


def test_full_happy_path_jira_only(integration_sandbox):
    """Project scope, default metrics, default state config — JSON to stdout
    byte-equals fixtures/proj_alpha/golden.json (after generated_at sub).

    Also asserts that ``meta.cohort_jql`` is **absent** (not null, not
    empty string) when --cohort-jql was not provided — spec § Cohort
    behaviour pins this and T11 enforces it.
    """
    integration_sandbox.use_fixture("proj_alpha")
    rc, stdout, stderr = _run_cli([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    _assert_byte_equal(stdout, PROJ_ALPHA / "golden.json")
    _allowlisted_calls(integration_sandbox.call_log())

    payload = json.loads(_substitute_generated_at(stdout).decode("utf-8"))
    assert "cohort_jql" not in payload["meta"]
    assert "cohort_breakdown" not in payload


def test_full_happy_path_with_cohort_jql(integration_sandbox):
    """--cohort-jql 'labels = ai-assisted' adds a cohort_breakdown block;
    byte-equals fixtures/proj_alpha/golden.cohort.json.

    Also asserts the spec-pinned invariant (plan line 117-118):

        cohort_breakdown.cohort.throughput
      + cohort_breakdown.control.throughput
      = aggregates.throughput

    A regression where the cohort/control split miscounts (e.g., counts
    the same issue on both sides, or drops uncategorised issues) would
    silently violate this even if it produced plausible-looking numbers.
    """
    integration_sandbox.use_fixture("proj_alpha", cohort_marker="labels = ai-assisted")
    rc, stdout, stderr = _run_cli([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--cohort-jql", "labels = ai-assisted",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    _assert_byte_equal(stdout, PROJ_ALPHA / "golden.cohort.json")

    payload = json.loads(_substitute_generated_at(stdout).decode("utf-8"))
    cb = payload["cohort_breakdown"]
    assert (
        cb["cohort"]["throughput"] + cb["control"]["throughput"]
        == payload["aggregates"]["throughput"]
    )
    # meta.cohort_jql is present when --cohort-jql is provided (spec).
    assert payload["meta"]["cohort_jql"] == "labels = ai-assisted"


def test_full_happy_path_with_metrics_filter(integration_sandbox):
    """--metrics throughput,cycle_time drops every other metric from
    aggregates. Asserts unrequested keys are absent (not null).

    Stricter than byte-equal: also parses the output and asserts the
    aggregates dict has exactly two keys (cycle_time_hours + throughput).
    """
    integration_sandbox.use_fixture("proj_alpha")
    rc, stdout, stderr = _run_cli([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--metrics", "throughput,cycle_time",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    _assert_byte_equal(stdout, PROJ_ALPHA / "golden.metrics_filter.json")

    payload = json.loads(stdout.decode("utf-8"))
    assert set(payload["aggregates"].keys()) == {"cycle_time_hours", "throughput"}


def test_full_happy_path_csv(integration_sandbox):
    """--format csv emits the long-form CSV. Byte-equals golden.csv."""
    integration_sandbox.use_fixture("proj_alpha")
    rc, stdout, stderr = _run_cli([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--format", "csv",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    _assert_byte_equal(stdout, PROJ_ALPHA / "golden.csv")


def test_full_happy_path_per_issue(integration_sandbox, tmp_path):
    """--per-issue writes JSONL to --output FILE. Byte-equals golden.per_issue.jsonl.

    Per the spec, line ordering is by key ascending (codepoint). Without
    --cohort-jql, the per-issue rows do NOT carry a ``cohort`` field
    (spec § Cohort behaviour: cohort-field presence is bound to
    cohort-jql mode; absence means "no cohort tagging").
    """
    integration_sandbox.use_fixture("proj_alpha")
    out_path = tmp_path / "per_issue.jsonl"
    rc, stdout, stderr = _run_cli([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--per-issue",
        "--output", str(out_path),
        "--yes",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    actual = out_path.read_bytes()
    _assert_byte_equal(actual, PROJ_ALPHA / "golden.per_issue.jsonl")
    # No cohort field absent --cohort-jql.
    assert b'"cohort"' not in actual


def test_full_happy_path_per_issue_with_cohort_jql(integration_sandbox, tmp_path):
    """--per-issue + --cohort-jql tags each row with ``cohort: true|false``.

    The cohort fixture marks ALPHA-1, ALPHA-3, ALPHA-7 as cohort
    members; every other delivered/cancelled/WIP row gets
    ``cohort: false``. No ``cohort_breakdown`` block is emitted in
    per-issue mode (spec § Cohort behaviour).
    """
    integration_sandbox.use_fixture("proj_alpha", cohort_marker="labels = ai-assisted")
    out_path = tmp_path / "per_issue.jsonl"
    rc, stdout, stderr = _run_cli([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--per-issue",
        "--cohort-jql", "labels = ai-assisted",
        "--output", str(out_path),
        "--yes",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    rows = [
        json.loads(line)
        for line in out_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    # Every row has a cohort field.
    assert all("cohort" in r for r in rows), "cohort field missing on some rows"
    cohort_keys = {r["key"] for r in rows if r["cohort"]}
    assert cohort_keys == {"ALPHA-1", "ALPHA-3", "ALPHA-7"}, (
        "expected cohort = {{ALPHA-1, ALPHA-3, ALPHA-7}}, got {}".format(
            sorted(cohort_keys)
        )
    )


# ---------------------------------------------------------------------------
# Cache write + cache hit on the same run (Windows os.replace risk surface)
# ---------------------------------------------------------------------------
def test_cache_write_then_read_same_run(integration_sandbox):
    """First invocation writes the cache; second hits it.

    The spec's Windows risk (plan line 1026) is that ``os.replace`` across
    drives fails; the sandbox pins cwd inside ``tmp_path`` so the cache
    dir and the (also tmp) source file are on the same drive in practice.
    This test exercises the cache-write + cache-hit code paths together.
    """
    integration_sandbox.use_fixture("proj_alpha")
    argv = [
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
    ]
    # First run: cache MISS — full pipeline runs, cache file is written.
    rc1, out1, err1 = _run_cli(argv)
    assert rc1 == 0, "first run failed; stderr={}".format(err1)
    log_after_first = integration_sandbox.call_log()
    # The first run hits jira for whoami + search + (changelog drain pages).
    search_calls_first = [c for c in log_after_first if c["verb"] == "search"]
    assert len(search_calls_first) >= 1

    # Confirm the cache file was actually written.
    cache_dir = integration_sandbox.tmp_path / ".context" / "flow-metrics" / "cache"
    cache_files = list(cache_dir.glob("*.jsonl"))
    assert cache_files, "cache file not written after first run"

    # Truncate the call log so the second run's call counts are observable
    # in isolation.
    integration_sandbox.call_log_path.write_text("", encoding="utf-8")

    # Second run: cache HIT — search must NOT be invoked.
    rc2, out2, err2 = _run_cli(argv)
    assert rc2 == 0, "second run failed; stderr={}".format(err2)
    log_second = integration_sandbox.call_log()
    search_calls_second = [c for c in log_second if c["verb"] == "search"]
    assert search_calls_second == [], "cache hit must skip jira.search()"
    # Output of cache hit must match output of cache miss byte-for-byte
    # (cache contract: same key → same output).
    assert _substitute_generated_at(out1) == _substitute_generated_at(out2)


# ---------------------------------------------------------------------------
# Unmapped status — spec § "Unmapped-status policy" maps to exit 2 with a
# message naming the offending raw status. This test feeds an in-window
# issue whose status doesn't appear under any canonical_states entry and
# asserts main() catches the timeline.UnmappedStatusError and exits 2.
# ---------------------------------------------------------------------------
def test_unmapped_status_exits_2_through_main(integration_sandbox, tmp_path):
    """Regression check for the wired exception handling.

    Pre-fix: UnmappedStatusError leaked from _run_pipeline as an uncaught
    exception. Post-fix: caught and mapped to EXIT_VALIDATION (2).
    """
    bad_fixture = tmp_path / "unmapped_status_fixture"
    bad_fixture.mkdir()
    (bad_fixture / "whoami.json").write_text('{"accountId": "test"}', encoding="utf-8")
    # One issue with a status ("Blocked") absent from the default state
    # config's canonical_states. The timeline walker raises on first
    # encounter.
    (bad_fixture / "search.jsonl").write_text(
        '{"key":"BAD-1","fields":{"created":"2026-01-02T00:00:00.000+0000",'
        '"status":{"name":"Blocked"},"issuetype":{"name":"Story"},'
        '"customfield_10001":"X"},"changelog":{"histories":[]}}\n',
        encoding="utf-8",
    )
    integration_sandbox.monkeypatch.setenv(
        "FLOW_METRICS_TEST_FIXTURE_DIR", str(bad_fixture)
    )
    rc, stdout, stderr = _run_cli([
        "--project", "BAD",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    assert rc == 2, "unmapped status must exit 2, got rc={} stderr={}".format(rc, stderr)
    assert "Blocked" in stderr, "error message must name the offending status"


# ---------------------------------------------------------------------------
# Test-isolation negative: misconfigured test fails loudly
# ---------------------------------------------------------------------------
def test_misconfigured_test_fails_loudly(monkeypatch, tmp_path):
    """Without ``FLOW_METRICS_JIRA_SCRIPT`` pointing at the replay, the
    pipeline must fail upstream-discovery rather than silently calling a
    real ``jira`` skill.

    This test deliberately bypasses the ``integration_sandbox`` fixture —
    the assertion is that the bypass surfaces as a discoverable failure,
    not a silent escape. (Without the sandbox there's still a chance the
    real ``jira`` skill exists on the developer's machine; we monkeypatch
    ``Path.home()`` to a nonexistent dir and chdir to ``tmp_path`` so the
    user-scope and project-scope candidates also fail.)
    """
    monkeypatch.delenv("FLOW_METRICS_JIRA_SCRIPT", raising=False)
    monkeypatch.delenv("FLOW_METRICS_JIRAALIGN_SCRIPT", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "noexist_home"))
    monkeypatch.chdir(tmp_path)

    rc, stdout, stderr = _run_cli([
        "--project", "ALPHA",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    assert rc == 2, "missing upstream must exit 2, got rc={} stderr={}".format(rc, stderr)
    assert "jira" in stderr and "not found" in stderr


# ---------------------------------------------------------------------------
# program_42 — Jira Align scope (placeholder — fixtures land in this PR;
# goldens are validated by the same byte-equal harness).
# ---------------------------------------------------------------------------
PROGRAM_42 = Path(__file__).resolve().parent / "fixtures" / "program_42"


def test_full_happy_path_program_scope(integration_sandbox):
    """--program-id 42 walks Jira Align for teams, then Jira for issues.

    Asserts:
    - byte-equal against ``golden.json``.
    - ``meta.per_team_double_counted == false`` (default state config
      ships ``team_field.kind = single_value``).
    - The run actually invokes ``jira-align`` (program scope's differentiator).
    - Every upstream call is in the read-only allowlist (plan line 1039).
    """
    integration_sandbox.use_fixture("program_42")
    rc, stdout, stderr = _run_cli([
        "--program-id", "42",
        "--align-join-field", "customfield_10001",
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    _assert_byte_equal(stdout, PROGRAM_42 / "golden.json")

    payload = json.loads(_substitute_generated_at(stdout).decode("utf-8"))
    assert payload["meta"]["per_team_double_counted"] is False

    _allowlisted_calls(integration_sandbox.call_log())
    align_calls = [c for c in integration_sandbox.call_log() if c["skill"] == "jira-align"]
    assert align_calls, "program scope must invoke jira-align"


def test_full_happy_path_program_scope_array_kind(integration_sandbox):
    """Same program-42 fixture but with ``team_field.kind = array`` — flips
    ``meta.per_team_double_counted`` to ``true``.

    Together with ``test_full_happy_path_program_scope`` (single_value /
    false) this covers both branches of the per-team double-count flag,
    per the brief: "Synthetic align responses must trigger
    meta.per_team_double_counted = true in one scenario and false in
    another."
    """
    integration_sandbox.use_fixture("program_42")
    state_override = PROGRAM_42 / "state.array.json"
    rc, stdout, stderr = _run_cli([
        "--program-id", "42",
        "--align-join-field", "customfield_10001",
        "--state-config", str(state_override),
        "--from", "2026-01-01", "--to", "2026-01-07",
        "--no-cache",
    ])
    assert rc == 0, "non-zero exit; stderr={}".format(stderr)
    _assert_byte_equal(stdout, PROGRAM_42 / "golden.array.json")

    payload = json.loads(_substitute_generated_at(stdout).decode("utf-8"))
    assert payload["meta"]["per_team_double_counted"] is True
