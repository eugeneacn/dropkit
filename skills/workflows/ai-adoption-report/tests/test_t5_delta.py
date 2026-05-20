"""T5 contract tests: delta math engine.

Mirrors every test enumerated in docs/specs/ai-adoption-report-plan.md
§T5, plus the additional cases implied by the spec ("absent in both
omits row", "canonical order preserved", "to_dict shape", "notes
unsorted").

T5 is a pure function over dict shapes; fixtures are inlined Python
dicts rather than full flow-metrics JSON files (T5 takes the
``aggregates`` subtree only — see prompt).
"""
from __future__ import annotations

import math
from typing import Any, Dict

import pytest

from ai_adoption_report.delta import (
    CANONICAL_METRIC_ORDER,
    DeltaResult,
    DeltaRow,
    FLOW_DISTRIBUTION_BUCKETS,
    compute_deltas,
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------
SIDE_LABELS = ("baseline", "current")


def _full_aggregates(**overrides: Any) -> Dict[str, Any]:
    """Every-metric-populated aggregates dict; tests override per case."""
    out: Dict[str, Any] = {
        "throughput": 84,
        "wip": 12,
        "flow_load": 6.5,
        "cycle_time_hours": {"p50": 38.2, "p75": 50.0, "p90": 80.0, "n": 100},
        "lead_time_hours": {"p50": 40.0, "p75": 60.0, "p90": 90.0, "n": 100},
        "flow_time_hours": {"p50": 40.0, "p75": 60.0, "p90": 90.0, "n": 100},
        "flow_efficiency": {"p50": 0.4, "p75": 0.6, "p90": 0.8, "n": 100},
        "rework_rate": 0.15,
        "defect_ratio": 0.2,
        "flow_distribution": {
            "feature": 0.5,
            "defect": 0.2,
            "debt": 0.15,
            "risk": 0.05,
            "subtask": 0.0,
            "other": 0.1,
            "denominator": 200,
        },
    }
    out.update(overrides)
    return out


def _rows_by_label(result: DeltaResult) -> Dict[str, DeltaRow]:
    return {row.metric_label: row for row in result.rows}


# ---------------------------------------------------------------------------
# Required tests from plan §T5
# ---------------------------------------------------------------------------
def test_percent_delta_zero_baseline_zero_current_renders_dash():
    a = _full_aggregates(throughput=0)
    b = _full_aggregates(throughput=0)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    row = _rows_by_label(result)["throughput"]
    assert row.a == 0
    assert row.b == 0
    assert row.abs_delta == 0  # abs is 0, NOT None when both sides are zero
    assert row.pct_delta is None
    assert (
        "throughput zero on both sides; percent delta undefined" in result.notes
    )


def test_percent_delta_zero_baseline_positive_current_renders_infinity():
    a = _full_aggregates(throughput=0)
    b = _full_aggregates(throughput=10)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    row = _rows_by_label(result)["throughput"]
    assert row.a == 0
    assert row.b == 10
    assert row.abs_delta == 10
    assert row.pct_delta == math.inf
    # No zero-both-sides or n-rule note for throughput here.
    assert not any("throughput zero" in n for n in result.notes)


@pytest.mark.parametrize(
    "a_val,b_val,null_side",
    [(None, 10, "baseline"), (10, None, "current")],
)
def test_percent_delta_null_either_side_renders_dash(a_val, b_val, null_side):
    a = _full_aggregates(rework_rate=a_val)
    b = _full_aggregates(rework_rate=b_val)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    row = _rows_by_label(result)["rework_rate"]
    assert row.a == a_val
    assert row.b == b_val
    assert row.abs_delta is None
    assert row.pct_delta is None
    assert "rework_rate null in {}".format(null_side) in result.notes


def test_percent_delta_decimal_fraction_signed():
    """T5 emits the full-precision decimal fraction. Rendering to one
    decimal place with a sign is T7's job — the fraction itself must
    carry the sign via ordinary float arithmetic.
    """
    a = _full_aggregates(throughput=84)
    b = _full_aggregates(throughput=102)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    row = _rows_by_label(result)["throughput"]
    assert row.abs_delta == 18
    assert row.pct_delta == pytest.approx((102 - 84) / 84)
    assert row.pct_delta > 0

    # And the negative-delta direction:
    a2 = _full_aggregates(cycle_time_hours={"p50": 38.2, "p75": 50.0, "p90": 80.0, "n": 100})
    b2 = _full_aggregates(cycle_time_hours={"p50": 31.5, "p75": 50.0, "p90": 80.0, "n": 100})
    result2 = compute_deltas(a2, b2, side_labels=SIDE_LABELS)
    row2 = _rows_by_label(result2)["cycle_time_hours p50"]
    assert row2.abs_delta == pytest.approx(31.5 - 38.2)
    assert row2.pct_delta == pytest.approx((31.5 - 38.2) / 38.2)
    assert row2.pct_delta < 0


def test_distribution_metrics_compared_per_percentile():
    a = _full_aggregates(
        cycle_time_hours={"p50": 38.2, "p75": 50.0, "p90": 80.0, "n": 100}
    )
    b = _full_aggregates(
        cycle_time_hours={"p50": 31.5, "p75": 48.0, "p90": 75.0, "n": 100}
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    labels = [row.metric_label for row in result.rows]
    assert "cycle_time_hours p50" in labels
    assert "cycle_time_hours p75" in labels
    assert "cycle_time_hours p90" in labels
    rows = _rows_by_label(result)
    assert rows["cycle_time_hours p50"].a == 38.2
    assert rows["cycle_time_hours p50"].b == 31.5
    assert rows["cycle_time_hours p75"].a == 50.0
    assert rows["cycle_time_hours p75"].b == 48.0
    assert rows["cycle_time_hours p90"].a == 80.0
    assert rows["cycle_time_hours p90"].b == 75.0


def test_n_differs_more_than_10pct_emits_note():
    # 20% delta -> note emitted.
    a = _full_aggregates(
        cycle_time_hours={"p50": 38.2, "p75": 50.0, "p90": 80.0, "n": 100}
    )
    b = _full_aggregates(
        cycle_time_hours={"p50": 31.5, "p75": 48.0, "p90": 75.0, "n": 120}
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    assert any(
        "n-differs: cycle_time_hours" in n and "n=100" in n and "n=120" in n
        for n in result.notes
    )
    # Only ONE n-differs note per metric — not one per percentile.
    cycle_n_notes = [
        n for n in result.notes if "n-differs: cycle_time_hours" in n
    ]
    assert len(cycle_n_notes) == 1


def test_n_differs_within_10pct_emits_no_note():
    # 5% delta -> no note.
    a = _full_aggregates(
        cycle_time_hours={"p50": 38.2, "p75": 50.0, "p90": 80.0, "n": 100}
    )
    b = _full_aggregates(
        cycle_time_hours={"p50": 31.5, "p75": 48.0, "p90": 75.0, "n": 105}
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    assert not any("n-differs: cycle_time_hours" in n for n in result.notes)


def test_n_differs_zero_on_either_side_always_emits_note():
    a = _full_aggregates(
        cycle_time_hours={"p50": None, "p75": None, "p90": None, "n": 0}
    )
    b = _full_aggregates(
        cycle_time_hours={"p50": 31.5, "p75": 48.0, "p90": 75.0, "n": 100}
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    assert any(
        "n-differs: cycle_time_hours" in n and "n=0" in n and "n=100" in n
        for n in result.notes
    )


def test_n_differs_zero_on_both_sides_emits_note():
    """Exercises the ``max(n_a, n_b) == 0`` short-circuit explicitly:
    both-zero must trigger the note (not divide by zero)."""
    a = _full_aggregates(
        cycle_time_hours={"p50": None, "p75": None, "p90": None, "n": 0}
    )
    b = _full_aggregates(
        cycle_time_hours={"p50": None, "p75": None, "p90": None, "n": 0}
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    n_notes = [n for n in result.notes if "n-differs: cycle_time_hours" in n]
    assert len(n_notes) == 1
    assert "n=0" in n_notes[0]


# ---------------------------------------------------------------------------
# Additional T5-implied tests
# ---------------------------------------------------------------------------
def test_absent_in_both_omits_row():
    a = _full_aggregates()
    b = _full_aggregates()
    del a["flow_load"]
    del b["flow_load"]
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    labels = [row.metric_label for row in result.rows]
    assert "flow_load" not in labels
    # No metric_absent note for flow_load either.
    assert not any("flow_load absent" in n for n in result.notes)


def test_absent_in_one_emits_row_with_none_and_note():
    a = _full_aggregates()
    b = _full_aggregates()
    del a["flow_load"]  # absent in baseline (the a side)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    rows = _rows_by_label(result)
    assert "flow_load" in rows
    row = rows["flow_load"]
    assert row.a is None
    assert row.b == 6.5
    assert row.abs_delta is None
    assert row.pct_delta is None
    assert "flow_load absent in baseline; cell omitted" in result.notes


def test_absent_in_one_bucket_emits_six_rows_one_note():
    """flow_distribution absent on one side emits six placeholder rows
    (one per canonical bucket) but exactly one ``metric_absent`` note —
    not one per bucket. Symmetric to the distribution-absent case."""
    a = _full_aggregates()
    b = _full_aggregates()
    del a["flow_distribution"]  # absent in baseline (a side)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    bucket_labels = [
        row.metric_label
        for row in result.rows
        if row.metric_label.startswith("flow_distribution.")
    ]
    assert bucket_labels == [
        "flow_distribution.{}".format(b) for b in FLOW_DISTRIBUTION_BUCKETS
    ]
    rows = _rows_by_label(result)
    for bucket in FLOW_DISTRIBUTION_BUCKETS:
        row = rows["flow_distribution.{}".format(bucket)]
        assert row.a is None
        assert row.abs_delta is None
        assert row.pct_delta is None
    absent_notes = [
        n for n in result.notes if "flow_distribution absent" in n
    ]
    assert absent_notes == [
        "flow_distribution absent in baseline; cell omitted"
    ]
    # No n-differs note when one side is absent.
    assert not any("n-differs: flow_distribution" in n for n in result.notes)


def test_both_sides_null_emits_two_notes():
    """A metric whose value is ``null`` on BOTH sides emits a note for
    each side and yields a row whose ``a`` / ``b`` / ``abs`` / ``pct``
    are all ``None``. The row is still emitted — "absent in both" only
    applies when the key is missing, not when the value is null."""
    a = _full_aggregates(rework_rate=None)
    b = _full_aggregates(rework_rate=None)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    rows = _rows_by_label(result)
    assert "rework_rate" in rows
    row = rows["rework_rate"]
    assert row.a is None
    assert row.b is None
    assert row.abs_delta is None
    assert row.pct_delta is None
    assert "rework_rate null in baseline" in result.notes
    assert "rework_rate null in current" in result.notes


def test_absent_in_one_distribution_emits_three_rows_one_note():
    """A distribution metric absent on one side emits three placeholder
    rows (p50 / p75 / p90) but exactly one ``metric_absent`` note."""
    a = _full_aggregates()
    b = _full_aggregates()
    del b["cycle_time_hours"]  # absent in current (the b side)
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    labels = [row.metric_label for row in result.rows]
    assert "cycle_time_hours p50" in labels
    assert "cycle_time_hours p75" in labels
    assert "cycle_time_hours p90" in labels
    rows = _rows_by_label(result)
    for p in ("p50", "p75", "p90"):
        r = rows["cycle_time_hours {}".format(p)]
        assert r.b is None
        assert r.abs_delta is None
        assert r.pct_delta is None
    absent_notes = [
        n for n in result.notes if "cycle_time_hours absent" in n
    ]
    assert absent_notes == ["cycle_time_hours absent in current; cell omitted"]


def test_canonical_metric_order_preserved():
    """Rows preserve canonical order even when some metrics are absent."""
    a = _full_aggregates()
    b = _full_aggregates()
    del a["flow_load"]
    del b["flow_load"]
    del a["flow_efficiency"]
    del b["flow_efficiency"]
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    labels = [row.metric_label for row in result.rows]
    # Each emitted label must appear in CANONICAL_METRIC_ORDER, and the
    # sequence must respect canonical ordering.
    canonical_index = {label: i for i, label in enumerate(CANONICAL_METRIC_ORDER)}
    for label in labels:
        assert label in canonical_index, label
    indices = [canonical_index[label] for label in labels]
    assert indices == sorted(indices)


def test_flow_distribution_iterated_per_bucket():
    a = _full_aggregates(
        flow_distribution={
            "feature": 0.5,
            "defect": 0.3,
            "debt": 0.1,
            "risk": 0.05,
            "subtask": 0.0,
            "other": 0.05,
            "denominator": 200,
        }
    )
    b = _full_aggregates(
        flow_distribution={
            "feature": 0.6,
            "defect": 0.2,
            "debt": 0.1,
            "risk": 0.05,
            "subtask": 0.0,
            "other": 0.05,
            "denominator": 250,
        }
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    bucket_rows = [
        row
        for row in result.rows
        if row.metric_label.startswith("flow_distribution.")
    ]
    bucket_labels = [row.metric_label for row in bucket_rows]
    assert bucket_labels == [
        "flow_distribution.{}".format(b) for b in FLOW_DISTRIBUTION_BUCKETS
    ]
    rows = _rows_by_label(result)
    assert rows["flow_distribution.feature"].a == 0.5
    assert rows["flow_distribution.feature"].b == 0.6
    assert rows["flow_distribution.feature"].abs_delta == pytest.approx(0.1)
    assert rows["flow_distribution.feature"].pct_delta == pytest.approx(0.2)
    # denominator triggers an n-rule note (200 vs 250 = 20% delta).
    fd_n_notes = [
        n for n in result.notes if "n-differs: flow_distribution" in n
    ]
    assert len(fd_n_notes) == 1
    assert "n=200" in fd_n_notes[0]
    assert "n=250" in fd_n_notes[0]


def test_flow_distribution_denominator_within_10pct_emits_no_note():
    a = _full_aggregates(
        flow_distribution={
            "feature": 0.5,
            "defect": 0.3,
            "debt": 0.1,
            "risk": 0.05,
            "subtask": 0.0,
            "other": 0.05,
            "denominator": 200,
        }
    )
    b = _full_aggregates(
        flow_distribution={
            "feature": 0.5,
            "defect": 0.3,
            "debt": 0.1,
            "risk": 0.05,
            "subtask": 0.0,
            "other": 0.05,
            "denominator": 210,
        }
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    assert not any("n-differs: flow_distribution" in n for n in result.notes)


def test_to_dict_shape_matches_spec():
    a = _full_aggregates()
    b = _full_aggregates(
        throughput=102,
        cycle_time_hours={"p50": 31.5, "p75": 48.0, "p90": 75.0, "n": 100},
    )
    out = compute_deltas(a, b, side_labels=SIDE_LABELS).to_dict()

    # Scalar -> flat dict.
    assert out["throughput"] == {
        "a": 84,
        "b": 102,
        "abs": 18,
        "pct": pytest.approx((102 - 84) / 84),
    }

    # Distribution -> nested under p50/p75/p90 in that order.
    assert "cycle_time_hours" in out
    assert list(out["cycle_time_hours"].keys()) == ["p50", "p75", "p90"]
    p50 = out["cycle_time_hours"]["p50"]
    assert p50["a"] == 38.2
    assert p50["b"] == 31.5
    assert p50["abs"] == pytest.approx(31.5 - 38.2)
    assert p50["pct"] == pytest.approx((31.5 - 38.2) / 38.2)

    # flow_distribution -> nested under bucket keys in canonical bucket
    # order (feature, defect, debt, risk, subtask, other).
    fd = out["flow_distribution"]
    assert list(fd.keys()) == list(FLOW_DISTRIBUTION_BUCKETS)
    for bucket in FLOW_DISTRIBUTION_BUCKETS:
        assert set(fd[bucket].keys()) == {"a", "b", "abs", "pct"}

    # Top-level key order follows canonical metric order.
    top_keys = list(out.keys())
    canonical_metric_names = (
        "throughput",
        "wip",
        "flow_load",
        "cycle_time_hours",
        "lead_time_hours",
        "flow_time_hours",
        "flow_efficiency",
        "rework_rate",
        "defect_ratio",
        "flow_distribution",
    )
    canonical_index = {name: i for i, name in enumerate(canonical_metric_names)}
    indices = [canonical_index[name] for name in top_keys]
    assert indices == sorted(indices)


def test_notes_unsorted_in_t5_output():
    """Lock down the "Notes merge contract": T5 does NOT sort its own
    notes. T7 is responsible for sorting and deduping the final merged
    list.

    We construct a fixture whose natural append order is the reverse
    of lex order — if T5 ever introduced a ``sorted()`` call, this
    assertion would flip.
    """
    # We need notes whose lex order differs from append order.
    # Append order will be: throughput (zero-both), cycle_time_hours
    # null in baseline (from null p50/p75/p90), n-differs (last).
    # The lex order would put "cycle_time_hours null in baseline"
    # before "n-differs..." before "throughput zero..." — different
    # from the append order.
    a = _full_aggregates(
        throughput=0,
        cycle_time_hours={"p50": None, "p75": None, "p90": None, "n": 0},
    )
    b = _full_aggregates(
        throughput=0,
        cycle_time_hours={"p50": 31.5, "p75": 48.0, "p90": 75.0, "n": 100},
    )
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    assert result.notes  # sanity
    assert result.notes != sorted(result.notes), (
        "T5 must NOT sort its own notes; T7 sorts the merged list. "
        "Got: {}".format(result.notes)
    )


# ---------------------------------------------------------------------------
# Misc behavioural checks
# ---------------------------------------------------------------------------
def test_side_labels_flow_into_notes():
    """T6's program cohort rollup will pass ``("control", "cohort")``;
    make sure the labels flow through into the absent/null note text.
    """
    a = _full_aggregates()
    b = _full_aggregates()
    del a["flow_load"]
    result = compute_deltas(a, b, side_labels=("control", "cohort"))
    assert "flow_load absent in control; cell omitted" in result.notes


def test_distribution_all_three_percentiles_null_emits_one_note():
    """When a distribution carries null p50/p75/p90 on one side, T5
    emits a single ``<metric> null in <side>`` note (not three)."""
    a = _full_aggregates(
        flow_efficiency={"p50": None, "p75": None, "p90": None, "n": 0}
    )
    b = _full_aggregates()
    result = compute_deltas(a, b, side_labels=SIDE_LABELS)
    null_notes = [
        n for n in result.notes if n == "flow_efficiency null in baseline"
    ]
    assert null_notes == ["flow_efficiency null in baseline"]


def test_canonical_metric_order_constant_matches_spec_layout():
    """Sanity check: CANONICAL_METRIC_ORDER carries 23 entries in the
    spec-pinned order (3 scalar + 12 distribution percentile + 2
    scalar + 6 bucket). T7 imports this constant for Markdown
    rendering — if the order or count ever drifts, T7's table
    breaks.
    """
    assert len(CANONICAL_METRIC_ORDER) == 23
    assert CANONICAL_METRIC_ORDER[0] == "throughput"
    assert CANONICAL_METRIC_ORDER[-1] == "flow_distribution.other"
