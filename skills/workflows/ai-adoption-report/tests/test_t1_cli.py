"""T1 contract tests for ai-adoption-report CLI scaffold.

Covers every test enumerated in docs/specs/ai-adoption-report-plan.md §T1.
The CLI module is invoked via ``main(argv=...)`` so each test controls
its own argv without touching the global process state.
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import pytest

import ai_adoption_report
from ai_adoption_report import (
    FORMAT_CHOICES,
    ValidationError,
    build_parser,
    main,
    parse_window_flag,
    validate_local_path,
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


def _ok_paths(tmp_path):
    """Return a small set of valid in-CWD paths usable in baseline-mode tests."""
    base = tmp_path / "baseline.json"
    curr = tmp_path / "current.json"
    out = tmp_path / "report.md"
    return str(base), str(curr), str(out)


# Spec § Inputs — flag → mode table. Subcommand --help text must list
# each of these.
_COMMON_FLAGS = ("--output", "--format", "--overwrite", "--title", "--verbose")
_MODE_FLAGS = {
    "baseline": _COMMON_FLAGS + ("--baseline", "--current", "--include-cohort-breakdown"),
    "cohort": _COMMON_FLAGS + ("--input",),
    "program": _COMMON_FLAGS + ("--inputs", "--window", "--include-cohort-breakdown"),
}


# ---------------------------------------------------------------------------
# Python version guard
# ---------------------------------------------------------------------------
def test_python_below_floor_exits_2():
    with pytest.raises(SystemExit) as exc:
        ai_adoption_report._check_python_version((3, 9, 7))
    assert exc.value.code == 2


def test_python_at_floor_does_not_exit():
    ai_adoption_report._check_python_version((3, 10, 0))
    ai_adoption_report._check_python_version((3, 11, 5))
    ai_adoption_report._check_python_version((4, 0, 0))


# ---------------------------------------------------------------------------
# --help
# ---------------------------------------------------------------------------
def test_help_exits_0():
    rc, out, _ = _run(["--help"])
    assert rc == 0
    for mode in ("baseline", "cohort", "program"):
        assert mode in out, "top-level --help missing subcommand {}".format(mode)


@pytest.mark.parametrize("mode", ["baseline", "cohort", "program"])
def test_subcommand_help_exits_0_and_lists_every_flag(mode):
    rc, out, _ = _run([mode, "--help"])
    assert rc == 0, "{} --help did not exit 0".format(mode)
    for flag in _MODE_FLAGS[mode]:
        assert flag in out, "{} --help is missing {}".format(mode, flag)


# ---------------------------------------------------------------------------
# Subcommand structure
# ---------------------------------------------------------------------------
def test_unknown_subcommand_exits_2():
    rc, _, _ = _run(["frobnicate", "--foo"])
    assert rc == 2


def test_missing_subcommand_exits_2():
    rc, _, _ = _run([])
    assert rc == 2


@pytest.mark.parametrize(
    "argv",
    [
        ["baseline", "--baseline", "b.json", "--current", "c.json", "--output", "o.md", "--bogus"],
        ["cohort", "--input", "i.json", "--output", "o.md", "--bogus"],
        ["program", "--inputs", "in", "--window", "2026-01-01..2026-03-31", "--output", "o.md", "--bogus"],
    ],
    ids=["baseline", "cohort", "program"],
)
def test_unknown_flag_exits_2(argv):
    rc, _, _ = _run(argv)
    assert rc == 2


# ---------------------------------------------------------------------------
# Required flags per mode
# ---------------------------------------------------------------------------
def test_baseline_requires_baseline_and_current(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Missing --current.
    rc, _, err = _run(["baseline", "--baseline", "b.json", "--output", "o.md"])
    assert rc == 2
    assert "--current" in err
    # Missing --baseline.
    rc, _, err = _run(["baseline", "--current", "c.json", "--output", "o.md"])
    assert rc == 2
    assert "--baseline" in err
    # Missing both.
    rc, _, err = _run(["baseline", "--output", "o.md"])
    assert rc == 2
    assert "--baseline" in err and "--current" in err


def test_cohort_requires_input(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run(["cohort", "--output", "o.md"])
    assert rc == 2
    assert "--input" in err


def test_program_requires_inputs_and_window(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Missing --window.
    rc, _, err = _run(["program", "--inputs", "indir", "--output", "o.md"])
    assert rc == 2
    assert "--window" in err
    # Missing --inputs.
    rc, _, err = _run(["program", "--window", "2026-01-01..2026-03-31", "--output", "o.md"])
    assert rc == 2
    assert "--inputs" in err
    # Missing both.
    rc, _, err = _run(["program", "--output", "o.md"])
    assert rc == 2
    assert "--inputs" in err and "--window" in err


# ---------------------------------------------------------------------------
# --window FROM..TO parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    [
        "2026-02-19T00:00:00Z..2026-12-31",  # T-suffix on FROM
        "2026-01-01..2026-12-31T00:00:00Z",  # T-suffix on TO
        "2026-2-19..2026-12-31",             # single-digit month
        "2026-02-19",                         # single date, no ..
        "2026-01-01..2026-06-30..2026-12-31",  # three dates
        "not-a-date..2026-12-31",            # non-ISO FROM
        "2026-01-01..not-a-date",            # non-ISO TO
        "..2026-12-31",                       # empty FROM
        "2026-01-01..",                       # empty TO
        "",                                   # empty string
        "2026-13-01..2026-12-31",            # invalid month
        "2026-02-30..2026-12-31",            # invalid day
    ],
)
def test_window_flag_not_two_iso_dates_exits_2(tmp_path, monkeypatch, value):
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run([
        "program",
        "--inputs", "indir",
        "--window", value,
        "--output", "o.md",
    ])
    assert rc == 2, "--window '{}' must exit 2".format(value)
    assert "--window" in err or "window" in err


def test_window_flag_returns_strings_verbatim():
    result = parse_window_flag("2026-01-01..2026-12-31")
    assert isinstance(result, tuple), "spec wants a 2-tuple, not a list"
    assert len(result) == 2
    a, b = result
    assert isinstance(a, str) and isinstance(b, str)
    assert a == "2026-01-01"
    assert b == "2026-12-31"


@pytest.mark.parametrize("trailing", ["\n", "\r", "\t", " "])
def test_window_flag_rejects_trailing_whitespace(trailing):
    # The regex anchors with \A and \Z (not ^ and $) so trailing whitespace
    # is rejected by the regex itself, not silently tolerated and then
    # caught downstream by date.fromisoformat.
    bad = "2026-01-01{}..2026-12-31".format(trailing)
    with pytest.raises(argparse.ArgumentTypeError):
        parse_window_flag(bad)


# ---------------------------------------------------------------------------
# Path-safety: every path-bearing flag must resolve inside CWD.
# ---------------------------------------------------------------------------
def _outside_path(tmp_path):
    """Return a path that resolves OUTSIDE the test's CWD.

    We chdir into ``tmp_path/work`` and use ``tmp_path`` itself as the
    outside-CWD location — guaranteed to be outside no matter where the
    OS puts the pytest tmpdir.
    """
    return str(tmp_path / "outside-cwd.json")


@pytest.mark.parametrize(
    "mode,flag",
    [
        ("baseline", "--baseline"),
        ("baseline", "--current"),
        ("baseline", "--output"),
        ("cohort", "--input"),
        ("cohort", "--output"),
        ("program", "--inputs"),
        ("program", "--output"),
    ],
)
def test_absolute_path_outside_cwd_exits_2(tmp_path, monkeypatch, mode, flag):
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    outside = _outside_path(tmp_path)

    if mode == "baseline":
        argv = ["baseline",
                "--baseline", "b.json",
                "--current", "c.json",
                "--output", "o.md"]
    elif mode == "cohort":
        argv = ["cohort", "--input", "i.json", "--output", "o.md"]
    else:
        argv = ["program",
                "--inputs", "indir",
                "--window", "2026-01-01..2026-03-31",
                "--output", "o.md"]

    # Replace the value of the flag-under-test with the outside-CWD path.
    idx = argv.index(flag)
    argv[idx + 1] = outside

    rc, _, err = _run(argv)
    assert rc == 2, "{} {} outside CWD must exit 2".format(mode, flag)
    # Pin both the flag-prefixed role name and the rule that fired — the
    # bare role substring ("baseline", "input", "output") collides with
    # too many other identifiers to be a real contract.
    assert "{}:".format(flag) in err, (
        "error must lead with the offending flag; got: {!r}".format(err)
    )
    assert "outside" in err or "current working directory" in err


def test_validate_local_path_accepts_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    p = validate_local_path("subdir/file.json", role="output")
    assert isinstance(p, pathlib.Path)
    assert p.is_absolute()


def test_validate_local_path_accepts_nonexistent_in_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Non-existent file inside CWD is fine — the file doesn't have to exist
    # yet (e.g. --output points at a yet-to-be-written report).
    p = validate_local_path(str(tmp_path / "will-be-created.md"), role="output")
    assert p == (tmp_path / "will-be-created.md").resolve()


def test_validate_local_path_rejects_null_byte(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValidationError) as exc:
        validate_local_path("ok\x00bad", role="output")
    assert "null byte" in str(exc.value)
    assert "output" in str(exc.value)


def test_validate_local_path_rejects_parent_traversal(tmp_path, monkeypatch):
    """A relative path with `..` that escapes CWD is rejected."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    with pytest.raises(ValidationError):
        validate_local_path("../escape.json", role="output")


# ---------------------------------------------------------------------------
# Validation runs BEFORE any file is read.
# ---------------------------------------------------------------------------
def test_validation_error_exits_2_before_any_file_read(tmp_path, monkeypatch):
    """Flag-combo / path-safety validation must fire before any file read.

    We monkey-patch ``pathlib.Path.read_text`` to raise unconditionally,
    then trigger a validation error (path outside CWD). The test passes
    iff exit 2 is returned without the patched read_text ever firing.
    """
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    called = {"read_text": 0}

    def boom(self, *a, **kw):
        called["read_text"] += 1
        raise AssertionError(
            "Path.read_text was invoked during T1 validation; nothing should read files yet"
        )

    monkeypatch.setattr(pathlib.Path, "read_text", boom)

    outside = str(tmp_path / "outside.json")
    rc, _, err = _run([
        "baseline",
        "--baseline", outside,
        "--current", "c.json",
        "--output", "o.md",
    ])
    assert rc == 2
    assert called["read_text"] == 0
    assert "--baseline:" in err


def test_stub_subcommand_returns_zero(tmp_path, monkeypatch):
    """With every flag valid and every path inside CWD, T1 stubs exit 0.

    The body just prints "not yet implemented" — later tasks replace each
    stub with the real implementation, but the harness wiring is settled
    in T1.
    """
    monkeypatch.chdir(tmp_path)
    b, c, o = _ok_paths(tmp_path)
    rc, out, _ = _run(["baseline", "--baseline", b, "--current", c, "--output", o])
    assert rc == 0
    assert "not yet implemented" in out


# ---------------------------------------------------------------------------
# --include-cohort-breakdown wiring (positive + negative across modes)
# ---------------------------------------------------------------------------
def test_include_cohort_breakdown_accepted_on_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b, c, o = _ok_paths(tmp_path)
    args = build_parser().parse_args([
        "baseline", "--baseline", b, "--current", c, "--output", o,
        "--include-cohort-breakdown",
    ])
    assert args.include_cohort_breakdown is True


def test_include_cohort_breakdown_default_false_on_baseline(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b, c, o = _ok_paths(tmp_path)
    args = build_parser().parse_args([
        "baseline", "--baseline", b, "--current", c, "--output", o,
    ])
    assert args.include_cohort_breakdown is False


def test_include_cohort_breakdown_accepted_on_program(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    o = str(tmp_path / "report.md")
    indir = str(tmp_path / "indir")
    args = build_parser().parse_args([
        "program",
        "--inputs", indir,
        "--window", "2026-01-01..2026-03-31",
        "--output", o,
        "--include-cohort-breakdown",
    ])
    assert args.include_cohort_breakdown is True


def test_include_cohort_breakdown_rejected_on_cohort(tmp_path, monkeypatch):
    """Spec table: cohort mode has no optional flags (—). The flag exists
    on baseline + program only; passing it to cohort must exit 2."""
    monkeypatch.chdir(tmp_path)
    rc, _, err = _run([
        "cohort", "--input", "i.json", "--output", "o.md",
        "--include-cohort-breakdown",
    ])
    assert rc == 2
    assert "include-cohort-breakdown" in err or "unrecognized" in err


# ---------------------------------------------------------------------------
# --format choices (contract: exactly markdown|json|both)
# ---------------------------------------------------------------------------
def test_format_choices_match_spec():
    assert set(FORMAT_CHOICES) == {"markdown", "json", "both"}


def test_format_default_is_both(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b, c, o = _ok_paths(tmp_path)
    args = build_parser().parse_args(["baseline", "--baseline", b, "--current", c, "--output", o])
    assert args.format == "both"


@pytest.mark.parametrize("value", ["markdown", "json", "both"])
def test_format_accepts_spec_values(tmp_path, monkeypatch, value):
    monkeypatch.chdir(tmp_path)
    b, c, o = _ok_paths(tmp_path)
    args = build_parser().parse_args([
        "baseline", "--baseline", b, "--current", c, "--output", o,
        "--format", value,
    ])
    assert args.format == value


def test_format_unknown_value_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, _, _ = _run([
        "baseline", "--baseline", "b.json", "--current", "c.json", "--output", "o.md",
        "--format", "yaml",
    ])
    assert rc == 2


# ---------------------------------------------------------------------------
# Subcommand stubs exit 0 with all three modes wired
# ---------------------------------------------------------------------------
def test_stub_cohort_returns_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run([
        "cohort",
        "--input", str(tmp_path / "in.json"),
        "--output", str(tmp_path / "out.md"),
    ])
    assert rc == 0
    assert "not yet implemented" in out


def test_stub_program_returns_zero(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc, out, _ = _run([
        "program",
        "--inputs", str(tmp_path / "indir"),
        "--window", "2026-01-01..2026-03-31",
        "--output", str(tmp_path / "out.md"),
    ])
    assert rc == 0
    assert "not yet implemented" in out


# ---------------------------------------------------------------------------
# Construction tests (parser shape)
# ---------------------------------------------------------------------------
def test_build_parser_has_all_three_subcommands():
    parser = build_parser()
    sub_actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
    assert sub_actions, "parser has no subparsers"
    assert set(sub_actions[0].choices) == {"baseline", "cohort", "program"}
