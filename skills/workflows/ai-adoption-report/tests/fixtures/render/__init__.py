"""T7 test fixtures.

Builder functions returning ``ReportData`` (and helper ``InputFile`` /
aggregate-dict) instances for the render tests. Constructed in Python
rather than loaded from JSON files so each fixture is self-documenting.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from ai_adoption_report.delta import compute_deltas
from ai_adoption_report.inputs import InputFile
from ai_adoption_report.modes import ReportData, canonical_scope_repr


# ---------------------------------------------------------------------------
# Aggregate-dict builders
# ---------------------------------------------------------------------------
def aggregate_block(
    *,
    throughput: int = 84,
    wip: int = 12,
    flow_load: float = 22.4,
    cycle_p50: float = 38.2,
    cycle_p75: float = 60.0,
    cycle_p90: float = 88.0,
    cycle_n: int = 100,
    lead_p50: float = 50.0,
    lead_p75: float = 70.0,
    lead_p90: float = 95.0,
    lead_n: int = 100,
    flow_time_p50: float = 45.0,
    flow_time_p75: float = 65.0,
    flow_time_p90: float = 90.0,
    flow_time_n: int = 100,
    flow_eff_p50: float = 0.62,
    flow_eff_p75: float = 0.78,
    flow_eff_p90: float = 0.91,
    flow_eff_n: int = 100,
    rework_rate: float = 0.05,
    defect_ratio: float = 0.12,
    fd_feature: float = 0.6,
    fd_defect: float = 0.1,
    fd_debt: float = 0.1,
    fd_risk: float = 0.05,
    fd_subtask: float = 0.1,
    fd_other: float = 0.05,
    fd_denominator: int = 100,
) -> dict:
    return {
        "throughput": throughput,
        "wip": wip,
        "flow_load": flow_load,
        "cycle_time_hours": {
            "p50": cycle_p50,
            "p75": cycle_p75,
            "p90": cycle_p90,
            "n": cycle_n,
        },
        "lead_time_hours": {
            "p50": lead_p50,
            "p75": lead_p75,
            "p90": lead_p90,
            "n": lead_n,
        },
        "flow_time_hours": {
            "p50": flow_time_p50,
            "p75": flow_time_p75,
            "p90": flow_time_p90,
            "n": flow_time_n,
        },
        "flow_efficiency": {
            "p50": flow_eff_p50,
            "p75": flow_eff_p75,
            "p90": flow_eff_p90,
            "n": flow_eff_n,
        },
        "rework_rate": rework_rate,
        "defect_ratio": defect_ratio,
        "flow_distribution": {
            "feature": fd_feature,
            "defect": fd_defect,
            "debt": fd_debt,
            "risk": fd_risk,
            "subtask": fd_subtask,
            "other": fd_other,
            "denominator": fd_denominator,
        },
    }


# ---------------------------------------------------------------------------
# InputFile builder
# ---------------------------------------------------------------------------
def make_input_file(
    *,
    basename: str = "PROJ-Foo-2024Q1.json",
    scope: Optional[dict] = None,
    scope_kind: str = "project+team",
    window_from: str = "2024-01-01",
    window_to: str = "2024-03-31",
    state_sha: str = "abc123",
    issuetype_sha: str = "def456",
    schema: tuple[int, int] = (1, 0),
    generated_at: str = "2024-04-02T08:00:00Z",
    aggregates: Optional[dict] = None,
    cohort_breakdown: Optional[dict] = None,
    per_team: Optional[list] = None,
    meta_extra: Optional[dict] = None,
) -> InputFile:
    if scope is None:
        scope = {"project": "PROJ", "team": "Foo"}
    meta = {
        "scope": scope,
        "window": {"from": window_from, "to": window_to},
        "state_config_sha": state_sha,
        "issuetype_config_sha": issuetype_sha,
        "schema_version": "{}.{}".format(*schema),
        "generated_at": generated_at,
    }
    if meta_extra:
        meta.update(meta_extra)
    return InputFile(
        path=Path("/tmp") / basename,
        basename=basename,
        scope=scope,
        scope_kind=scope_kind,
        window_from=window_from,
        window_to=window_to,
        meta=meta,
        aggregates=aggregates if aggregates is not None else {},
        cohort_breakdown=cohort_breakdown,
        per_team=per_team,
        schema_version=schema,
    )


# ---------------------------------------------------------------------------
# ReportData builders
# ---------------------------------------------------------------------------
def baseline_report(
    *,
    include_cohort_breakdown: bool = False,
    extra_notes: Optional[list[str]] = None,
    scope: Optional[dict] = None,
) -> ReportData:
    """Baseline-mode ReportData with non-trivial deltas across every metric."""
    scope = scope or {"project": "PROJ", "team": "Foo"}
    a_agg = aggregate_block(
        throughput=84,
        cycle_p50=38.2,
        rework_rate=0.05,
        defect_ratio=0.12,
    )
    b_agg = aggregate_block(
        throughput=102,
        cycle_p50=31.5,
        rework_rate=0.07,
        defect_ratio=0.10,
    )
    a_input = make_input_file(
        basename="PROJ-Foo-2024Q1.json",
        scope=scope,
        scope_kind="project+team",
        window_from="2024-01-01",
        window_to="2024-03-31",
        aggregates=a_agg,
    )
    b_input = make_input_file(
        basename="PROJ-Foo-2024Q2.json",
        scope=scope,
        scope_kind="project+team",
        window_from="2024-04-01",
        window_to="2024-06-30",
        aggregates=b_agg,
    )
    result = compute_deltas(
        a_agg, b_agg, side_labels=("baseline", "current")
    )

    cohort_deltas = None
    cohort_side_labels = None
    cohort_notes: list[str] = []
    if include_cohort_breakdown:
        # Cohort vs control on the current side, comparing the cohort sub-
        # side at A vs the cohort sub-side at B (mirrors run_baseline's
        # logic).
        a_cohort = aggregate_block(throughput=20, cycle_p50=42.0)
        b_cohort = aggregate_block(throughput=35, cycle_p50=28.0)
        a_input.cohort_breakdown = {"cohort": a_cohort, "control": a_agg}
        b_input.cohort_breakdown = {"cohort": b_cohort, "control": b_agg}
        cohort_result = compute_deltas(
            a_cohort,
            b_cohort,
            side_labels=("baseline-cohort", "current-cohort"),
        )
        cohort_deltas = cohort_result.to_dict()
        cohort_side_labels = ("baseline-cohort", "current-cohort")
        cohort_notes.extend(cohort_result.notes)

    header_line = (
        "**Baseline window:** 2024-01-01..2024-03-31 | "
        "**Current window:** 2024-04-01..2024-06-30 | "
        "**Scope:** {}".format(canonical_scope_repr(scope, "project+team"))
    )

    notes = list(result.notes) + list(cohort_notes)
    if extra_notes:
        notes.extend(extra_notes)

    return ReportData(
        mode="baseline",
        header_line=header_line,
        inputs=[a_input, b_input],
        deltas=result.to_dict(),
        cohort_deltas=cohort_deltas,
        cohort_side_labels=cohort_side_labels,
        per_scope_rows=None,
        program_aggregates=None,
        notes=notes,
    )


def cohort_report(*, extra_notes: Optional[list[str]] = None) -> ReportData:
    """Cohort-mode ReportData; one input with cohort_breakdown."""
    scope = {"project": "PROJ", "team": "Foo"}
    control_agg = aggregate_block(throughput=60, cycle_p50=42.0, rework_rate=0.06)
    cohort_agg = aggregate_block(throughput=42, cycle_p50=33.0, rework_rate=0.04)
    inp = make_input_file(
        basename="PROJ-Foo-2024Q1.json",
        scope=scope,
        cohort_breakdown={"cohort": cohort_agg, "control": control_agg},
        meta_extra={"cohort_jql": 'labels = "ai-cohort"'},
    )
    result = compute_deltas(
        control_agg, cohort_agg, side_labels=("control", "cohort")
    )
    header_line = (
        "**Window:** 2024-01-01..2024-03-31 | "
        "**Scope:** {} | "
        '**Cohort JQL:** labels = "ai-cohort"'.format(
            canonical_scope_repr(scope, "project+team")
        )
    )
    notes = list(result.notes)
    if extra_notes:
        notes.extend(extra_notes)
    return ReportData(
        mode="cohort",
        header_line=header_line,
        inputs=[inp],
        deltas=result.to_dict(),
        cohort_deltas=None,
        per_scope_rows=None,
        program_aggregates=None,
        notes=notes,
    )


def program_report(
    *,
    include_cohort_breakdown: bool = False,
    extra_notes: Optional[list[str]] = None,
    scope_team_names: tuple[tuple[str, str], ...] = (
        ("PROJ", "Foo"),
        ("PROJ", "Bar"),
        ("QUUX", "Baz"),
    ),
) -> ReportData:
    """Program-mode ReportData with multiple scopes + aggregate row."""
    inputs: list[InputFile] = []
    per_scope_rows: list[dict] = []
    for project, team in scope_team_names:
        scope = {"project": project, "team": team}
        agg = aggregate_block(
            throughput=40 + len(team), cycle_p50=35.0 + len(team)
        )
        inp = make_input_file(
            basename="{}-{}-2024Q1.json".format(project, team),
            scope=scope,
            aggregates=agg,
        )
        inputs.append(inp)
        per_scope_rows.append(
            {
                "scope": scope,
                "scope_kind": "project+team",
                "scope_repr": canonical_scope_repr(scope, "project+team"),
                "aggregates": agg,
            }
        )
    program_aggregates = aggregate_block(
        throughput=sum(40 + len(t) for _, t in scope_team_names),
        cycle_p50=37.0,
    )

    cohort_deltas = None
    cohort_side_labels = None
    if include_cohort_breakdown:
        cohort_agg = aggregate_block(throughput=20, cycle_p50=30.0)
        control_agg = aggregate_block(throughput=80, cycle_p50=40.0)
        cohort_result = compute_deltas(
            control_agg, cohort_agg, side_labels=("control", "cohort")
        )
        cohort_deltas = cohort_result.to_dict()
        cohort_side_labels = ("control", "cohort")

    header_line = (
        "**Window:** 2024-01-01..2024-03-31 | "
        "**Scopes:** {} (project={}, program=0, portfolio=0)".format(
            len(inputs), len(inputs)
        )
    )

    return ReportData(
        mode="program",
        header_line=header_line,
        inputs=inputs,
        deltas={},
        cohort_deltas=cohort_deltas,
        cohort_side_labels=cohort_side_labels,
        per_scope_rows=sorted(per_scope_rows, key=lambda r: r["scope_repr"]),
        program_aggregates=program_aggregates,
        notes=list(extra_notes or []),
    )


__all__ = [
    "aggregate_block",
    "make_input_file",
    "baseline_report",
    "cohort_report",
    "program_report",
]
