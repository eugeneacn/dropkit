"""Per-issue derivation — :class:`PerIssueRow` and :func:`derive_row`.

T5 substrate: walks each issue's :class:`Timeline`, applies the four
population predicates, and emits a :class:`PerIssueRow` carrying every
field a downstream aggregator (T6) or per-issue consumer
(``ai-adoption-cohort``) needs.

Field-presence rules per docs/specs/flow-metrics.md § "Per-issue mode":

- Delivered-in-window rows carry ``cycle_time_hours``,
  ``lead_time_hours``, ``flow_efficiency``, ``first_commitment_at``,
  ``first_delivery_at``, ``issuetype_at_delivery``, ``issuetype_bucket``,
  ``rework_count`` populated from the timeline.
- Cancelled-in-window or WIP-only rows emit ``null`` for the
  delivery-based fields and ``0`` for ``rework_count``;
  ``cycle_eligible`` is ``false``.
- ``cohort`` is left as ``None`` here; the cohort path (T8) stamps it.
- ``wip_samples`` carries one bool per inclusive calendar day in the
  window (anchor: ``(d + 1 day) 00:00 UTC − 1µs``). T6's Flow Load
  computation is a streaming sum across rows of these per-day samples;
  the last sample is identically ``wip_at_to``.

The streaming entry point :func:`iter_per_issue_rows` calls
:meth:`JiraClient.search` once (with ``compose_jql(..., order_by_key=
True)``) and walks each issue via T4's
:func:`iter_issue_changelog`. Rows are yielded lazily so peak memory is
O(transitions per issue), per the spec's bounded-memory contract.

Stdlib only. Python >= 3.10.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Iterator, List, Mapping, Optional, Tuple

from . import compose_jql
from .changelog import ChangelogEntry, iter_issue_changelog
from .config import IssuetypeConfig, StateConfig
from .predicates import (
    cancelled_in_window,
    cycle_eligible,
    delivered_in_window,
    wip_at_to,
)
from .timeline import Timeline
from .upstream import JiraClient


NO_TEAM = "(no team)"


@dataclass
class PerIssueRow:
    """One row of ``--per-issue`` output.

    Field order matches the spec's per-issue example. Nullable fields
    use ``Optional`` types; the JSONL serializer emits ``null`` for
    them. ``cohort`` is set later by the cohort path; ``None`` here
    means "cohort wasn't requested or hasn't been applied yet" — the
    serializer omits it or fills it as appropriate.
    """

    key: str
    issue_created: datetime
    first_commitment_at: Optional[datetime]
    first_delivery_at: Optional[datetime]
    cycle_eligible: bool
    cycle_time_hours: Optional[float]
    lead_time_hours: Optional[float]
    flow_efficiency: Optional[float]
    rework_count: int
    issuetype_at_delivery: Optional[str]
    issuetype_bucket: Optional[str]
    team: str
    delivered_in_window: bool
    cancelled_in_window: bool
    wip_at_to: bool
    wip_samples: Tuple[bool, ...] = field(default_factory=tuple)
    cohort: Optional[bool] = None


def _hours_between(start: datetime, end: datetime) -> float:
    return (end - start).total_seconds() / 3600.0


def _resolve_team(issue: Mapping, state_config: StateConfig) -> str:
    """Return the team string for the issue's row.

    Field-level permission undercount: if ``team_field.id`` is missing
    or null on the issue, the row's ``team`` is the synthetic string
    ``"(no team)"``. The aggregator (T6) counts these and emits a
    ``notes`` line — that aggregation is downstream of this function.

    Supports ``team_field.kind`` in ``{single_value, array}``. For
    ``array``, the per-issue row carries the first non-empty team name;
    full overlap semantics (an issue counted in every team's rollup)
    live in T9's aggregator. ``user_picker_group`` is deferred to v2.
    """
    tf = state_config.team_field
    if tf is None or tf.id is None:
        return NO_TEAM
    fields = issue.get("fields") or {}
    raw = fields.get(tf.id)
    if raw is None:
        return NO_TEAM
    if isinstance(raw, str):
        return raw if raw else NO_TEAM
    if isinstance(raw, Mapping):
        for k in ("value", "name"):
            v = raw.get(k)
            if isinstance(v, str) and v:
                return v
        return NO_TEAM
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item:
                return item
            if isinstance(item, Mapping):
                for k in ("value", "name"):
                    v = item.get(k)
                    if isinstance(v, str) and v:
                        return v
        return NO_TEAM
    return NO_TEAM


def _first_commitment_at_or_before(
    timeline: Timeline, before_or_at: datetime
) -> Optional[datetime]:
    """Timestamp of the first changelog transition into ``commitment_state``
    whose timestamp is ``<= before_or_at``. ``None`` if no such transition.
    """
    commitment = timeline.config.commitment_state
    for t in timeline.status_transitions:
        if t.timestamp > before_or_at:
            break
        if t.to_canonical == commitment:
            return t.timestamp
    return None


def _flow_efficiency(
    timeline: Timeline,
    state_config: StateConfig,
    interval: tuple,
) -> Optional[float]:
    """``active_t / (active_t + wait_t)`` over ``interval``.

    Returns ``None`` for the zero-denominator case (e.g. an
    instantaneous commit-to-delivery). The aggregator counts these in
    ``notes``.
    """
    active = timedelta(0)
    for s in state_config.active_states:
        active += timeline.time_in(s, interval)
    wait = timedelta(0)
    for s in state_config.wait_states:
        wait += timeline.time_in(s, interval)
    total = active + wait
    total_s = total.total_seconds()
    if total_s <= 0:
        return None
    return active.total_seconds() / total_s


def _wip_samples(
    timeline: Timeline,
    state_config: StateConfig,
    window: Any,
    delivered: bool,
) -> Tuple[bool, ...]:
    """Per-day WIP-style samples for the inclusive window.

    One bool per calendar day ``d`` from ``window.from_date`` through
    ``window.to_date`` inclusive, sampled at ``(d + 1 day) 00:00 UTC −
    1µs`` — the same anchor as :func:`predicates.wip_at_to`. A delivered-
    in-window issue contributes all-``False`` (the WIP membership
    predicate excludes it on every day); a non-delivered issue gets one
    ``True`` per day where its canonical state at the anchor is in
    ``active_states``. Samples taken before the issue's ``created`` are
    forced to ``False`` (an issue cannot be WIP before it exists).
    T6's :func:`aggregate.aggregate` sums these column-wise across rows
    to derive Flow Load.
    """
    sample_count = (window.to_date - window.from_date).days + 1
    if delivered:
        return tuple([False] * sample_count)
    active = state_config.active_states
    out: List[bool] = []
    for i in range(sample_count):
        day = window.from_date + timedelta(days=i)
        anchor = (
            datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
            + timedelta(days=1)
            - timedelta(microseconds=1)
        )
        if anchor < timeline.created:
            out.append(False)
            continue
        out.append(timeline.state_at(anchor) in active)
    return tuple(out)


def derive_row(
    issue: Mapping,
    changelog: Iterable[ChangelogEntry],
    state_config: StateConfig,
    issuetype_config: IssuetypeConfig,
    window: Any,
) -> PerIssueRow:
    """Build a :class:`PerIssueRow` for one issue.

    The caller is responsible for filtering out rows that are not in
    scope (none of delivered_in_window / cancelled_in_window / wip_at_to
    are true) — :func:`iter_per_issue_rows` does this.

    Raises :class:`UnmappedStatusError` (via :class:`Timeline`
    construction) if the changelog or baseline contains a raw status
    not in ``state_config.canonical_states``.
    """
    timeline = Timeline(issue, changelog, state_config)
    delivered = delivered_in_window(timeline, window)
    cancelled = cancelled_in_window(timeline, window)
    wip = wip_at_to(timeline, window)
    is_cycle_eligible = cycle_eligible(timeline, window) if delivered else False
    wip_samples = _wip_samples(timeline, state_config, window, delivered)

    first_delivery_at: Optional[datetime] = None
    first_commitment_at: Optional[datetime] = None
    cycle_time_hours: Optional[float] = None
    lead_time_hours: Optional[float] = None
    flow_efficiency: Optional[float] = None
    rework_count = 0
    issuetype_at_delivery: Optional[str] = None
    issuetype_bucket: Optional[str] = None

    if delivered:
        first_delivery_at = timeline.first_canonical_transition_into(
            state_config.delivery_state
        )
        # ``first_delivery_at`` is guaranteed non-None here:
        # ``delivered_in_window`` returned True.
        assert first_delivery_at is not None
        lead_time_hours = _hours_between(timeline.created, first_delivery_at)

        edges = timeline.backward_edges(state_config.rework_signals)
        rework_count = sum(1 for ts, _, _ in edges if ts <= first_delivery_at)

        raw_issuetype = timeline.issuetype_at(first_delivery_at)
        if raw_issuetype:
            issuetype_at_delivery = raw_issuetype
            bucket = issuetype_config.bucket_for(raw_issuetype)
            issuetype_bucket = bucket if bucket is not None else "other"

        if is_cycle_eligible:
            first_commitment_at = _first_commitment_at_or_before(
                timeline, first_delivery_at
            )
            if first_commitment_at is not None:
                cycle_time_hours = _hours_between(
                    first_commitment_at, first_delivery_at
                )
                flow_efficiency = _flow_efficiency(
                    timeline,
                    state_config,
                    (first_commitment_at, first_delivery_at),
                )

    team = _resolve_team(issue, state_config)

    return PerIssueRow(
        key=str(issue.get("key", "")),
        issue_created=timeline.created,
        first_commitment_at=first_commitment_at,
        first_delivery_at=first_delivery_at,
        cycle_eligible=is_cycle_eligible,
        cycle_time_hours=cycle_time_hours,
        lead_time_hours=lead_time_hours,
        flow_efficiency=flow_efficiency,
        rework_count=rework_count,
        issuetype_at_delivery=issuetype_at_delivery,
        issuetype_bucket=issuetype_bucket,
        team=team,
        delivered_in_window=delivered,
        cancelled_in_window=cancelled,
        wip_at_to=wip,
        wip_samples=wip_samples,
        cohort=None,
    )


def _default_fields(state_config: StateConfig) -> str:
    """Default field list for the Jira search. Includes the configured
    team field id if one is set so :func:`_resolve_team` can read it.
    """
    base: List[str] = ["summary", "status", "issuetype", "created"]
    tf = state_config.team_field
    if tf is not None and tf.id:
        base.append(tf.id)
    return ",".join(base)


def iter_per_issue_rows(
    jira: JiraClient,
    scope_clause: str,
    user_clause: Optional[str],
    state_config: StateConfig,
    issuetype_config: IssuetypeConfig,
    window: Any,
    *,
    fields: Optional[str] = None,
) -> Iterator[PerIssueRow]:
    """Stream per-issue rows for ``scope_clause`` (+ optional
    ``user_clause``) over ``window``.

    Composes JQL via :func:`compose_jql` with ``order_by_key=True`` so
    every ``jira: search`` invocation ends in ``ORDER BY key ASC``
    (spec output-canonicalization rule 4). Per the bounded-memory
    contract, both the search and the per-issue changelog drain are
    streamed; rows are yielded one at a time.

    Only emits rows that are in scope per the spec's per-issue
    membership rule:
    - delivered-in-window, OR
    - cancelled-in-window, OR
    - in-WIP at the WIP-instant.
    """
    full_jql = compose_jql(scope_clause, user_clause, order_by_key=True)
    field_set = fields if fields is not None else _default_fields(state_config)

    for issue in jira.search(full_jql, fields=field_set, expand="changelog"):
        key = issue.get("key")
        if not isinstance(key, str):
            continue
        changelog_iter = iter_issue_changelog(jira, key, issue.get("changelog"))
        row = derive_row(issue, changelog_iter, state_config, issuetype_config, window)
        if row.delivered_in_window or row.cancelled_in_window or row.wip_at_to:
            yield row


__all__ = [
    "NO_TEAM",
    "PerIssueRow",
    "derive_row",
    "iter_per_issue_rows",
]
