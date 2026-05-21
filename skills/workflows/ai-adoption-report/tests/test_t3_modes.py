"""T3 contract tests: baseline + cohort modes.

Covers every test enumerated in docs/specs/ai-adoption-report-plan.md
§T3, plus a smoke-test that the CLI dispatch wires baseline/cohort to
the new :mod:`ai_adoption_report.modes` runners.

Each test runs the CLI via ``main(argv)`` so the path-safety wrapper
in :func:`ai_adoption_report.main` is exercised end-to-end. Fixtures
are copied into ``tmp_path`` and the working directory is switched to
``tmp_path`` so the spec's "inside CWD" rule is satisfied.
"""
from __future__ import annotations

import io
import json
import shutil
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from ai_adoption_report import ValidationError, main
from ai_adoption_report.modes import (
    ReportData,
    canonical_scope_repr,
    run_baseline,
    run_cohort,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "inputs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _copy(name: str, dest_dir: Path, *, as_name: str | None = None) -> Path:
    """Copy a fixture into ``dest_dir`` and return the destination path."""
    src = FIXTURES_DIR / name
    dst = dest_dir / (as_name or name)
    shutil.copyfile(src, dst)
    return dst


def _write_json(path: Path, doc: Dict[str, Any]) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _run(argv) -> Tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        try:
            rc = main(argv)
        except SystemExit as e:
            rc = e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    return rc, out.getvalue(), err.getvalue()


def _baseline_doc(
    *,
    scope: Dict[str, Any],
    window_from: str,
    window_to: str,
    state_sha: str = "a" * 64,
    issuetype_sha: str = "b" * 64,
    cohort_jql: str | None = None,
    cohort_breakdown: Dict[str, Any] | None = None,
    per_team: Any = None,
    aggregates: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "caller": "test-account",
        "scope": scope,
        "window": {"from": window_from, "to": window_to},
        "state_config_sha": state_sha,
        "issuetype_config_sha": issuetype_sha,
        "schema_version": "1.0",
        "generated_at": "2026-07-02T08:00:00Z",
    }
    if cohort_jql is not None:
        meta["cohort_jql"] = cohort_jql
    doc: Dict[str, Any] = {
        "meta": meta,
        "aggregates": aggregates if aggregates is not None else {"throughput": 50},
    }
    if cohort_breakdown is not None:
        doc["cohort_breakdown"] = cohort_breakdown
    if per_team is not None:
        doc["per_team"] = per_team
    return doc


# ---------------------------------------------------------------------------
# canonical_scope_repr (spec lines 510-515)
# ---------------------------------------------------------------------------
def test_canonical_scope_repr_project_team():
    out = canonical_scope_repr({"project": "PROJ", "team": "Foo"}, "project+team")
    assert out == "kind=project+team;project=PROJ;team=Foo;program_id=;portfolio_id="


def test_canonical_scope_repr_portfolio():
    out = canonical_scope_repr({"portfolio_id": "P1"}, "portfolio")
    assert out == "kind=portfolio;project=;team=;program_id=;portfolio_id=P1"


# ---------------------------------------------------------------------------
# Baseline mode
# ---------------------------------------------------------------------------
def test_baseline_scope_mismatch_exits_2_with_both_scopes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b = _copy("baseline_q1_alpha.json", tmp_path)
    c = _copy("current_q2_beta.json", tmp_path)
    rc, _, err = _run(
        ["baseline", "--baseline", str(b), "--current", str(c), "--output", "o.md"]
    )
    assert rc == 2
    # Spec line 155: "exit 2 with both scopes printed". Assert each
    # scope's dict-repr appears verbatim in stderr.
    assert "'project': 'ALPHA'" in err
    assert "'project': 'BETA'" in err


def test_baseline_window_overlap_exits_2(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Baseline 2024-01-01..2024-04-30, current 2024-03-01..2024-06-30.
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2024-01-01",
            window_to="2024-04-30",
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2024-03-01",
            window_to="2024-06-30",
        ),
    )
    rc, _, err = _run(
        ["baseline", "--baseline", str(base), "--current", str(curr), "--output", "o.md"]
    )
    assert rc == 2
    assert "2024-01-01" in err
    assert "2024-04-30" in err
    assert "2024-03-01" in err
    assert "2024-06-30" in err
    assert "overlap" in err.lower()


def test_baseline_back_to_back_windows_allowed(tmp_path, monkeypatch):
    """Spec line 159: equal endpoints (back-to-back) are allowed."""
    monkeypatch.chdir(tmp_path)
    b = _copy("baseline_q1_alpha.json", tmp_path)
    c = _copy("current_back_to_back_alpha.json", tmp_path)
    rc, out, err = _run(
        ["baseline", "--baseline", str(b), "--current", str(c), "--output", "o.md"]
    )
    assert rc == 0, "unexpected exit; stderr={!r}".format(err)
    assert "overlap" not in err.lower()
    # T3 still prints repr(ReportData) until T7 lands.
    assert "ReportData" in out


def test_baseline_config_sha_drift_emits_note_and_renders_deltas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            state_sha="a" * 64,
            issuetype_sha="b" * 64,
            aggregates={"throughput": 50, "wip": 5},
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            state_sha="c" * 64,  # drift
            issuetype_sha="b" * 64,
            aggregates={"throughput": 75, "wip": 6},
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=False)
    )
    drift_notes = [n for n in report.notes if n.startswith("config-sha-drift:")]
    assert len(drift_notes) == 1
    assert "state_config_sha" in drift_notes[0]
    assert "a" * 64 in drift_notes[0]
    assert "c" * 64 in drift_notes[0]
    # Deltas still computed despite drift.
    assert report.deltas, "deltas dict must be non-empty when both sides carry metrics"
    assert "throughput" in report.deltas


def test_baseline_include_cohort_breakdown_without_cohort_noops_with_note(
    tmp_path, monkeypatch
):
    """Spec lines 171-172: flag no-ops silently with a notes entry when
    either input lacks cohort_breakdown."""
    monkeypatch.chdir(tmp_path)
    # Baseline has cohort_breakdown; current does not.
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            cohort_jql="labels = ai",
            cohort_breakdown={"cohort": {"throughput": 30}, "control": {"throughput": 20}},
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=True)
    )
    assert report.cohort_deltas is None
    noop_notes = [
        n for n in report.notes if n.startswith("cohort-breakdown-absent:")
    ]
    assert len(noop_notes) == 1
    assert "curr.json" in noop_notes[0]


def test_baseline_include_cohort_breakdown_jql_mismatch_omits_section_with_note(
    tmp_path, monkeypatch
):
    """Spec lines 173-175: section omitted, literal mismatch note."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            cohort_jql="labels = ai",
            cohort_breakdown={"cohort": {"throughput": 30}, "control": {"throughput": 20}},
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            cohort_jql="labels = ai-tools",
            cohort_breakdown={"cohort": {"throughput": 40}, "control": {"throughput": 30}},
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=True)
    )
    assert report.cohort_deltas is None
    mismatch_notes = [
        n for n in report.notes if n.startswith("cohort-jql-mismatch:")
    ]
    assert len(mismatch_notes) == 1
    # Literal form per spec lines 173-175.
    assert mismatch_notes[0] == (
        "cohort-jql-mismatch: labels = ai vs labels = ai-tools; "
        "cohort breakdown comparison omitted"
    )


def test_baseline_per_team_present_emits_ignored_note(tmp_path, monkeypatch):
    """Spec lines 177-183: per_team is ignored; a notes entry records
    the basename when either input has a non-empty per_team."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            per_team=[{"team": "Foo", "aggregates": {"throughput": 20}}],
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=False)
    )
    ignored = [
        n for n in report.notes
        if "ignored in baseline mode" in n and "base.json" in n
    ]
    assert len(ignored) == 1
    # Literal form per spec lines 180-182.
    assert ignored[0] == (
        "per_team data present in base.json; ignored in baseline mode "
        "(use program mode for multi-team rollup)"
    )


def test_baseline_returns_report_with_expected_shape(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b = _copy("baseline_q1_alpha.json", tmp_path)
    c = _copy("current_q2_alpha.json", tmp_path)
    report = run_baseline(
        Namespace(baseline=b, current=c, include_cohort_breakdown=False)
    )
    assert isinstance(report, ReportData)
    assert report.mode == "baseline"
    assert "Baseline window:" in report.header_line
    assert "Current window:" in report.header_line
    assert "Scope:" in report.header_line
    assert "kind=project" in report.header_line
    assert len(report.inputs) == 2
    assert report.per_scope_rows is None
    assert report.cohort_deltas is None
    assert "throughput" in report.deltas


# ---------------------------------------------------------------------------
# Cohort mode
# ---------------------------------------------------------------------------
def test_cohort_input_without_cohort_breakdown_exits_2(tmp_path, monkeypatch):
    """Spec line 191: literal error string."""
    monkeypatch.chdir(tmp_path)
    inp = _copy("project_basic.json", tmp_path)
    rc, _, err = _run(
        ["cohort", "--input", str(inp), "--output", "o.md"]
    )
    assert rc == 2
    assert (
        "--input was not produced with --cohort-jql; no "
        "cohort_breakdown block present" in err
    )


def test_cohort_emits_cohort_vs_control_deltas(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    inp = _write_json(
        tmp_path / "cohort.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            cohort_jql="labels = ai",
            cohort_breakdown={
                "cohort": {"throughput": 40, "wip": 6},
                "control": {"throughput": 30, "wip": 5},
            },
        ),
    )
    report = run_cohort(Namespace(input=inp))
    assert report.mode == "cohort"
    assert report.cohort_deltas is None  # cohort mode's primary deltas ARE the breakdown
    assert "throughput" in report.deltas
    # Side A=control (30), side B=cohort (40) → +10 abs.
    assert report.deltas["throughput"]["a"] == 30
    assert report.deltas["throughput"]["b"] == 40
    assert report.deltas["throughput"]["abs"] == 10
    # Header line per spec line 438.
    assert "Window:" in report.header_line
    assert "Cohort JQL:" in report.header_line
    assert "labels = ai" in report.header_line


def test_cohort_cli_dispatch_smoke(tmp_path, monkeypatch):
    """End-to-end: CLI baseline + cohort exit 0 with valid fixtures."""
    monkeypatch.chdir(tmp_path)
    inp = _write_json(
        tmp_path / "cohort.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            cohort_jql="labels = ai",
            cohort_breakdown={
                "cohort": {"throughput": 40},
                "control": {"throughput": 30},
            },
        ),
    )
    rc, out, err = _run(
        ["cohort", "--input", str(inp), "--output", "o.md"]
    )
    assert rc == 0, "stderr={!r}".format(err)
    assert "ReportData" in out


def test_baseline_cli_dispatch_smoke(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    b = _copy("baseline_q1_alpha.json", tmp_path)
    c = _copy("current_q2_alpha.json", tmp_path)
    rc, out, err = _run(
        ["baseline", "--baseline", str(b), "--current", str(c), "--output", "o.md"]
    )
    assert rc == 0, "stderr={!r}".format(err)
    assert "ReportData" in out


# ---------------------------------------------------------------------------
# Notes-merge contract: T5 notes flow onto ReportData.notes (T7 sorts).
# ---------------------------------------------------------------------------
def test_baseline_t5_notes_concatenated_unsorted(tmp_path, monkeypatch):
    """Plan §T5 "Notes merge contract": T3 concatenates T5's notes onto
    ReportData.notes in append order. T7 sorts. Verify by triggering a
    T5 ``metric_absent`` note (asymmetric metrics) and confirming the
    note string appears verbatim on ReportData.notes."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            aggregates={"throughput": 10},
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            # Add an extra metric so the absent-side note fires.
            aggregates={"throughput": 12, "wip": 8},
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=False)
    )
    assert any("wip absent in baseline; cell omitted" == n for n in report.notes), \
        "T5 absent-side note must appear on ReportData.notes; got {!r}".format(
            report.notes
        )


# ---------------------------------------------------------------------------
# Adversarial-review additions: gaps in the original test set
# ---------------------------------------------------------------------------
def test_baseline_issuetype_config_sha_drift_emits_note(tmp_path, monkeypatch):
    """Spec line 161 names both ``state_config_sha`` AND
    ``issuetype_config_sha``. The original drift test only covered state;
    this one pins the issuetype branch."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            state_sha="a" * 64,
            issuetype_sha="b" * 64,
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            state_sha="a" * 64,
            issuetype_sha="d" * 64,  # drift
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=False)
    )
    drift = [n for n in report.notes if n.startswith("config-sha-drift:")]
    assert len(drift) == 1
    assert "issuetype_config_sha" in drift[0]
    assert "d" * 64 in drift[0]


def test_baseline_both_sha_drift_emits_two_notes(tmp_path, monkeypatch):
    """When both SHAs drift simultaneously, both notes fire."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            state_sha="a" * 64,
            issuetype_sha="b" * 64,
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            state_sha="c" * 64,
            issuetype_sha="d" * 64,
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=False)
    )
    drift = [n for n in report.notes if n.startswith("config-sha-drift:")]
    assert len(drift) == 2
    sha_names = {"state_config_sha", "issuetype_config_sha"}
    assert {sha for n in drift for sha in sha_names if sha in n} == sha_names


def test_baseline_include_cohort_breakdown_happy_path_populates_cohort_deltas(
    tmp_path, monkeypatch
):
    """Spec lines 167-170 happy branch: both inputs have cohort_breakdown
    with matching JQL → cohort_deltas is populated and rendered through
    DeltaResult.to_dict (so T7 sees the canonical shape)."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            cohort_jql="labels = ai",
            cohort_breakdown={
                "cohort": {"throughput": 30, "wip": 4},
                "control": {"throughput": 20, "wip": 3},
            },
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            cohort_jql="labels = ai",
            cohort_breakdown={
                "cohort": {"throughput": 50, "wip": 6},
                "control": {"throughput": 25, "wip": 4},
            },
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=True)
    )
    assert report.cohort_deltas is not None
    # to_dict shape: each scalar maps to {a, b, abs, pct}.
    assert report.cohort_deltas["throughput"]["a"] == 30
    assert report.cohort_deltas["throughput"]["b"] == 50
    assert report.cohort_deltas["throughput"]["abs"] == 20
    # No JQL-mismatch / absent notes when the happy path runs.
    assert not any(n.startswith("cohort-jql-mismatch:") for n in report.notes)
    assert not any(n.startswith("cohort-breakdown-absent:") for n in report.notes)


def test_baseline_cohort_breakdown_absent_when_baseline_lacks_it(
    tmp_path, monkeypatch
):
    """Coverage parallel to the existing 'current lacks it' test. The
    absent-noop branch must fire identically when the baseline side is
    the one missing the block."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            cohort_jql="labels = ai",
            cohort_breakdown={"cohort": {"throughput": 5}, "control": {"throughput": 3}},
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=True)
    )
    assert report.cohort_deltas is None
    noop = [n for n in report.notes if n.startswith("cohort-breakdown-absent:")]
    assert len(noop) == 1
    assert "base.json" in noop[0]
    assert "curr.json" not in noop[0]


def test_baseline_cohort_breakdown_absent_lists_both_when_both_lack_it(
    tmp_path, monkeypatch
):
    """When *both* sides lack cohort_breakdown the note names both
    basenames (alphabetical). One note total — not two."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=True)
    )
    noop = [n for n in report.notes if n.startswith("cohort-breakdown-absent:")]
    assert len(noop) == 1, "expected exactly one absent-noop note, got {!r}".format(noop)
    assert "base.json" in noop[0]
    assert "curr.json" in noop[0]


def test_baseline_window_overlap_by_one_day_exits_2(tmp_path, monkeypatch):
    """Boundary regression: baseline.window.to one day past current.window.from
    must still exit 2. Guards against an off-by-one ``>=`` vs ``>`` bug."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-04-01",
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-03-31",
            window_to="2026-06-30",
        ),
    )
    rc, _, err = _run(
        ["baseline", "--baseline", str(base), "--current", str(curr), "--output", "o.md"]
    )
    assert rc == 2
    assert "overlap" in err.lower()


def test_baseline_per_team_in_current_only_emits_note_naming_current(
    tmp_path, monkeypatch
):
    """Spec line 180-182: the note names whichever input has per_team. The
    original test exercised baseline-side; this covers current-side."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
            per_team=[{"team": "Bar", "aggregates": {"throughput": 15}}],
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=False)
    )
    ignored = [n for n in report.notes if "ignored in baseline mode" in n]
    assert len(ignored) == 1
    assert "curr.json" in ignored[0]
    assert "base.json" not in ignored[0]


def test_baseline_per_team_empty_list_emits_no_note(tmp_path, monkeypatch):
    """Spec wording: 'non-empty per_team'. An explicit empty list must
    NOT trigger the note. Defensive check — T2 happily passes [] through."""
    monkeypatch.chdir(tmp_path)
    base = _write_json(
        tmp_path / "base.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            per_team=[],
        ),
    )
    curr = _write_json(
        tmp_path / "curr.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-04-01",
            window_to="2026-06-30",
        ),
    )
    report = run_baseline(
        Namespace(baseline=base, current=curr, include_cohort_breakdown=False)
    )
    assert not any("ignored in baseline mode" in n for n in report.notes)


def test_run_baseline_raises_validation_error_on_scope_mismatch(tmp_path, monkeypatch):
    """Library-level contract: run_baseline raises ValidationError (not
    SystemExit) so non-CLI callers can catch and react. The CLI wrapper
    translates this into exit 2."""
    monkeypatch.chdir(tmp_path)
    b = _copy("baseline_q1_alpha.json", tmp_path)
    c = _copy("current_q2_beta.json", tmp_path)
    with pytest.raises(ValidationError) as exc:
        run_baseline(Namespace(baseline=b, current=c, include_cohort_breakdown=False))
    assert "scope" in str(exc.value).lower()


def test_run_cohort_raises_validation_error_when_breakdown_missing(tmp_path, monkeypatch):
    """Spec line 191 literal error string surfaces as ValidationError text."""
    monkeypatch.chdir(tmp_path)
    inp = _copy("project_basic.json", tmp_path)
    with pytest.raises(ValidationError) as exc:
        run_cohort(Namespace(input=inp))
    assert str(exc.value) == (
        "--input was not produced with --cohort-jql; no "
        "cohort_breakdown block present"
    )


def test_cohort_t5_notes_concatenated_unsorted(tmp_path, monkeypatch):
    """Cohort-mode counterpart to the baseline notes-merge test. T5's
    notes must flow onto ReportData.notes with side labels reflecting
    ``("control", "cohort")``."""
    monkeypatch.chdir(tmp_path)
    inp = _write_json(
        tmp_path / "cohort.json",
        _baseline_doc(
            scope={"project": "ALPHA"},
            window_from="2026-01-01",
            window_to="2026-03-31",
            cohort_jql="labels = ai",
            cohort_breakdown={
                # cohort has an extra metric → T5 emits "wip absent in control".
                "cohort": {"throughput": 40, "wip": 6},
                "control": {"throughput": 30},
            },
        ),
    )
    report = run_cohort(Namespace(input=inp))
    assert any(
        n == "wip absent in control; cell omitted" for n in report.notes
    ), "expected T5 absent-side note with 'control' label; got {!r}".format(
        report.notes
    )
