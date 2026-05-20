"""T6 contract + construction tests for aggregation.

Test names match the plan (docs/specs/flow-metrics-plan.md § T6,
lines 532-582) verbatim so the spec ↔ test mapping stays auditable.
PerIssueRow inputs are constructed directly — no Timeline / changelog
plumbing involved; T5's tests cover that layer.
"""
from __future__ import annotations

import weakref
from datetime import date, datetime, timedelta, timezone
from typing import Iterator, List, Optional, Tuple

from flow_metrics import Window
from flow_metrics import aggregate as agg_mod
from flow_metrics.aggregate import (
    FLOW_DISTRIBUTION_BUCKETS,
    aggregate,
)
from flow_metrics.config import load_state_config
from flow_metrics.per_issue import PerIssueRow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ts(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _window(from_str: str, to_str: str) -> Window:
    fd = date.fromisoformat(from_str)
    td = date.fromisoformat(to_str)
    from_utc = datetime(fd.year, fd.month, fd.day, tzinfo=timezone.utc)
    to_excl = datetime(td.year, td.month, td.day, tzinfo=timezone.utc) + timedelta(days=1)
    return Window(from_date=fd, to_date=td, from_utc=from_utc, to_exclusive_utc=to_excl)


WINDOW = _window("2026-04-01", "2026-04-30")
STATE = load_state_config()


def _row(
    *,
    key: str = "PROJ-1",
    issue_created: datetime = _ts(2026, 4, 1),
    first_commitment_at: Optional[datetime] = None,
    first_delivery_at: Optional[datetime] = None,
    cycle_eligible: bool = False,
    cycle_time_hours: Optional[float] = None,
    lead_time_hours: Optional[float] = None,
    flow_efficiency: Optional[float] = None,
    rework_count: int = 0,
    issuetype_at_delivery: Optional[str] = None,
    issuetype_bucket: Optional[str] = None,
    team: str = "Foo",
    delivered_in_window: bool = False,
    cancelled_in_window: bool = False,
    wip_at_to: bool = False,
    wip_samples: Tuple[bool, ...] = (),
    cohort: Optional[bool] = None,
) -> PerIssueRow:
    return PerIssueRow(
        key=key,
        issue_created=issue_created,
        first_commitment_at=first_commitment_at,
        first_delivery_at=first_delivery_at,
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


def _delivered(
    *,
    key: str = "PROJ-1",
    cycle_time_hours: Optional[float] = 24.0,
    lead_time_hours: Optional[float] = 48.0,
    flow_efficiency: Optional[float] = 0.5,
    cycle_eligible: bool = True,
    rework_count: int = 0,
    issuetype_bucket: str = "feature",
    wip_samples_len: int = 0,
) -> PerIssueRow:
    """Build a 'happy path' delivered-in-window row.

    ``wip_samples_len`` controls how many ``False`` samples to attach
    (delivered-in-window issues contribute zero to Flow Load by spec).
    """
    return _row(
        key=key,
        first_commitment_at=_ts(2026, 4, 5),
        first_delivery_at=_ts(2026, 4, 10),
        cycle_eligible=cycle_eligible,
        cycle_time_hours=cycle_time_hours,
        lead_time_hours=lead_time_hours,
        flow_efficiency=flow_efficiency,
        rework_count=rework_count,
        issuetype_at_delivery="Story" if issuetype_bucket == "feature" else issuetype_bucket.title(),
        issuetype_bucket=issuetype_bucket,
        delivered_in_window=True,
        wip_samples=tuple([False] * wip_samples_len),
    )


# ===========================================================================
# Contract tests (from spec)
# ===========================================================================
class TestContract:
    def test_flow_load_includes_both_endpoints(self) -> None:
        # Window [2026-01-01, 2026-01-05] → 5 samples, each at
        # (d + 1 day) 00:00 UTC − 1µs. The aggregator's flow_load_sample_count
        # field surfaces the actual sample-anchor count.
        window = _window("2026-01-01", "2026-01-05")
        block = aggregate(iter([]), window, STATE)
        assert block.flow_load_sample_count == 5

    def test_flow_load_weekend_inclusion_recorded(self) -> None:
        # T11 owns the notes-line wording. T6's contract is to surface the
        # sample count (so notes can render "N samples, weekends included").
        window = _window("2026-01-01", "2026-01-07")
        block = aggregate(iter([]), window, STATE)
        # Days Jan 1..Jan 7 inclusive → 7 samples, regardless of weekends.
        assert block.flow_load_sample_count == 7

    def test_flow_distribution_sums_to_one(self) -> None:
        rows = [
            _delivered(key="A", issuetype_bucket="feature"),
            _delivered(key="B", issuetype_bucket="defect"),
            _delivered(key="C", issuetype_bucket="debt"),
            _delivered(key="D", issuetype_bucket="risk"),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        total = sum(block.flow_distribution[b] for b in FLOW_DISTRIBUTION_BUCKETS)
        # 4-dp tolerance per spec.
        assert abs(total - 1.0) <= 1e-4

    def test_flow_distribution_denominator_includes_subtasks(self) -> None:
        # Spec fixture: 80 non-subtask + 20 subtask deliveries.
        rows: List[PerIssueRow] = []
        for i in range(80):
            rows.append(_delivered(key="F{}".format(i), issuetype_bucket="feature"))
        for i in range(20):
            rows.append(_delivered(key="S{}".format(i), issuetype_bucket="subtask"))

        # Default --include-subtasks=false: throughput excludes subtasks,
        # but the distribution denominator is over ALL delivered.
        default_block = aggregate(iter(rows), WINDOW, STATE)
        assert default_block.throughput == 80
        assert default_block.flow_distribution_denominator == 100
        assert default_block.flow_distribution["subtask"] > 0

        with_flag = aggregate(iter(rows), WINDOW, STATE, include_subtasks=True)
        assert with_flag.throughput == 100
        assert with_flag.flow_distribution_denominator == 100

    def test_defect_ratio_equals_flow_distribution_defect(self) -> None:
        # Fixture skewed so throughput ≠ distribution denominator: 1 defect,
        # 4 features, 5 subtasks; default flag excludes subtasks from
        # throughput but not from distribution.
        rows = [_delivered(key="D0", issuetype_bucket="defect")]
        for i in range(4):
            rows.append(_delivered(key="F{}".format(i), issuetype_bucket="feature"))
        for i in range(5):
            rows.append(_delivered(key="S{}".format(i), issuetype_bucket="subtask"))

        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.throughput == 5
        assert block.flow_distribution_denominator == 10
        assert block.defect_ratio == block.flow_distribution["defect"]
        assert block.defect_ratio == round(1 / 10, 4)

    def test_rework_rate_null_on_zero_throughput(self) -> None:
        # Zero delivered-in-window rows → null rework_rate, not 0 / not NaN.
        block = aggregate(iter([]), WINDOW, STATE)
        assert block.throughput == 0
        assert block.rework_rate is None

    def test_flow_time_alias_equals_lead_time(self) -> None:
        # flow_time_hours must equal lead_time_hours byte-for-byte (spec
        # is explicit it is not a separate computation).
        rows = [
            _delivered(key="A", lead_time_hours=12.5),
            _delivered(key="B", lead_time_hours=48.0),
            _delivered(key="C", lead_time_hours=100.0),
            _delivered(key="D", lead_time_hours=240.0),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.flow_time_hours == block.lead_time_hours

    def test_percentile_computed_at_full_precision(self, monkeypatch) -> None:
        # Verifies the round-once contract: exactly one round() call per
        # percentile per percentile-bearing metric (cycle / lead / flow_eff).
        # flow_time_hours aliases lead_time_hours (no separate compute).
        calls: List[Tuple[float, int]] = []
        original = agg_mod._round

        def counting(value, ndigits):
            calls.append((value, ndigits))
            return original(value, ndigits)

        monkeypatch.setattr(agg_mod, "_round", counting)
        rows = [
            _delivered(key="A", cycle_time_hours=10.0, lead_time_hours=10.0, flow_efficiency=0.1),
            _delivered(key="B", cycle_time_hours=20.0, lead_time_hours=20.0, flow_efficiency=0.2),
            _delivered(key="C", cycle_time_hours=30.0, lead_time_hours=30.0, flow_efficiency=0.3),
            _delivered(key="D", cycle_time_hours=40.0, lead_time_hours=40.0, flow_efficiency=0.4),
        ]
        aggregate(iter(rows), WINDOW, STATE)
        # 3 percentile-bearing metrics × 3 percentiles (p50/p75/p90) = 9.
        assert len(calls) == 9


# ===========================================================================
# Construction tests
# ===========================================================================
class TestConstruction:
    def test_percentile_method_exclusive(self) -> None:
        # Fixture: [10, 20, 30, 40]. p50 via stdlib's exclusive method at
        # index 49 is 25.0. Plan text mentions hand-computed p75=32.5 /
        # p90=39.0, but those values do not correspond to Python's
        # stdlib `statistics.quantiles(..., method="exclusive")` —
        # which gives 37.5 / 45.0 at indices 74 / 89. The implementation
        # pin in the plan is the stdlib method; the test asserts the
        # values stdlib actually produces. The 32.5 / 39.0 plan annotation
        # is a known typo (see plan T6 §"Construction tests").
        rows = [
            _delivered(key="A", cycle_time_hours=10.0),
            _delivered(key="B", cycle_time_hours=20.0),
            _delivered(key="C", cycle_time_hours=30.0),
            _delivered(key="D", cycle_time_hours=40.0),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.cycle_time_hours.p50 == 25.0
        assert block.cycle_time_hours.p75 == 37.5
        assert block.cycle_time_hours.p90 == 45.0

    def test_percentile_p75_and_p90_consistent(self) -> None:
        # Sanity ordering across percentiles.
        rows = [
            _delivered(key="K{}".format(i), cycle_time_hours=float(i * 7 + 3))
            for i in range(15)
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        p = block.cycle_time_hours
        assert p.p50 is not None and p.p75 is not None and p.p90 is not None
        assert p.p75 >= p.p50
        assert p.p90 >= p.p75

    def test_throughput_excludes_cancelled(self) -> None:
        # Cancelled rows never enter throughput, but the cancelled count
        # increments — for the notes line.
        rows = [
            _delivered(key="A"),
            _delivered(key="B"),
            _row(
                key="C",
                issue_created=_ts(2026, 4, 1),
                cancelled_in_window=True,
            ),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.throughput == 2
        assert block.cancelled_in_window == 1

    def test_throughput_excludes_subtask_by_default(self) -> None:
        rows = [
            _delivered(key="F", issuetype_bucket="feature"),
            _delivered(key="S", issuetype_bucket="subtask"),
        ]
        default_block = aggregate(iter(rows), WINDOW, STATE)
        assert default_block.throughput == 1

        with_flag = aggregate(iter(rows), WINDOW, STATE, include_subtasks=True)
        assert with_flag.throughput == 2

    def test_wip_excludes_cancelled_when_no_reopen(self) -> None:
        # Issue cancelled in-window, still cancelled at WIP-instant
        # → wip_at_to: false, cancelled_in_window: true. T5 already
        # computes those booleans correctly; T6's job is to count.
        # 5 days in window → 5 false wip_samples (still cancelled at
        # each anchor — not active).
        rows = [
            _row(
                key="C",
                issue_created=_ts(2026, 4, 1),
                cancelled_in_window=True,
                wip_at_to=False,
                wip_samples=tuple([False] * 30),
            ),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.wip == 0
        assert block.cancelled_in_window == 1

    def test_wip_includes_cancelled_then_reopened(self) -> None:
        # Cancelled-then-reopened to in_progress: wip_at_to: true AND
        # cancelled_in_window: true. Both signals reported simultaneously
        # per Decision #29.
        rows = [
            _row(
                key="C",
                issue_created=_ts(2026, 4, 1),
                cancelled_in_window=True,
                wip_at_to=True,
                # Final 10 days the issue is back in_progress.
                wip_samples=tuple([False] * 20 + [True] * 10),
            ),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.wip == 1
        assert block.cancelled_in_window == 1

    def test_flow_load_sample_count_matches_inclusive_day_count(self) -> None:
        # Spec's contract-test fixture: [2026-01-01, 2026-01-05] → 5
        # samples (Jan 1..Jan 5 inclusive). A 90-day-difference window
        # ([2026-01-01, 2026-04-01]) → 91 samples.
        small = aggregate(iter([]), _window("2026-01-01", "2026-01-05"), STATE)
        assert small.flow_load_sample_count == 5

        big = aggregate(iter([]), _window("2026-01-01", "2026-04-01"), STATE)
        assert big.flow_load_sample_count == 91

        # And flow_load is the mean — for an empty-row stream over 91
        # days, flow_load is 0.0.
        assert big.flow_load == 0.0

    def test_flow_load_is_mean_of_daily_samples(self) -> None:
        # Three days in window; one issue active on each of 3 days, one
        # active on 1 day only. mean([2, 2, 2]) — wait, the math: row1
        # has wip_samples=(T,T,T), row2 has (T,F,F). Per-day totals
        # [2, 1, 1]. mean = 4/3.
        window = _window("2026-04-01", "2026-04-03")
        rows = [
            _row(
                key="A",
                issue_created=_ts(2026, 4, 1),
                wip_at_to=True,
                wip_samples=(True, True, True),
            ),
            _row(
                key="B",
                issue_created=_ts(2026, 4, 1),
                wip_at_to=False,
                wip_samples=(True, False, False),
            ),
        ]
        block = aggregate(iter(rows), window, STATE)
        assert block.flow_load == round(4 / 3, 4)
        assert block.wip == 1  # only row A is wip at WIP-instant

    def test_aggregate_n_per_metric(self) -> None:
        # 5 delivered, 1 skipped commitment (delivered_without_commitment),
        # 1 zero-denominator flow_efficiency exclusion.
        # Expected: throughput == 5, cycle_time.n == 4 (5 delivered − 1
        # skipped commitment), flow_efficiency.n == 3 (4 cycle-eligible
        # − 1 zero-denominator), lead_time.n == 5.
        rows = [
            _delivered(key="A", cycle_time_hours=10.0, flow_efficiency=0.5),
            _delivered(key="B", cycle_time_hours=20.0, flow_efficiency=0.6),
            _delivered(key="C", cycle_time_hours=30.0, flow_efficiency=0.7),
            _delivered(
                key="D",
                cycle_time_hours=40.0,
                flow_efficiency=None,  # zero-denominator exclusion
                cycle_eligible=True,
            ),
            # Skipped commitment: cycle_eligible False, cycle_time_hours None.
            _delivered(
                key="E",
                cycle_eligible=False,
                cycle_time_hours=None,
                flow_efficiency=None,
                lead_time_hours=200.0,
            ),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.throughput == 5
        assert block.cycle_time_hours.n == 4
        assert block.flow_efficiency.n == 3
        assert block.lead_time_hours.n == 5
        assert block.delivered_without_commitment == 1
        assert block.flow_efficiency_zero_denominator == 1

    def test_aggregation_does_not_buffer_full_row_list(self) -> None:
        # Stream 10k synthetic delivered-in-window rows through a
        # generator. Track each row via weakref; after aggregation, the
        # aggregator must not retain references — at most a constant
        # number of rows may still be alive (the iterator's last yield
        # may linger in the for-loop's local binding).
        N = 10_000
        refs: List[weakref.ref] = []

        def gen() -> Iterator[PerIssueRow]:
            for i in range(N):
                row = _delivered(
                    key="K{}".format(i),
                    cycle_time_hours=float(i % 100),
                    lead_time_hours=float(i % 100),
                    flow_efficiency=(i % 100) / 100.0,
                )
                refs.append(weakref.ref(row))
                yield row

        block = aggregate(gen(), WINDOW, STATE)

        # Sanity: every row was consumed.
        assert block.throughput == N

        # Force a GC pass so any cycles or cached frames release.
        import gc

        gc.collect()

        alive = sum(1 for r in refs if r() is not None)
        # The aggregator must not have buffered the full stream. A
        # constant tail (well under 1%) is acceptable — Python may keep
        # the most-recently-iterated row alive in the loop frame.
        assert alive < 100, "expected ~0 rows alive, found {}".format(alive)


# ===========================================================================
# Aux: cancellation / WIP / distribution edge coverage
# ===========================================================================
class TestEdges:
    def test_unmapped_issuetype_counter_increments_for_other_bucket(self) -> None:
        # T11 reads this counter to surface "N delivered with unmapped
        # issuetype" in notes. 'other' bucket is the unmapped sink.
        rows = [
            _delivered(key="A", issuetype_bucket="feature"),
            _delivered(key="B", issuetype_bucket="other"),
            _delivered(key="C", issuetype_bucket="other"),
        ]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.unmapped_issuetype == 2

    def test_empty_distribution_does_not_divide_by_zero(self) -> None:
        # Zero delivered rows → distribution all-zero, denominator zero.
        block = aggregate(iter([]), WINDOW, STATE)
        assert block.flow_distribution_denominator == 0
        for bucket in FLOW_DISTRIBUTION_BUCKETS:
            assert block.flow_distribution[bucket] == 0.0
        assert block.defect_ratio == 0.0

    def test_percentile_returns_none_for_under_two_samples(self) -> None:
        # statistics.quantiles requires ≥ 2 samples; aggregator returns
        # PercentileStat with None values and the actual n.
        rows = [_delivered(key="A", cycle_time_hours=10.0, lead_time_hours=10.0)]
        block = aggregate(iter(rows), WINDOW, STATE)
        assert block.cycle_time_hours.n == 1
        assert block.cycle_time_hours.p50 is None
        assert block.cycle_time_hours.p75 is None
        assert block.cycle_time_hours.p90 is None
