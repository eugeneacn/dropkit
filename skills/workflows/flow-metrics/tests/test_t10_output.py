"""T10 contract + construction tests for output rendering.

Test names match docs/specs/flow-metrics-plan.md § T10 (lines 789-821)
and the corresponding contract tests in docs/specs/flow-metrics.md §
"Output" verbatim so the spec ↔ test mapping stays auditable.

The renderer is a pure function of its inputs; tests construct
``AggregateBlock`` / ``PerIssueRow`` / ``Report`` instances directly, no
Jira / Timeline / cohort plumbing involved. The cohort, per-team and
notes paths are exercised at the dict-shape level; the underlying
T6/T8/T9 modules have their own coverage.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from flow_metrics.aggregate import AggregateBlock, PercentileStat
from flow_metrics.output import (
    BUCKET_ORDER,
    CANONICAL_METRICS_ORDER,
    CSV_HEADER,
    Report,
    render_csv,
    render_json,
    render_jsonl,
)
from flow_metrics.per_issue import PerIssueRow
from flow_metrics.per_team import PerTeamRow


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
def _percentile(p50: Optional[float], p75: Optional[float], p90: Optional[float], n: int) -> PercentileStat:
    return PercentileStat(p50=p50, p75=p75, p90=p90, n=n)


def _make_block(
    *,
    cycle_p50: Optional[float] = 38.2,
    throughput: int = 84,
    wip: int = 17,
    flow_load: float = 21.4,
    rework_rate: Optional[float] = 0.42,
    flow_eff_p50: Optional[float] = 0.58,
    distribution: Optional[Dict[str, float]] = None,
    denominator: int = 102,
) -> AggregateBlock:
    dist = distribution if distribution is not None else {
        "feature": 0.4608,
        "defect": 0.1961,
        "debt": 0.1078,
        "risk": 0.0294,
        "subtask": 0.1765,
        "other": 0.0294,
    }
    return AggregateBlock(
        cycle_time_hours=_percentile(cycle_p50, 91.0, 168.4, 80),
        lead_time_hours=_percentile(120.5, 340.0, 720.0, 84),
        flow_time_hours=_percentile(120.5, 340.0, 720.0, 84),
        throughput=throughput,
        wip=wip,
        flow_load=flow_load,
        rework_rate=rework_rate,
        flow_efficiency=_percentile(flow_eff_p50, 0.72, 0.86, 76),
        flow_distribution=dist,
        flow_distribution_denominator=denominator,
        defect_ratio=dist["defect"],
        cancelled_in_window=0,
        delivered_without_commitment=0,
        flow_efficiency_zero_denominator=0,
        unmapped_issuetype=0,
        flow_load_sample_count=91,
    )


def _make_meta(*, with_cohort_jql: bool = False, **extra: Any) -> Dict[str, Any]:
    meta: Dict[str, Any] = {
        "scope": {"project": "PROJ", "team": "Foo"},
        "window": {"from": "2026-02-19", "to": "2026-05-19"},
        "state_config_sha": "abc",
        "issuetype_config_sha": "def",
        "generated_at": "2026-05-19T14:00:00Z",
        "sources": ["jira"],
        "schema_version": "1.0",
        "caller": "5b10ac8d82e05b22cc7d4ef5",
        "per_team_double_counted": False,
    }
    if with_cohort_jql:
        meta["cohort_jql"] = "labels = ai-assisted"
    meta.update(extra)
    return meta


def _make_report(**overrides: Any) -> Report:
    defaults: Dict[str, Any] = {
        "aggregate": _make_block(),
        "meta": _make_meta(),
        "notes": [],
        "metrics_requested": list(CANONICAL_METRICS_ORDER),
        "cohort_breakdown": None,
        "per_team": [],
        "per_issue": None,
    }
    defaults.update(overrides)
    return Report(**defaults)


def _decode(out: bytes) -> Dict[str, Any]:
    return json.loads(out.decode("utf-8"))


# ---------------------------------------------------------------------------
# Contract tests (from spec)
# ---------------------------------------------------------------------------
class TestContract:
    def test_stable_output_for_same_inputs(self) -> None:
        # Two renders of the same Report produce byte-identical output —
        # the canonicalisation invariant the spec hangs on.
        report = _make_report()
        a = render_json(report)
        b = render_json(report)
        assert a == b

    def test_per_team_sort_uses_codepoint_order(self) -> None:
        # T10 emits per_team in input order; T9's per_team_rollup is the
        # one that sorts codepoint. Here we feed pre-sorted rows and assert
        # the serializer preserves that order verbatim (no re-sort that
        # could mask a T9 regression).
        # Codepoint order: uppercase < lowercase, ASCII < Latin-1.
        names = ["Zebra", "Über-team", "alpha"]
        rows = [PerTeamRow(team=n, aggregates=_make_block(throughput=1)) for n in names]
        report = _make_report(per_team=rows)
        out = _decode(render_json(report))
        assert [r["team"] for r in out["per_team"]] == names

    def test_notes_sorted_lexicographically(self) -> None:
        # Notes arrive in arbitrary order from T11; the renderer sorts.
        unsorted = [
            "z final note",
            "a first note",
            "m middle note",
            "B mixed-case note",
        ]
        report = _make_report(notes=unsorted)
        out = _decode(render_json(report))
        assert out["notes"] == sorted(unsorted)

    def test_per_issue_emits_jsonl_sorted_by_key(self) -> None:
        # Per-issue lines preserve input order (the upstream JQL guarantees
        # ORDER BY key ASC). Each LINE's keys are codepoint-sorted.
        rows = [_make_per_issue_row(key="PROJ-1"), _make_per_issue_row(key="PROJ-2")]
        lines = list(render_jsonl(iter(rows)))
        # Line order: PROJ-1 then PROJ-2 (input order).
        decoded = [json.loads(line.decode("utf-8").rstrip("\n")) for line in lines]
        assert [d["key"] for d in decoded] == ["PROJ-1", "PROJ-2"]
        # Each line's keys are codepoint-sorted.
        for line in lines:
            text = line.decode("utf-8").rstrip("\n")
            keys = _extract_top_level_keys(text)
            assert keys == sorted(keys)

    def test_csv_long_form_columns(self) -> None:
        report = _make_report()
        csv_bytes = render_csv(report)
        text = csv_bytes.decode("utf-8")
        header = text.splitlines()[0]
        # Columns in exact spec order.
        assert header.split(",") == list(CSV_HEADER)

    def test_metrics_filter_omits_unrequested(self) -> None:
        # --metrics throughput,wip -> aggregates has ONLY those two keys.
        report = _make_report(metrics_requested=["throughput", "wip"])
        out = _decode(render_json(report))
        assert set(out["aggregates"].keys()) == {"throughput", "wip"}
        # meta.metrics_requested reflects what was requested.
        assert out["meta"]["metrics_requested"] == ["throughput", "wip"]

    def test_flow_distribution_and_defect_ratio_independent(self) -> None:
        # Requesting flow_distribution alone must NOT auto-include
        # defect_ratio, and vice versa. They share the underlying
        # distribution data; the requested-set check is per-metric.
        only_dist = _decode(render_json(_make_report(metrics_requested=["flow_distribution"])))
        assert "flow_distribution" in only_dist["aggregates"]
        assert "defect_ratio" not in only_dist["aggregates"]

        only_ratio = _decode(render_json(_make_report(metrics_requested=["defect_ratio"])))
        assert "defect_ratio" in only_ratio["aggregates"]
        assert "flow_distribution" not in only_ratio["aggregates"]


# ---------------------------------------------------------------------------
# Construction tests
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_json_keys_sorted_at_every_level_except_bucket_maps(self) -> None:
        # Recursive descent: every dict's keys are codepoint-sorted,
        # except flow_distribution (bucket-order).
        report = _make_report(
            cohort_breakdown={"cohort": _make_block(), "control": _make_block()},
            per_team=[PerTeamRow(team="Foo", aggregates=_make_block())],
        )
        out_bytes = render_json(report)
        # Walk the byte string at "key": positions and verify ordering
        # by parsing the JSON and re-walking the parsed structure with
        # an iter-keys check at each dict node.
        out = json.loads(out_bytes.decode("utf-8"))

        bucket_paths = {
            ("aggregates", "flow_distribution"),
            ("cohort_breakdown", "cohort", "flow_distribution"),
            ("cohort_breakdown", "control", "flow_distribution"),
        }

        def _walk(node: Any, path: Tuple[str, ...]) -> None:
            if isinstance(node, dict):
                # Re-parse the on-wire bytes for ordering — json.loads
                # preserves insertion order in py>=3.7, so this works.
                # Skip bucket-order maps.
                is_bucket = path in bucket_paths or (
                    len(path) >= 3
                    and path[0] == "per_team"
                    and path[-2] == "aggregates"
                    and path[-1] == "flow_distribution"
                )
                if not is_bucket:
                    keys = list(node.keys())
                    assert keys == sorted(keys), (
                        "keys not sorted at path {!r}: {!r}".format(path, keys)
                    )
                for k, v in node.items():
                    _walk(v, path + (k,))
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    # For per_team list, treat each row by tagging the
                    # path with the field name (no index).
                    _walk(v, path)

        _walk(out, ())

    def test_floats_rounded_to_4dp(self) -> None:
        # Every float in the serialised output matches the regex —
        # implicitly verifies both rounding (no 0.46075000000001
        # artifacts) and no scientific notation.
        report = _make_report()
        out = render_json(report)
        text = out.decode("utf-8")
        # Pull every number-like literal from the output.
        # Avoid matching numbers inside strings (dates, sha hex) by
        # scanning for `": <number>` and `, <number>` and `[ <number>`
        # patterns.
        pattern = re.compile(r"[:,\[]\s*(-?\d+(?:\.\d+)?)\b(?!\")")
        regex = re.compile(r"^-?\d+(\.\d{1,4})?$")
        floats_found = [
            m.group(1) for m in pattern.finditer(text) if "." in m.group(1)
        ]
        assert floats_found, "no floats present in output — fixture mis-built"
        for v in floats_found:
            assert regex.match(v), "float {!r} fails 4-dp regex".format(v)

    def test_integer_counts_no_decimal_point(self) -> None:
        # throughput, n, wip, flow_distribution.denominator serialize as
        # ints — never `.0`. Spec-pinned by the "Counts (`n`, `throughput`,
        # `wip`, `flow_distribution.denominator`) stay as integers" rule.
        report = _make_report()
        out = _decode(render_json(report))
        agg = out["aggregates"]
        assert isinstance(agg["throughput"], int)
        assert not isinstance(agg["throughput"], bool)
        assert isinstance(agg["wip"], int)
        assert isinstance(agg["flow_distribution"]["denominator"], int)
        assert isinstance(agg["cycle_time_hours"]["n"], int)
        # And the on-wire form has no ".0".
        text = render_json(report).decode("utf-8")
        # The throughput field appears as `"throughput":84`, never `84.0`.
        assert '"throughput":84' in text
        assert '"throughput":84.0' not in text

    def test_flow_distribution_bucket_order_not_lexicographic(self) -> None:
        # Lex order of buckets: debt, defect, denominator, feature, other,
        # risk, subtask. Canonical bucket order: feature, defect, debt,
        # risk, subtask, other, denominator. Assert canonical, not lex.
        report = _make_report()
        out_bytes = render_json(report)
        text = out_bytes.decode("utf-8")
        # Find the flow_distribution object in aggregates and check key
        # order textually (json.loads preserves it in py>=3.7).
        out = json.loads(text)
        keys = list(out["aggregates"]["flow_distribution"].keys())
        assert keys == list(BUCKET_ORDER)

    def test_meta_metrics_requested_canonical_order(self) -> None:
        # Order matches spec's --metrics enumeration, not lex.
        report = _make_report()
        out = _decode(render_json(report))
        assert out["meta"]["metrics_requested"] == list(CANONICAL_METRICS_ORDER)

        # Also: feeding an unsorted list re-sorts to canonical defensively.
        scrambled = list(CANONICAL_METRICS_ORDER)
        scrambled.reverse()
        report2 = _make_report(metrics_requested=scrambled)
        out2 = _decode(render_json(report2))
        assert out2["meta"]["metrics_requested"] == list(CANONICAL_METRICS_ORDER)

    def test_meta_sources_sorted_lexicographic(self) -> None:
        # Lex sort: ["jira", "jira-align"]. Feeding the reverse order
        # gets re-sorted defensively.
        report = _make_report(meta=_make_meta(sources=["jira-align", "jira"]))
        out = _decode(render_json(report))
        assert out["meta"]["sources"] == ["jira", "jira-align"]

    def test_csv_scalar_metrics_leave_p75_p90_blank(self) -> None:
        # throughput row has p50=84 (the throughput value) and p75/p90
        # blank. Spec example: line 820 of the plan.
        report = _make_report(metrics_requested=["throughput"])
        text = render_csv(report).decode("utf-8")
        lines = text.splitlines()
        assert lines[0] == ",".join(CSV_HEADER)
        # Exactly one data row for throughput.
        row = lines[1].split(",")
        assert row[0] == "throughput"
        # p50 column index = 4 (metric, scope, cohort, team, p50, ...).
        assert row[4] == "84"
        # p75, p90 blank.
        assert row[5] == ""
        assert row[6] == ""


# ---------------------------------------------------------------------------
# Extra coverage: cohort omission, scope behaviour, JSONL shape
# ---------------------------------------------------------------------------
class TestExtra:
    def test_meta_cohort_jql_omitted_when_absent(self) -> None:
        # Spec § "Cohort behaviour" — key absent (not null, not "") when
        # the caller didn't pass it through meta.
        report = _make_report()
        out = _decode(render_json(report))
        assert "cohort_jql" not in out["meta"]
        # cohort_breakdown also absent when no breakdown provided.
        assert "cohort_breakdown" not in out

    def test_meta_cohort_jql_present_when_provided(self) -> None:
        report = _make_report(meta=_make_meta(with_cohort_jql=True))
        out = _decode(render_json(report))
        assert out["meta"]["cohort_jql"] == "labels = ai-assisted"

    def test_cohort_breakdown_emitted_when_provided(self) -> None:
        report = _make_report(
            cohort_breakdown={"cohort": _make_block(), "control": _make_block()}
        )
        out = _decode(render_json(report))
        assert set(out["cohort_breakdown"].keys()) == {"cohort", "control"}

    def test_per_issue_jsonl_keys_sorted_codepoint(self) -> None:
        row = _make_per_issue_row(key="PROJ-99")
        lines = list(render_jsonl(iter([row])))
        text = lines[0].decode("utf-8").rstrip("\n")
        keys = _extract_top_level_keys(text)
        assert keys == sorted(keys)

    def test_per_issue_jsonl_floats_rounded(self) -> None:
        row = _make_per_issue_row(
            key="PROJ-1",
            cycle_time_hours=36.12345678,
            lead_time_hours=140.0,
            flow_efficiency=0.6112233445,
        )
        line = next(render_jsonl(iter([row])))
        text = line.decode("utf-8").rstrip("\n")
        # 36.1235 (banker's-rounding-tolerant: round(36.12345678, 4) =
        # 36.1235). 140.0 stays 140.0. 0.6112.
        assert '"cycle_time_hours":36.1235' in text
        assert '"lead_time_hours":140.0' in text
        assert '"flow_efficiency":0.6112' in text

    def test_per_issue_jsonl_nulls_for_non_delivered(self) -> None:
        # Cancelled-in-window row: nullable fields emit JSON null.
        row = _make_per_issue_row(
            key="PROJ-CANCEL",
            delivered_in_window=False,
            cancelled_in_window=True,
            cycle_eligible=False,
            cycle_time_hours=None,
            lead_time_hours=None,
            flow_efficiency=None,
            first_commitment_at=None,
            first_delivery_at=None,
            issuetype_at_delivery=None,
            issuetype_bucket=None,
        )
        line = next(render_jsonl(iter([row])))
        text = line.decode("utf-8").rstrip("\n")
        assert '"cycle_time_hours":null' in text
        assert '"lead_time_hours":null' in text
        assert '"flow_efficiency":null' in text
        assert '"first_commitment_at":null' in text
        assert '"first_delivery_at":null' in text
        assert '"issuetype_at_delivery":null' in text
        assert '"issuetype_bucket":null' in text
        assert '"cancelled_in_window":true' in text
        assert '"delivered_in_window":false' in text

    def test_per_issue_jsonl_omits_wip_samples(self) -> None:
        # wip_samples is an internal flow_load detail; spec § "Per-issue
        # mode" does not list it among the emitted fields.
        row = _make_per_issue_row(key="K", wip_samples=(True, False, True))
        text = next(render_jsonl(iter([row]))).decode("utf-8")
        assert "wip_samples" not in text

    def test_per_team_double_counted_passthrough(self) -> None:
        # T9 sets the bool; T10 emits whatever's in meta.
        report = _make_report(meta=_make_meta(per_team_double_counted=True))
        out = _decode(render_json(report))
        assert out["meta"]["per_team_double_counted"] is True

    def test_csv_per_team_rows_have_team_label(self) -> None:
        report = _make_report(
            metrics_requested=["throughput"],
            per_team=[
                PerTeamRow(team="Bar", aggregates=_make_block(throughput=10)),
                PerTeamRow(team="Foo", aggregates=_make_block(throughput=20)),
            ],
        )
        text = render_csv(report).decode("utf-8")
        lines = text.splitlines()
        # Header + 1 global + 2 per-team.
        assert len(lines) == 4
        # Per-team rows carry the team name in column 3 (zero-indexed).
        per_team_rows = [row.split(",") for row in lines[2:]]
        assert {r[3] for r in per_team_rows} == {"Bar", "Foo"}
        # cohort label is "all" for per-team rows.
        assert all(r[2] == "all" for r in per_team_rows)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_per_issue_row(
    *,
    key: str = "PROJ-1",
    delivered_in_window: bool = True,
    cancelled_in_window: bool = False,
    wip_at_to: bool = False,
    cycle_eligible: bool = True,
    cycle_time_hours: Optional[float] = 36.1,
    lead_time_hours: Optional[float] = 140.2,
    flow_efficiency: Optional[float] = 0.61,
    rework_count: int = 1,
    first_commitment_at: Optional[datetime] = None,
    first_delivery_at: Optional[datetime] = None,
    issuetype_at_delivery: Optional[str] = "Bug",
    issuetype_bucket: Optional[str] = "defect",
    team: str = "Foo",
    wip_samples: Tuple[bool, ...] = (),
    cohort: Optional[bool] = True,
) -> PerIssueRow:
    fc = first_commitment_at if first_commitment_at is not None else datetime(2026, 4, 12, 9, 0, tzinfo=timezone.utc)
    fd = first_delivery_at if first_delivery_at is not None else datetime(2026, 4, 13, 21, 6, tzinfo=timezone.utc)
    if not delivered_in_window:
        # Caller overrode delivery — but spec says non-delivered rows
        # carry null for these; the synthetic-default path above would
        # back-fill, so respect the explicit None override here.
        fc = first_commitment_at
        fd = first_delivery_at
    return PerIssueRow(
        key=key,
        issue_created=datetime(2026, 4, 8, 12, 0, tzinfo=timezone.utc),
        first_commitment_at=fc,
        first_delivery_at=fd,
        cycle_eligible=cycle_eligible,
        cycle_time_hours=cycle_time_hours,
        lead_time_hours=lead_time_hours,
        flow_efficiency=flow_efficiency,
        rework_count=rework_count,
        issuetype_at_delivery=issuetype_at_delivery,
        issuetype_bucket=issuetype_bucket,
        team=team,
        delivered_in_window=delivered_in_window,
        cancelled_in_window=cancelled_in_window,
        wip_at_to=wip_at_to,
        wip_samples=wip_samples,
        cohort=cohort,
    )


_KEY_RE = re.compile(r'"([^"\\]*)":')


def _extract_top_level_keys(text: str) -> List[str]:
    """Pull top-level keys out of a single-line JSON object string.

    Walks bracket depth to avoid descending into nested objects/arrays.
    The renderer's output is single-line JSON, so a simple scan suffices.
    """
    keys: List[str] = []
    depth = 0
    i = 0
    in_string = False
    escape = False
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if c == "\\":
            escape = True
            i += 1
            continue
        if c == '"':
            in_string = not in_string
            i += 1
            continue
        if in_string:
            i += 1
            continue
        if c == "{":
            depth += 1
            if depth == 1:
                # We just entered the top-level object — scan for keys.
                pass
            i += 1
            continue
        if c == "}":
            depth -= 1
            i += 1
            continue
        if c == "[":
            depth += 1
            i += 1
            continue
        if c == "]":
            depth -= 1
            i += 1
            continue
        i += 1
    # Re-scan with a simpler approach: match "<key>": only at depth 1.
    depth = 0
    in_string = False
    escape = False
    i = 0
    pending_key: Optional[str] = None
    while i < len(text):
        c = text[i]
        if escape:
            escape = False
            i += 1
            continue
        if in_string:
            if c == "\\":
                escape = True
            elif c == '"':
                in_string = False
                # If we were collecting a key, finalize.
                if pending_key is not None and depth == 1:
                    # Look ahead for the colon to confirm this is a key.
                    j = i + 1
                    while j < len(text) and text[j] in " \t":
                        j += 1
                    if j < len(text) and text[j] == ":":
                        keys.append(pending_key)
                    pending_key = None
            else:
                if pending_key is not None:
                    pending_key += c
            i += 1
            continue
        if c == '"':
            in_string = True
            if depth == 1:
                pending_key = ""
            i += 1
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
        i += 1
    return keys
