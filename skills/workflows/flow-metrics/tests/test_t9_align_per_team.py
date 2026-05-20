"""T9 contract + construction tests for Jira Align integration and the
per-team rollup.

Test names match docs/specs/flow-metrics-plan.md § T9 (lines 729-759) and
the corresponding contract tests in docs/specs/flow-metrics.md §
"Jira Align integration" / "Output" verbatim, so the spec ↔ test
mapping stays auditable.

The :class:`JiraAlignClient` is never spawned for real here — every
upstream invocation is mediated through a tiny stub or :class:`MagicMock`
that records ``raw_get`` calls. Per spec § "Read-only contract" the
allowlist enforcement lives in
:class:`flow_metrics.upstream.JiraAlignClient`; T9's tests focus on the
calling pattern and the response-shape validation, not on the wrapper
itself.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple
from unittest.mock import MagicMock

import pytest

from flow_metrics import Window
from flow_metrics.align import (
    AlignResponseError,
    AlignScope,
    compute_sources,
    require_align_join_field,
    resolve_teams,
    teams_for_scope,
    validate_align_teams_path,
)
from flow_metrics.config import TeamField, load_state_config
from flow_metrics.per_issue import NO_TEAM, PerIssueRow
from flow_metrics.per_team import (
    bucket_by_team,
    compose_program_scope_jql,
    per_team_double_counted,
    per_team_rollup,
)


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
    team: str = "Foo",
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
) -> PerIssueRow:
    """Construct a delivered-in-window Story row by default — enough to
    drive the aggregator's throughput counter without dragging in the
    full Timeline / changelog pipeline."""
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
        team=team,
        delivered_in_window=delivered_in_window,
        cancelled_in_window=cancelled_in_window,
        wip_at_to=wip_at_to,
        wip_samples=wip_samples,
        cohort=None,
    )


class _StubAlign:
    """JiraAlignClient stand-in: records every ``raw_get`` invocation and
    replays a scripted response per path.

    Match-against-path semantics so the test can pre-load multiple paths
    (portfolio walk hits one ``portfolios/<id>/programs`` and then one
    ``programs/<pid>/teams`` per program). Unknown paths raise so a
    typo'd fixture surfaces loudly instead of returning ``None``.
    """

    def __init__(self, responses: dict) -> None:
        self._responses = dict(responses)
        self.calls: List[str] = []

    def raw_get(self, path, params=None):  # type: ignore[no-untyped-def]
        self.calls.append(path)
        if path not in self._responses:
            raise KeyError("no scripted response for path {!r}".format(path))
        return self._responses[path]


# ===========================================================================
# Contract tests (spec § Jira Align integration / Output)
# ===========================================================================
def test_jira_only_run_does_not_call_jira_align() -> None:
    """With ``--project KEY`` scope the mocked ``jira-align`` skill must
    record zero invocations. The gate lives in :func:`teams_for_scope`:
    a ``None`` scope short-circuits before the client is consulted."""
    align = MagicMock()
    teams = teams_for_scope(align, scope=None)
    assert teams == []
    # No method was invoked on the client — including ``raw_get`` and
    # any attribute access we might add later.
    assert align.method_calls == []


def test_program_scope_uses_raw_get_teams_path() -> None:
    """With ``--program-id 42`` the mocked ``jira-align`` records exactly
    one call to ``raw GET programs/42/teams`` (or the
    ``--align-teams-path`` override when set)."""
    # Default path: programs/<id>/teams.
    align = _StubAlign({"programs/42/teams": [{"id": 1}, {"id": 2}]})
    scope = AlignScope(kind="program", value="42")
    teams = resolve_teams(align, scope)
    assert align.calls == ["programs/42/teams"]
    assert [t.id for t in teams] == ["1", "2"]

    # Override honored at call time: the override path is used verbatim
    # even when its ``<id>`` differs from the scope id. Validation of
    # the override happens at startup via :func:`validate_align_teams_path`
    # — by the time the override reaches :func:`resolve_teams` it is
    # already known-safe.
    align2 = _StubAlign({"programs/99/teams": [{"id": 5}]})
    scope2 = AlignScope(
        kind="program", value="42", teams_path_override="programs/99/teams"
    )
    resolve_teams(align2, scope2)
    assert align2.calls == ["programs/99/teams"]


def test_program_scope_teams_intersected_via_jira_team_field() -> None:
    """After resolving team ids via Jira Align, the Jira-side fetch goes
    through ``jira: search`` with the configured ``team_field.id`` in
    the JQL — not via Jira Align."""
    align = _StubAlign({"programs/42/teams": [{"id": 1}, {"id": 7}]})
    scope = AlignScope(kind="program", value="42")
    teams = resolve_teams(align, scope)
    jql = compose_program_scope_jql(
        team_field_id="customfield_10001",
        team_ids=[t.id for t in teams],
        user_clause=None,
    )
    # The team_field id (NOT a Jira Align path) is what drives the
    # subsequent Jira query.
    assert '"customfield_10001" in (1, 7)' in jql
    assert jql.endswith("ORDER BY key ASC")


def test_missing_align_join_field_exits_2() -> None:
    """``--program-id 42`` with no ``align_join_field`` in state config
    and no ``--align-join-field`` CLI override is a validation error
    (exit 2). Routed through :func:`require_align_join_field` so the
    CLI failure mode is documented in one place."""
    # The shipped default state config does not set align_join_field;
    # this is the exact case the test pins.
    assert STATE.align_join_field is None
    with pytest.raises(ValueError, match="align_join_field"):
        require_align_join_field(STATE, cli_override=None)
    # Whitespace-only override is treated as "missing", same as None.
    with pytest.raises(ValueError, match="align_join_field"):
        require_align_join_field(STATE, cli_override="   ")
    # A non-empty CLI override satisfies the rule.
    assert require_align_join_field(STATE, cli_override="Epic Link") == "Epic Link"


def test_align_teams_path_rejects_traversal() -> None:
    """``--align-teams-path "../admin/users"`` rejects at startup;
    ``--align-teams-path "/programs/42/teams"`` (leading slash) also
    rejects. Neither reaches any upstream call."""
    with pytest.raises(ValueError, match="traversal"):
        validate_align_teams_path("../admin/users")
    with pytest.raises(ValueError, match="traversal"):
        validate_align_teams_path("programs/../admin/users")
    with pytest.raises(ValueError, match="absolute"):
        validate_align_teams_path("/programs/42/teams")


def test_align_teams_path_validates_response_shape() -> None:
    """When the mocked ``jira-align`` returns a list of items missing
    the ``id`` field, the resolver raises :class:`AlignResponseError`
    with ``"unexpected response shape from <path>"`` — the CLI maps that
    to exit 3."""
    align = _StubAlign({"programs/42/teams": [{"name": "Foo"}]})
    scope = AlignScope(kind="program", value="42")
    with pytest.raises(
        AlignResponseError,
        match=r"unexpected response shape from programs/42/teams",
    ):
        resolve_teams(align, scope)


def test_per_team_array_kind_double_count_flagged() -> None:
    """Fixture with ``team_field.kind: array`` and one issue assigned to
    two teams: the issue appears in two ``per_team`` rows;
    ``meta.per_team_double_counted == True``; ``notes`` records the
    double-count signal."""
    team_field = TeamField(id="customfield_10001", kind="array")
    rows = [_row(key="A"), _row(key="B")]
    teams_lookup = {"A": ["Foo", "Bar"], "B": ["Bar"]}
    notes = MagicMock()
    buckets = bucket_by_team(
        rows,
        team_field,
        teams_for_row=lambda r: teams_lookup[r.key],
        notes=notes,
    )
    out = per_team_rollup(buckets, STATE, WINDOW)
    by_team = {r.team: r for r in out}
    assert set(by_team) == {"Foo", "Bar"}
    # Foo has only A; Bar has both A and B — overlap because A is in
    # both teams' array.
    assert by_team["Foo"].aggregates.throughput == 1
    assert by_team["Bar"].aggregates.throughput == 2
    # Sum > global throughput (2): 1 + 2 = 3 — the double-count signal.
    total = sum(r.aggregates.throughput for r in out)
    assert total == 3 and total > len(rows)
    # meta-level signal that T10 will surface as ``per_team_double_counted``.
    assert per_team_double_counted(team_field) is True
    # K = 1: only issue A belongs to more than one team (Foo + Bar);
    # issue B is in just Bar. The notes collector receives the K count
    # so T11 can fill the spec wording "K issues belong to multiple
    # teams and are counted in each".
    notes.add_per_team_double_counted.assert_called_once_with(1)


def test_per_team_single_value_kind_sums_to_throughput() -> None:
    """Default ``single_value`` kind: ``sum(per_team[*].throughput)``
    equals the global ``aggregates.throughput`` — the buckets partition
    the in-scope rows exactly, with no overlap."""
    from flow_metrics.aggregate import aggregate

    team_field = TeamField(id="customfield_10001", kind="single_value")
    rows = [
        _row(key="A", team="Foo"),
        _row(key="B", team="Foo"),
        _row(key="C", team="Bar"),
    ]
    notes = MagicMock()
    buckets = bucket_by_team(list(rows), team_field, notes=notes)
    out = per_team_rollup(buckets, STATE, WINDOW)
    per_team_sum = sum(r.aggregates.throughput for r in out)
    # T6-API: aggregate(rows, window, config, *, include_subtasks=False).
    global_block = aggregate(iter(rows), WINDOW, STATE)
    assert per_team_sum == global_block.throughput
    # single_value kind must NOT signal double-counting.
    assert per_team_double_counted(team_field) is False
    notes.add_per_team_double_counted.assert_not_called()


def test_per_team_sort_uses_codepoint_order() -> None:
    """Fixture with team names ``"Zebra"``, ``"Über-team"``, ``"alpha"``.

    The pinning rule (T9 plan, line 739-740): Unicode codepoint order,
    Python's default :func:`sorted` on strings — explicit anti-locale.
    Codepoints: ``Z`` (0x5A) < ``a`` (0x61) < ``Ü`` (0xDC), so the
    output order is ``Zebra``, ``alpha``, ``Über-team``: uppercase ASCII
    first, then lowercase ASCII, then Latin-1 supplement. (The spec's
    prose example at flow-metrics.md:1208-1211 claims an order that
    contradicts its own "ASCII before non-ASCII" explanation; the plan
    task description and ``sorted(list_of_strings)`` are the canonical
    source.)
    """
    team_field = TeamField(id="customfield_10001", kind="single_value")
    rows = [
        _row(key="A", team="alpha"),
        _row(key="B", team="Zebra"),
        _row(key="C", team="Über-team"),
    ]
    buckets = bucket_by_team(rows, team_field)
    out = per_team_rollup(buckets, STATE, WINDOW)
    # Codepoint comparison: Z (0x5A) < a (0x61) < Ü (0xDC).
    assert [r.team for r in out] == ["Zebra", "alpha", "Über-team"]
    # Defensive: lock in the codepoint relation a locale-aware sort
    # would invert (most locales fold case and place "Über" near "U").
    assert ord("Z") < ord("a") < ord("Ü")
    # And the rollup output must match plain :func:`sorted` exactly.
    assert [r.team for r in out] == sorted(r.team for r in out)


def test_meta_sources_reflects_skills_called() -> None:
    """``meta.sources`` is ``["jira"]`` for project scope and
    ``["jira", "jira-align"]`` (sorted) for program / portfolio scope.
    The list is computed by :func:`compute_sources` and merged into the
    meta block by T10."""
    assert compute_sources("project") == ["jira"]
    # Both Jira Align scopes share the same source list — there's no
    # finer-grained ``portfolio`` skill. The helper accepts both the
    # spec-pinned cache vocabulary (``program``/``portfolio``) and the
    # CLI-flag spelling (``program-id``/``portfolio-id``).
    assert compute_sources("program") == ["jira", "jira-align"]
    assert compute_sources("portfolio") == ["jira", "jira-align"]
    assert compute_sources("program-id") == ["jira", "jira-align"]
    assert compute_sources("portfolio-id") == ["jira", "jira-align"]
    # Codepoint sort: "jira" < "jira-align" (shorter prefix-equal string
    # sorts first). The helper's output must equal :func:`sorted`.
    assert compute_sources("program") == sorted(["jira", "jira-align"])


# ===========================================================================
# Construction tests
# ===========================================================================
def test_program_scope_passes_team_field_to_jira_jql() -> None:
    """Generated JQL has the form
    ``"<team_field.id>" in (<team_a>, <team_b>, ...) ORDER BY key ASC``.

    Construction-level pin: the team-field id is the sole scope
    selector, with the team-id list rendered as a Jira ``IN`` clause."""
    jql = compose_program_scope_jql(
        team_field_id="customfield_10001",
        team_ids=["1", "2", "7"],
        user_clause=None,
    )
    assert jql == '"customfield_10001" in (1, 2, 7) ORDER BY key ASC'

    # ``--jql`` user clause is parenthesized via compose_jql, same rule
    # as every other JQL the skill builds.
    jql_with_user = compose_program_scope_jql(
        team_field_id="customfield_10001",
        team_ids=["1", "2"],
        user_clause="labels = ai-assisted",
    )
    assert jql_with_user == (
        '("customfield_10001" in (1, 2)) AND (labels = ai-assisted) '
        "ORDER BY key ASC"
    )


def test_program_scope_jql_has_no_project_clause() -> None:
    """Explicit anti-test: the composed JQL must NOT contain
    ``project = ...`` — v1 assumes one Jira ↔ one Jira Align pair so
    the team-field membership alone scopes the fetch."""
    jql = compose_program_scope_jql(
        team_field_id="customfield_10001",
        team_ids=["1", "2"],
        user_clause=None,
    )
    assert "project = " not in jql
    assert "project=" not in jql
    # Even when a user clause is supplied, the scope half stays project-
    # less: compose_program_scope_jql never injects ``project = ...``.
    jql_with_user = compose_program_scope_jql(
        team_field_id="customfield_10001",
        team_ids=["1"],
        user_clause="project = PROJ",
    )
    # The user clause may itself mention "project = " — that's the
    # caller's prerogative — but our scope half doesn't.
    assert jql_with_user.startswith('("customfield_10001" in (1))')


def test_portfolio_scope_walks_programs_then_teams() -> None:
    """Call sequence: ``portfolios/<id>/programs`` first, then for each
    returned program ``programs/<pid>/teams``. The Jira-side JQL is
    composed last with all collected team ids."""
    align = _StubAlign({
        "portfolios/7/programs": [{"id": 11}, {"id": 22}],
        "programs/11/teams": [{"id": 100}, {"id": 101}],
        "programs/22/teams": [{"id": 200}],
    })
    scope = AlignScope(kind="portfolio", value="7")
    teams = resolve_teams(align, scope)
    # Portfolio listing strictly before any team listing.
    assert align.calls == [
        "portfolios/7/programs",
        "programs/11/teams",
        "programs/22/teams",
    ]
    assert [t.id for t in teams] == ["100", "101", "200"]
    # Composed Jira JQL carries all team ids in encounter order.
    jql = compose_program_scope_jql(
        team_field_id="customfield_10001",
        team_ids=[t.id for t in teams],
        user_clause=None,
    )
    assert '"customfield_10001" in (100, 101, 200)' in jql


def test_align_teams_path_override_validated_as_exact_pattern() -> None:
    """``programs/42/features`` is rejected at startup (not at call
    time) because it is not one of the four allowed Jira Align
    nested-resource paths — even though it doesn't contain ``..`` or a
    leading slash."""
    with pytest.raises(ValueError, match="not one of the allowed"):
        validate_align_teams_path("programs/42/features")
    # The four allowed exact patterns all pass.
    for ok in (
        "programs/42",
        "programs/42/teams",
        "portfolios/7",
        "portfolios/7/programs",
    ):
        assert validate_align_teams_path(ok) == ok
    # Non-numeric id is still rejected — the patterns pin ``[0-9]+``.
    with pytest.raises(ValueError, match="not one of the allowed"):
        validate_align_teams_path("programs/abc/teams")


def test_field_level_permission_undercount_recorded() -> None:
    """Fixture with one issue whose ``team_field`` returns null: the row
    has ``team == NO_TEAM`` (T5's :func:`_resolve_team` does the
    conversion), goes into a synthetic ``(no team)`` per_team row, and
    ``notes.add_field_permission_undercount`` is called with the count.

    Also pins the reconcile-with-global property the spec calls out:
    routing null-team rows into the synthetic bucket (instead of
    dropping them) keeps ``sum(per_team[*].throughput) ==
    aggregates.throughput`` for single_value kinds even when permissions
    masked the team.
    """
    from flow_metrics.aggregate import aggregate

    team_field = TeamField(id="customfield_10001", kind="single_value")
    rows = [
        _row(key="A", team="Foo"),
        _row(key="B", team="Foo"),
        _row(key="C", team=NO_TEAM),
    ]
    notes = MagicMock()
    buckets = bucket_by_team(list(rows), team_field, notes=notes)
    # Synthetic "(no team)" bucket exists and has the orphaned row.
    assert NO_TEAM in buckets
    assert [r.key for r in buckets[NO_TEAM]] == ["C"]
    # Notes collector saw exactly the under-counted total, once.
    notes.add_field_permission_undercount.assert_called_once_with(
        "customfield_10001", 1
    )

    out = per_team_rollup(buckets, STATE, WINDOW)
    by_team = {r.team: r for r in out}
    # The "(no team)" row appears in the per_team output so global
    # aggregates still reconcile with the per-team sum (single_value).
    assert NO_TEAM in by_team
    assert by_team[NO_TEAM].aggregates.throughput == 1
    # Global reconciliation: per_team sum matches aggregates.throughput.
    global_block = aggregate(iter(rows), WINDOW, STATE)
    assert sum(r.aggregates.throughput for r in out) == global_block.throughput


def test_bucket_by_team_array_kind_without_extractor_raises() -> None:
    """``team_field.kind='array'`` without a ``teams_for_row`` callable
    is rejected upfront: PerIssueRow only carries the first team for
    array fields, so silently degrading to single-value semantics would
    produce wrong throughput. Refuses with a message that names the
    missing argument so the caller can see the contract."""
    team_field = TeamField(id="customfield_10001", kind="array")
    rows = [_row(key="A", team="Foo")]
    with pytest.raises(ValueError, match="teams_for_row"):
        bucket_by_team(rows, team_field)
