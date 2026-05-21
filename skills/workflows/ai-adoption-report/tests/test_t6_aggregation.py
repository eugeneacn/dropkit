"""T6 contract tests: program-mode aggregation engine.

Covers every test listed in docs/specs/ai-adoption-report-plan.md §T6
(spec lines 593-616) plus the additional invariants the task brief
calls out:

- single-scope sanity (aggregate equals the scope it consumed),
- throughput per-week window normalisation (spec line 373),
- canonical insertion order across top-level metric keys,
- per-scope row canonical sort.

Most aggregation tests build :class:`ProgramScope` objects in-memory
because the math is the unit under test and the T4 discovery pipeline
is verified separately. The end-to-end runs (run_program with a real
inputs directory) verify the wiring + notes-merge + header line.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from ai_adoption_report.aggregation import (
    aggregate_cohort_side,
    aggregate_non_cohort,
    weighted_sum_and_average,
)
from ai_adoption_report.delta import CANONICAL_METRIC_ORDER
from ai_adoption_report.modes import ReportData, run_program
from ai_adoption_report.program_discovery import ProgramScope


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
DEFAULT_WINDOW = ("2026-01-01", "2026-01-31")


def _scope(
    *,
    scope: Dict[str, Any] = None,
    scope_kind: str = "project",
    aggregates: Dict[str, Any] = None,
    cohort_breakdown: Optional[Dict[str, Any]] = None,
    source_basename: str = "scope.json",
    from_per_team: bool = False,
    cohort_jql: Optional[str] = None,
) -> ProgramScope:
    return ProgramScope(
        scope=scope if scope is not None else {"project": "PROJ"},
        scope_kind=scope_kind,
        aggregates=aggregates if aggregates is not None else {},
        cohort_breakdown=cohort_breakdown,
        source_basename=source_basename,
        from_per_team=from_per_team,
        cohort_jql=cohort_jql,
        per_team_double_counted=False,
    )


def _meta(
    scope: Dict[str, Any],
    *,
    window: Tuple[str, str] = DEFAULT_WINDOW,
    cohort_jql: Optional[str] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "caller": "test",
        "scope": scope,
        "window": {"from": window[0], "to": window[1]},
        "state_config_sha": "a" * 8,
        "issuetype_config_sha": "b" * 8,
        "schema_version": "1.0",
        "generated_at": "2026-02-01T00:00:00Z",
    }
    if cohort_jql is not None:
        meta["cohort_jql"] = cohort_jql
    return meta


def _write_input(
    dir_path: Path,
    basename: str,
    scope: Dict[str, Any],
    *,
    aggregates: Optional[Dict[str, Any]] = None,
    cohort_breakdown: Optional[Dict[str, Any]] = None,
    per_team: Optional[List[Dict[str, Any]]] = None,
    cohort_jql: Optional[str] = None,
    window: Tuple[str, str] = DEFAULT_WINDOW,
) -> Path:
    doc: Dict[str, Any] = {
        "meta": _meta(scope, window=window, cohort_jql=cohort_jql),
        "aggregates": aggregates if aggregates is not None else {},
    }
    if cohort_breakdown is not None:
        doc["cohort_breakdown"] = cohort_breakdown
    if per_team is not None:
        doc["per_team"] = per_team
    path = dir_path / basename
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


def _args(
    inputs_dir: Path,
    *,
    window: Tuple[str, str] = DEFAULT_WINDOW,
    include_cohort_breakdown: bool = False,
) -> argparse.Namespace:
    return argparse.Namespace(
        inputs=str(inputs_dir),
        window=window,
        include_cohort_breakdown=include_cohort_breakdown,
    )


# ---------------------------------------------------------------------------
# weighted_sum_and_average
# ---------------------------------------------------------------------------
def test_weighted_sum_and_average_basic():
    sum_w, mean = weighted_sum_and_average([0.5, 0.4], [10, 20])
    assert sum_w == 30
    assert mean == pytest.approx((0.5 * 10 + 0.4 * 20) / 30)


def test_weighted_sum_and_average_zero_weights_returns_none():
    sum_w, mean = weighted_sum_and_average([0.5, 0.4], [0, 0])
    assert sum_w == 0
    assert mean is None


def test_weighted_sum_and_average_skips_none_values():
    sum_w, mean = weighted_sum_and_average([0.5, None, 0.4], [10, 99, 20])
    # None value's weight (99) is skipped entirely
    assert sum_w == 30
    assert mean == pytest.approx((0.5 * 10 + 0.4 * 20) / 30)


# ---------------------------------------------------------------------------
# Plan-listed tests
# ---------------------------------------------------------------------------
def test_program_throughput_weighted_rework_rate_zero_denom_renders_dash():
    """Spec lines 377-379. When throughput is zero across every scope,
    rework_rate's weighted average is undefined; the cell becomes
    ``None`` (T7 renders ``—``) and an aggregation-zero-denominator
    note fires.
    """
    scopes = [
        _scope(aggregates={"throughput": 0, "rework_rate": 0.1}, source_basename="a.json"),
        _scope(aggregates={"throughput": 0, "rework_rate": 0.2}, source_basename="b.json"),
    ]
    agg, notes = aggregate_non_cohort(scopes)
    assert agg["rework_rate"] is None
    assert any("aggregation-zero-denominator" in n and "rework_rate" in n for n in notes)


def test_program_distribution_metric_renders_median_of_medians():
    """Spec lines 374-375 + 381-384. For three scopes with cycle_time
    p50 values [10, 20, 30], the program aggregate p50 is the median of
    the per-scope medians = 20.
    """
    scopes = [
        _scope(
            aggregates={"cycle_time_hours": {"p50": 10, "p75": 12, "p90": 14, "n": 5}},
            source_basename="a.json",
        ),
        _scope(
            aggregates={"cycle_time_hours": {"p50": 20, "p75": 24, "p90": 28, "n": 5}},
            source_basename="b.json",
        ),
        _scope(
            aggregates={"cycle_time_hours": {"p50": 30, "p75": 36, "p90": 42, "n": 5}},
            source_basename="c.json",
        ),
    ]
    agg, notes = aggregate_non_cohort(scopes)
    assert agg["cycle_time_hours"]["p50"] == 20
    assert agg["cycle_time_hours"]["p75"] == 24
    assert agg["cycle_time_hours"]["p90"] == 28
    assert agg["cycle_time_hours"]["n"] == 15
    assert any("median-of-medians-approximation" in n for n in notes)


def test_program_cohort_breakdown_partial_emits_count_note():
    """Spec lines 302-304. 3 scopes, 1 with cohort_breakdown, 2
    without; emits the literal note naming the missing basenames in
    codepoint-ascending order.
    """
    scopes = [
        _scope(
            aggregates={"throughput": 5},
            cohort_breakdown={
                "cohort": {"throughput": 2},
                "control": {"throughput": 3},
            },
            source_basename="c.json",
        ),
        _scope(aggregates={"throughput": 10}, source_basename="a.json"),
        _scope(aggregates={"throughput": 8}, source_basename="b.json"),
    ]
    _, cohort_notes = aggregate_cohort_side(scopes, "cohort")
    assert any(
        n == "cohort-breakdown-missing: 2 of 3 scopes (basenames: a.json, "
        "b.json); cohort rollup computed over the remaining 1"
        for n in cohort_notes
    )


def test_program_mixed_cohort_jql_emits_note_and_proceeds(tmp_path):
    """Spec lines 305-308. Two scopes with different meta.cohort_jql →
    note fires AND the cohort rollup still produces a result.
    """
    _write_input(
        tmp_path,
        "a.json",
        {"project": "ALPHA"},
        aggregates={"throughput": 10},
        cohort_breakdown={
            "cohort": {"throughput": 4, "rework_rate": 0.1},
            "control": {"throughput": 6, "rework_rate": 0.2},
        },
        cohort_jql="labels = ai-cohort",
    )
    _write_input(
        tmp_path,
        "b.json",
        {"project": "BETA"},
        aggregates={"throughput": 20},
        cohort_breakdown={
            "cohort": {"throughput": 8, "rework_rate": 0.3},
            "control": {"throughput": 12, "rework_rate": 0.4},
        },
        cohort_jql="component = AI",
    )
    report = run_program(_args(tmp_path, include_cohort_breakdown=True))
    assert report.cohort_deltas is not None
    assert any("mixed-cohort-jql" in n for n in report.notes)


def test_program_no_cohort_inputs_omits_section_with_note():
    """Spec lines 309-310. Zero scopes carry cohort_breakdown → cohort
    deltas omitted AND cohort-breakdown-section-empty note fires.
    """
    scopes = [
        _scope(aggregates={"throughput": 10}, source_basename="a.json"),
        _scope(aggregates={"throughput": 20}, source_basename="b.json"),
    ]
    cohort_agg, cohort_notes = aggregate_cohort_side(scopes, "cohort")
    assert cohort_agg is None
    assert "cohort-breakdown-section-empty" in cohort_notes


def test_program_cohort_rollup_aggregates_sides_independently():
    """Spec lines 596-599 — the pinned-decimal fixture.

    Scope 1 cohort = (thru=10, rework=0.5); control = (thru=90, rework=0.1).
    Scope 2 cohort = (thru=20, rework=0.4); control = (thru=80, rework=0.2).

    Cohort rollup rework_rate = (0.5*10 + 0.4*20) / (10+20) = 13/30.
    Control rollup rework_rate = (0.1*90 + 0.2*80) / (90+80) = 25/170.

    NOT the cross-side weighted mean (0.15) — sides are aggregated
    independently per spec lines 252-301.
    """
    scopes = [
        _scope(
            cohort_breakdown={
                "cohort": {"throughput": 10, "rework_rate": 0.5},
                "control": {"throughput": 90, "rework_rate": 0.1},
            },
            source_basename="s1.json",
            cohort_jql="labels = ai-cohort",
        ),
        _scope(
            cohort_breakdown={
                "cohort": {"throughput": 20, "rework_rate": 0.4},
                "control": {"throughput": 80, "rework_rate": 0.2},
            },
            source_basename="s2.json",
            cohort_jql="labels = ai-cohort",
        ),
    ]
    cohort_agg, _ = aggregate_cohort_side(scopes, "cohort")
    control_agg, _ = aggregate_cohort_side(scopes, "control")

    assert cohort_agg["rework_rate"] == pytest.approx(13 / 30, abs=1e-6)
    assert control_agg["rework_rate"] == pytest.approx(25 / 170, abs=1e-6)

    # Negative assertions: cohort rollup must NOT collapse to the
    # cross-side weighted mean. The task brief pins the 0.1500 check
    # (a safe "definitely not the right answer" sentinel); the
    # additional check against the literal cross-side mean (38/200)
    # specifically rules out the most common wrong impl — mixing
    # cohort + control numerators and denominators into one ratio.
    assert cohort_agg["rework_rate"] != pytest.approx(0.1500, abs=0.001)
    cross_side_mean = (0.5 * 10 + 0.4 * 20 + 0.1 * 90 + 0.2 * 80) / (10 + 20 + 90 + 80)
    assert cohort_agg["rework_rate"] != pytest.approx(cross_side_mean, abs=1e-6)


def test_program_defect_ratio_weighted_by_distribution_denominator():
    """Spec lines 600-604 + line 378. defect_ratio uses the
    flow_distribution.denominator as weight, NOT throughput.

    Fixture: throughput != flow_distribution.denominator (because
    subtasks are excluded from throughput but included in
    flow_distribution.denominator per flow-metrics decision 25).
    Constructed so that throughput-weighted gives a different answer.

    - Scope A: throughput=10, fd.denominator=100, defect_ratio=0.5
    - Scope B: throughput=90, fd.denominator=10,  defect_ratio=0.1

    Throughput-weighted (wrong): (0.5*10 + 0.1*90) / (10+90) = 14/100 = 0.14
    Denominator-weighted (right): (0.5*100 + 0.1*10) / (100+10) = 51/110 ≈ 0.4636
    """
    scopes = [
        _scope(
            aggregates={
                "throughput": 10,
                "defect_ratio": 0.5,
                "flow_distribution": {"denominator": 100, "feature": 0.5},
            },
            source_basename="a.json",
        ),
        _scope(
            aggregates={
                "throughput": 90,
                "defect_ratio": 0.1,
                "flow_distribution": {"denominator": 10, "feature": 0.5},
            },
            source_basename="b.json",
        ),
    ]
    agg, _ = aggregate_non_cohort(scopes)
    assert agg["defect_ratio"] == pytest.approx(51 / 110, abs=1e-6)
    assert agg["defect_ratio"] != pytest.approx(0.14, abs=0.001)


def test_program_cohort_defect_ratio_weighted_by_cohort_denominator():
    """Spec lines 605-609. Same as above but inside
    cohort_breakdown.cohort: the cohort-side defect_ratio rollup uses
    cohort_breakdown.cohort.flow_distribution.denominator as weight,
    NOT throughput, NOT global flow_distribution.denominator.
    """
    scopes = [
        _scope(
            aggregates={
                "throughput": 50,
                "flow_distribution": {"denominator": 999, "feature": 0.5},
            },
            cohort_breakdown={
                "cohort": {
                    "throughput": 10,
                    "defect_ratio": 0.5,
                    "flow_distribution": {"denominator": 100, "feature": 0.5},
                },
                "control": {
                    "throughput": 40,
                    "defect_ratio": 0.0,
                    "flow_distribution": {"denominator": 50, "feature": 0.5},
                },
            },
            source_basename="a.json",
            cohort_jql="labels = ai-cohort",
        ),
        _scope(
            aggregates={
                "throughput": 50,
                "flow_distribution": {"denominator": 999, "feature": 0.5},
            },
            cohort_breakdown={
                "cohort": {
                    "throughput": 90,
                    "defect_ratio": 0.1,
                    "flow_distribution": {"denominator": 10, "feature": 0.5},
                },
                "control": {
                    "throughput": 40,
                    "defect_ratio": 0.0,
                    "flow_distribution": {"denominator": 50, "feature": 0.5},
                },
            },
            source_basename="b.json",
            cohort_jql="labels = ai-cohort",
        ),
    ]
    cohort_agg, _ = aggregate_cohort_side(scopes, "cohort")
    # Cohort denominator-weighted: (0.5*100 + 0.1*10) / 110 = 51/110.
    assert cohort_agg["defect_ratio"] == pytest.approx(51 / 110, abs=1e-6)
    # NOT throughput-weighted: (0.5*10 + 0.1*90) / 100 = 0.14.
    assert cohort_agg["defect_ratio"] != pytest.approx(0.14, abs=0.001)


def test_program_cohort_missing_flow_distribution_drops_from_distribution_rollup_only():
    """Spec lines 610-614 + 289-294. Scope B's cohort side is missing
    flow_distribution; it still contributes to throughput and
    rework_rate, but NOT to defect_ratio or flow_distribution.
    """
    scopes = [
        _scope(
            cohort_breakdown={
                "cohort": {
                    "throughput": 10,
                    "rework_rate": 0.5,
                    "defect_ratio": 0.5,
                    "flow_distribution": {
                        "denominator": 100,
                        "feature": 0.5,
                        "defect": 0.5,
                    },
                },
                "control": {"throughput": 90, "rework_rate": 0.1},
            },
            source_basename="a.json",
            cohort_jql="labels = ai-cohort",
        ),
        _scope(
            cohort_breakdown={
                "cohort": {
                    "throughput": 20,
                    "rework_rate": 0.4,
                    # No flow_distribution / defect_ratio here.
                },
                "control": {"throughput": 80, "rework_rate": 0.2},
            },
            source_basename="b.json",
            cohort_jql="labels = ai-cohort",
        ),
    ]
    cohort_agg, cohort_notes = aggregate_cohort_side(scopes, "cohort")

    # Throughput sum includes scope B.
    assert cohort_agg["throughput"] == 30
    # rework_rate weighted by cohort throughput, INCLUDES scope B.
    assert cohort_agg["rework_rate"] == pytest.approx(
        (0.5 * 10 + 0.4 * 20) / 30, abs=1e-6
    )
    # defect_ratio + flow_distribution use only scope A (single
    # contributor → result is scope A's own value).
    assert cohort_agg["defect_ratio"] == pytest.approx(0.5, abs=1e-9)
    assert cohort_agg["flow_distribution"]["denominator"] == 100
    assert cohort_agg["flow_distribution"]["feature"] == pytest.approx(0.5, abs=1e-9)

    assert any(
        "cohort-flow_distribution-missing" in n and "side=cohort" in n and "b.json" in n
        for n in cohort_notes
    )


def test_program_flow_distribution_buckets_sum_to_one_after_aggregation():
    """Per-bucket weighted averages with shared denominator weights
    preserve the unit-sum invariant (each scope's bucket shares sum to
    1 by construction in flow-metrics).
    """
    scopes = [
        _scope(
            aggregates={
                "throughput": 10,
                "flow_distribution": {
                    "denominator": 100,
                    "feature": 0.5,
                    "defect": 0.2,
                    "debt": 0.1,
                    "risk": 0.1,
                    "subtask": 0.05,
                    "other": 0.05,
                },
            },
            source_basename="a.json",
        ),
        _scope(
            aggregates={
                "throughput": 20,
                "flow_distribution": {
                    "denominator": 50,
                    "feature": 0.3,
                    "defect": 0.3,
                    "debt": 0.2,
                    "risk": 0.1,
                    "subtask": 0.05,
                    "other": 0.05,
                },
            },
            source_basename="b.json",
        ),
    ]
    agg, _ = aggregate_non_cohort(scopes)
    fd = agg["flow_distribution"]
    bucket_sum = sum(
        fd[k] for k in ("feature", "defect", "debt", "risk", "subtask", "other")
    )
    assert bucket_sum == pytest.approx(1.0, abs=1e-9)
    assert fd["denominator"] == 150


def test_program_per_team_flattened_rows_excluded_from_cohort_rollup():
    """Spec lines 232-244. ``from_per_team=True`` rows contribute to
    the non-cohort aggregates table but NOT to either cohort side, even
    when ``--include-cohort-breakdown`` is on.
    """
    scopes = [
        _scope(
            aggregates={"throughput": 10, "rework_rate": 0.1},
            cohort_breakdown={
                "cohort": {"throughput": 4, "rework_rate": 0.5},
                "control": {"throughput": 6, "rework_rate": 0.05},
            },
            source_basename="a.json",
            cohort_jql="labels = ai-cohort",
        ),
        _scope(
            scope={"project": "PROJ", "team": "Foo"},
            scope_kind="project+team",
            aggregates={"throughput": 99, "rework_rate": 0.9},
            source_basename="b.json",
            from_per_team=True,
        ),
    ]
    non_cohort, _ = aggregate_non_cohort(scopes)
    # Non-cohort includes the per_team-flattened row (throughput 10 + 99).
    assert non_cohort["throughput"] == 109

    cohort_agg, _ = aggregate_cohort_side(scopes, "cohort")
    # Cohort rollup uses only the eligible (non-per_team) scope.
    assert cohort_agg["throughput"] == 4
    assert cohort_agg["rework_rate"] == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Additional T6 invariants
# ---------------------------------------------------------------------------
def test_program_aggregates_match_per_scope_when_single_scope():
    """Sanity: with a single scope the program-wide aggregate equals
    that scope's per-metric value (sums of one == identity, medians of
    one == identity, weighted averages of one term == the term).
    """
    scope = _scope(
        aggregates={
            "throughput": 42,
            "wip": 7,
            "flow_load": 11,
            "cycle_time_hours": {"p50": 12.5, "p75": 30.0, "p90": 50.0, "n": 9},
            "rework_rate": 0.25,
            "defect_ratio": 0.4,
            "flow_distribution": {
                "denominator": 80,
                "feature": 0.6,
                "defect": 0.4,
            },
        },
        source_basename="only.json",
    )
    agg, _ = aggregate_non_cohort([scope])
    assert agg["throughput"] == 42
    assert agg["wip"] == 7
    assert agg["flow_load"] == 11
    assert agg["cycle_time_hours"]["p50"] == 12.5
    assert agg["cycle_time_hours"]["n"] == 9
    assert agg["rework_rate"] == pytest.approx(0.25, abs=1e-9)
    assert agg["defect_ratio"] == pytest.approx(0.4, abs=1e-9)
    assert agg["flow_distribution"]["feature"] == pytest.approx(0.6, abs=1e-9)
    assert agg["flow_distribution"]["denominator"] == 80


def test_program_throughput_per_week_normalisation(tmp_path):
    """Spec line 373. throughput=100 in a 14-day inclusive window ⇒
    throughput_per_week = 50.
    """
    window = ("2025-01-01", "2025-01-14")  # inclusive: 14 days = 2 weeks
    _write_input(
        tmp_path,
        "a.json",
        {"project": "ALPHA"},
        aggregates={"throughput": 100},
        window=window,
    )
    report = run_program(_args(tmp_path, window=window))
    assert report.program_aggregates["throughput"] == 100
    assert report.program_aggregates["throughput_per_week"] == pytest.approx(50.0)


def test_program_aggregate_dict_keys_in_canonical_order():
    """Top-level metric keys in the aggregate dict iterate in the same
    order as :data:`CANONICAL_METRIC_ORDER` collapsed to one entry per
    top-level metric. T7's CanonicalEncoder relies on insertion order.
    """
    scope = _scope(
        aggregates={
            "throughput": 1,
            "wip": 2,
            "flow_load": 3,
            "cycle_time_hours": {"p50": 1.0, "p75": 1.0, "p90": 1.0, "n": 1},
            "lead_time_hours": {"p50": 1.0, "p75": 1.0, "p90": 1.0, "n": 1},
            "flow_time_hours": {"p50": 1.0, "p75": 1.0, "p90": 1.0, "n": 1},
            "flow_efficiency": {"p50": 0.5, "p75": 0.5, "p90": 0.5, "n": 1},
            "rework_rate": 0.1,
            "defect_ratio": 0.2,
            "flow_distribution": {"denominator": 10, "feature": 1.0},
        },
        source_basename="only.json",
    )
    agg, _ = aggregate_non_cohort([scope])
    expected_top_level_order = []
    for label in CANONICAL_METRIC_ORDER:
        # CANONICAL_METRIC_ORDER carries entries like "cycle_time_hours p50"
        # and "flow_distribution.feature". Collapse to top-level metric.
        if " " in label:
            top = label.split(" ", 1)[0]
        elif "." in label:
            top = label.split(".", 1)[0]
        else:
            top = label
        if top not in expected_top_level_order:
            expected_top_level_order.append(top)
    # Filter to the keys actually present (throughput_per_week is added
    # by run_program, not aggregate_non_cohort).
    keys_in_canonical = [k for k in expected_top_level_order if k in agg]
    assert list(agg.keys()) == keys_in_canonical


def test_program_per_scope_rows_sorted_canonically(tmp_path):
    """Spec lines 506-507. ``per_scope_rows`` is sorted by canonical
    scope-repr codepoint-ascending.
    """
    # Two project-kind scopes; canonical reprs sort by the project
    # value because every other field is empty. Write them in
    # non-sorted basename order; the result should still come out
    # sorted by canonical repr.
    _write_input(tmp_path, "zebra.json", {"project": "BETA"}, aggregates={"throughput": 1})
    _write_input(tmp_path, "alpha.json", {"project": "ALPHA"}, aggregates={"throughput": 2})
    report = run_program(_args(tmp_path))
    reprs = [row["scope_repr"] for row in report.per_scope_rows]
    assert reprs == sorted(reprs)


def test_program_header_line_format(tmp_path):
    """Spec line 439. Header carries Window and Scopes with per-family
    kind counts. Kind counts collapse ``+team`` into the parent family.
    """
    # Two project-family inputs (one project, one project+team) plus a
    # per_team-flattened row from the project+team's per_team array.
    # Avoids cross-family overlap rules from the T4 dedupe pass.
    _write_input(tmp_path, "a.json", {"project": "ALPHA"}, aggregates={"throughput": 1})
    _write_input(
        tmp_path,
        "b.json",
        {"project": "BETA", "team": "Foo"},
        aggregates={"throughput": 2},
    )
    report = run_program(_args(tmp_path))
    assert "**Window:** 2026-01-01..2026-01-31" in report.header_line
    assert "**Scopes:** 2" in report.header_line
    # Both scopes are in the project family (project + project+team).
    assert "project=2" in report.header_line
    assert "program=0" in report.header_line
    assert "portfolio=0" in report.header_line


def test_program_end_to_end_returns_report_data(tmp_path):
    """Smoke test: end-to-end run produces a non-empty ReportData with
    the expected mode/aggregates wiring.
    """
    _write_input(
        tmp_path,
        "a.json",
        {"project": "ALPHA"},
        aggregates={
            "throughput": 10,
            "rework_rate": 0.2,
            "flow_distribution": {"denominator": 50, "feature": 0.8, "defect": 0.2},
            "defect_ratio": 0.1,
        },
    )
    _write_input(
        tmp_path,
        "b.json",
        {"project": "BETA"},
        aggregates={
            "throughput": 20,
            "rework_rate": 0.3,
            "flow_distribution": {"denominator": 100, "feature": 0.5, "defect": 0.5},
            "defect_ratio": 0.2,
        },
    )
    report = run_program(_args(tmp_path))
    assert isinstance(report, ReportData)
    assert report.mode == "program"
    assert report.deltas == {}
    assert report.cohort_deltas is None
    assert report.program_aggregates["throughput"] == 30
    # rework_rate weighted by throughput: (0.2*10 + 0.3*20)/30 = 8/30
    assert report.program_aggregates["rework_rate"] == pytest.approx(
        8 / 30, abs=1e-6
    )
    assert len(report.per_scope_rows) == 2
