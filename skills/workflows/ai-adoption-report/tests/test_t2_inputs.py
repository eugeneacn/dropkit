"""T2 contract tests: input loading, meta validation, scope-kind inference.

Mirrors every test enumerated in docs/specs/ai-adoption-report-plan.md
§T2. Each error path is asserted to (a) exit 2 / raise
:class:`ValidationError`, and (b) name the offending file's basename in
the error message so the user knows which file in a glob is bad.
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from ai_adoption_report import ValidationError
from ai_adoption_report.inputs import (
    InputFile,
    REQUIRED_META_KEYS,
    collect_mixed_major_note,
    infer_scope_kind,
    load_input,
)


FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "inputs"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _good_meta() -> Dict[str, Any]:
    return {
        "caller": "test-account",
        "scope": {"project": "ALPHA"},
        "window": {"from": "2026-01-01", "to": "2026-01-31"},
        "state_config_sha": "a" * 64,
        "issuetype_config_sha": "b" * 64,
        "schema_version": "1.0",
        "generated_at": "2026-02-01T00:00:00Z",
    }


def _good_doc(meta_override: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    meta = _good_meta()
    if meta_override is not None:
        meta.update(meta_override)
    return {"meta": meta, "aggregates": {}}


def _write_json(path: Path, doc: Any) -> Path:
    path.write_text(json.dumps(doc), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Missing-required-meta-field — parameterised across all six keys
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("missing_key", list(REQUIRED_META_KEYS))
def test_missing_required_meta_field_exits_2(tmp_path, missing_key):
    doc = _good_doc()
    del doc["meta"][missing_key]
    path = _write_json(tmp_path / "bad-{}.json".format(missing_key), doc)

    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg, "error must name the basename; got: {!r}".format(msg)
    assert missing_key in msg, "error must name the missing field; got: {!r}".format(msg)


# ---------------------------------------------------------------------------
# Unreadable file
# ---------------------------------------------------------------------------
def test_unreadable_input_file_exits_2_with_basename(tmp_path):
    path = tmp_path / "does-not-exist.json"
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    assert path.name in str(exc.value)


@pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0,
    reason="chmod-based permission denial requires POSIX non-root",
)
def test_unreadable_input_file_permission_denied_exits_2_with_basename(tmp_path):
    path = _write_json(tmp_path / "noperm.json", _good_doc())
    path.chmod(0)
    try:
        with pytest.raises(ValidationError) as exc:
            load_input(path)
        assert path.name in str(exc.value)
    finally:
        # Restore so pytest's tmp_path cleanup can rm the file.
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)


# ---------------------------------------------------------------------------
# Invalid JSON
# ---------------------------------------------------------------------------
def test_invalid_json_input_exits_2_with_basename(tmp_path):
    path = tmp_path / "garbage.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "JSON" in msg or "json" in msg


def test_top_level_not_object_exits_2_with_basename(tmp_path):
    path = _write_json(tmp_path / "array.json", [1, 2, 3])
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    assert path.name in str(exc.value)


def test_top_level_null_exits_2_with_basename(tmp_path):
    """``json.loads("null")`` returns ``None``; top-level must be an object."""
    path = tmp_path / "null.json"
    path.write_text("null", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    assert path.name in str(exc.value)


def test_empty_file_exits_2_with_basename(tmp_path):
    """Empty file is not valid JSON; should surface a JSON-decode error."""
    path = tmp_path / "empty.json"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "JSON" in msg


def test_meta_missing_entirely_exits_2_with_basename(tmp_path):
    path = _write_json(tmp_path / "no-meta.json", {"aggregates": {}})
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "meta" in msg


@pytest.mark.parametrize(
    "meta_value",
    ["a string", 42, [1, 2], None],
    ids=["string", "int", "list", "null"],
)
def test_meta_not_object_exits_2_with_basename(tmp_path, meta_value):
    """``meta`` present but wrong type — must be rejected, not silently
    treated as a dict via duck-typing."""
    path = _write_json(tmp_path / "bad-meta-type.json", {"meta": meta_value})
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "meta" in msg


def test_meta_window_not_object_exits_2(tmp_path):
    """``meta.window`` must be an object; a date-range string is rejected."""
    doc = _good_doc({"window": "2026-01-01..2026-12-31"})
    path = _write_json(tmp_path / "bad-window-type.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "window" in msg


# ---------------------------------------------------------------------------
# Window format
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "window_override",
    [
        {"from": "2026-02-19T00:00:00Z", "to": "2026-03-19"},  # T-suffix on from
        {"from": "2026-02-19", "to": "2026-03-19T00:00:00Z"},  # T-suffix on to
        {"from": "2026-2-19", "to": "2026-03-19"},             # single-digit month
        {"from": "2026/02/19", "to": "2026-03-19"},            # slashes
        {"from": "", "to": "2026-03-19"},                       # empty string
        {"to": "2026-03-19"},                                    # missing 'from'
        {"from": "2026-02-19"},                                  # missing 'to'
        {},                                                       # missing both
    ],
    ids=[
        "from_t_suffix",
        "to_t_suffix",
        "from_single_digit_month",
        "from_slashes",
        "from_empty",
        "missing_from",
        "missing_to",
        "missing_both",
    ],
)
def test_window_not_iso_date_exits_2(tmp_path, window_override):
    doc = _good_doc({"window": window_override})
    path = _write_json(tmp_path / "bad-window.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "window" in msg


def test_window_invalid_calendar_date_exits_2(tmp_path):
    """The regex passes ``2026-02-30`` but ``date.fromisoformat`` rejects it."""
    doc = _good_doc({"window": {"from": "2026-02-30", "to": "2026-03-19"}})
    path = _write_json(tmp_path / "bad-cal.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    assert path.name in str(exc.value)


def test_window_endpoints_round_trip_verbatim(tmp_path):
    """String equality is the spec's window-match rule; no normalisation."""
    doc = _good_doc({"window": {"from": "2026-01-01", "to": "2026-12-31"}})
    path = _write_json(tmp_path / "ok-window.json", doc)
    inp = load_input(path)
    assert inp.window_from == "2026-01-01"
    assert inp.window_to == "2026-12-31"


# ---------------------------------------------------------------------------
# schema_version parsing
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "value",
    ["1", "1.0.0", "v1.0", "1.x", "", "1.0 ", " 1.0", 1, 1.0, None, ["1", "0"]],
    ids=[
        "no_minor", "three_parts", "v_prefix", "non_digit_minor",
        "empty_string", "trailing_space", "leading_space", "int",
        "float", "null", "array",
    ],
)
def test_schema_version_unparseable_exits_2(tmp_path, value):
    doc = _good_doc({"schema_version": value})
    path = _write_json(tmp_path / "bad-schema.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "schema_version" in msg


def test_schema_version_parses_as_tuple(tmp_path):
    doc = _good_doc({"schema_version": "3.7"})
    path = _write_json(tmp_path / "ok-schema.json", doc)
    inp = load_input(path)
    assert inp.schema_version == (3, 7)


# ---------------------------------------------------------------------------
# mixed-major schema versions
# ---------------------------------------------------------------------------
def test_mixed_major_schema_versions_emits_note():
    a = load_input(FIXTURES_DIR / "project_basic.json")    # schema 1.0
    b = load_input(FIXTURES_DIR / "schema_v2.json")        # schema 2.1
    note = collect_mixed_major_note([a, b])
    assert note is not None
    assert note.startswith("mixed-major-schema-versions: ")
    assert a.basename in note
    assert b.basename in note


def test_mixed_major_schema_versions_same_major_returns_none():
    a = load_input(FIXTURES_DIR / "project_basic.json")    # schema 1.0
    b = load_input(FIXTURES_DIR / "project_team.json")     # schema 1.0
    assert collect_mixed_major_note([a, b]) is None


def test_mixed_major_schema_versions_single_input_returns_none():
    a = load_input(FIXTURES_DIR / "project_basic.json")
    assert collect_mixed_major_note([a]) is None


def test_mixed_major_schema_versions_empty_input_returns_none():
    """No inputs → no note. Guards against a degenerate empty-glob run
    silently emitting ``"mixed-major-schema-versions: "`` with no list."""
    assert collect_mixed_major_note([]) is None


def test_mixed_major_schema_versions_groups_basenames_by_major():
    """Same major across multiple files groups them together in the
    output; different majors get separate segments. Pins the rendering
    enough for downstream golden-file tests to depend on it."""
    from ai_adoption_report.notes import Note

    note = Note.mixed_major_schema_versions([
        (1, "a.json"),
        (2, "c.json"),
        (1, "b.json"),
    ])
    assert note.startswith("mixed-major-schema-versions: ")
    # Lower major first, basenames lex within each group.
    assert "1 (a.json, b.json)" in note
    assert "2 (c.json)" in note
    # Major ordering: 1's segment appears before 2's.
    assert note.index("1 (") < note.index("2 (")


def test_note_factory_rejects_single_major():
    """Note.mixed_major_schema_versions is the wording-only layer; the
    'should we emit?' decision lives in collect_mixed_major_note. Calling
    the factory with a single major is a caller bug."""
    from ai_adoption_report.notes import Note

    with pytest.raises(ValueError):
        Note.mixed_major_schema_versions([(1, "a.json"), (1, "b.json")])
    with pytest.raises(ValueError):
        Note.mixed_major_schema_versions([])


# ---------------------------------------------------------------------------
# Scope shape
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "bad_scope",
    [
        {"team": "Foo"},                                  # team alone
        {"project": "P", "program_id": 42},               # program_id + project
        {"project": "P", "portfolio_id": "9"},            # portfolio_id + project
        {"program_id": "42", "portfolio_id": "9"},        # both Align ids
        {},                                               # empty
    ],
    ids=[
        "team_alone", "project_plus_program", "project_plus_portfolio",
        "program_plus_portfolio", "empty",
    ],
)
def test_unrecognised_scope_shape_exits_2(tmp_path, bad_scope):
    """Dict-shape mismatch: spec lines 141-142 pin the literal prefix
    ``"unrecognised scope shape in <file>"``."""
    doc = _good_doc({"scope": bad_scope})
    path = _write_json(tmp_path / "bad-scope.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "unrecognised scope shape in" in msg, (
        "spec lines 141-142 pin this literal prefix; got: {!r}".format(msg)
    )


@pytest.mark.parametrize(
    "bad_scope",
    ["not-a-dict", ["project", "P"], 42, None],
    ids=["string", "list", "int", "null"],
)
def test_scope_wrong_type_exits_2(tmp_path, bad_scope):
    """``meta.scope`` must be an object. Wrong-type uses a separate
    error message (the scope dict can't be rendered when there's no
    dict)."""
    doc = _good_doc({"scope": bad_scope})
    path = _write_json(tmp_path / "bad-scope-type.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    msg = str(exc.value)
    assert path.name in msg
    assert "scope" in msg


# ---------------------------------------------------------------------------
# Scope kind inference (the happy path)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "scope,expected",
    [
        ({"portfolio_id": "7"}, "portfolio"),
        ({"program_id": "42"}, "program"),
        ({"project": "ALPHA"}, "project"),
        ({"project": "ALPHA", "team": "Foo"}, "project+team"),
        # Synthesized-only kinds produced by T4's per_team flattening of
        # program- or portfolio-scope inputs. Not emitted by flow-metrics
        # directly; inference must accept them so T4 can re-infer on the
        # synthesised dict (see T4 prompt §"What to build").
        ({"program_id": "42", "team": "Foo"}, "program+team"),
        ({"portfolio_id": "7", "team": "Foo"}, "portfolio+team"),
    ],
    ids=["portfolio", "program", "project", "project_team",
         "program_team", "portfolio_team"],
)
def test_scope_kind_inferred_correctly(scope, expected):
    assert infer_scope_kind(scope, basename="x.json") == expected


@pytest.mark.parametrize(
    "fixture,expected",
    [
        ("portfolio.json", "portfolio"),
        ("program.json", "program"),
        ("project_basic.json", "project"),
        ("project_team.json", "project+team"),
    ],
)
def test_scope_kind_inferred_from_fixtures(fixture, expected):
    inp = load_input(FIXTURES_DIR / fixture)
    assert inp.scope_kind == expected


# ---------------------------------------------------------------------------
# cohort_breakdown and per_team passthrough
# ---------------------------------------------------------------------------
def test_cohort_breakdown_passthrough():
    with_cohort = load_input(FIXTURES_DIR / "project_with_cohort.json")
    without = load_input(FIXTURES_DIR / "project_basic.json")
    assert with_cohort.cohort_breakdown is not None
    assert "cohort" in with_cohort.cohort_breakdown
    assert without.cohort_breakdown is None


def test_per_team_passthrough():
    with_per_team = load_input(FIXTURES_DIR / "program.json")
    without = load_input(FIXTURES_DIR / "project_basic.json")
    assert with_per_team.per_team is not None
    assert len(with_per_team.per_team) == 2
    assert without.per_team is None


def test_cohort_breakdown_wrong_type_exits_2(tmp_path):
    doc = _good_doc()
    doc["cohort_breakdown"] = "not-an-object"
    path = _write_json(tmp_path / "bad-cohort.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    assert path.name in str(exc.value)


def test_per_team_wrong_type_exits_2(tmp_path):
    doc = _good_doc()
    doc["per_team"] = {"not": "a list"}
    path = _write_json(tmp_path / "bad-pt.json", doc)
    with pytest.raises(ValidationError) as exc:
        load_input(path)
    assert path.name in str(exc.value)


# ---------------------------------------------------------------------------
# Sanity gate: every checked-in fixture round-trips
# ---------------------------------------------------------------------------
def _fixture_files():
    return sorted(FIXTURES_DIR.glob("*.json"))


@pytest.mark.parametrize(
    "fixture",
    _fixture_files(),
    ids=lambda p: p.name,
)
def test_inputfile_roundtrips_every_fixture(fixture):
    inp = load_input(fixture)
    assert isinstance(inp, InputFile)
    assert inp.path == fixture
    assert inp.basename == fixture.name
    assert inp.scope_kind in {"portfolio", "program", "project", "project+team"}
    # Window survives verbatim.
    assert inp.window_from == inp.meta["window"]["from"]
    assert inp.window_to == inp.meta["window"]["to"]
    # schema_version parses to a 2-tuple of ints.
    assert isinstance(inp.schema_version, tuple)
    assert len(inp.schema_version) == 2
    assert all(isinstance(x, int) for x in inp.schema_version)


def test_fixture_directory_is_not_empty():
    """Guards against the parametrize collapsing silently if the dir is empty."""
    assert _fixture_files(), "no fixtures present in {}".format(FIXTURES_DIR)
