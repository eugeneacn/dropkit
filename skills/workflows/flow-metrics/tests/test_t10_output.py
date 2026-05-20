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
        # The contract T10 owns is "do not re-sort per_team — preserve
        # caller order verbatim". T9's per_team_rollup is responsible
        # for sorting codepoint; T10's job is not to undo that.
        #
        # The fixture feeds names in codepoint order
        # (``Z`` < ``a`` < ``Ü`` by codepoint: 0x5A < 0x61 < 0xDC).
        # That same list is NOT in Python's default lex order — if T10
        # called `sorted()` (which uses codepoint) the output would
        # become ``["Zebra", "alpha", "Über-team"]``, catching the
        # regression. The test verifies preservation, which is what
        # T10 owns; the "codepoint" guarantee belongs to T9 and is
        # locked there by ``test_per_team_sort_uses_codepoint_order``
        # in tests/test_t9_align_per_team.py.
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
        # Verify both the header AND the (metric, scope, cohort, team)
        # tuple semantics on at least one data row. A test that only
        # checks the header would pass against an impl that emitted
        # rows in the wrong column order.
        report = _make_report(
            metrics_requested=["throughput", "cycle_time"],
            per_team=[PerTeamRow(team="Foo", aggregates=_make_block(throughput=42))],
        )
        csv_bytes = render_csv(report)
        text = csv_bytes.decode("utf-8")
        lines = text.splitlines()
        assert lines[0].split(",") == list(CSV_HEADER)
        # Find the row for global throughput.
        rows = [line.split(",") for line in lines[1:]]
        global_throughput = next(
            r for r in rows if r[0] == "throughput" and r[3] == ""
        )
        # metric, scope, cohort, team
        assert global_throughput[0] == "throughput"
        assert global_throughput[1] == "PROJ/Foo"  # scope from meta
        assert global_throughput[2] == "all"
        assert global_throughput[3] == ""
        # cycle_time is percentile-bearing — p50/p75/p90/count all filled.
        global_cycle = next(r for r in rows if r[0] == "cycle_time" and r[3] == "")
        assert global_cycle[4] != ""  # p50
        assert global_cycle[5] != ""  # p75
        assert global_cycle[6] != ""  # p90
        assert global_cycle[7] != ""  # count

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
        # except flow_distribution (bucket-order). Positively asserts
        # both halves — sort everywhere except the four bucket paths,
        # AND canonical bucket order at all four bucket paths (including
        # the per-team copy, which the path-pattern alone wouldn't catch
        # if a future refactor sorted lex by accident).
        report = _make_report(
            cohort_breakdown={"cohort": _make_block(), "control": _make_block()},
            per_team=[PerTeamRow(team="Foo", aggregates=_make_block())],
        )
        out_bytes = render_json(report)
        out = json.loads(out_bytes.decode("utf-8"))

        bucket_paths = {
            ("aggregates", "flow_distribution"),
            ("cohort_breakdown", "cohort", "flow_distribution"),
            ("cohort_breakdown", "control", "flow_distribution"),
        }

        def _walk(node: Any, path: Tuple[str, ...]) -> None:
            if isinstance(node, dict):
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
                for v in node:
                    _walk(v, path)

        _walk(out, ())

        # Positive bucket-order assertions at every bucket-map path,
        # including the per-team copy. If the bucket-order exception is
        # ever removed, these fail before the walk's negative coverage
        # would (since lex-sorted keys ALSO pass `keys == sorted(keys)`).
        expected = list(BUCKET_ORDER)
        assert list(out["aggregates"]["flow_distribution"].keys()) == expected
        assert (
            list(out["cohort_breakdown"]["cohort"]["flow_distribution"].keys())
            == expected
        )
        assert (
            list(out["cohort_breakdown"]["control"]["flow_distribution"].keys())
            == expected
        )
        assert (
            list(out["per_team"][0]["aggregates"]["flow_distribution"].keys())
            == expected
        )

    def test_floats_rounded_to_4dp(self) -> None:
        # Inject a value that visibly NEEDS rounding (5+ decimal digits)
        # so the test fails if the pre-walk is removed — a fixture that
        # uses values which already serialise ≤4 dp would let a bug
        # through. ``round(21.40005, 4)`` lands on ``21.4001`` under
        # Python's banker's rounding tie-breaks; the assertion below
        # tolerates either round-half-up or round-half-even by demanding
        # only "no 5+ dp ever appears on the wire".
        report = _make_report(
            aggregate=_make_block(
                flow_load=21.40005,
                rework_rate=0.123456789,
                flow_eff_p50=0.6543219876,
            )
        )
        out = render_json(report)
        text = out.decode("utf-8")
        # Pull every numeric literal preceded by `:`, `,`, or `[`.
        pattern = re.compile(r"[:,\[]\s*(-?\d+(?:\.\d+)?)\b(?!\")")
        regex = re.compile(r"^-?\d+(\.\d{1,4})?$")
        floats_found = [
            m.group(1) for m in pattern.finditer(text) if "." in m.group(1)
        ]
        # Sanity: the fixture's needs-rounding values landed in the output.
        assert any(v.startswith("21.4") for v in floats_found), (
            "fixture's flow_load value missing from output"
        )
        # The unrounded source `0.123456789` must not survive verbatim.
        assert "0.123456789" not in text
        assert "0.6543219876" not in text
        # No float has more than 4 decimal digits.
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

    def test_meta_cohort_jql_dropped_when_none_or_empty(self) -> None:
        # Spec § "Cohort behaviour" line 1128-1131: key must be **absent**
        # — not null, not "". A generic meta builder that always sets the
        # field (with None when --cohort-jql is unused) must not leak
        # ``"cohort_jql":null`` past the renderer.
        for value in (None, ""):
            report = _make_report(meta=_make_meta(cohort_jql=value))
            out = _decode(render_json(report))
            assert "cohort_jql" not in out["meta"], (
                "cohort_jql={!r} should be dropped, not emitted".format(value)
            )

    def test_cohort_breakdown_emitted_when_provided(self) -> None:
        report = _make_report(
            cohort_breakdown={"cohort": _make_block(), "control": _make_block()}
        )
        out = _decode(render_json(report))
        assert set(out["cohort_breakdown"].keys()) == {"cohort", "control"}

    def test_cohort_breakdown_omitted_when_empty(self) -> None:
        # An empty dict (caller passes ``cohort_breakdown={}`` instead of
        # ``None``) must not emit ``"cohort_breakdown":{}`` — spec says
        # the block is absent when --cohort-jql wasn't provided, and an
        # empty dict is the same contract violation as None being misread.
        report = _make_report(cohort_breakdown={})
        out = _decode(render_json(report))
        assert "cohort_breakdown" not in out

    def test_cohort_breakdown_omitted_when_partial(self) -> None:
        # Spec lines 406-428: both `cohort` and `control` always appear
        # together. Receiving only one side is upstream contract
        # violation; the renderer silently skips rather than producing
        # spec-undefined partial output. Same rule applies to CSV.
        only_cohort = _make_report(cohort_breakdown={"cohort": _make_block()})
        out = _decode(render_json(only_cohort))
        assert "cohort_breakdown" not in out
        only_control = _make_report(cohort_breakdown={"control": _make_block()})
        out2 = _decode(render_json(only_control))
        assert "cohort_breakdown" not in out2

    def test_csv_cohort_breakdown_rows_emitted(self) -> None:
        # Mirrors the JSON-side cohort_breakdown contract on the CSV
        # surface. Both sides present → CSV gets one row per metric per
        # side, with the `cohort` column set to "cohort" / "control".
        report = _make_report(
            metrics_requested=["throughput"],
            cohort_breakdown={
                "cohort": _make_block(throughput=31),
                "control": _make_block(throughput=53),
            },
        )
        text = render_csv(report).decode("utf-8")
        lines = text.splitlines()
        rows = [line.split(",") for line in lines[1:]]
        # global + cohort + control = 3 throughput rows.
        throughput_rows = [r for r in rows if r[0] == "throughput"]
        assert len(throughput_rows) == 3
        cohort_labels = {r[2] for r in throughput_rows}
        assert cohort_labels == {"all", "cohort", "control"}

    def test_csv_cohort_breakdown_omitted_when_partial(self) -> None:
        # CSV's partial-cohort rule mirrors the JSON side.
        report = _make_report(
            metrics_requested=["throughput"],
            cohort_breakdown={"cohort": _make_block(throughput=31)},
        )
        text = render_csv(report).decode("utf-8")
        lines = text.splitlines()
        rows = [line.split(",") for line in lines[1:]]
        # Only the global row remains.
        cohort_labels = {r[2] for r in rows}
        assert cohort_labels == {"all"}

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

    def test_meta_passthrough_preserves_required_fields(self) -> None:
        # The whole meta block lives at the seam between T11 (builder) and
        # T10 (renderer). A regex bug in _meta_to_dict could silently drop
        # fields like schema_version or state_config_sha; this test pins
        # the spec-example shape.
        report = _make_report()
        out = _decode(render_json(report))
        meta = out["meta"]
        assert meta["schema_version"] == "1.0"
        assert meta["state_config_sha"] == "abc"
        assert meta["issuetype_config_sha"] == "def"
        assert meta["caller"] == "5b10ac8d82e05b22cc7d4ef5"
        assert meta["scope"] == {"project": "PROJ", "team": "Foo"}
        assert meta["window"] == {"from": "2026-02-19", "to": "2026-05-19"}

    def test_report_metrics_requested_wins_over_meta(self) -> None:
        # `meta.metrics_requested` is overridden by the Report-level
        # field. Locks in the single-source-of-truth contract so a future
        # refactor that flipped the precedence would surface immediately.
        report = _make_report(
            metrics_requested=["wip"],
            meta=_make_meta(metrics_requested=["throughput", "cycle_time"]),
        )
        out = _decode(render_json(report))
        assert out["meta"]["metrics_requested"] == ["wip"]
        # And the aggregates dict reflects the Report-level list — not meta.
        assert set(out["aggregates"].keys()) == {"wip"}

    def test_meta_metrics_requested_dedupes_and_drops_unknown(self) -> None:
        # Two safety nets: a metric repeated in the caller's list emits
        # once on the wire, and an unknown metric (e.g. typo'd CLI flag
        # that bypassed validation) is dropped from meta rather than
        # advertised as published. Otherwise meta would lie:
        # `metrics_requested` would list a metric `aggregates` doesn't
        # carry.
        report = _make_report(
            metrics_requested=["wip", "wip", "throughput", "made_up_metric"]
        )
        out = _decode(render_json(report))
        assert out["meta"]["metrics_requested"] == ["throughput", "wip"]
        assert set(out["aggregates"].keys()) == {"throughput", "wip"}

    def test_csv_flow_distribution_rows_have_six_buckets(self) -> None:
        # flow_distribution explodes into one row per bucket in the
        # canonical (feature, defect, debt, risk, subtask, other) order,
        # with the distribution denominator in the ``count`` column and
        # p75 / p90 blank. The underlying long-form (metric, scope,
        # cohort, team) contract is preserved per row.
        report = _make_report(metrics_requested=["flow_distribution"])
        text = render_csv(report).decode("utf-8")
        lines = text.splitlines()
        assert lines[0].split(",") == list(CSV_HEADER)
        bucket_rows = [
            line.split(",") for line in lines[1:]
            if line.split(",")[0].startswith("flow_distribution.")
        ]
        # Exactly six bucket rows (one per canonical bucket).
        assert len(bucket_rows) == 6
        names = [r[0] for r in bucket_rows]
        assert names == [
            "flow_distribution.feature",
            "flow_distribution.defect",
            "flow_distribution.debt",
            "flow_distribution.risk",
            "flow_distribution.subtask",
            "flow_distribution.other",
        ]
        # Each bucket row: p75 / p90 blank, count = denominator (102).
        for r in bucket_rows:
            assert r[5] == ""  # p75 blank
            assert r[6] == ""  # p90 blank
            assert r[7] == "102"

    def test_per_issue_jsonl_omits_cohort_when_none(self) -> None:
        # `--per-issue` without `--cohort-jql` leaves `row.cohort` as
        # None (T8's tag_cohort never ran). Emitting `"cohort":null`
        # would mislead downstream consumers — spec § "Cohort behaviour"
        # binds cohort-field presence to cohort-jql mode. Absence is the
        # documented signal for "no cohort".
        row = _make_per_issue_row(key="PROJ-NO-COHORT", cohort=None)
        line = next(render_jsonl(iter([row])))
        text = line.decode("utf-8")
        assert "cohort" not in text or '"cohort":' not in text
        # Sanity: the rest of the row is still present.
        assert '"key":"PROJ-NO-COHORT"' in text

    def test_per_issue_jsonl_emits_cohort_when_tagged(self) -> None:
        # The flip side of the previous test: when cohort is True/False
        # the field IS emitted with the boolean. Pins both halves.
        row_true = _make_per_issue_row(key="A", cohort=True)
        row_false = _make_per_issue_row(key="B", cohort=False)
        text_t = next(render_jsonl(iter([row_true]))).decode("utf-8")
        text_f = next(render_jsonl(iter([row_false]))).decode("utf-8")
        assert '"cohort":true' in text_t
        assert '"cohort":false' in text_f

    def test_per_issue_jsonl_cohort_omission_across_row_classes(self) -> None:
        # Cohort=None omission applies regardless of row classification —
        # delivered, cancelled, and wip-only paths all behave the same.
        # Locks the field-agnostic single-`is not None` check at one
        # place in the impl.
        delivered = _make_per_issue_row(key="D", cohort=None)
        cancelled = _make_per_issue_row(
            key="C",
            cohort=None,
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
        wip_only = _make_per_issue_row(
            key="W",
            cohort=None,
            delivered_in_window=False,
            wip_at_to=True,
            cycle_eligible=False,
            cycle_time_hours=None,
            lead_time_hours=None,
            flow_efficiency=None,
            first_commitment_at=None,
            first_delivery_at=None,
            issuetype_at_delivery=None,
            issuetype_bucket=None,
        )
        for row in (delivered, cancelled, wip_only):
            line = next(render_jsonl(iter([row])))
            text = line.decode("utf-8")
            assert '"cohort":' not in text, (
                "cohort=None should be omitted for row {!r}; got: {}".format(
                    row.key, text
                )
            )

    def test_render_jsonl_never_emits_cohort_breakdown(self) -> None:
        # Spec line 1124-1127 (test_per_issue_omits_cohort_breakdown):
        # per-issue mode has no aggregate object, and `cohort_breakdown`
        # must NOT appear in any per-issue output. Negative coverage on
        # the renderer surface.
        rows = [_make_per_issue_row(key="A"), _make_per_issue_row(key="B")]
        for line in render_jsonl(iter(rows)):
            text = line.decode("utf-8")
            assert "cohort_breakdown" not in text

    def test_render_json_emits_empty_notes_array(self) -> None:
        # Spec example always shows a `notes` array, even when no notes
        # have been collected. Locks the "always emit, even if empty"
        # behaviour so a future refactor that drops empty notes doesn't
        # silently break downstream consumers that index `notes[0]` or
        # similar.
        report = _make_report(notes=[])
        out = _decode(render_json(report))
        assert out["notes"] == []

    def test_render_json_with_empty_meta(self) -> None:
        # Defensive: a caller passing `meta={}` (e.g. early-pipeline
        # smoke test) still produces a valid Report. The renderer
        # injects `metrics_requested` from the Report-level field, so
        # the output has at least that one meta key.
        report = _make_report(meta={})
        out = _decode(render_json(report))
        assert out["meta"]["metrics_requested"] == list(CANONICAL_METRICS_ORDER)

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


def _extract_top_level_keys(text: str) -> List[str]:
    """Pull top-level keys out of a single-line JSON object string.

    Relies on ``json.loads`` preserving dict insertion order (py >= 3.7),
    so the returned list matches the textual on-wire key order.
    """
    return list(json.loads(text).keys())
