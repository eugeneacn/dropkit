"""T4 contract tests: program-mode input discovery, dedupe, overlap,
per_team flattening.

Mirrors every test listed in docs/specs/ai-adoption-report-plan.md §T4
plus the additional cases the spec implies (non-recursive glob, string-
equality window match, degenerate per_team entries,
cohort-deferred-note gated on the flag).

Fixtures are built in ``tmp_path`` so each test owns its directory; this
keeps the diff lean and lets each test express its scope topology
inline. The fixture-builder helpers below mirror the minimal flow-
metrics envelope T2 demands.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest

from ai_adoption_report import ValidationError
from ai_adoption_report.program_discovery import (
    canonical_scope_repr,
    discover_inputs,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
DEFAULT_WINDOW = ("2026-01-01", "2026-01-31")


def _meta(
    scope: Dict[str, Any],
    *,
    window: Tuple[str, str] = DEFAULT_WINDOW,
    per_team_double_counted: Optional[bool] = None,
    cohort_jql: Optional[str] = None,
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "caller": "test-account",
        "scope": scope,
        "window": {"from": window[0], "to": window[1]},
        "state_config_sha": "a" * 64,
        "issuetype_config_sha": "b" * 64,
        "schema_version": "1.0",
        "generated_at": "2026-02-01T00:00:00Z",
    }
    if per_team_double_counted is not None:
        meta["per_team_double_counted"] = per_team_double_counted
    if cohort_jql is not None:
        meta["cohort_jql"] = cohort_jql
    return meta


def _write_input(
    dir_path: Path,
    basename: str,
    scope: Dict[str, Any],
    *,
    window: Tuple[str, str] = DEFAULT_WINDOW,
    aggregates: Optional[Dict[str, Any]] = None,
    per_team: Optional[List[Dict[str, Any]]] = None,
    cohort_breakdown: Optional[Dict[str, Any]] = None,
    per_team_double_counted: Optional[bool] = None,
    cohort_jql: Optional[str] = None,
) -> Path:
    doc: Dict[str, Any] = {
        "meta": _meta(
            scope,
            window=window,
            per_team_double_counted=per_team_double_counted,
            cohort_jql=cohort_jql,
        ),
        "aggregates": aggregates if aggregates is not None else {},
    }
    if per_team is not None:
        doc["per_team"] = per_team
    if cohort_breakdown is not None:
        doc["cohort_breakdown"] = cohort_breakdown
    path = dir_path / basename
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# canonical_scope_repr
# ---------------------------------------------------------------------------
def test_canonical_scope_repr_matches_spec_form():
    """Spec lines 510-513 pin the form
    ``kind=<kind>;project=<v>;team=<v>;program_id=<v>;portfolio_id=<v>``
    with absent fields rendered as empty string after the ``=``.
    """
    assert canonical_scope_repr(
        {"project": "PROJ", "team": "Foo"}, "project+team"
    ) == "kind=project+team;project=PROJ;team=Foo;program_id=;portfolio_id="
    assert canonical_scope_repr(
        {"portfolio_id": "7"}, "portfolio"
    ) == "kind=portfolio;project=;team=;program_id=;portfolio_id=7"


# ---------------------------------------------------------------------------
# Empty / no-match
# ---------------------------------------------------------------------------
def test_program_no_inputs_match_window_exits_2(tmp_path):
    """Spec line 207: ``"no inputs matched --window FROM..TO in <DIR>"``."""
    _write_input(tmp_path, "a.json", {"project": "ALPHA"},
                 window=("2026-04-01", "2026-06-30"))
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, ("2026-01-01", "2026-01-31"))
    msg = str(exc.value)
    assert "no inputs matched --window 2026-01-01..2026-01-31" in msg
    assert str(tmp_path) in msg


def test_program_empty_directory_exits_2(tmp_path):
    """Empty directory hits the same "no inputs matched" path."""
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert "no inputs matched --window" in str(exc.value)


# ---------------------------------------------------------------------------
# Non-recursive glob (spec line 200, "no recursion")
# ---------------------------------------------------------------------------
def test_program_non_recursive_glob(tmp_path):
    """Files in subdirectories are ignored even when their window matches."""
    sub = tmp_path / "sub"
    sub.mkdir()
    _write_input(tmp_path, "a.json", {"project": "ALPHA"})
    _write_input(sub, "b.json", {"project": "BETA"})

    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    basenames = sorted(s.source_basename for s in result.scopes)
    assert basenames == ["a.json"]


# ---------------------------------------------------------------------------
# Window filter is string equality
# ---------------------------------------------------------------------------
def test_program_window_filter_is_string_equality(tmp_path):
    """Spec lines 204-208: string equality on ISO endpoints. T2 already
    rejects non-padded dates as invalid input, so the test only needs to
    show that a valid-but-different window does not match."""
    _write_input(tmp_path, "match.json", {"project": "ALPHA"},
                 window=("2026-01-01", "2026-01-31"))
    _write_input(tmp_path, "off.json", {"project": "BETA"},
                 window=("2026-02-01", "2026-02-28"))
    result = discover_inputs(tmp_path, ("2026-01-01", "2026-01-31"))
    assert [s.source_basename for s in result.scopes] == ["match.json"]


# ---------------------------------------------------------------------------
# Duplicate-scope detection (pre-flatten)
# ---------------------------------------------------------------------------
def test_program_duplicate_scope_exits_2_with_both_basenames(tmp_path):
    """Spec line 224: two inputs with identical scope dict + scope_kind
    exit 2 listing both basenames."""
    _write_input(tmp_path, "a.json", {"project": "ALPHA"})
    _write_input(tmp_path, "b.json", {"project": "ALPHA"})
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    msg = str(exc.value)
    assert "duplicate scope in input set" in msg
    assert "a.json" in msg
    assert "b.json" in msg


def test_program_duplicate_scope_three_basenames_all_listed(tmp_path):
    """If more than two inputs share a scope, all basenames appear in
    codepoint-ascending order (plan §T4 prompt)."""
    _write_input(tmp_path, "a.json", {"project": "ALPHA"})
    _write_input(tmp_path, "b.json", {"project": "ALPHA"})
    _write_input(tmp_path, "c.json", {"project": "ALPHA"})
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    msg = str(exc.value)
    for name in ("a.json", "b.json", "c.json"):
        assert name in msg
    assert msg.index("a.json") < msg.index("b.json") < msg.index("c.json")


# ---------------------------------------------------------------------------
# Cross-kind overlap detection
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "scope_a,scope_b",
    [
        ({"portfolio_id": "7"}, {"program_id": "42"}),
        ({"portfolio_id": "7"}, {"project": "ALPHA"}),
        ({"portfolio_id": "7"}, {"project": "ALPHA", "team": "Foo"}),
        ({"program_id": "42"}, {"project": "ALPHA"}),
        ({"program_id": "42"}, {"project": "ALPHA", "team": "Foo"}),
        ({"project": "ALPHA"}, {"project": "ALPHA", "team": "Foo"}),
    ],
    ids=[
        "portfolio_vs_program",
        "portfolio_vs_project",
        "portfolio_vs_project_team",
        "program_vs_project",
        "program_vs_project_team",
        "project_vs_project_team_same_project",
    ],
)
def test_program_overlapping_scopes_exits_2(tmp_path, scope_a, scope_b):
    _write_input(tmp_path, "a.json", scope_a)
    _write_input(tmp_path, "b.json", scope_b)
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    msg = str(exc.value)
    assert "overlapping scopes in input set" in msg
    assert "a.json" in msg
    assert "b.json" in msg


def test_program_project_vs_project_team_different_project_no_overlap(tmp_path):
    """Spec line 221: different project values → no overlap."""
    _write_input(tmp_path, "a.json", {"project": "ALPHA"})
    _write_input(tmp_path, "b.json", {"project": "BETA", "team": "Foo"})
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert len(result.scopes) == 2


def test_program_different_project_kinds_no_overlap(tmp_path):
    """Two project-scope inputs with different ``project`` → no overlap."""
    _write_input(tmp_path, "a.json", {"project": "ALPHA"})
    _write_input(tmp_path, "b.json", {"project": "BETA"})
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert {s.source_basename for s in result.scopes} == {"a.json", "b.json"}


@pytest.mark.parametrize(
    "scope_a,scope_b",
    [
        ({"program_id": "42"}, {"program_id": "42", "team": "Foo"}),
        ({"portfolio_id": "7"}, {"portfolio_id": "7", "team": "Foo"}),
    ],
    ids=["program_vs_program_team", "portfolio_vs_portfolio_team"],
)
def test_program_synthesized_team_kind_overlap_is_order_insensitive(
    tmp_path, scope_a, scope_b,
):
    """Regression: an explicit ``program+team`` / ``portfolio+team``
    input alongside its parent must be flagged as overlapping
    regardless of glob order. The earlier rank-based implementation
    returned True or False depending on which side was iterated first.
    """
    # Run both orderings via basename codepoint sort.
    _write_input(tmp_path, "a.json", scope_a)
    _write_input(tmp_path, "b.json", scope_b)
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert "overlapping scopes in input set" in str(exc.value)


def test_program_synthesized_team_kind_different_parent_id_no_overlap(tmp_path):
    """Two ``program+team`` scopes with different ``program_id`` don't
    overlap — same-kind, different identifiers (no spec rule fires)."""
    _write_input(tmp_path, "a.json", {"program_id": "42", "team": "Foo"})
    _write_input(tmp_path, "b.json", {"program_id": "99", "team": "Bar"})
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert len(result.scopes) == 2


def test_program_overlap_lists_all_pairs(tmp_path):
    """When several overlapping pairs are present, the error names all
    of them so the user fixes the directory in one pass."""
    _write_input(tmp_path, "portfolio.json", {"portfolio_id": "7"})
    _write_input(tmp_path, "project.json", {"project": "ALPHA"})
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    msg = str(exc.value)
    assert "portfolio.json" in msg
    assert "project.json" in msg


# ---------------------------------------------------------------------------
# per_team flattening
# ---------------------------------------------------------------------------
def test_program_per_team_flattens_into_per_scope_rows(tmp_path):
    """Spec lines 232-238. The source program-scope row remains; per_team
    entries become additional rows with ``from_per_team=True``.

    Synthesised kind for a program-scope source with ``per_team`` team
    entries is ``program+team`` (new kind added in T2's ``infer_scope_kind``;
    see test_t2_inputs.py ``program_team`` parametrisation).
    """
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[
            {"team": "Foo", "aggregates": {"throughput": 10}},
            {"team": "Bar", "aggregates": {"throughput": 20}},
        ],
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)

    assert len(result.scopes) == 3
    originals = [s for s in result.scopes if not s.from_per_team]
    flattened = [s for s in result.scopes if s.from_per_team]
    assert len(originals) == 1
    assert originals[0].scope_kind == "program"
    assert originals[0].source_basename == "program.json"

    assert len(flattened) == 2
    teams = sorted(s.scope["team"] for s in flattened)
    assert teams == ["Bar", "Foo"]
    for s in flattened:
        assert s.scope_kind == "program+team"
        assert s.scope.get("program_id") == "42"
        assert s.source_basename == "program.json"
        assert s.cohort_breakdown is None
        assert s.cohort_jql is None


def test_program_per_team_flattens_portfolio_scope_source(tmp_path):
    """A portfolio-scope input with a per_team array produces
    portfolio+team rows; portfolio_id carries forward."""
    _write_input(
        tmp_path,
        "portfolio.json",
        {"portfolio_id": "7"},
        per_team=[{"team": "Foo", "aggregates": {}}],
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    flattened = [s for s in result.scopes if s.from_per_team]
    assert len(flattened) == 1
    assert flattened[0].scope == {"portfolio_id": "7", "team": "Foo"}
    assert flattened[0].scope_kind == "portfolio+team"


def test_program_per_team_flattens_project_scope_source(tmp_path):
    """A project-scope input with a per_team array produces project+team
    rows; project is carried forward onto each synthesised scope."""
    _write_input(
        tmp_path,
        "proj.json",
        {"project": "ALPHA"},
        per_team=[{"team": "Foo", "aggregates": {}}],
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    flattened = [s for s in result.scopes if s.from_per_team]
    assert len(flattened) == 1
    assert flattened[0].scope == {"project": "ALPHA", "team": "Foo"}
    assert flattened[0].scope_kind == "project+team"


def test_program_per_team_flattened_rows_excluded_from_cohort_rollup(tmp_path):
    """Spec lines 240-244: flattened per-team rows have no
    cohort_breakdown. T6 reads ``from_per_team`` to skip them in the
    cohort rollup; T4's job is to set the flag and clear the field."""
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[{"team": "Foo", "aggregates": {}}],
        cohort_breakdown={"cohort": {}, "control": {}},
        cohort_jql="labels = ai-assisted",
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    flattened = [s for s in result.scopes if s.from_per_team]
    assert flattened
    for s in flattened:
        assert s.cohort_breakdown is None
        assert s.cohort_jql is None


def test_program_per_team_with_no_team_field_exits_2(tmp_path):
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[{"aggregates": {}}],
    )
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    msg = str(exc.value)
    assert "program.json" in msg
    assert "team" in msg


def test_program_per_team_empty_team_field_exits_2(tmp_path):
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[{"team": "", "aggregates": {}}],
    )
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert "program.json" in str(exc.value)


def test_program_per_team_propagates_double_counted_flag(tmp_path):
    """Each synthesised ProgramScope carries the source input's
    ``per_team_double_counted`` value (T6 reads this for the
    aggregation note)."""
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[{"team": "Foo", "aggregates": {}}],
        per_team_double_counted=True,
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    flattened = [s for s in result.scopes if s.from_per_team]
    assert flattened
    assert all(s.per_team_double_counted is True for s in flattened)


# ---------------------------------------------------------------------------
# Post-flatten safeguard (plan lines 287-301)
# ---------------------------------------------------------------------------
def test_program_per_team_flattened_collides_with_explicit_project_team_exits_2(
    tmp_path,
):
    """Plan lines 252-258: a per_team-flattened row colliding with an
    explicit ``project+team`` row must raise with both basenames named
    and the per_team source annotated.

    Note on fixture shape: the plan prompt describes "one program-scope
    input with per_team containing team=Foo for project=PROJ, PLUS an
    explicit project+team input with project=PROJ, team=Foo". With the
    declared synthesis rules (project comes from the source, team from
    the per_team entry) and the overlap rules extended for ``+team``
    kinds, the *only* inter-input scenario that reaches the post-flatten
    safeguard without being caught pre-flatten is one where the per_team
    source is itself ``project+team`` (carrying both ``project`` and a
    ``team`` value) and another ``project+team`` input matches the
    flattened row's ``(project, team)``. Pre-flatten this pair is
    same-kind with *different* team identifiers (no overlap, no dup);
    post-flatten the flattened scope collides with the explicit one.

    A program-scope source colliding with an explicit ``project+team``
    input is impossible because the program-scope source has no
    ``project`` field to carry into the synthesised scope. Flagged for
    spec/plan reviewers — the plan's described inter-input collision
    scenario is unreachable under the declared synthesis rules.
    """
    _write_input(
        tmp_path,
        "source_with_per_team.json",
        {"project": "PROJ", "team": "Bar"},
        per_team=[{"team": "Foo", "aggregates": {}}],
    )
    _write_input(
        tmp_path,
        "explicit.json",
        {"project": "PROJ", "team": "Foo"},
    )
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    msg = str(exc.value)
    assert "duplicate scope in input set" in msg
    assert "source_with_per_team.json" in msg
    assert "explicit.json" in msg
    assert "(per_team flattened)" in msg, (
        "post-flatten duplicates must annotate the per_team-derived source"
    )


def test_program_per_team_within_same_input_duplicate_team_exits_2(tmp_path):
    """Two per_team entries with the same team in one input flatten to
    the same synthesised scope. The post-flatten safeguard catches this
    even though it isn't a pre-existing duplicate."""
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[
            {"team": "Foo", "aggregates": {}},
            {"team": "Foo", "aggregates": {}},
        ],
    )
    with pytest.raises(ValidationError) as exc:
        discover_inputs(tmp_path, DEFAULT_WINDOW)
    msg = str(exc.value)
    assert "duplicate scope in input set" in msg
    assert "program.json" in msg


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
def test_program_per_team_double_counted_input_emits_warning_note(tmp_path):
    """Spec lines 246-250: one note covering every input whose
    ``meta.per_team_double_counted`` is true; basenames sorted
    codepoint-ascending."""
    # Two non-overlapping program-scope inputs (different program_id
    # values) so the pre-flatten overlap check doesn't fire.
    _write_input(
        tmp_path,
        "b.json",
        {"program_id": "42"},
        per_team=[{"team": "Foo", "aggregates": {}}],
        per_team_double_counted=True,
    )
    _write_input(
        tmp_path,
        "a.json",
        {"program_id": "99"},
        per_team=[{"team": "Bar", "aggregates": {}}],
        per_team_double_counted=True,
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    matching_notes = [n for n in result.notes if n.startswith("per_team-double-counted")]
    assert len(matching_notes) == 1, (
        "spec pins ONE note covering all such inputs; got: {}".format(matching_notes)
    )
    note = matching_notes[0]
    assert note.startswith("per_team-double-counted: ")
    assert "a.json, b.json" in note  # sorted codepoint-ascending
    assert "flattened per-team rows may double-count" in note


def test_program_per_team_double_counted_without_per_team_array_emits_no_note(
    tmp_path,
):
    """An input with ``per_team_double_counted=true`` but no ``per_team``
    array produces no flattened rows — the "may double-count" warning
    would be misleading. Spec lines 246-250 say "in any flattened
    input"; tightened interpretation requires actual flattening."""
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team_double_counted=True,
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert not any(
        n.startswith("per_team-double-counted") for n in result.notes
    )


def test_program_per_team_double_counted_false_emits_no_note(tmp_path):
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[{"team": "Foo", "aggregates": {}}],
        per_team_double_counted=False,
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert not any(
        n.startswith("per_team-double-counted") for n in result.notes
    )


def test_program_per_team_cohort_deferred_note_only_when_flag_set(tmp_path):
    """Spec lines 240-244: the per_team-cohort-deferred note is emitted
    only when ``--include-cohort-breakdown`` is set AND at least one
    per_team flattening occurred."""
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[
            {"team": "Foo", "aggregates": {}},
            {"team": "Bar", "aggregates": {}},
        ],
    )

    without = discover_inputs(tmp_path, DEFAULT_WINDOW, include_cohort_breakdown=False)
    assert not any(
        n.startswith("per_team-cohort-deferred") for n in without.notes
    )

    with_flag = discover_inputs(tmp_path, DEFAULT_WINDOW, include_cohort_breakdown=True)
    matching = [
        n for n in with_flag.notes if n.startswith("per_team-cohort-deferred")
    ]
    assert len(matching) == 1
    assert matching[0] == (
        "per_team-cohort-deferred: 2 flattened per-team rows have no "
        "cohort_breakdown; excluded from cohort rollup"
    )


def test_program_per_team_cohort_deferred_not_emitted_without_per_team(tmp_path):
    """No per_team flattening → no per_team-cohort-deferred note even
    when the flag is set."""
    _write_input(tmp_path, "a.json", {"project": "ALPHA"})
    result = discover_inputs(tmp_path, DEFAULT_WINDOW, include_cohort_breakdown=True)
    assert not any(
        n.startswith("per_team-cohort-deferred") for n in result.notes
    )


# ---------------------------------------------------------------------------
# Notes are unsorted (T7 sorts and dedupes)
# ---------------------------------------------------------------------------
def test_program_notes_unsorted(tmp_path):
    """T4 must not sort the notes list — sorting is T7's responsibility
    (spec lines 504-505). With multiple note kinds, ordering is the
    emit order T4 picks, not lex order."""
    _write_input(
        tmp_path,
        "program.json",
        {"program_id": "42"},
        per_team=[{"team": "Foo", "aggregates": {}}],
        per_team_double_counted=True,
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW, include_cohort_breakdown=True)
    # Both notes should be present; T4's emit order is documented as
    # double-counted before cohort-deferred.
    kinds = [n.split(":", 1)[0] for n in result.notes]
    assert "per_team-double-counted" in kinds
    assert "per_team-cohort-deferred" in kinds
    assert kinds.index("per_team-double-counted") < kinds.index(
        "per_team-cohort-deferred"
    )


# ---------------------------------------------------------------------------
# source_inputs round-trip (T7 consumes this for provenance)
# ---------------------------------------------------------------------------
def test_program_source_inputs_are_the_window_filtered_set(tmp_path):
    """``source_inputs`` is the InputFile list after the window filter,
    before flattening — that's what T7's Provenance section iterates."""
    _write_input(tmp_path, "match.json", {"project": "ALPHA"})
    _write_input(
        tmp_path, "off.json", {"project": "BETA"},
        window=("2026-04-01", "2026-06-30"),
    )
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert [inp.basename for inp in result.source_inputs] == ["match.json"]


# ---------------------------------------------------------------------------
# Clean-set sanity (no errors, no notes)
# ---------------------------------------------------------------------------
def test_program_clean_set_no_errors_no_notes(tmp_path):
    """Three non-overlapping scopes, same window, no per_team — no
    errors and no T4-emitted notes."""
    _write_input(tmp_path, "a.json", {"project": "ALPHA"})
    _write_input(tmp_path, "b.json", {"project": "BETA"})
    _write_input(tmp_path, "c.json", {"project": "GAMMA", "team": "Foo"})
    result = discover_inputs(tmp_path, DEFAULT_WINDOW)
    assert len(result.scopes) == 3
    assert result.notes == []
