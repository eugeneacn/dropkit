"""T1 contract + construction tests for flow-metrics CLI scaffold.

Covers every test enumerated in docs/specs/flow-metrics-plan.md § T1 and
the corresponding contract tests in docs/specs/flow-metrics.md.

The CLI module is imported lazily inside helpers so each test can
control sys.argv-equivalents via main(argv=...).
"""
from __future__ import annotations

import io
import os
import sys
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

import flow_metrics
from flow_metrics import (
    ALL_METRICS,
    ValidationError,
    build_parser,
    compose_jql,
    confirm_overwrite,
    main,
    parse_window,
    validate_path,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _run(argv):
    """Run main(argv) and capture (rc, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return rc, out.getvalue(), err.getvalue()


# ---------------------------------------------------------------------------
# Python version guard
# ---------------------------------------------------------------------------
def test_python_below_floor_exits_2():
    with pytest.raises(SystemExit) as exc:
        flow_metrics._check_python_version((3, 9, 7))
    assert exc.value.code == 2


def test_python_at_floor_does_not_exit():
    # Should be a no-op (no SystemExit raised).
    flow_metrics._check_python_version((3, 10, 0))
    flow_metrics._check_python_version((3, 11, 5))
    flow_metrics._check_python_version((4, 0, 0))


# ---------------------------------------------------------------------------
# argparse / help
# ---------------------------------------------------------------------------
def test_help_exits_0():
    rc, out, err = _run(["--help"])
    assert rc == 0
    # Spec § Inputs synopsis flags — every one must appear in --help text.
    expected_flags = [
        "--project",
        "--team",
        "--program-id",
        "--portfolio-id",
        "--from",
        "--to",
        "--jql",
        "--align-filter",
        "--cohort-jql",
        "--metrics",
        "--state-config",
        "--issuetype-config",
        "--team-field-override",
        "--align-join-field",
        "--align-teams-path",
        "--include-subtasks",
        "--format",
        "--output",
        "--per-issue",
        "--no-cache",
        "--verbose",
    ]
    for flag in expected_flags:
        assert flag in out, "--help is missing {}".format(flag)


def test_unknown_flag_exits_2():
    rc, out, err = _run(["--project", "PROJ", "--bogus"])
    assert rc == 2


# ---------------------------------------------------------------------------
# Scope / required-flag / mutex validation
# ---------------------------------------------------------------------------
def test_requires_exactly_one_scope():
    """Spec § Inputs: exactly one of --project / --program-id / --portfolio-id."""
    # Zero scope flags -> exit 2 and name the missing flags.
    rc, _, err = _run([])
    assert rc == 2, "no scope flags must exit 2"
    assert "--project" in err
    assert "--program-id" in err
    assert "--portfolio-id" in err

    # Each pairwise combination of two scope flags -> exit 2.
    for combo in (
        ["--project", "PROJ", "--program-id", "42"],
        ["--project", "PROJ", "--portfolio-id", "7"],
        ["--program-id", "42", "--portfolio-id", "7"],
    ):
        rc, _, _ = _run(combo)
        assert rc == 2, "two scope flags must exit 2 (combo: {})".format(combo)

    # All three scope flags -> exit 2.
    rc, _, _ = _run(["--project", "PROJ", "--program-id", "42", "--portfolio-id", "7"])
    assert rc == 2


def test_team_only_valid_with_project():
    rc, out, err = _run(["--team", "Foo", "--program-id", "42"])
    assert rc == 2
    assert "--team" in err


def test_team_with_project_is_ok():
    rc, out, err = _run(["--project", "PROJ", "--team", "Foo"])
    assert rc == 0  # T1 stub


def test_per_issue_requires_output_flag():
    rc, out, err = _run(["--project", "PROJ", "--per-issue"])
    assert rc == 2
    assert "--per-issue" in err and "--output" in err


# ---------------------------------------------------------------------------
# Window resolution
# ---------------------------------------------------------------------------
def test_default_window_is_last_90_days_utc():
    # Pin "now" so the test is hermetic.
    fixed = datetime(2026, 5, 19, 14, 0, 0, tzinfo=timezone.utc)
    w = parse_window(None, None, now=fixed)
    assert w.to_date == date(2026, 5, 19)
    assert w.from_date == date(2026, 2, 18)  # 2026-05-19 - 90 days
    # to - from = 90 days
    assert (w.to_date - w.from_date).days == 90


def test_to_is_inclusive_of_named_day():
    # Plan T1: "--from 2026-04-30 --to 2026-05-19 resolves to
    # [2026-04-30 00:00 UTC, 2026-05-20 00:00 UTC)"
    w = parse_window("2026-04-30", "2026-05-19")
    assert w.from_utc == datetime(2026, 4, 30, 0, 0, 0, tzinfo=timezone.utc)
    assert w.to_exclusive_utc == datetime(2026, 5, 20, 0, 0, 0, tzinfo=timezone.utc)


def test_window_from_after_to_rejected():
    with pytest.raises(ValidationError):
        parse_window("2026-05-20", "2026-05-19")


def test_window_invalid_date_format_rejected():
    with pytest.raises(ValidationError):
        parse_window("not-a-date", "2026-05-19")
    with pytest.raises(ValidationError):
        parse_window("2026-05-19", "20260519")


def test_window_uses_clock_seam(monkeypatch):
    """Window default-resolution must consult clock.today_utc (the seam)."""
    fixed = datetime(2026, 1, 15, 6, 30, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(flow_metrics.clock, "today_utc", lambda: fixed)
    w = parse_window(None, None)
    assert w.to_date == date(2026, 1, 15)


def test_window_naive_now_treated_as_utc():
    """Defensive: a naive `now` must not be reinterpreted via local-tz.

    Picked 23:59:59 so any east-of-UTC environment that mistakenly treated
    naive as local would roll the date forward to May 20.
    """
    naive = datetime(2026, 5, 19, 23, 59, 59)  # no tzinfo
    w = parse_window(None, None, now=naive)
    assert w.to_date == date(2026, 5, 19)
    assert w.from_utc.tzinfo is timezone.utc
    assert w.to_exclusive_utc.tzinfo is timezone.utc


# ---------------------------------------------------------------------------
# Validation runs before any upstream call (T1: easy to assert since the
# upstream layer doesn't exist yet; validation errors return exit 2 from
# main() before reaching the stub print).
# ---------------------------------------------------------------------------
def test_validation_error_exits_2_before_any_upstream_call():
    rc, out, err = _run(["--project", "PROJ", "--program-id", "42"])
    assert rc == 2
    # Stub message must NOT appear.
    assert "not yet implemented" not in out


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------
@pytest.mark.skipif(os.name == "nt", reason="POSIX system roots")
def test_rejects_output_in_etc():
    rc, out, err = _run(["--project", "PROJ", "--output", "/etc/foo"])
    assert rc == 2
    assert "/etc/foo" in err or "system root" in err


@pytest.mark.skipif(os.name != "nt", reason="Windows system roots")
def test_rejects_output_in_windows_dir():
    rc, out, err = _run(["--project", "PROJ", "--output", "C:\\Windows\\foo.json"])
    assert rc == 2


def test_rejects_output_with_null_byte():
    rc, out, err = _run(["--project", "PROJ", "--output", "ok\x00bad"])
    assert rc == 2
    assert "null byte" in err


@pytest.mark.skipif(os.name == "nt", reason="POSIX /proc")
def test_rejects_state_config_in_proc():
    rc, out, err = _run(["--project", "PROJ", "--state-config", "/proc/self/maps"])
    assert rc == 2


@pytest.mark.skipif(os.name == "nt", reason="POSIX /etc")
def test_rejects_issuetype_config_in_etc():
    rc, out, err = _run(["--project", "PROJ", "--issuetype-config", "/etc/passwd"])
    assert rc == 2


def test_validate_path_accepts_tmp(tmp_path):
    p = validate_path(str(tmp_path / "out.json"), "output")
    assert isinstance(p, Path)


# ---------------------------------------------------------------------------
# Overwrite-confirm helper (T1 ships the TTY-detection helper; T10 wires
# the actual write path)
# ---------------------------------------------------------------------------
def test_overwrite_aborts_without_tty(tmp_path, monkeypatch):
    existing = tmp_path / "out.json"
    existing.write_text("prior")
    # Force no-TTY explicitly so the test is deterministic under pytest -s
    # (where stdin would otherwise still be a real terminal).
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    rc, out, err = _run(["--project", "PROJ", "--output", str(existing)])
    assert rc == 1
    # File must still hold its prior contents — abort path doesn't write.
    assert existing.read_text() == "prior"


def test_overwrite_yes_flag_through_cli(tmp_path, monkeypatch):
    """`--yes` bypasses the abort even with an existing file and no TTY."""
    existing = tmp_path / "out.json"
    existing.write_text("prior")
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False, raising=False)
    rc, out, err = _run(["--project", "PROJ", "--output", str(existing), "--yes"])
    # T1 stub still doesn't write, but the abort must NOT fire.
    assert rc == 0
    assert "not yet implemented" in out


def test_overwrite_yes_bypasses_prompt(tmp_path):
    existing = tmp_path / "out.json"
    existing.write_text("prior")
    assert confirm_overwrite(existing, yes=True) is True


def test_overwrite_helper_no_tty_returns_false(tmp_path):
    existing = tmp_path / "out.json"
    existing.write_text("prior")
    assert confirm_overwrite(existing, yes=False, stdin_isatty=False, stdout_isatty=False) is False


def test_overwrite_helper_tty_yes_response(tmp_path):
    existing = tmp_path / "out.json"
    existing.write_text("prior")
    assert (
        confirm_overwrite(
            existing,
            yes=False,
            stdin_isatty=True,
            stdout_isatty=True,
            prompt_response="y",
        )
        is True
    )


def test_overwrite_helper_tty_no_response(tmp_path):
    existing = tmp_path / "out.json"
    existing.write_text("prior")
    assert (
        confirm_overwrite(
            existing,
            yes=False,
            stdin_isatty=True,
            stdout_isatty=True,
            prompt_response="",
        )
        is False
    )


def test_overwrite_helper_nonexistent_path_allowed(tmp_path):
    not_there = tmp_path / "does_not_exist.json"
    assert confirm_overwrite(not_there, yes=False, stdin_isatty=False, stdout_isatty=False) is True


# ---------------------------------------------------------------------------
# JQL composition (contract tests from spec § Inputs)
# ---------------------------------------------------------------------------
def test_jql_user_clause_parenthesized():
    # `--jql "a OR b"` against a project scope clause must yield
    # `(<scope>) AND (a OR b) ORDER BY key ASC` — pinned byte-for-byte
    # so a buggy implementation that mis-parenthesizes or adds extra
    # tokens can't slip past.
    assert (
        compose_jql("project = PROJ", "a OR b")
        == "(project = PROJ) AND (a OR b) ORDER BY key ASC"
    )


def test_align_filter_user_clause_parenthesized():
    # Same parenthesization rule for the OData side. compose_jql is a
    # string helper; the OData wrapper reuses the same shape.
    assert (
        compose_jql(
            "programID eq 42",
            "createDate gt 2026-01-01",
            order_by_key=False,
        )
        == "(programID eq 42) AND (createDate gt 2026-01-01)"
    )


def test_compose_jql_no_user_clause():
    out = compose_jql("project = PROJ", None)
    assert out == "project = PROJ ORDER BY key ASC"


def test_compose_jql_empty_user_clause():
    out = compose_jql("project = PROJ", "   ")
    assert out == "project = PROJ ORDER BY key ASC"


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------
def test_build_parser_has_every_spec_flag():
    parser = build_parser()
    actions = {a.dest for a in parser._actions}
    # Spot every dest we depend on downstream.
    for dest in (
        "project",
        "team",
        "program_id",
        "portfolio_id",
        "from_date",
        "to_date",
        "jql",
        "align_filter",
        "cohort_jql",
        "metrics",
        "state_config",
        "issuetype_config",
        "team_field_override",
        "align_join_field",
        "align_teams_path",
        "include_subtasks",
        "format",
        "output",
        "per_issue",
        "no_cache",
        "verbose",
        "yes",
    ):
        assert dest in actions, "parser missing dest {}".format(dest)


def test_metric_names_complete():
    # Spec § Inputs --metrics table.
    expected = {
        "cycle_time",
        "lead_time",
        "throughput",
        "wip",
        "flow_load",
        "rework_rate",
        "flow_time",
        "flow_efficiency",
        "flow_distribution",
        "defect_ratio",
    }
    assert set(ALL_METRICS) == expected


def test_unknown_metric_rejected():
    rc, out, err = _run(["--project", "PROJ", "--metrics", "throughput,bogus"])
    assert rc == 2
    assert "bogus" in err


def test_stub_command_path_returns_zero():
    rc, out, err = _run(["--project", "PROJ"])
    assert rc == 0
    assert "not yet implemented" in out


def test_stub_command_path_project_scope_in_output():
    rc, out, err = _run(
        ["--project", "PROJ", "--from", "2026-01-01", "--to", "2026-01-31"]
    )
    assert rc == 0
    assert "project=PROJ" in out
    assert "2026-01-01" in out
    assert "2026-01-31" in out
