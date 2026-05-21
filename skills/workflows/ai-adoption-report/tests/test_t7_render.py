"""T7 contract tests for render.py.

Covers every test from plan §T7 (lines 443-461) plus the implied tests
listed in the T7 task brief.
"""
from __future__ import annotations

import json
import math
import re

import pytest

from ai_adoption_report.delta import (
    CANONICAL_METRIC_ORDER,
    PERCENTILES,
    compute_deltas,
)
from ai_adoption_report.modes import ReportData
from ai_adoption_report.render import (
    _MARKDOWN_ESCAPE_CHARS,
    _finalize_notes,
    _fmt_cell,
    _fmt_percent,
    _md_escape,
    render_json,
    render_markdown,
)

from fixtures.render import (
    aggregate_block,
    baseline_report,
    cohort_report,
    make_input_file,
    program_report,
)


GENERATED_AT = "2026-05-19T14:30:00Z"
TITLE = "AI-adoption report — test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _section_present(md: str, heading: str) -> bool:
    return "\n## {}\n".format(heading) in "\n" + md


def _table_after(md: str, heading: str) -> list[str]:
    """Return the lines (excluding heading + blank) of the table under
    ``heading``. Includes the header row, separator row, and data rows
    in document order. Empty list if heading not present.
    """
    lines = md.splitlines()
    try:
        i = lines.index("## {}".format(heading))
    except ValueError:
        return []
    out: list[str] = []
    for line in lines[i + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("|"):
            out.append(line)
    return out


# ---------------------------------------------------------------------------
# Markdown — section omission
# ---------------------------------------------------------------------------
def test_markdown_sections_omitted_when_empty():
    # Program mode with zero per-scope rows → no Per-scope rows header.
    degen = program_report(scope_team_names=())
    degen.per_scope_rows = []
    md = render_markdown(degen, title=TITLE, generated_at=GENERATED_AT)
    assert not _section_present(md, "Per-scope rows")
    # Baseline mode without --include-cohort-breakdown → no Cohort breakdown.
    bl = baseline_report(include_cohort_breakdown=False)
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    assert not _section_present(md, "Cohort breakdown")
    # Report with empty notes → no Notes section.
    bl_quiet = baseline_report()
    bl_quiet.notes = []
    md = render_markdown(bl_quiet, title=TITLE, generated_at=GENERATED_AT)
    assert not _section_present(md, "Notes")


# ---------------------------------------------------------------------------
# Markdown — unicode minus vs ASCII hyphen
# ---------------------------------------------------------------------------
def test_markdown_unicode_minus_in_numeric_cells_ascii_hyphen_in_dates():
    bl = baseline_report()  # cycle p50 goes 38.2 → 31.5 (negative delta)
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    # The Δ abs cell for cycle_time_hours p50 should carry U+2212.
    assert "−" in md, "expected U+2212 (unicode minus) somewhere in numeric cells"
    # The window dates in the header line use ASCII hyphen.
    header = md.split("## Summary")[0]
    assert "2024-01-01..2024-03-31" in header
    # And nowhere in the date range should U+2212 appear (only ASCII -).
    assert "2024−0101" not in md  # belt + braces
    date_match = re.search(r"2024-\d\d-\d\d\.\.2024-\d\d-\d\d", header)
    assert date_match is not None


# ---------------------------------------------------------------------------
# Markdown — escape rule
# ---------------------------------------------------------------------------
def test_markdown_scope_team_names_escaped():
    # Project + team with every Markdown escape char in the names.
    funky_scope = {"project": "PROJ|pipe", "team": "Foo*star_under[bracket]back\\slash#hash+plus`tick"}
    bl = baseline_report(scope=funky_scope)
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    # Every escape char must appear backslash-prefixed somewhere in the
    # rendered Markdown.
    for c in _MARKDOWN_ESCAPE_CHARS:
        assert "\\" + c in md, (
            "expected backslash-escaped '{}' in rendered Markdown".format(c)
        )

    # ASCII hyphen in Mobile-Web must NOT be escaped.
    hyphen_scope = {"project": "PROJ", "team": "Mobile-Web"}
    bl2 = baseline_report(scope=hyphen_scope)
    md2 = render_markdown(bl2, title=TITLE, generated_at=GENERATED_AT)
    assert "Mobile-Web" in md2
    assert "Mobile\\-Web" not in md2


# ---------------------------------------------------------------------------
# Markdown — canonical row order
# ---------------------------------------------------------------------------
def test_markdown_metric_rows_in_canonical_order():
    bl = baseline_report()
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    rows = _table_after(md, "Metric deltas")
    # Drop header + separator rows.
    data_rows = rows[2:]
    # Pull the metric label from the first column.
    labels = [r.split("|", 2)[1].strip() for r in data_rows]
    assert labels == list(CANONICAL_METRIC_ORDER)


# ---------------------------------------------------------------------------
# Markdown — distribution metric one row per percentile
# ---------------------------------------------------------------------------
def test_markdown_distribution_metric_one_row_per_percentile():
    bl = baseline_report()
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    rows = _table_after(md, "Metric deltas")
    text = "\n".join(rows)
    for p in PERCENTILES:
        assert "cycle_time_hours {}".format(p) in text


# ---------------------------------------------------------------------------
# Markdown — n-differs note appears in Notes section
# ---------------------------------------------------------------------------
def test_markdown_n_differs_more_than_10pct_emits_note():
    # Construct a baseline where cycle_time_hours.n differs > 10%.
    a_agg = aggregate_block()
    b_agg = aggregate_block()
    a_agg["cycle_time_hours"]["n"] = 100
    b_agg["cycle_time_hours"]["n"] = 130
    result = compute_deltas(a_agg, b_agg, side_labels=("baseline", "current"))
    bl = baseline_report()
    bl.deltas = result.to_dict()
    bl.notes = list(result.notes)
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    notes_block = md.split("## Notes")[1] if "## Notes" in md else ""
    assert "n-differs: cycle_time_hours" in notes_block


# ---------------------------------------------------------------------------
# JSON — keys sorted except deltas
# ---------------------------------------------------------------------------
def test_json_sidecar_keys_sorted_except_deltas_in_canonical_order():
    bl = baseline_report()
    js = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    parsed = json.loads(js)

    # Top-level keys sorted lex.
    top_keys = list(parsed.keys())
    assert top_keys == sorted(top_keys), top_keys

    # meta keys sorted lex.
    meta_keys = list(parsed["meta"].keys())
    assert meta_keys == sorted(meta_keys), meta_keys

    # meta.inputs[0] keys sorted lex.
    inp_keys = list(parsed["meta"]["inputs"][0].keys())
    assert inp_keys == sorted(inp_keys), inp_keys

    # deltas keys follow CANONICAL_METRIC_ORDER (top-level metric names).
    deltas_keys = list(parsed["deltas"].keys())
    # Compute the expected top-level metric names from CANONICAL_METRIC_ORDER
    # (collapse "<metric> p50" → "metric", "flow_distribution.x" → "flow_distribution").
    expected: list[str] = []
    for label in CANONICAL_METRIC_ORDER:
        top = label.split(" ", 1)[0].split(".", 1)[0]
        if top not in expected:
            expected.append(top)
    # Filter expected to ones actually present in deltas (the fixture
    # populates all of them).
    expected = [m for m in expected if m in deltas_keys]
    assert deltas_keys == expected, (deltas_keys, expected)


# ---------------------------------------------------------------------------
# JSON — floats rounded to 4dp
# ---------------------------------------------------------------------------
def test_json_sidecar_floats_4dp():
    # Build a delta with a non-round pct that the renderer must round to 4dp.
    a_agg = aggregate_block(throughput=7, rework_rate=0.21428571428)
    b_agg = aggregate_block(throughput=8, rework_rate=0.21428571428 * 2)
    result = compute_deltas(a_agg, b_agg, side_labels=("baseline", "current"))
    bl = baseline_report()
    bl.deltas = result.to_dict()
    js = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    # The raw 0.21428571428 must NOT appear; the rounded 0.2143 must.
    assert "0.21428571428" not in js
    assert "0.2143" in js


# ---------------------------------------------------------------------------
# JSON — inputs sorted by basename
# ---------------------------------------------------------------------------
def test_json_sidecar_inputs_sorted_by_basename():
    bl = baseline_report()
    # Reverse the inputs list to confirm the renderer re-sorts.
    bl.inputs = list(reversed(bl.inputs))
    js = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    parsed = json.loads(js)
    basenames = [i["basename"] for i in parsed["meta"]["inputs"]]
    assert basenames == sorted(basenames), basenames


# ---------------------------------------------------------------------------
# JSON — scope_kind on inputs
# ---------------------------------------------------------------------------
def test_json_sidecar_scope_kind_present_on_inputs():
    bl = baseline_report()
    js = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    parsed = json.loads(js)
    valid_kinds = {
        "project", "project+team", "program", "program+team",
        "portfolio", "portfolio+team",
    }
    for inp in parsed["meta"]["inputs"]:
        assert "scope_kind" in inp
        assert inp["scope_kind"] in valid_kinds, inp["scope_kind"]


# ---------------------------------------------------------------------------
# Byte-identical rerun modulo generated_at
# ---------------------------------------------------------------------------
def test_byte_identical_rerun_modulo_generated_at(monkeypatch):
    monkeypatch.setenv("LC_ALL", "C")
    bl = baseline_report(include_cohort_breakdown=True)

    md_a = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    md_b = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    assert md_a == md_b

    js_a = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    js_b = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    assert js_a == js_b

    other_at = "2099-12-31T23:59:59Z"
    md_c = render_markdown(bl, title=TITLE, generated_at=other_at)
    js_c = render_json(bl, title=TITLE, generated_at=other_at)
    # Only generated_at differs.
    assert md_a.replace(GENERATED_AT, other_at) == md_c
    # JSON: the generated_at value appears verbatim; replace and compare.
    assert js_a.replace(GENERATED_AT, other_at) == js_c


# ---------------------------------------------------------------------------
# Notes — merged + sorted + deduped from all sources
# ---------------------------------------------------------------------------
def test_notes_from_all_sources_merged_and_sorted():
    bl = baseline_report()
    # Inject one T2-style note, one T4-style note, one T5-style note.
    t2 = "mixed-major-schema-versions: 1 (PROJ-Foo-2024Q1.json), 2 (PROJ-Foo-2024Q2.json)"
    t4 = "per_team-double-counted: PROJ-Foo-2024Q1.json; flattened per-team rows may double-count issues that span multiple teams"
    t5 = "cycle_time_hours null in baseline"
    bl.notes = bl.notes + [t2, t4, t5, t5]  # one duplicate

    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    js = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    parsed = json.loads(js)

    for n in (t2, t4, t5):
        assert n in md
        assert n in parsed["notes"]
    # Dedup: t5 appears only once in JSON notes.
    assert parsed["notes"].count(t5) == 1
    # Lex sort.
    assert parsed["notes"] == sorted(parsed["notes"])


# ---------------------------------------------------------------------------
# Additional implied tests
# ---------------------------------------------------------------------------
def test_percent_cell_positive_zero_renders_plus_zero():
    assert _fmt_percent(0.0) == "+0.0%"
    assert _fmt_percent(-0.0) == "+0.0%"


def test_percent_cell_infinity_renders_with_unicode_symbol():
    assert _fmt_percent(math.inf) == "+∞%"
    assert _fmt_percent(-math.inf) == "−∞%"


def test_em_dash_for_none_cells():
    assert _fmt_cell(None, kind="int") == "—"
    assert _fmt_cell(None, kind="float") == "—"
    assert _fmt_cell(None, kind="percent") == "—"
    assert _fmt_cell(None, kind="hours") == "—"


def test_provenance_section_lists_every_input():
    bl = baseline_report()
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    prov_section = md.split("## Provenance")[1]
    for inp in bl.inputs:
        assert inp.basename in prov_section
        # window dates
        assert inp.window_from in prov_section
        assert inp.window_to in prov_section
        # both shas
        assert inp.meta["state_config_sha"] in prov_section
        assert inp.meta["issuetype_config_sha"] in prov_section
        # generated_at
        assert inp.meta["generated_at"] in prov_section
        # schema version
        major, minor = inp.schema_version
        assert "schema {}.{}".format(major, minor) in prov_section


def test_markdown_summary_line_present():
    bl = baseline_report()
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    assert "## Summary" in md
    # Pull the line(s) after the heading until the next "## ".
    summary_block = md.split("## Summary")[1].split("## ")[0].strip()
    assert summary_block, "summary block must be non-empty"


# ---------------------------------------------------------------------------
# Program-mode specific
# ---------------------------------------------------------------------------
def test_program_mode_per_scope_table_includes_aggregate_row():
    rep = program_report()
    md = render_markdown(rep, title=TITLE, generated_at=GENERATED_AT)
    rows = _table_after(md, "Per-scope rows")
    data = rows[2:]  # header + separator
    # Last row should be the Aggregate row.
    assert data[-1].split("|", 2)[1].strip() == "Aggregate"
    # Per-scope rows sorted by scope_repr.
    scope_labels = [r.split("|", 2)[1].strip() for r in data[:-1]]
    assert scope_labels == sorted(scope_labels)


def test_program_mode_json_has_per_scope_and_program_aggregates():
    rep = program_report()
    js = render_json(rep, title=TITLE, generated_at=GENERATED_AT)
    parsed = json.loads(js)
    assert "per_scope" in parsed
    assert isinstance(parsed["per_scope"], list)
    assert "program_aggregates" in parsed
    # per_scope sorted by scope_repr.
    reprs = [r["scope_repr"] for r in parsed["per_scope"]]
    assert reprs == sorted(reprs)


def test_program_mode_summary_describes_scope_count():
    rep = program_report()
    md = render_markdown(rep, title=TITLE, generated_at=GENERATED_AT)
    summary = md.split("## Summary")[1].split("## ")[0]
    assert "scope" in summary.lower()


# ---------------------------------------------------------------------------
# Cohort breakdown in JSON
# ---------------------------------------------------------------------------
def test_baseline_with_cohort_breakdown_emits_cohort_section():
    bl = baseline_report(include_cohort_breakdown=True)
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    assert _section_present(md, "Cohort breakdown")
    # Baseline+cohort labels: ("baseline-cohort", "current-cohort").
    rows = _table_after(md, "Cohort breakdown")
    assert "baseline-cohort" in rows[0]
    assert "current-cohort" in rows[0]

    js = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    parsed = json.loads(js)
    assert "cohort_breakdown" in parsed
    assert parsed["meta"]["options"]["include_cohort_breakdown"] is True


# ---------------------------------------------------------------------------
# _finalize_notes
# ---------------------------------------------------------------------------
def test_finalize_notes_sorts_and_dedupes():
    inp = ["b", "a", "b", "c", "a"]
    assert _finalize_notes(inp) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Numeric formatting smoke tests
# ---------------------------------------------------------------------------
def test_fmt_cell_float_strips_trailing_zeros():
    # 38.20000000000001 → 38.2 (round to 4dp, json.dumps shortest repr).
    s = _fmt_cell(38.20000000000001, kind="float")
    assert s == "38.2"


def test_fmt_cell_hours_uses_raw_hours_not_days():
    s = _fmt_cell(48.0, kind="hours")
    # Raw hours; not converted to days.
    assert s == "48"


def test_fmt_cell_negative_uses_unicode_minus():
    s = _fmt_cell(-6.7, kind="hours")
    assert s.startswith("−")
    assert "-" not in s  # no ASCII hyphen


# ---------------------------------------------------------------------------
# Adversarial coverage (post-review additions)
# ---------------------------------------------------------------------------
def test_metric_absent_on_both_sides_omits_row():
    """Spec line 362: metrics absent from both sides are omitted entirely.
    Trivially relies on T5 producing no row, but verify T7 doesn't
    surface anything (e.g., no ghost row for ``defect_ratio`` when
    neither side has it).
    """
    a = {"throughput": 80}
    b = {"throughput": 100}
    result = compute_deltas(a, b, side_labels=("baseline", "current"))
    bl = baseline_report()
    bl.deltas = result.to_dict()
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    rows = _table_after(md, "Metric deltas")
    text = "\n".join(rows)
    assert "defect_ratio" not in text
    assert "rework_rate" not in text
    assert "cycle_time_hours" not in text


def test_zero_baseline_pct_renders_inf_in_markdown_table():
    """Spec lines 326-327: A=0,B>0 → +∞%. Exercise the full pipeline so
    a regression in _delta_rows_for_render or _fmt_cell surfaces.
    """
    a = {"throughput": 0, "rework_rate": 0.0}
    b = {"throughput": 5, "rework_rate": 0.1}
    result = compute_deltas(a, b, side_labels=("baseline", "current"))
    bl = baseline_report()
    bl.deltas = result.to_dict()
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    rows = "\n".join(_table_after(md, "Metric deltas"))
    assert "+∞%" in rows


def test_cohort_breakdown_json_keys_sorted_alphabetically():
    """JSON canonicalization spec line 508: only ``deltas`` is the
    canonical-order exception. ``cohort_breakdown`` is sort_keys=True.
    """
    bl = baseline_report(include_cohort_breakdown=True)
    js = render_json(bl, title=TITLE, generated_at=GENERATED_AT)
    parsed = json.loads(js)
    cohort_keys = list(parsed["cohort_breakdown"].keys())
    assert cohort_keys == sorted(cohort_keys), cohort_keys


def test_cohort_breakdown_column_labels_match_data_baseline():
    """Verify the cohort-breakdown table header matches the side_labels
    threaded from compute_deltas. For baseline+cohort: labels are
    ``("baseline-cohort", "current-cohort")``.
    """
    bl = baseline_report(include_cohort_breakdown=True)
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    rows = _table_after(md, "Cohort breakdown")
    header = rows[0]
    assert "baseline-cohort" in header
    assert "current-cohort" in header
    # And the legacy hardcoded labels are NOT present.
    assert "| cohort |" not in header
    assert "| control |" not in header


def test_cohort_breakdown_column_labels_match_data_program():
    """For program-mode cohort rollup: labels are
    ``("control", "cohort")``. Confirm the column order matches.
    """
    rep = program_report(include_cohort_breakdown=True)
    md = render_markdown(rep, title=TITLE, generated_at=GENERATED_AT)
    rows = _table_after(md, "Cohort breakdown")
    header = rows[0]
    # Column order is "Metric | control | cohort | Δ abs | Δ %"
    parts = [p.strip() for p in header.split("|") if p.strip()]
    assert parts[1] == "control"
    assert parts[2] == "cohort"


def test_provenance_sorted_by_basename_in_markdown():
    """Provenance bullets in Markdown sorted by basename ascending.
    Counterpart to ``test_json_sidecar_inputs_sorted_by_basename`` for
    the Markdown path.
    """
    bl = baseline_report()
    bl.inputs = list(reversed(bl.inputs))
    md = render_markdown(bl, title=TITLE, generated_at=GENERATED_AT)
    prov = md.split("## Provenance")[1]
    # Pull the first token of each bullet (escaped basename).
    bullets = [
        line[2:].split(" — ", 1)[0]
        for line in prov.splitlines()
        if line.startswith("- ")
    ]
    # Strip escape backslashes for the sort comparison (escaped
    # underscores would otherwise distort sort).
    raw = [b.replace("\\", "") for b in bullets]
    assert raw == sorted(raw)


def test_title_with_markdown_specials_is_escaped():
    """User-supplied title is escaped before insertion into the heading."""
    bl = baseline_report()
    md = render_markdown(
        bl, title="Report *with* |pipes| and _underscores_", generated_at=GENERATED_AT
    )
    first = md.splitlines()[0]
    assert "\\*with\\*" in first
    assert "\\|pipes\\|" in first
    assert "\\_underscores\\_" in first


def test_program_mode_json_deltas_is_empty_dict():
    """Program mode produces no global deltas; the JSON sidecar must
    still emit ``"deltas":{}`` (not omit the key) so the schema is
    consistent across modes.
    """
    rep = program_report()
    js = render_json(rep, title=TITLE, generated_at=GENERATED_AT)
    assert '"deltas":{}' in js
    parsed = json.loads(js)
    assert parsed["deltas"] == {}


def test_cohort_mode_renders_with_control_cohort_labels():
    """Cohort-mode primary delta table uses labels ``("control",
    "cohort")``. Exercises the cohort_report fixture for end-to-end
    coverage of the third mode.
    """
    rep = cohort_report()
    md = render_markdown(rep, title=TITLE, generated_at=GENERATED_AT)
    rows = _table_after(md, "Metric deltas")
    header = rows[0]
    parts = [p.strip() for p in header.split("|") if p.strip()]
    assert parts[1] == "control"
    assert parts[2] == "cohort"
    # JSON sidecar: mode field round-trips.
    js = render_json(rep, title=TITLE, generated_at=GENERATED_AT)
    assert json.loads(js)["meta"]["mode"] == "cohort"


def test_meta_options_include_cohort_breakdown_reflects_cohort_deltas_presence():
    """``meta.options.include_cohort_breakdown`` mirrors whether
    ``cohort_deltas`` was populated, so the flag round-trips through the
    sidecar without T7 needing access to the original CLI args.
    """
    bl_off = baseline_report(include_cohort_breakdown=False)
    js_off = render_json(bl_off, title=TITLE, generated_at=GENERATED_AT)
    assert json.loads(js_off)["meta"]["options"]["include_cohort_breakdown"] is False

    bl_on = baseline_report(include_cohort_breakdown=True)
    js_on = render_json(bl_on, title=TITLE, generated_at=GENERATED_AT)
    assert json.loads(js_on)["meta"]["options"]["include_cohort_breakdown"] is True
