"""T5 contract + construction tests for per-issue derivation.

Covers every test enumerated in docs/specs/flow-metrics-plan.md § T5
and the corresponding contract tests in docs/specs/flow-metrics.md
§ "Metric definitions" → "Core population predicates" / § "Outputs"
→ "Per-issue mode".

Timelines are constructed directly from synthetic :class:`ChangelogEntry`
lists; no ``subprocess`` ever runs. The streaming entry point is
exercised against a stub jira client so the JQL-suffix contract test
locks in the spec's output-canonicalization rule 4.
"""
from __future__ import annotations

import json
from dataclasses import fields as dc_fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pytest

from flow_metrics import Window
from flow_metrics.changelog import ChangelogEntry
from flow_metrics.config import (
    IssuetypeConfig,
    StateConfig,
    _build_issuetype_config,
    _build_state_config,
    validate_issuetype_config,
    validate_state_config,
)
from flow_metrics.per_issue import (
    NO_TEAM,
    PerIssueRow,
    derive_row,
    iter_per_issue_rows,
)
from flow_metrics.predicates import (
    cancelled_in_window,
    cycle_eligible,
    delivered_in_window,
    wip_at_to,
    wip_instant,
)
from flow_metrics.timeline import Timeline, UnmappedStatusError


REFERENCES_DIR = Path(__file__).resolve().parent.parent / "references"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ts(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def _entry(ts: datetime, field: str, frm: str, to: str, *, author: str = "alice") -> ChangelogEntry:
    return ChangelogEntry(
        timestamp=ts, author=author, field=field, from_value=frm, to_value=to,
    )


def _issue(
    key: str = "PROJ-1",
    created: datetime = _ts(2026, 1, 1),
    status_name: str = "Done",
    issuetype_name: str = "Story",
    extra_fields: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    fields = {
        "created": created.strftime("%Y-%m-%dT%H:%M:%S.000+0000"),
        "status": {"name": status_name},
        "issuetype": {"name": issuetype_name},
    }
    if extra_fields:
        fields.update(extra_fields)
    return {"key": key, "fields": fields}


def _window(from_str: str, to_str: str) -> Window:
    fd = date.fromisoformat(from_str)
    td = date.fromisoformat(to_str)
    from_utc = datetime(fd.year, fd.month, fd.day, tzinfo=timezone.utc)
    to_excl = datetime(td.year, td.month, td.day, tzinfo=timezone.utc) + timedelta(days=1)
    return Window(from_date=fd, to_date=td, from_utc=from_utc, to_exclusive_utc=to_excl)


def _state_config(**overrides: Any) -> StateConfig:
    """Build a state config, starting from the shipped default and
    applying overrides at the top level.
    """
    with open(REFERENCES_DIR / "states.default.json", encoding="utf-8") as f:
        parsed = json.load(f)
    parsed.update(overrides)
    validate_state_config(parsed)
    return _build_state_config(parsed)


def _issuetype_config() -> IssuetypeConfig:
    with open(REFERENCES_DIR / "issuetypes.default.json", encoding="utf-8") as f:
        parsed = json.load(f)
    validate_issuetype_config(parsed)
    return _build_issuetype_config(parsed)


WINDOW = _window("2026-04-01", "2026-04-30")
STATE = _state_config()
ITYPE = _issuetype_config()


# ===========================================================================
# Timeline tests
# ===========================================================================
class TestTimeline:
    def test_initial_status_from_first_transition_from_value(self) -> None:
        issue = _issue(status_name="Done")
        cl = [
            _entry(_ts(2026, 4, 10), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 11), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert tl.initial_status == "backlog"

    def test_initial_status_from_issue_when_no_transitions(self) -> None:
        issue = _issue(status_name="In Progress")
        tl = Timeline(issue, [], STATE)
        assert tl.initial_status == "in_progress"

    def test_first_canonical_transition_into_returns_none_when_missing(self) -> None:
        issue = _issue(status_name="In Progress")
        cl = [_entry(_ts(2026, 4, 10), "status", "Backlog", "In Progress")]
        tl = Timeline(issue, cl, STATE)
        assert tl.first_canonical_transition_into("done") is None

    def test_first_canonical_transition_into_returns_first_match(self) -> None:
        issue = _issue(status_name="Done")
        cl = [
            _entry(_ts(2026, 4, 10), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 11), "status", "In Progress", "Done"),
            _entry(_ts(2026, 4, 12), "status", "Done", "In Progress"),
            _entry(_ts(2026, 4, 13), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert tl.first_canonical_transition_into("done") == _ts(2026, 4, 11)

    def test_state_at_walks_transitions(self) -> None:
        issue = _issue(status_name="Done")
        cl = [
            _entry(_ts(2026, 4, 10), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 15), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert tl.state_at(_ts(2026, 4, 5)) == "backlog"
        assert tl.state_at(_ts(2026, 4, 10)) == "in_progress"
        assert tl.state_at(_ts(2026, 4, 12)) == "in_progress"
        assert tl.state_at(_ts(2026, 4, 15)) == "done"
        assert tl.state_at(_ts(2026, 4, 20)) == "done"

    def test_time_in_within_interval(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        # backlog: 4d, in_progress: 5d, done: rest.
        assert tl.time_in("backlog", (_ts(2026, 4, 1), _ts(2026, 4, 20))) == timedelta(days=4)
        assert tl.time_in("in_progress", (_ts(2026, 4, 1), _ts(2026, 4, 20))) == timedelta(days=5)
        assert tl.time_in("done", (_ts(2026, 4, 1), _ts(2026, 4, 20))) == timedelta(days=10)

    def test_time_in_clips_to_interval(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        # Interval that starts mid-in_progress, ends mid-done.
        assert tl.time_in(
            "in_progress", (_ts(2026, 4, 7), _ts(2026, 4, 12))
        ) == timedelta(days=3)

    def test_backward_edges_counts_distinct_transitions(self) -> None:
        issue = _issue(status_name="Done")
        cl = [
            _entry(_ts(2026, 4, 1), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 2), "status", "In Progress", "Backlog"),
            _entry(_ts(2026, 4, 3), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 4), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        edges = tl.backward_edges(STATE.rework_signals)
        assert len(edges) == 1
        assert edges[0][0] == _ts(2026, 4, 2)
        assert edges[0][1] == "in_progress"
        assert edges[0][2] == "backlog"

    def test_issuetype_at_walks_changelog(self) -> None:
        issue = _issue(issuetype_name="Bug")
        cl = [
            _entry(_ts(2026, 4, 10), "issuetype", "Story", "Bug"),
        ]
        tl = Timeline(issue, cl, STATE)
        # Initial is "Story" (from_value of first issuetype transition).
        assert tl.issuetype_at(_ts(2026, 4, 5)) == "Story"
        assert tl.issuetype_at(_ts(2026, 4, 10)) == "Bug"
        assert tl.issuetype_at(_ts(2026, 4, 20)) == "Bug"

    def test_issuetype_at_falls_back_to_current(self) -> None:
        issue = _issue(issuetype_name="Story")
        tl = Timeline(issue, [], STATE)
        assert tl.issuetype_at(_ts(2026, 4, 15)) == "Story"

    def test_defensive_sort_handles_out_of_order_changelog(self) -> None:
        # T4 may yield pages in inconsistent order across Server/Cloud
        # pagination; Timeline must sort defensively or every downstream
        # query silently breaks.
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
        ]
        tl = Timeline(issue, cl, STATE)
        # Sorted: backlog→in_progress at t1, in_progress→done at t2.
        assert tl.first_canonical_transition_into("in_progress") == _ts(2026, 4, 5)
        assert tl.first_canonical_transition_into("done") == _ts(2026, 4, 10)

    def test_backward_edges_count_distinct_once_when_multiple_signals_match(self) -> None:
        # Default config has both signal {in_progress→backlog} and
        # signal {in_review→backlog} — both could potentially match a
        # single in_review→backlog edge. The spec says count exactly
        # once per edge.
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 3), "status", "In Progress", "In Review"),
            _entry(_ts(2026, 4, 4), "status", "In Review", "Backlog"),
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 6), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        edges = tl.backward_edges(STATE.rework_signals)
        # Exactly one backward edge: in_review → backlog.
        assert len(edges) == 1
        assert (edges[0][1], edges[0][2]) == ("in_review", "backlog")

    def test_state_at_handles_issue_created_in_active_state(self) -> None:
        # Created already in_progress (no transitions): state_at any
        # instant after created is in_progress.
        issue = _issue(status_name="In Progress", created=_ts(2026, 4, 1))
        tl = Timeline(issue, [], STATE)
        assert tl.state_at(_ts(2026, 4, 30)) == "in_progress"
        assert tl.first_canonical_transition_into("in_progress") is None


# ===========================================================================
# Predicate tests
# ===========================================================================
class TestPredicates:
    def test_delivered_in_window_true(self) -> None:
        issue = _issue(status_name="Done")
        cl = [
            _entry(_ts(2026, 4, 1), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 15), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert delivered_in_window(tl, WINDOW) is True

    def test_delivered_in_window_false_when_before(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 3, 1))
        cl = [_entry(_ts(2026, 3, 15), "status", "In Progress", "Done")]
        tl = Timeline(issue, cl, STATE)
        assert delivered_in_window(tl, WINDOW) is False

    def test_delivered_in_window_uses_first_ever_not_most_recent(self) -> None:
        # Delivered before window, reopened, redelivered in window:
        # first-ever delivery is OUTSIDE window → False.
        issue = _issue(status_name="Done", created=_ts(2026, 3, 1))
        cl = [
            _entry(_ts(2026, 3, 10), "status", "In Progress", "Done"),
            _entry(_ts(2026, 3, 15), "status", "Done", "In Progress"),
            _entry(_ts(2026, 4, 15), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert delivered_in_window(tl, WINDOW) is False

    def test_cycle_eligible_requires_commitment_at_or_before_delivery(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert cycle_eligible(tl, WINDOW) is True

    def test_cycle_eligible_false_when_skipped(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [_entry(_ts(2026, 4, 10), "status", "Backlog", "Done")]
        tl = Timeline(issue, cl, STATE)
        assert cycle_eligible(tl, WINDOW) is False

    def test_cancelled_in_window_true(self) -> None:
        issue = _issue(status_name="Cancelled", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Cancelled"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert cancelled_in_window(tl, WINDOW) is True

    def test_cancelled_in_window_false_when_delivered(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert cancelled_in_window(tl, WINDOW) is False

    def test_wip_at_to_active_state(self) -> None:
        issue = _issue(status_name="In Progress", created=_ts(2026, 4, 1))
        cl = [_entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress")]
        tl = Timeline(issue, cl, STATE)
        assert wip_at_to(tl, WINDOW) is True

    def test_wip_at_to_wait_state_false(self) -> None:
        # In Review at WIP-instant → wait_state (default config) → False.
        issue = _issue(status_name="In Review", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "In Review"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert wip_at_to(tl, WINDOW) is False

    def test_wip_instant_one_microsecond_before_exclusive(self) -> None:
        wi = wip_instant(WINDOW)
        assert wi == WINDOW.to_exclusive_utc - timedelta(microseconds=1)


# ===========================================================================
# Contract tests from spec
# ===========================================================================
class TestContractTests:
    # -- Cycle time --
    def test_cycle_time_first_commitment_to_first_delivery(self) -> None:
        t1 = _ts(2026, 4, 10, hour=9)
        t2 = _ts(2026, 4, 11, hour=21)
        issue = _issue(status_name="Done", created=_ts(2026, 4, 8))
        cl = [
            _entry(t1, "status", "Backlog", "In Progress"),
            _entry(t2, "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.cycle_eligible is True
        assert row.cycle_time_hours == pytest.approx((t2 - t1).total_seconds() / 3600.0)

    def test_cycle_time_excludes_skipped_commitment(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 8))
        cl = [_entry(_ts(2026, 4, 12), "status", "Backlog", "Done")]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is True
        assert row.cycle_eligible is False
        assert row.cycle_time_hours is None
        assert row.lead_time_hours is not None

    def test_cycle_time_excludes_issue_delivered_after_to(self) -> None:
        # Delivery 1 microsecond AT or AFTER the to_exclusive bound:
        # not delivered-in-window.
        after_to = WINDOW.to_exclusive_utc + timedelta(hours=1)
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(after_to, "status", "In Progress", "Done"),
        ]
        tl = Timeline(issue, cl, STATE)
        assert delivered_in_window(tl, WINDOW) is False

    def test_lead_time_uses_created_to_first_delivery(self) -> None:
        created = _ts(2026, 4, 1, hour=8)
        delivery = _ts(2026, 4, 10, hour=10)
        issue = _issue(status_name="Done", created=created)
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(delivery, "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.lead_time_hours == pytest.approx(
            (delivery - created).total_seconds() / 3600.0
        )

    def test_throughput_first_ever_delivery_in_window(self) -> None:
        # Delivered before window, redelivered in window → not in scope.
        issue = _issue(status_name="Done", created=_ts(2026, 3, 1))
        cl = [
            _entry(_ts(2026, 3, 15), "status", "In Progress", "Done"),
            _entry(_ts(2026, 3, 20), "status", "Done", "In Progress"),
            _entry(_ts(2026, 4, 15), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is False

    def test_throughput_reopen_in_window_doesnt_double_count(self) -> None:
        # First delivery in window, reopen, redeliver in window — still one row.
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
            _entry(_ts(2026, 4, 12), "status", "Done", "In Progress"),
            _entry(_ts(2026, 4, 15), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is True
        assert row.first_delivery_at == _ts(2026, 4, 10)

    def test_wip_at_to_inclusive(self) -> None:
        # Active state at WIP-instant.
        issue_active = _issue(
            key="A-1", status_name="In Progress", created=_ts(2026, 4, 1)
        )
        cl_active = [_entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress")]
        row_a = derive_row(issue_active, cl_active, STATE, ITYPE, WINDOW)
        assert row_a.wip_at_to is True
        assert row_a.delivered_in_window is False

        # Wait state at WIP-instant.
        issue_review = _issue(
            key="A-2", status_name="In Review", created=_ts(2026, 4, 1)
        )
        cl_review = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 7), "status", "In Progress", "In Review"),
        ]
        row_r = derive_row(issue_review, cl_review, STATE, ITYPE, WINDOW)
        assert row_r.wip_at_to is False

    # -- Rework --
    def test_rework_counts_distinct_backward_edges(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 3), "status", "In Progress", "Backlog"),
            _entry(_ts(2026, 4, 4), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 5), "status", "In Progress", "In Review"),
            _entry(_ts(2026, 4, 6), "status", "In Review", "In Progress"),
            _entry(_ts(2026, 4, 7), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        # Two backward edges before delivery:
        #   in_progress → backlog, in_review → in_progress.
        assert row.rework_count == 2

    def test_rework_pre_delivery_only(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 5), "status", "In Progress", "Done"),
            # Post-delivery rework edges — must NOT count in v1.
            _entry(_ts(2026, 4, 6), "status", "Done", "In Progress"),
            _entry(_ts(2026, 4, 7), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.rework_count == 0

    def test_default_rework_signals_cover_in_progress_to_backlog(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 3), "status", "In Progress", "Backlog"),
            _entry(_ts(2026, 4, 4), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 5), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.rework_count == 1

    def test_default_rework_signals_cover_in_test_to_in_review(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 2), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 3), "status", "In Progress", "In Review"),
            _entry(_ts(2026, 4, 4), "status", "In Review", "In Test"),
            _entry(_ts(2026, 4, 5), "status", "In Test", "In Review"),
            _entry(_ts(2026, 4, 6), "status", "In Review", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.rework_count == 1

    # -- Flow efficiency --
    def test_flow_efficiency_active_over_total(self) -> None:
        # 2h in_progress, 2h in_review, 2h in_progress, 2h in_test, done.
        # Active = 4h, wait = 4h, total = 8h → fe = 0.5.
        t_commit = _ts(2026, 4, 10, hour=8)
        t_review = t_commit + timedelta(hours=2)
        t_progress_again = t_review + timedelta(hours=2)
        t_test = t_progress_again + timedelta(hours=2)
        t_done = t_test + timedelta(hours=2)
        issue = _issue(status_name="Done", created=_ts(2026, 4, 9))
        cl = [
            _entry(t_commit, "status", "Backlog", "In Progress"),
            _entry(t_review, "status", "In Progress", "In Review"),
            _entry(t_progress_again, "status", "In Review", "In Progress"),
            _entry(t_test, "status", "In Progress", "In Test"),
            _entry(t_done, "status", "In Test", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.flow_efficiency == pytest.approx(0.5)

    def test_flow_efficiency_uses_commitment_to_delivery_interval(self) -> None:
        # Backlog 5h, then in_progress 2h, done. Backlog time is BEFORE
        # commitment so excluded; FE interval is [t_commit, t_done].
        t_commit = _ts(2026, 4, 10, hour=13)  # 5h after created at 08:00
        t_done = t_commit + timedelta(hours=2)
        issue = _issue(status_name="Done", created=_ts(2026, 4, 10, hour=8))
        cl = [
            _entry(t_commit, "status", "Backlog", "In Progress"),
            _entry(t_done, "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        # In the interval [t_commit, t_done]: active = 2h, wait = 0h → fe = 1.0.
        assert row.flow_efficiency == pytest.approx(1.0)
        assert row.cycle_time_hours == pytest.approx(2.0)

    def test_flow_efficiency_ignores_time_before_first_commitment(self) -> None:
        # Custom config: commitment_state = in_review (not active);
        # active = [in_progress], wait = [backlog, in_test]. This makes
        # the partition asymmetric across the commitment boundary so the
        # test actually distinguishes "pre-commit excluded" from
        # "pre-commit included":
        #
        #   - 2h in_progress (pre-commitment, MUST be excluded)
        #   - 2h in_review (commitment; neither active nor wait → 0)
        #   - 2h in_test (post-commitment, wait)
        #   - delivered
        #
        # Correct: active=0, wait=2h, fe = 0 / 2 = 0.0.
        # Buggy (pre-commit included): active=2h, wait=2h, fe = 0.5.
        custom = _state_config(
            commitment_state="in_review",
            active_states=["in_progress"],
            wait_states=["backlog", "in_test"],
        )
        t_progress_pre = _ts(2026, 4, 10, hour=10)
        t_commit = t_progress_pre + timedelta(hours=2)   # → In Review
        t_test = t_commit + timedelta(hours=2)            # → In Test
        t_done = t_test + timedelta(hours=2)              # → Done
        issue = _issue(status_name="Done", created=_ts(2026, 4, 10, hour=8))
        cl = [
            _entry(t_progress_pre, "status", "Backlog", "In Progress"),
            _entry(t_commit, "status", "In Progress", "In Review"),
            _entry(t_test, "status", "In Review", "In Test"),
            _entry(t_done, "status", "In Test", "Done"),
        ]
        row = derive_row(issue, cl, custom, ITYPE, WINDOW)
        assert row.flow_efficiency == pytest.approx(0.0)

    def test_flow_efficiency_done_time_excluded(self) -> None:
        # Plain flow ending at done. Time in done (after first delivery)
        # is outside the FE interval and excluded by construction.
        t_commit = _ts(2026, 4, 10, hour=8)
        t_done = t_commit + timedelta(hours=4)
        issue = _issue(status_name="Done", created=_ts(2026, 4, 9))
        cl = [
            _entry(t_commit, "status", "Backlog", "In Progress"),
            _entry(t_done, "status", "In Progress", "Done"),
            # Post-delivery reopen and redeliver — outside FE interval.
            _entry(t_done + timedelta(hours=4), "status", "Done", "In Progress"),
            _entry(t_done + timedelta(hours=8), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        # FE only counts pre-first-delivery time.
        assert row.flow_efficiency == pytest.approx(1.0)

    def test_flow_efficiency_zero_denominator_excluded(self) -> None:
        # Instantaneous commit-to-delivery: active_t + wait_t == 0.
        t = _ts(2026, 4, 10, hour=8)
        issue = _issue(status_name="Done", created=_ts(2026, 4, 9))
        cl = [
            _entry(t, "status", "Backlog", "In Progress"),
            _entry(t, "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.cycle_eligible is True
        assert row.flow_efficiency is None

    def test_flow_efficiency_default_config_non_degenerate(self) -> None:
        # Spec fixture: 4h in_progress / 16h in_review / 8h in_progress
        # / 4h in_test / done. Default config → fe = 12/32 = 0.375.
        t_commit = _ts(2026, 4, 10, hour=8)
        t_review = t_commit + timedelta(hours=4)
        t_progress2 = t_review + timedelta(hours=16)
        t_test = t_progress2 + timedelta(hours=8)
        t_done = t_test + timedelta(hours=4)
        issue = _issue(status_name="Done", created=_ts(2026, 4, 9))
        cl = [
            _entry(t_commit, "status", "Backlog", "In Progress"),
            _entry(t_review, "status", "In Progress", "In Review"),
            _entry(t_progress2, "status", "In Review", "In Progress"),
            _entry(t_test, "status", "In Progress", "In Test"),
            _entry(t_done, "status", "In Test", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.flow_efficiency == pytest.approx(12.0 / 32.0)

    # -- Issuetype at delivery --
    def test_issuetype_at_delivery_used_for_distribution(self) -> None:
        delivery = _ts(2026, 4, 10, hour=10)
        # Issuetype changes Story → Bug 1h BEFORE delivery.
        issue = _issue(status_name="Done", issuetype_name="Bug",
                       created=_ts(2026, 4, 9))
        cl = [
            _entry(_ts(2026, 4, 10, hour=8), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10, hour=9), "issuetype", "Story", "Bug"),
            _entry(delivery, "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.issuetype_at_delivery == "Bug"
        assert row.issuetype_bucket == "defect"

    def test_unmapped_issuetype_falls_back_to_other_bucket(self) -> None:
        # Spec § Issuetype configuration: "Unmapped issuetypes go into a
        # 'other' bucket reported in notes. They do not exit 2."
        issue = _issue(
            status_name="Done", issuetype_name="Spike", created=_ts(2026, 4, 1)
        )
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.issuetype_at_delivery == "Spike"
        assert row.issuetype_bucket == "other"

    def test_post_delivery_commitment_doesnt_make_cycle_eligible(self) -> None:
        # Issue created in backlog, transitions DIRECTLY to done (first
        # delivery, no preceding commitment), then post-delivery moves
        # back through in_progress. The post-delivery commitment must
        # NOT satisfy cycle-eligibility (spec: commitment "at or before"
        # first-ever delivery).
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 10), "status", "Backlog", "Done"),
            _entry(_ts(2026, 4, 12), "status", "Done", "In Progress"),
            _entry(_ts(2026, 4, 15), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is True
        assert row.cycle_eligible is False
        assert row.cycle_time_hours is None
        assert row.first_commitment_at is None

    def test_issuetype_change_at_exact_delivery_instant(self) -> None:
        # Issuetype changed AT the same timestamp as first delivery.
        # The walker uses ``<=`` so the post-change value is what's
        # reported as issuetype_at_delivery.
        delivery = _ts(2026, 4, 10, hour=10)
        issue = _issue(status_name="Done", issuetype_name="Bug",
                       created=_ts(2026, 4, 9))
        cl = [
            _entry(_ts(2026, 4, 10, hour=8), "status", "Backlog", "In Progress"),
            _entry(delivery, "issuetype", "Story", "Bug"),
            _entry(delivery, "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.issuetype_at_delivery == "Bug"
        assert row.issuetype_bucket == "defect"

    # -- Cancelled --
    def test_cancelled_excluded_from_throughput(self) -> None:
        issue = _issue(status_name="Cancelled", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Won't Do"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is False
        assert row.cancelled_in_window is True

    def test_cancelled_then_reopened_still_cancelled_in_window(self) -> None:
        # Cancel in window, reopen to active. State at WIP-instant is
        # in_progress (active). Both signals true.
        issue = _issue(status_name="In Progress", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Cancelled"),
            _entry(_ts(2026, 4, 12), "status", "Cancelled", "In Progress"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is False
        assert row.cancelled_in_window is True
        assert row.wip_at_to is True

    # -- Subtasks --
    def test_subtask_excluded_by_default(self) -> None:
        # Per-issue level: the row carries the "subtask" bucket regardless
        # of the throughput-flag (T6 handles inclusion). delivered_in_window
        # is still True for subtasks.
        issue = _issue(status_name="Done", issuetype_name="Sub-task",
                       created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is True
        assert row.issuetype_bucket == "subtask"

    def test_subtask_included_with_flag(self) -> None:
        # Same — bucket label is the same; the "with flag" semantics
        # apply at the aggregator (T6).
        issue = _issue(status_name="Done", issuetype_name="Subtask",
                       created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is True
        assert row.issuetype_bucket == "subtask"

    def test_cycle_time_n_can_differ_from_throughput(self) -> None:
        # Issue delivered without commitment — counted in lead/throughput
        # but NOT in cycle.
        issue = _issue(status_name="Done", created=_ts(2026, 4, 5))
        cl = [_entry(_ts(2026, 4, 10), "status", "Backlog", "Done")]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is True
        assert row.cycle_eligible is False
        assert row.cycle_time_hours is None
        assert row.lead_time_hours is not None


# ===========================================================================
# Construction tests
# ===========================================================================
class TestConstruction:
    def test_unmapped_status_exits_2_at_walk_time(self) -> None:
        # A raw status not under any canonical_states entry → walker raises.
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "Mystery State"),
            _entry(_ts(2026, 4, 10), "status", "Mystery State", "Done"),
        ]
        with pytest.raises(UnmappedStatusError) as exc:
            Timeline(issue, cl, STATE)
        assert exc.value.status == "Mystery State"

    def test_status_renamed_mid_window(self) -> None:
        # The "In Review" status was renamed "Reviewing" in Jira mid-window
        # and only the old name is mapped. The walker hits the new name
        # and raises.
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "In Review"),
            _entry(_ts(2026, 4, 12), "status", "In Review", "Reviewing"),
            _entry(_ts(2026, 4, 15), "status", "Reviewing", "Done"),
        ]
        with pytest.raises(UnmappedStatusError) as exc:
            Timeline(issue, cl, STATE)
        assert exc.value.status == "Reviewing"

    def test_per_issue_row_field_shape(self) -> None:
        # Every field in the spec's per-issue example present and typed
        # correctly on a delivered row.
        issue = _issue(
            key="PROJ-123",
            status_name="Done",
            issuetype_name="Bug",
            created=_ts(2026, 4, 8),
            extra_fields={"customfield_10001": "Foo"},
        )
        cl = [
            _entry(_ts(2026, 4, 12, hour=9), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 13, hour=21), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.key == "PROJ-123"
        assert isinstance(row.issue_created, datetime)
        assert isinstance(row.first_commitment_at, datetime)
        assert isinstance(row.first_delivery_at, datetime)
        assert isinstance(row.cycle_eligible, bool) and row.cycle_eligible is True
        assert isinstance(row.cycle_time_hours, float)
        assert isinstance(row.lead_time_hours, float)
        assert isinstance(row.flow_efficiency, float)
        assert isinstance(row.rework_count, int)
        assert isinstance(row.issuetype_at_delivery, str)
        assert isinstance(row.issuetype_bucket, str)
        assert row.issuetype_bucket == "defect"
        assert isinstance(row.team, str) and row.team == "Foo"
        assert row.delivered_in_window is True
        assert row.cancelled_in_window is False
        assert row.wip_at_to is False

        # The spec example carries exactly these field names — verify each
        # appears on the dataclass (cohort is the optional add at the end).
        expected_fields = {
            "key", "issue_created", "first_commitment_at", "first_delivery_at",
            "cycle_eligible", "cycle_time_hours", "lead_time_hours",
            "flow_efficiency", "rework_count", "issuetype_at_delivery",
            "issuetype_bucket", "team", "delivered_in_window",
            "cancelled_in_window", "wip_at_to", "wip_samples", "cohort",
        }
        assert {f.name for f in dc_fields(PerIssueRow)} == expected_fields

    def test_per_issue_non_delivered_emits_nulls(self) -> None:
        # Cancelled-in-window: delivery-based fields null, rework_count 0.
        issue = _issue(
            status_name="Cancelled",
            issuetype_name="Story",
            created=_ts(2026, 4, 1),
        )
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Cancelled"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is False
        assert row.cancelled_in_window is True
        assert row.cycle_eligible is False
        assert row.cycle_time_hours is None
        assert row.lead_time_hours is None
        assert row.flow_efficiency is None
        assert row.first_commitment_at is None
        assert row.first_delivery_at is None
        assert row.issuetype_at_delivery is None
        assert row.issuetype_bucket is None
        assert row.rework_count == 0

    def test_per_issue_wip_only_emits_nulls(self) -> None:
        # In-WIP at WIP-instant, no delivery, no cancellation → same null pattern.
        issue = _issue(
            status_name="In Progress",
            issuetype_name="Story",
            created=_ts(2026, 4, 1),
        )
        cl = [_entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress")]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is False
        assert row.cancelled_in_window is False
        assert row.wip_at_to is True
        assert row.cycle_eligible is False
        assert row.cycle_time_hours is None
        assert row.lead_time_hours is None
        assert row.flow_efficiency is None
        assert row.first_commitment_at is None
        assert row.first_delivery_at is None
        assert row.issuetype_at_delivery is None
        assert row.issuetype_bucket is None
        assert row.rework_count == 0

    def test_per_issue_no_team_for_missing_field(self) -> None:
        issue = _issue(status_name="Done", created=_ts(2026, 4, 1))  # no team field
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.team == NO_TEAM

    def test_per_issue_team_resolves_value_dict(self) -> None:
        issue = _issue(
            status_name="Done",
            created=_ts(2026, 4, 1),
            extra_fields={"customfield_10001": {"value": "Foo"}},
        )
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.team == "Foo"

    def test_per_issue_team_resolves_array_takes_first(self) -> None:
        # array kind: per-issue row stores the first non-empty team
        # name. Full overlap semantics (an issue counted in every team
        # rollup) lives in T9; this test pins the per-issue contract.
        issue = _issue(
            status_name="Done",
            created=_ts(2026, 4, 1),
            extra_fields={"customfield_10001": [
                {"value": "Foo"}, {"value": "Bar"},
            ]},
        )
        cl = [
            _entry(_ts(2026, 4, 5), "status", "Backlog", "In Progress"),
            _entry(_ts(2026, 4, 10), "status", "In Progress", "Done"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.team == "Foo"

    def test_cancelled_before_window_then_cancelled_again_in_window(self) -> None:
        # Cancel before window, reopen, cancel again in window. The
        # in-window cancellation transition is what triggers the
        # cancelled-in-window predicate.
        issue = _issue(status_name="Cancelled", created=_ts(2026, 2, 1))
        cl = [
            _entry(_ts(2026, 2, 10), "status", "In Progress", "Cancelled"),
            _entry(_ts(2026, 3, 1), "status", "Cancelled", "In Progress"),
            _entry(_ts(2026, 4, 15), "status", "In Progress", "Cancelled"),
        ]
        row = derive_row(issue, cl, STATE, ITYPE, WINDOW)
        assert row.delivered_in_window is False
        assert row.cancelled_in_window is True
        assert row.wip_at_to is False


# ===========================================================================
# JQL composition + streaming entry point
# ===========================================================================
class _StubJira:
    """Minimal jira client stand-in for the streaming entry point.

    Captures every search() invocation's JQL and yields the canned
    issues. ``raw_get`` returns empty pages so changelog drain is a
    no-op.
    """

    def __init__(self, issues: Optional[List[Dict[str, Any]]] = None) -> None:
        self.search_calls: List[Dict[str, Any]] = []
        self.raw_get_calls: List[Dict[str, Any]] = []
        self._issues = list(issues or [])

    def search(self, jql: str, fields: Optional[str] = None,
               expand: Optional[str] = None,
               page_size: Optional[int] = None) -> Iterable[dict]:
        self.search_calls.append(
            {"jql": jql, "fields": fields, "expand": expand, "page_size": page_size}
        )
        for issue in self._issues:
            yield issue

    def raw_get(self, path: str, params: Optional[Dict[str, str]] = None) -> Any:
        self.raw_get_calls.append({"path": path, "params": dict(params or {})})
        return {"histories": [], "isLast": True}


class TestStreamingEntryPoint:
    def test_search_jql_ends_with_order_by_key_asc(self) -> None:
        jira = _StubJira(issues=[])
        rows = list(
            iter_per_issue_rows(
                jira, "project = PROJ", None, STATE, ITYPE, WINDOW,
            )
        )
        assert rows == []
        assert len(jira.search_calls) == 1
        jql = jira.search_calls[0]["jql"]
        assert jql.endswith(" ORDER BY key ASC")

    def test_search_jql_combines_user_clause(self) -> None:
        jira = _StubJira(issues=[])
        list(
            iter_per_issue_rows(
                jira, "project = PROJ", "labels = ai", STATE, ITYPE, WINDOW,
            )
        )
        jql = jira.search_calls[0]["jql"]
        assert jql == "(project = PROJ) AND (labels = ai) ORDER BY key ASC"

    def test_iter_emits_only_in_scope_rows(self) -> None:
        # Three issues: one delivered, one out-of-window, one cancelled.
        issue_delivered = _issue(
            key="PROJ-1", status_name="Done", created=_ts(2026, 4, 1)
        )
        issue_delivered["changelog"] = {
            "histories": [
                {
                    "id": "1",
                    "created": "2026-04-02T12:00:00.000+0000",
                    "author": {"displayName": "alice"},
                    "items": [{
                        "field": "status",
                        "fromString": "Backlog",
                        "toString": "In Progress",
                    }],
                },
                {
                    "id": "2",
                    "created": "2026-04-10T12:00:00.000+0000",
                    "author": {"displayName": "alice"},
                    "items": [{
                        "field": "status",
                        "fromString": "In Progress",
                        "toString": "Done",
                    }],
                },
            ],
            "isLast": True,
        }

        issue_out_of_window = _issue(
            key="PROJ-2", status_name="Done", created=_ts(2026, 1, 1)
        )
        issue_out_of_window["changelog"] = {
            "histories": [
                {
                    "id": "1",
                    "created": "2026-01-05T12:00:00.000+0000",
                    "author": {"displayName": "alice"},
                    "items": [{
                        "field": "status",
                        "fromString": "Backlog",
                        "toString": "In Progress",
                    }],
                },
                {
                    "id": "2",
                    "created": "2026-01-10T12:00:00.000+0000",
                    "author": {"displayName": "alice"},
                    "items": [{
                        "field": "status",
                        "fromString": "In Progress",
                        "toString": "Done",
                    }],
                },
            ],
            "isLast": True,
        }

        issue_cancelled = _issue(
            key="PROJ-3", status_name="Cancelled", created=_ts(2026, 4, 1)
        )
        issue_cancelled["changelog"] = {
            "histories": [
                {
                    "id": "1",
                    "created": "2026-04-10T12:00:00.000+0000",
                    "author": {"displayName": "alice"},
                    "items": [{
                        "field": "status",
                        "fromString": "Backlog",
                        "toString": "Cancelled",
                    }],
                },
            ],
            "isLast": True,
        }

        jira = _StubJira(issues=[issue_delivered, issue_out_of_window, issue_cancelled])
        rows = list(
            iter_per_issue_rows(
                jira, "project = PROJ", None, STATE, ITYPE, WINDOW,
            )
        )
        # PROJ-1 delivered, PROJ-3 cancelled. PROJ-2 dropped (out of scope).
        keys = [r.key for r in rows]
        assert keys == ["PROJ-1", "PROJ-3"]
