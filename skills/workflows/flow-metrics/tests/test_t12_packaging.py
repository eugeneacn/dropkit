"""T12 contract + construction tests for packaging artefacts.

Covers every test enumerated in docs/specs/flow-metrics-plan.md § T12
(lines 907-921):

- ``test_skill_md_lists_all_subcommands_from_spec``
- ``test_manifest_declares_dependencies``
- ``test_default_state_config_passes_validation``
- ``test_default_issuetype_config_passes_validation``
- ``test_output_json_validates_against_schema``
- ``test_skill_md_security_rules_present``

Stdlib only — the schema validator is a minimal homegrown walker so
``requirements.txt`` stays empty (the v1 "no pip deps" rule the spec
pins).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Set

from flow_metrics.aggregate import AggregateBlock, PercentileStat
from flow_metrics.config import (
    load_issuetype_config,
    load_state_config,
)
from flow_metrics.output import (
    CANONICAL_METRICS_ORDER,
    Report,
    render_json,
)
from flow_metrics.per_team import PerTeamRow


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SKILL_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = SKILL_DIR.parent.parent.parent
SPEC_PATH = REPO_ROOT / "docs" / "specs" / "flow-metrics.md"
SKILL_MD = SKILL_DIR / "SKILL.md"
MANIFEST = SKILL_DIR / "manifest.json"
OUTPUT_SCHEMA = SKILL_DIR / "references" / "output.schema.json"
REQUIREMENTS_TXT = SKILL_DIR / "requirements.txt"
REFERENCES_DIR = SKILL_DIR / "references"


# ---------------------------------------------------------------------------
# Spec inputs-table parser (data-driven; the test must NOT hardcode flags)
# ---------------------------------------------------------------------------
_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]+")


def _parse_spec_inputs_flags() -> Set[str]:
    """Extract every CLI flag named in the spec's Inputs section.

    The Inputs section is a markdown ``### Inputs`` heading followed by
    a fenced-code synopsis block and a ``| Flag | Meaning |`` table.
    The synopsis lists flag names; the table's first cell repeats them
    with semantic descriptions. We parse both so the result is robust
    to either renaming.

    Returns a set of flag tokens (e.g. ``"--project"``, ``"--from"``).
    Flags appearing in the spec's narrative *outside* the Inputs
    section are deliberately excluded — the SKILL.md contract is about
    what the CLI accepts, not about every flag the spec mentions.
    """
    text = SPEC_PATH.read_text(encoding="utf-8")
    # Inputs section spans from "### Inputs" through the next "### "
    # heading at the same level (or EOF).
    m = re.search(r"^###\s+Inputs\s*\n(.*?)(?=^###\s+|\Z)", text, re.MULTILINE | re.DOTALL)
    assert m, "spec is missing the '### Inputs' section — packaging test cannot run"
    inputs_block = m.group(1)
    flags: Set[str] = set()
    for token in _FLAG_RE.findall(inputs_block):
        # The synopsis uses bare flag forms; the table backticks them
        # (e.g. ``| `--project KEY` | ...``) but the regex picks up
        # either. The ``--yes`` flag is implementation-only (overwrite
        # confirmation) and isn't documented as a primary input; the
        # synopsis omits it. Skip the implementation-detail subset.
        flags.add(token)
    # Sanity floor: if the parser produces nothing or a degenerate
    # result, surface that as a test failure rather than silently
    # claiming SKILL.md is "complete".
    assert len(flags) >= 10, "spec inputs parser yielded too few flags: {}".format(flags)
    return flags


def _parse_skill_md_flags() -> Set[str]:
    """Extract every flag named in SKILL.md (anywhere in the file)."""
    text = SKILL_MD.read_text(encoding="utf-8")
    return set(_FLAG_RE.findall(text))


# ---------------------------------------------------------------------------
# Tests: SKILL.md
# ---------------------------------------------------------------------------
def test_skill_md_lists_all_subcommands_from_spec() -> None:
    """SKILL.md must mention every flag the spec's Inputs section names.

    Data-driven: the spec table is parsed at test time; the test does
    NOT hardcode the flag list, so it cannot drift from the spec.
    """
    spec_flags = _parse_spec_inputs_flags()
    skill_flags = _parse_skill_md_flags()
    missing = sorted(spec_flags - skill_flags)
    assert not missing, (
        "SKILL.md is missing CLI flags listed in docs/specs/flow-metrics.md "
        "§Inputs: {}".format(missing)
    )


def test_skill_md_security_rules_present() -> None:
    """SKILL.md must name the three security postures.

    Substring checks (case-insensitive). Documenting the substrings
    inline so a future SKILL.md edit knows what not to remove:

    1. ``"read-only"`` — the upstream-skill allowlist contract.
    2. ``"credentials.env"`` — credential isolation (this skill never
       reads the upstream skill's credential file).
    3. The no-write-verb posture. Accepted phrasings (any one suffices):
       ``"write verb"`` (spec phrasing in §"Read-only contract"),
       ``"no write"``, ``"no put/post/delete"``,
       ``"no post/put/patch/delete"``. The test accepts any of these so
       a reviewer rephrasing the security section faithful to the spec
       does not need to also edit this test. If you want to add a
       further synonym, add it to ``write_phrasings`` below.
    """
    text = SKILL_MD.read_text(encoding="utf-8").lower()
    assert "read-only" in text, "SKILL.md must mention 'read-only' contract"
    assert "credentials.env" in text, (
        "SKILL.md must explicitly name 'credentials.env' as the credential file this skill never reads"
    )
    write_phrasings = (
        "write verb",
        "no write",
        "no put/post/delete",
        "no post/put/patch/delete",
        "no post / put / patch / delete",
    )
    assert any(p in text for p in write_phrasings), (
        "SKILL.md must mention the no-write-verb posture; "
        "accepted phrasings: {}".format(", ".join(repr(p) for p in write_phrasings))
    )


# ---------------------------------------------------------------------------
# Tests: manifest.json
# ---------------------------------------------------------------------------
def test_manifest_declares_dependencies() -> None:
    """manifest.json must declare jira + jira-align under deps.skills by name."""
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest.get("id") == "flow-metrics"
    assert manifest.get("category") == "workflows"
    deps = manifest.get("deps", {})
    skills = deps.get("skills") or []
    names = {entry.get("name") for entry in skills if isinstance(entry, dict)}
    assert "jira" in names, "manifest deps.skills must list 'jira' by name"
    assert "jira-align" in names, "manifest deps.skills must list 'jira-align' by name"
    # _runtime_contract clause must be present (matches jira-defect-flow
    # pattern — name-not-path is the architectural rule).
    assert "_runtime_contract" in deps, (
        "manifest deps must carry the _runtime_contract clause naming the by-name discipline"
    )
    # No pip deps in v1 (stdlib-only invariant).
    assert "pip" not in deps, (
        "v1 must remain stdlib-only; manifest deps.pip is not permitted (see manifest's _pip_rationale)"
    )


# ---------------------------------------------------------------------------
# Tests: default config files
# ---------------------------------------------------------------------------
def test_default_state_config_passes_validation() -> None:
    """references/states.default.json loads cleanly and produces a valid StateConfig."""
    cfg = load_state_config(REFERENCES_DIR / "states.default.json")
    # Spec-pinned anchors — sanity check the shipped config matches what
    # the spec example documents.
    assert cfg.commitment_state == "in_progress"
    assert cfg.delivery_state == "done"
    assert "cancelled" in cfg.terminal_non_delivery_states
    # team_field is shipped so first-run users get a working config.
    assert cfg.team_field is not None
    assert cfg.team_field.kind in ("single_value", "array")


def test_default_issuetype_config_passes_validation() -> None:
    """references/issuetypes.default.json loads cleanly."""
    cfg = load_issuetype_config(REFERENCES_DIR / "issuetypes.default.json")
    # Defect bucket is the load-bearing one (drives defect_ratio); pin it.
    defect = cfg.bucket_for("Bug")
    assert defect == "defect"


# ---------------------------------------------------------------------------
# Minimal homegrown JSON Schema validator (stdlib only, no jsonschema)
# ---------------------------------------------------------------------------
# Handles the subset of draft 2020-12 that output.schema.json uses:
# type, required, properties, additionalProperties, items, $ref (local
# only, "#/$defs/..."), enum, pattern, minimum, maximum. Refuses to
# silently pass unknown keywords — a future schema feature that lands
# without validator support fails closed.
_HANDLED_KEYWORDS = frozenset({
    "$schema", "$id", "$ref", "$defs",
    "title", "description",
    "type", "properties", "required", "additionalProperties",
    "items", "enum", "pattern", "const", "uniqueItems",
    "minimum", "maximum",
    "oneOf",
})


class _SchemaError(AssertionError):
    pass


def _resolve_ref(root: Dict[str, Any], ref: str) -> Dict[str, Any]:
    if not ref.startswith("#/"):
        raise _SchemaError("only local $ref is supported, got: {}".format(ref))
    node: Any = root
    for part in ref[2:].split("/"):
        node = node[part]
    return node


def _type_matches(value: Any, types: Iterable[str]) -> bool:
    for t in types:
        if t == "object" and isinstance(value, dict):
            return True
        if t == "array" and isinstance(value, list):
            return True
        if t == "string" and isinstance(value, str):
            return True
        if t == "boolean" and isinstance(value, bool):
            return True
        if t == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if t == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if t == "null" and value is None:
            return True
    return False


def _validate(value: Any, schema: Dict[str, Any], root: Dict[str, Any], path: str) -> None:
    if "$ref" in schema:
        return _validate(value, _resolve_ref(root, schema["$ref"]), root, path)
    # Surface any unhandled keyword so silent-passes can't sneak in.
    unknown = set(schema.keys()) - _HANDLED_KEYWORDS
    if unknown:
        raise _SchemaError("validator does not handle schema keywords {} at {}".format(unknown, path))
    if "oneOf" in schema:
        matches = 0
        for branch in schema["oneOf"]:
            try:
                _validate(value, branch, root, path)
                matches += 1
            except _SchemaError:
                pass
        if matches != 1:
            raise _SchemaError(
                "oneOf at {} matched {} branches; expected exactly 1".format(path, matches)
            )
    type_field = schema.get("type")
    if type_field is not None:
        types = type_field if isinstance(type_field, list) else [type_field]
        if not _type_matches(value, types):
            raise _SchemaError("type mismatch at {}: expected {}, got {}".format(path, types, type(value).__name__))
    if "enum" in schema:
        if value not in schema["enum"]:
            raise _SchemaError("enum mismatch at {}: {!r} not in {}".format(path, value, schema["enum"]))
    if "const" in schema:
        if value != schema["const"]:
            raise _SchemaError("const mismatch at {}: {!r} != {!r}".format(path, value, schema["const"]))
    if "pattern" in schema and isinstance(value, str):
        if not re.search(schema["pattern"], value):
            raise _SchemaError("pattern mismatch at {}: {!r} !~ {}".format(path, value, schema["pattern"]))
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise _SchemaError("minimum violated at {}: {} < {}".format(path, value, schema["minimum"]))
        if "maximum" in schema and value > schema["maximum"]:
            raise _SchemaError("maximum violated at {}: {} > {}".format(path, value, schema["maximum"]))
    if isinstance(value, dict):
        required = schema.get("required", [])
        for k in required:
            if k not in value:
                raise _SchemaError("missing required key {!r} at {}".format(k, path))
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for k, v in value.items():
            sub_path = "{}.{}".format(path, k)
            if k in properties:
                _validate(v, properties[k], root, sub_path)
            else:
                if additional is False:
                    raise _SchemaError("unexpected key {!r} at {} (additionalProperties: false)".format(k, path))
                if isinstance(additional, dict):
                    _validate(v, additional, root, sub_path)
    if isinstance(value, list):
        items = schema.get("items")
        if items is not None:
            for i, v in enumerate(value):
                _validate(v, items, root, "{}[{}]".format(path, i))
        if schema.get("uniqueItems") is True:
            # JSON-equivalence dedup: hashable values use set; unhashable
            # (dict / list) get json-encoded for membership testing.
            seen: list = []
            for i, v in enumerate(value):
                key = json.dumps(v, sort_keys=True) if isinstance(v, (dict, list)) else v
                if key in seen:
                    raise _SchemaError("uniqueItems violated at {}[{}]: duplicate {!r}".format(path, i, v))
                seen.append(key)


def _validate_against_schema(instance: Any, schema: Dict[str, Any]) -> None:
    """Public entry: raises _SchemaError on any violation."""
    _validate(instance, schema, schema, "$")


# ---------------------------------------------------------------------------
# Tests: output.schema.json validates a real render
# ---------------------------------------------------------------------------
def _percentile(p50: Optional[float], p75: Optional[float], p90: Optional[float], n: int) -> PercentileStat:
    return PercentileStat(p50=p50, p75=p75, p90=p90, n=n)


def _golden_block() -> AggregateBlock:
    return AggregateBlock(
        cycle_time_hours=_percentile(38.2, 91.0, 168.4, 80),
        lead_time_hours=_percentile(120.5, 340.0, 720.0, 84),
        flow_time_hours=_percentile(120.5, 340.0, 720.0, 84),
        throughput=84,
        wip=17,
        flow_load=21.4,
        rework_rate=0.42,
        flow_efficiency=_percentile(0.58, 0.72, 0.86, 76),
        flow_distribution={
            "feature": 0.4608,
            "defect": 0.1961,
            "debt": 0.1078,
            "risk": 0.0294,
            "subtask": 0.1765,
            "other": 0.0294,
        },
        flow_distribution_denominator=102,
        defect_ratio=0.1961,
        cancelled_in_window=0,
        delivered_without_commitment=0,
        flow_efficiency_zero_denominator=0,
        unmapped_issuetype=0,
        flow_load_sample_count=91,
    )


def _golden_meta(cohort_jql: Optional[str] = None) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "scope": {"project": "PROJ", "team": "Foo"},
        "window": {"from": "2026-02-19", "to": "2026-05-19"},
        "state_config_sha": "abc123",
        "issuetype_config_sha": "def456",
        "generated_at": "2026-05-19T14:00:00Z",
        "sources": ["jira"],
        "schema_version": "1.0",
        "caller": "5b10ac8d82e05b22cc7d4ef5",
        "per_team_double_counted": False,
    }
    if cohort_jql is not None:
        meta["cohort_jql"] = cohort_jql
    return meta


def _load_schema() -> Dict[str, Any]:
    return json.loads(OUTPUT_SCHEMA.read_text(encoding="utf-8"))


def test_output_json_validates_against_schema() -> None:
    """A canonical render must validate against references/output.schema.json.

    Three shapes are validated, since the schema's optional blocks
    (``cohort_breakdown``, ``per_team``) only kick in on certain inputs:

    1. Plain aggregate (no cohort, no per_team).
    2. Aggregate + cohort_breakdown.
    3. Aggregate + per_team rollup.

    If any of these rejects, the schema is wrong (or the renderer is) —
    fix the schema before claiming T12 done.
    """
    schema = _load_schema()

    # 1. Plain aggregate.
    report = Report(
        aggregate=_golden_block(),
        meta=_golden_meta(),
        notes=["12 issues entered in-progress before window start."],
        metrics_requested=list(CANONICAL_METRICS_ORDER),
    )
    payload = json.loads(render_json(report).decode("utf-8"))
    _validate_against_schema(payload, schema)

    # 2. Cohort breakdown.
    report_cohort = Report(
        aggregate=_golden_block(),
        meta=_golden_meta(cohort_jql="labels = ai-assisted"),
        notes=[],
        metrics_requested=list(CANONICAL_METRICS_ORDER),
        cohort_breakdown={"cohort": _golden_block(), "control": _golden_block()},
    )
    payload_cohort = json.loads(render_json(report_cohort).decode("utf-8"))
    _validate_against_schema(payload_cohort, schema)
    assert payload_cohort["meta"]["cohort_jql"] == "labels = ai-assisted"
    assert "cohort_breakdown" in payload_cohort

    # 3. Per-team rollup.
    per_team_rows = [
        PerTeamRow(team="Bar", aggregates=_golden_block()),
        PerTeamRow(team="Foo", aggregates=_golden_block()),
    ]
    report_pt = Report(
        aggregate=_golden_block(),
        meta=_golden_meta(),
        notes=[],
        metrics_requested=list(CANONICAL_METRICS_ORDER),
        per_team=per_team_rows,
    )
    payload_pt = json.loads(render_json(report_pt).decode("utf-8"))
    _validate_against_schema(payload_pt, schema)
    assert "per_team" in payload_pt
    assert [row["team"] for row in payload_pt["per_team"]] == ["Bar", "Foo"]


def test_output_schema_rejects_unknown_metric_in_aggregates() -> None:
    """Schema enforces the unrequested-metrics-are-absent rule.

    ``aggregates.additionalProperties: false`` is what makes the rule
    machine-checkable: a renderer regression that emits a metric key
    the spec doesn't define (typo, leaked internal counter, future
    metric not yet on the schema) must fail validation. This test
    feeds an aggregates dict with a name not in the schema's
    ``properties`` map — the only way it can pass is via
    ``additionalProperties``, so removing the ``: false`` would
    silently let it through.
    """
    schema = _load_schema()
    bad_payload = {
        "meta": _golden_meta(),
        "aggregates": {
            "throughput": 1,
            "surprise_metric": 42,
        },
        "notes": [],
    }
    try:
        _validate_against_schema(bad_payload, schema)
    except _SchemaError:
        return
    raise AssertionError(
        "schema accepted an unknown key inside aggregates; "
        "additionalProperties: false is not enforced — unrequested-"
        "metrics-are-absent rule is not machine-checkable"
    )


def _empty_block() -> AggregateBlock:
    """An AggregateBlock matching the empty-cohort / empty-project shape:
    every percentile null, throughput 0, rework_rate null."""
    return AggregateBlock(
        cycle_time_hours=_percentile(None, None, None, 0),
        lead_time_hours=_percentile(None, None, None, 0),
        flow_time_hours=_percentile(None, None, None, 0),
        throughput=0,
        wip=0,
        flow_load=0.0,
        rework_rate=None,
        flow_efficiency=_percentile(None, None, None, 0),
        flow_distribution={
            "feature": 0.0, "defect": 0.0, "debt": 0.0,
            "risk": 0.0, "subtask": 0.0, "other": 0.0,
        },
        flow_distribution_denominator=0,
        defect_ratio=0.0,
        cancelled_in_window=0,
        delivered_without_commitment=0,
        flow_efficiency_zero_denominator=0,
        unmapped_issuetype=0,
        flow_load_sample_count=91,
    )


def test_output_schema_accepts_null_percentiles_for_empty_aggregate() -> None:
    """Schema must permit null p50/p75/p90 + null rework_rate (spec:
    percentiles are null when n<2; rework_rate is null when throughput
    is 0). Two locations exercise the null shape:

    1. Top-level ``aggregates`` (empty-project scope — exits 0).
    2. ``cohort_breakdown.cohort`` (empty cohort — exits 0).

    A schema regression that tightened any percentile field to
    ``"number"`` only would be caught at either site; both are
    exercised so a refactor that breaks only one site doesn't sneak
    through.
    """
    schema = _load_schema()
    # 1. Top-level empty aggregate.
    report_empty = Report(
        aggregate=_empty_block(),
        meta=_golden_meta(),
        notes=[],
        metrics_requested=list(CANONICAL_METRICS_ORDER),
    )
    payload_empty = json.loads(render_json(report_empty).decode("utf-8"))
    _validate_against_schema(payload_empty, schema)
    assert payload_empty["aggregates"]["throughput"] == 0
    assert payload_empty["aggregates"]["cycle_time_hours"]["p50"] is None
    assert payload_empty["aggregates"]["rework_rate"] is None

    # 2. Empty cohort inside cohort_breakdown.
    report_empty_cohort = Report(
        aggregate=_golden_block(),
        meta=_golden_meta(cohort_jql="labels = ai-assisted"),
        notes=[],
        metrics_requested=list(CANONICAL_METRICS_ORDER),
        cohort_breakdown={"cohort": _empty_block(), "control": _golden_block()},
    )
    payload_cohort = json.loads(render_json(report_empty_cohort).decode("utf-8"))
    _validate_against_schema(payload_cohort, schema)
    cohort = payload_cohort["cohort_breakdown"]["cohort"]
    assert cohort["throughput"] == 0
    assert cohort["cycle_time_hours"]["p50"] is None
    assert cohort["rework_rate"] is None


def test_output_schema_rejects_scope_with_no_keys() -> None:
    """``meta.scope`` must satisfy oneOf {project, program_id, portfolio_id}.

    A renderer regression that emits ``"scope": {}`` (which would be
    consumer-poisoning — the report has no scope label) must fail
    validation. The first review flagged the symmetric gap on
    aggregates' ``additionalProperties: false``; this is the scope-side
    analog.
    """
    schema = _load_schema()
    bad_meta = _golden_meta()
    bad_meta["scope"] = {}
    bad_payload = {
        "meta": bad_meta,
        "aggregates": {},
        "notes": [],
    }
    try:
        _validate_against_schema(bad_payload, schema)
    except _SchemaError:
        return
    raise AssertionError("schema accepted meta.scope = {}; scope oneOf is not enforced")


def test_output_schema_rejects_scope_with_two_keys() -> None:
    """``meta.scope`` must NOT have both project and program_id set."""
    schema = _load_schema()
    bad_meta = _golden_meta()
    bad_meta["scope"] = {"project": "PROJ", "program_id": "42"}
    bad_payload = {
        "meta": bad_meta,
        "aggregates": {},
        "notes": [],
    }
    try:
        _validate_against_schema(bad_payload, schema)
    except _SchemaError:
        return
    raise AssertionError(
        "schema accepted meta.scope with both project and program_id; "
        "scope oneOf is not enforced (or matches 2 branches, which would be a validator bug)"
    )


def test_output_schema_rejects_unknown_top_level_key() -> None:
    """A top-level key the spec doesn't define must fail validation."""
    schema = _load_schema()
    bad_payload = {
        "meta": _golden_meta(),
        "aggregates": {},
        "notes": [],
        "surprise": 42,
    }
    try:
        _validate_against_schema(bad_payload, schema)
    except _SchemaError:
        return
    raise AssertionError("schema accepted an unknown top-level key")


# ---------------------------------------------------------------------------
# Tests: requirements.txt is empty (stdlib-only invariant)
# ---------------------------------------------------------------------------
def test_requirements_txt_has_no_pip_dependencies() -> None:
    """v1 is stdlib only — requirements.txt must declare no packages.

    Comment lines (``#``) and blank lines are allowed. Any line that
    looks like a requirement specifier is a regression.
    """
    text = REQUIREMENTS_TXT.read_text(encoding="utf-8")
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        raise AssertionError(
            "requirements.txt line {}: {!r} declares a pip dependency; "
            "v1 is stdlib only (see manifest deps._pip_rationale)".format(lineno, raw)
        )
