"""T3 file-consumer modes: ``baseline`` and ``cohort``.

Both modes load one or two flow-metrics JSONs via T2's
:func:`inputs.load_input`, run T5's :func:`delta.compute_deltas` on the
relevant aggregate pair, and return a :class:`ReportData` for T7 to
render. ``program`` mode (T4/T6) populates the same dataclass with
:attr:`ReportData.per_scope_rows`; the field is ``None`` for baseline
and cohort.

Notes-merge contract (plan §T5 lines 355-362): T5 returns its notes
unsorted; T3 concatenates them onto :attr:`ReportData.notes` in append
order. T7 sorts and dedupes the final list — T3 does NOT pre-sort.

All exit-2 conditions raise :class:`ValidationError`; the CLI entry
point in :mod:`ai_adoption_report` catches and prints them.

Stdlib only. Python >= 3.10.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Literal, Optional

from . import ValidationError
from .delta import compute_deltas
from .inputs import InputFile, load_input, collect_mixed_major_note
from .notes import Note


# ---------------------------------------------------------------------------
# Canonical scope representation (spec lines 510-515)
# ---------------------------------------------------------------------------
# Temporary home — T7 may relocate when it owns the renderer. Kept here
# because both header-line assembly (T3) and per-scope-row labels (T6)
# need the same string and the spec defines it once.
_SCOPE_FIELDS = ("project", "team", "program_id", "portfolio_id")


def canonical_scope_repr(scope: dict, kind: str) -> str:
    """Render the spec's canonical scope string.

    Form: ``kind=<kind>;project=<v>;team=<v>;program_id=<v>;portfolio_id=<v>``.
    Absent fields render as the empty string after the ``=``. The field
    order is fixed by the spec and does NOT follow the input dict's
    insertion order.
    """
    parts = ["kind={}".format(kind)]
    for f in _SCOPE_FIELDS:
        parts.append("{}={}".format(f, scope.get(f, "")))
    return ";".join(parts)


# ---------------------------------------------------------------------------
# ReportData
# ---------------------------------------------------------------------------
@dataclass
class ReportData:
    """The mode-agnostic data bundle T7 renders.

    ``deltas`` and ``cohort_deltas`` carry the
    :meth:`delta.DeltaResult.to_dict` shape (the canonical
    insertion-order metric dict that the JSON sidecar emits). T3 calls
    ``to_dict`` so T7 sees the same structure regardless of mode.

    ``per_scope_rows`` stays ``None`` for baseline + cohort; T4/T6
    populates it for program mode.

    ``notes`` is the merged unsorted list (T2's mixed-major note +
    T3's drift / per_team / cohort-jql notes + T5's compute_deltas
    notes). T7 sorts and dedupes the final list per spec line 504.
    """

    mode: Literal["baseline", "cohort", "program"]
    header_line: str
    inputs: List[InputFile]
    deltas: dict
    cohort_deltas: Optional[dict] = None
    per_scope_rows: Optional[list] = None
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Mode: baseline
# ---------------------------------------------------------------------------
def run_baseline(args) -> ReportData:
    """Run baseline mode end-to-end and return :class:`ReportData`.

    ``args`` is the argparse namespace from the ``baseline`` subparser.
    Expects ``args.baseline``, ``args.current``, and
    ``args.include_cohort_breakdown``.
    """
    baseline = load_input(args.baseline)
    current = load_input(args.current)
    inputs = [baseline, current]
    notes: List[str] = []

    # T2 cross-input note (mixed schema majors). Same call pattern T4
    # will use in program mode, kept here for the baseline pair so the
    # warning surfaces in single-pair runs too.
    mixed_major = collect_mixed_major_note(inputs)
    if mixed_major is not None:
        notes.append(mixed_major)

    # Spec lines 153-156: exact dict equality on meta.scope.
    if baseline.scope != current.scope:
        raise ValidationError(
            "baseline-mode scope mismatch: baseline scope {} vs current "
            "scope {}".format(baseline.scope, current.scope)
        )

    # Spec lines 157-160: baseline.window.to <= current.window.from.
    # ISO YYYY-MM-DD strings compare correctly under lex order
    # (spec line 127 — string equality is the official match rule).
    if baseline.window_to > current.window_from:
        raise ValidationError(
            "baseline-mode window overlap: baseline {}..{} overlaps "
            "current {}..{}".format(
                baseline.window_from, baseline.window_to,
                current.window_from, current.window_to,
            )
        )

    # Spec lines 161-165: drift emits a note; deltas still compute.
    if baseline.meta.get("state_config_sha") != current.meta.get("state_config_sha"):
        notes.append(
            Note.config_sha_drift(
                "state_config_sha",
                baseline.meta.get("state_config_sha"),
                current.meta.get("state_config_sha"),
            )
        )
    if baseline.meta.get("issuetype_config_sha") != current.meta.get("issuetype_config_sha"):
        notes.append(
            Note.config_sha_drift(
                "issuetype_config_sha",
                baseline.meta.get("issuetype_config_sha"),
                current.meta.get("issuetype_config_sha"),
            )
        )

    # Spec lines 177-183: per_team is ignored in baseline mode; note
    # per input that carries one. ``per_team`` arrives as a list (or
    # None); only non-empty lists trigger the note.
    for inp in inputs:
        if inp.per_team:
            notes.append(Note.per_team_ignored_in_baseline(inp.basename))

    # Primary deltas (spec §"Delta math"). T5 returns notes unsorted;
    # T3 concatenates per the notes-merge contract.
    primary = compute_deltas(
        baseline.aggregates,
        current.aggregates,
        side_labels=("baseline", "current"),
    )
    notes.extend(primary.notes)

    cohort_deltas: Optional[dict] = None
    if getattr(args, "include_cohort_breakdown", False):
        cohort_deltas, cohort_notes = _baseline_cohort_section(baseline, current)
        notes.extend(cohort_notes)

    header_line = (
        "**Baseline window:** {bf}..{bt} | "
        "**Current window:** {cf}..{ct} | "
        "**Scope:** {scope}"
    ).format(
        bf=baseline.window_from,
        bt=baseline.window_to,
        cf=current.window_from,
        ct=current.window_to,
        scope=canonical_scope_repr(baseline.scope, baseline.scope_kind),
    )

    return ReportData(
        mode="baseline",
        header_line=header_line,
        inputs=inputs,
        deltas=primary.to_dict(),
        cohort_deltas=cohort_deltas,
        per_scope_rows=None,
        notes=notes,
    )


def _baseline_cohort_section(
    baseline: InputFile,
    current: InputFile,
) -> tuple[Optional[dict], List[str]]:
    """Return ``(cohort_deltas, notes)`` for the optional cohort section.

    Three branches per spec lines 167-175:
    1. Either input lacks ``cohort_breakdown`` → no-op + note,
       ``cohort_deltas`` stays ``None``.
    2. Both present but ``meta.cohort_jql`` differs → section omitted,
       mismatch note, ``cohort_deltas`` stays ``None``.
    3. Both present and JQLs match → compute deltas across the
       cohort/control pair across the two windows (NOT within-window).
    """
    notes: List[str] = []
    missing_basenames = [
        inp.basename for inp in (baseline, current) if inp.cohort_breakdown is None
    ]
    if missing_basenames:
        notes.append(Note.cohort_breakdown_absent_noop(missing_basenames))
        return None, notes

    a_jql = baseline.meta.get("cohort_jql")
    b_jql = current.meta.get("cohort_jql")
    if a_jql != b_jql:
        notes.append(Note.cohort_jql_mismatch(a_jql, b_jql))
        return None, notes

    # The spec is silent on which sub-side gets compared across windows
    # in baseline mode. The natural reading of "cohort-vs-control deltas
    # across the two windows" is: compare the cohort side at baseline
    # vs the cohort side at current (and likewise for control). Our T5
    # engine handles one pair at a time; the section here compares
    # ``baseline.cohort`` vs ``current.cohort`` because that's the
    # quantity a baseline reader asks about ("did AI adoption move the
    # cohort?"). T7 may add a second sub-table for control later;
    # extending requires only another compute_deltas call.
    result = compute_deltas(
        baseline.cohort_breakdown.get("cohort", {}),
        current.cohort_breakdown.get("cohort", {}),
        side_labels=("baseline-cohort", "current-cohort"),
    )
    notes.extend(result.notes)
    return result.to_dict(), notes


# ---------------------------------------------------------------------------
# Mode: cohort
# ---------------------------------------------------------------------------
def run_cohort(args) -> ReportData:
    """Run cohort mode end-to-end and return :class:`ReportData`.

    Side A is ``control`` and side B is ``cohort`` per spec line 194
    and plan §T3 line 230.
    """
    inp = load_input(args.input)

    if inp.cohort_breakdown is None:
        # Spec line 191: literal error string.
        raise ValidationError(
            "--input was not produced with --cohort-jql; no "
            "cohort_breakdown block present"
        )

    notes: List[str] = []
    result = compute_deltas(
        inp.cohort_breakdown.get("control", {}),
        inp.cohort_breakdown.get("cohort", {}),
        side_labels=("control", "cohort"),
    )
    notes.extend(result.notes)

    header_line = (
        "**Window:** {f}..{t} | **Scope:** {scope} | **Cohort JQL:** {jql}"
    ).format(
        f=inp.window_from,
        t=inp.window_to,
        scope=canonical_scope_repr(inp.scope, inp.scope_kind),
        jql=inp.meta.get("cohort_jql", ""),
    )

    return ReportData(
        mode="cohort",
        header_line=header_line,
        inputs=[inp],
        deltas=result.to_dict(),
        cohort_deltas=None,
        per_scope_rows=None,
        notes=notes,
    )


__all__ = [
    "ReportData",
    "canonical_scope_repr",
    "run_baseline",
    "run_cohort",
]
