"""T8 contract + construction tests for cohort split.

Test names match docs/specs/flow-metrics-plan.md § T8 (lines 676-697) and
the corresponding contract tests in docs/specs/flow-metrics.md §
"Cohort behaviour" verbatim, so the spec ↔ test mapping stays auditable.

PerIssueRow inputs are constructed directly — no Timeline / changelog
plumbing involved. The cohort layer is a pure transformation over
:class:`PerIssueRow` iterators (rows produced upstream by T5 or replayed
from T7's cache); its tests don't need the full derivation pipeline.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple
from unittest.mock import MagicMock

from flow_metrics import Window, compose_jql
from flow_metrics.aggregate import aggregate
from flow_metrics.cohort import (
    aggregate_cohort,
    build_cohort_breakdown,
    cohort_meta,
    resolve_cohort_keys,
    tag_cohort,
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
    key: str,
    delivered_in_window: bool = True,
    cycle_eligible: bool = True,
    cycle_time_hours: Optional[float] = 24.0,
    lead_time_hours: Optional[float] = 48.0,
    flow_efficiency: Optional[float] = 0.5,
    rework_count: int = 0,
    issuetype_bucket: str = "feature",
    issuetype_at_delivery: Optional[str] = "Story",
    cancelled_in_window: bool = False,
    wip_at_to: bool = False,
    wip_samples: Tuple[bool, ...] = (),
    cohort: Optional[bool] = None,
) -> PerIssueRow:
    """Build a per-issue row with sensible defaults for a delivered Story."""
    return PerIssueRow(
        key=key,
        issue_created=_ts(2026, 4, 1),
        first_commitment_at=_ts(2026, 4, 5) if delivered_in_window else None,
        first_delivery_at=_ts(2026, 4, 10) if delivered_in_window else None,
        cycle_eligible=cycle_eligible if delivered_in_window else False,
        cycle_time_hours=cycle_time_hours if delivered_in_window else None,
        lead_time_hours=lead_time_hours if delivered_in_window else None,
        flow_efficiency=flow_efficiency if delivered_in_window else None,
        rework_count=rework_count,
        issuetype_at_delivery=issuetype_at_delivery if delivered_in_window else None,
        issuetype_bucket=issuetype_bucket if delivered_in_window else None,
        team="Foo",
        delivered_in_window=delivered_in_window,
        cancelled_in_window=cancelled_in_window,
        wip_at_to=wip_at_to,
        wip_samples=wip_samples,
        cohort=cohort,
    )


class _StubJira:
    """JiraClient stand-in that records every ``search`` invocation.

    Returns a fixed list of issue dicts and counts the call so the
    "exactly one search" construction test can assert against it.
    """

    def __init__(self, issues: list) -> None:
        self._issues = list(issues)
        self.search_calls: list = []

    def search(self, jql, fields=None, expand=None, page_size=None):
        self.search_calls.append(
            {"jql": jql, "fields": fields, "expand": expand, "page_size": page_size}
        )
        return iter(self._issues)


# ===========================================================================
# Contract tests (spec § Cohort behaviour)
# ===========================================================================
def test_cohort_split_disjoint() -> None:
    """Every in-scope row gets ``cohort: True`` or ``False`` — never both,
    never missing."""
    rows = [_row(key="PROJ-1"), _row(key="PROJ-2"), _row(key="PROJ-3")]
    keys = {"PROJ-1", "PROJ-3"}
    tagged = list(tag_cohort(iter(rows), keys))
    cohort_vals = [r.cohort for r in tagged]
    assert cohort_vals == [True, False, True]
    # Every flag is a definite bool — never None — after tagging.
    assert all(isinstance(v, bool) for v in cohort_vals)


def test_empty_cohort_does_not_exit_nonzero() -> None:
    """Cohort-jql matching zero issues produces a zero-throughput cohort
    block with null percentiles and the empty-cohort note is recorded."""
    rows = [_row(key="PROJ-1"), _row(key="PROJ-2")]
    notes = MagicMock()
    breakdown = build_cohort_breakdown(
        iter(rows), cohort_keys=set(), config=STATE, window=WINDOW, notes=notes
    )
    cohort_block = breakdown["cohort"]
    assert cohort_block.throughput == 0
    assert cohort_block.cycle_time_hours.p50 is None
    assert cohort_block.cycle_time_hours.p75 is None
    assert cohort_block.cycle_time_hours.p90 is None
    assert cohort_block.lead_time_hours.p50 is None
    assert cohort_block.rework_rate is None
    notes.add_empty_cohort.assert_called_once()


def test_cohort_aggregates_match_subset() -> None:
    """The aggregator run over the ``cohort=True`` subset must produce
    the same :class:`AggregateBlock` as the cohort side of
    :func:`build_cohort_breakdown`."""
    rows = [
        _row(key="PROJ-1", cycle_time_hours=10.0, lead_time_hours=20.0),
        _row(key="PROJ-2", cycle_time_hours=30.0, lead_time_hours=40.0),
        _row(key="PROJ-3", cycle_time_hours=50.0, lead_time_hours=60.0),
        _row(key="PROJ-4", cycle_time_hours=70.0, lead_time_hours=80.0),
    ]
    cohort_keys = {"PROJ-1", "PROJ-3"}
    notes = MagicMock()
    breakdown = build_cohort_breakdown(
        list(rows), cohort_keys, config=STATE, window=WINDOW, notes=notes
    )

    # Independent subset aggregation: re-tag a fresh copy of the rows
    # and aggregate only the cohort=True subset.
    fresh = [_row(key=r.key, cycle_time_hours=r.cycle_time_hours,
                  lead_time_hours=r.lead_time_hours) for r in rows]
    tagged = list(tag_cohort(iter(fresh), cohort_keys))
    cohort_only = aggregate(
        iter(r for r in tagged if r.cohort), WINDOW, STATE
    )

    assert breakdown["cohort"] == cohort_only


def test_cohort_rework_rate_denominator_is_cohort_throughput() -> None:
    """Fixture: cohort throughput=10 with 5 backward edges (rework_rate
    0.5); control throughput=90 with 9 backward edges (rework_rate 0.1).
    Cohort breakdown must report ``cohort.rework_rate == 0.5``, NOT the
    globally-averaged 0.14."""
    cohort_rows = (
        [_row(key="C-{}".format(i + 1), rework_count=1) for i in range(5)]
        + [_row(key="C-{}".format(i + 6), rework_count=0) for i in range(5)]
    )
    control_rows = (
        [_row(key="X-{}".format(i + 1), rework_count=1) for i in range(9)]
        + [_row(key="X-{}".format(i + 10), rework_count=0) for i in range(81)]
    )
    all_rows = cohort_rows + control_rows
    cohort_keys = {r.key for r in cohort_rows}
    notes = MagicMock()
    breakdown = build_cohort_breakdown(
        all_rows, cohort_keys, config=STATE, window=WINDOW, notes=notes
    )
    assert breakdown["cohort"].throughput == 10
    assert breakdown["cohort"].rework_rate == 0.5
    assert breakdown["control"].throughput == 90
    # Symmetric for the control side: 9 / 90 == 0.1.
    assert breakdown["control"].rework_rate == 0.1
    # Empty-cohort note path NOT taken when the cohort has rows.
    notes.add_empty_cohort.assert_not_called()


def test_per_issue_omits_cohort_breakdown() -> None:
    """In per-issue mode, every JSONL row carries the cohort field; the
    aggregate-only ``cohort_breakdown`` object never exists on a row.

    Tested at the data-shape boundary: :func:`tag_cohort` is the per-
    issue cohort path; it sets the row-level ``cohort`` bool and adds
    no breakdown structure to the rows themselves. T10 enforces the
    rendering contract (no ``cohort_breakdown`` in JSONL output).
    """
    rows = [_row(key="PROJ-1"), _row(key="PROJ-2")]
    tagged = list(tag_cohort(iter(rows), {"PROJ-1"}))
    assert tagged[0].cohort is True
    assert tagged[1].cohort is False
    # PerIssueRow has no ``cohort_breakdown`` attribute — that's an
    # aggregate-mode-only object, never present per-row.
    assert not hasattr(tagged[0], "cohort_breakdown")
    assert not hasattr(tagged[1], "cohort_breakdown")


def test_meta_cohort_jql_omitted_when_absent() -> None:
    """``meta.cohort_jql`` is missing entirely — not null, not empty —
    when ``--cohort-jql`` was not provided; present and verbatim when
    it was. The shape contract lives in :func:`cohort_meta`; T10 merges
    its return into the top-level ``meta`` block."""
    assert cohort_meta(None) == {}
    assert cohort_meta("") == {}
    assert cohort_meta("   ") == {}
    assert cohort_meta("labels = ai-assisted") == {
        "cohort_jql": "labels = ai-assisted"
    }


def test_cohort_jql_user_clause_parenthesized() -> None:
    """Cohort JQL composes with scope as ``(<scope>) AND (<cohort_jql>)``
    — both sides parenthesized, regardless of internal operator
    precedence. Pinned byte-for-byte against :func:`compose_jql`."""
    assert (
        compose_jql("project = PROJ", "labels = ai-assisted OR labels = beta")
        == "(project = PROJ) AND (labels = ai-assisted OR labels = beta) ORDER BY key ASC"
    )


def test_jql_user_clause_parenthesized() -> None:
    """``--jql`` clause is wrapped identically to cohort JQL."""
    assert (
        compose_jql("project = PROJ", "a OR b")
        == "(project = PROJ) AND (a OR b) ORDER BY key ASC"
    )


def test_align_filter_user_clause_parenthesized() -> None:
    """``--align-filter`` (OData) follows the same parenthesization rule.
    ``order_by_key=False`` because OData doesn't ``ORDER BY key``."""
    assert (
        compose_jql(
            "programID eq 42",
            "createDate gt 2026-01-01",
            order_by_key=False,
        )
        == "(programID eq 42) AND (createDate gt 2026-01-01)"
    )


# ===========================================================================
# Construction tests
# ===========================================================================
def test_cohort_resolution_one_query() -> None:
    """The cohort issue set is fetched exactly once.

    One ``jira.search`` call with the composed cohort JQL; per-issue
    rows are tagged from the resulting key set in memory (no second
    search to re-check membership per row).
    """
    stub = _StubJira([
        {"key": "PROJ-1", "fields": {}},
        {"key": "PROJ-3", "fields": {}},
    ])
    keys = resolve_cohort_keys(
        stub, cohort_jql="labels = ai-assisted", scope="project = PROJ"
    )
    assert keys == {"PROJ-1", "PROJ-3"}
    assert len(stub.search_calls) == 1
    # Composed JQL pins both parenthesization and the ORDER BY suffix.
    assert stub.search_calls[0]["jql"] == (
        "(project = PROJ) AND (labels = ai-assisted) ORDER BY key ASC"
    )

    # Tagging is purely in-memory — no extra search calls.
    rows = [_row(key="PROJ-1"), _row(key="PROJ-2"), _row(key="PROJ-3")]
    tagged = list(tag_cohort(iter(rows), keys))
    assert [r.cohort for r in tagged] == [True, False, True]
    assert len(stub.search_calls) == 1


def test_cohort_breakdown_flow_distribution_cohort_restricted() -> None:
    """Cohort's ``flow_distribution.denominator`` = delivered-in-window
    cohort issues incl subtasks.

    Fixture: cohort has 5 Story (feature) + 2 Sub-task delivered rows;
    control has 10 Story delivered rows. With ``--include-subtasks``
    defaulted to ``False``, cohort throughput excludes subtasks (5),
    but the flow_distribution denominator counts them (7). Control's
    denominator is its own 10 — never cross-contaminated.
    """
    cohort_rows = (
        [_row(key="C-{}".format(i + 1), issuetype_bucket="feature") for i in range(5)]
        + [
            _row(
                key="C-S-{}".format(i + 1),
                issuetype_bucket="subtask",
                issuetype_at_delivery="Sub-task",
            )
            for i in range(2)
        ]
    )
    control_rows = [
        _row(key="X-{}".format(i + 1), issuetype_bucket="feature") for i in range(10)
    ]
    all_rows = cohort_rows + control_rows
    cohort_keys = {r.key for r in cohort_rows}
    notes = MagicMock()
    breakdown = build_cohort_breakdown(
        all_rows, cohort_keys, config=STATE, window=WINDOW, notes=notes
    )
    cohort_block = breakdown["cohort"]
    # Subtasks excluded from throughput by default ...
    assert cohort_block.throughput == 5
    # ... but counted in the flow_distribution denominator.
    assert cohort_block.flow_distribution_denominator == 7
    assert cohort_block.flow_distribution["subtask"] > 0
    # Control is unaffected by the cohort's subtasks.
    assert breakdown["control"].throughput == 10
    assert breakdown["control"].flow_distribution_denominator == 10
    assert breakdown["control"].flow_distribution["subtask"] == 0.0


def test_aggregate_cohort_filters_by_flag() -> None:
    """``aggregate_cohort(..., cohort=True)`` runs T6 against only the
    rows whose ``cohort`` flag is True. Mirror call with ``cohort=False``
    covers the control side."""
    rows = [
        _row(key="A", cohort=True, cycle_time_hours=10.0, lead_time_hours=10.0),
        _row(key="B", cohort=False, cycle_time_hours=99.0, lead_time_hours=99.0),
        _row(key="C", cohort=True, cycle_time_hours=20.0, lead_time_hours=20.0),
    ]
    cohort_block = aggregate_cohort(rows, cohort=True, config=STATE, window=WINDOW)
    assert cohort_block.throughput == 2
    control_block = aggregate_cohort(rows, cohort=False, config=STATE, window=WINDOW)
    assert control_block.throughput == 1


def test_resolve_cohort_keys_uses_compose_jql_parenthesization() -> None:
    """``resolve_cohort_keys`` must route through :func:`compose_jql` so
    a buggy implementation that string-concats can't slip past."""
    stub = _StubJira([])
    resolve_cohort_keys(stub, cohort_jql="a OR b", scope="project = PROJ")
    assert stub.search_calls[0]["jql"] == (
        "(project = PROJ) AND (a OR b) ORDER BY key ASC"
    )


def test_tag_cohort_handles_already_tagged_rows() -> None:
    """Replaying rows from cache may have ``cohort=None`` or stale flags;
    :func:`tag_cohort` overwrites unconditionally so the final tag
    reflects the *current* cohort key set."""
    rows = [
        _row(key="K-1", cohort=True),   # stale; must flip to False
        _row(key="K-2", cohort=None),
    ]
    tagged = list(tag_cohort(iter(rows), {"K-2"}))
    assert tagged[0].cohort is False
    assert tagged[1].cohort is True
