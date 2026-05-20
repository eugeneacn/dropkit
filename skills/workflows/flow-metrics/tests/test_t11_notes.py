"""T11 contract + construction tests for the notes collector and meta block.

Test names match docs/specs/flow-metrics-plan.md § T11 (lines 862-882)
and the spec contract tests § "Permission undercounting" line 1289-1300
verbatim so the spec ↔ test mapping stays auditable.

T10's :mod:`test_t10_output` covers ``test_notes_sorted_lexicographically``
at the renderer (integration) layer; the same-named test here covers
the collector directly (unit). The overlap is intentional — both layers
must be idempotent under sorting.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from flow_metrics.meta import (
    SCHEMA_VERSION,
    CallerResolutionError,
    build_meta,
    resolve_caller,
)
from flow_metrics.notes import NotesCollector


# ---------------------------------------------------------------------------
# Contract tests (from spec § "Permission undercounting" + plan T11)
# ---------------------------------------------------------------------------
class TestContract:
    def test_caller_in_meta_cloud(self) -> None:
        """Spec line 1291-1292: Cloud whoami payload with both
        ``accountId`` and ``name`` resolves to ``accountId``."""
        caller = resolve_caller({"accountId": "abc", "name": "alice"})
        assert caller == "abc"

    def test_caller_in_meta_server(self) -> None:
        """Spec line 1293-1295: Server payload with ``name`` and ``key``
        but no ``accountId`` resolves to ``name``."""
        caller = resolve_caller({"name": "alice", "key": "JIRAUSER123"})
        assert caller == "alice"

    def test_caller_unrecognized_whoami_exits_3(self) -> None:
        """Spec line 1296-1297: payload with neither field → exit 3.

        :func:`resolve_caller` raises :class:`CallerResolutionError`;
        the CLI maps it to exit 3 with a message mentioning ``whoami``.
        """
        with pytest.raises(CallerResolutionError) as excinfo:
            resolve_caller({"key": "JIRAUSER123"})
        assert "whoami" in str(excinfo.value)

    def test_permission_undercount_recorded_in_notes(self) -> None:
        """Spec line 1298-1300: when get-project reports a higher total
        than the in-scope JQL, ``notes`` records the delta. Unit test
        — calls the collector directly with the delta count."""
        notes = NotesCollector()
        notes.add_permission_undercount(7)
        out = notes.finalize()
        # Exactly one note line, containing the delta.
        assert len(out) == 1
        assert "7" in out[0]
        assert "permissions" in out[0]
        assert "inaccessible" in out[0]

    def test_notes_sorted_lexicographically(self) -> None:
        """Plan line 868 — also covered at the renderer layer in T10's
        ``TestContract.test_notes_sorted_lexicographically``; here we
        exercise the collector's :meth:`finalize` directly to lock in
        unit-level coverage of the sort. T10's version goes through the
        renderer."""
        notes = NotesCollector()
        # Add in deliberately non-lex order; finalize must re-sort.
        notes.add_cancelled(5)
        notes.add_window_edge_count(3)
        notes.add_skipped_commitment(2)
        notes.add_defect_ratio_disclaimer()  # two lines
        out = notes.finalize()
        assert out == sorted(out)


# ---------------------------------------------------------------------------
# Construction tests (plan lines 872-882)
# ---------------------------------------------------------------------------
class TestConstruction:
    def test_notes_include_window_edge_count(self) -> None:
        """Plan line 872-873: ``notes`` says "N issues entered in-progress
        before window start"."""
        notes = NotesCollector()
        notes.add_window_edge_count(12)
        out = notes.finalize()
        assert any("12" in line and "entered in-progress" in line and "window start" in line for line in out)

    def test_notes_include_unmapped_issuetype_count(self) -> None:
        """Plan line 874-875: ``notes`` says "N issues had unmapped
        issuetype 'X'; bucketed as 'other'"."""
        notes = NotesCollector()
        notes.add_unmapped_issuetype("Spike", 3)
        out = notes.finalize()
        assert any(
            "3" in line and "unmapped issuetype 'Spike'" in line and "bucketed as 'other'" in line
            for line in out
        )

    def test_notes_include_skipped_commitment_count(self) -> None:
        """Plan line 876."""
        notes = NotesCollector()
        notes.add_skipped_commitment(4)
        out = notes.finalize()
        assert any("4" in line and "commitment-state entry" in line for line in out)

    def test_notes_include_zero_denominator_flow_eff_count(self) -> None:
        """Plan line 877."""
        notes = NotesCollector()
        notes.add_zero_denominator_flow_eff(4)
        out = notes.finalize()
        assert any(
            "4" in line and "zero (active_t + wait_t)" in line and "flow_efficiency" in line
            for line in out
        )

    def test_notes_include_cancelled_count(self) -> None:
        """Plan line 878-879: single line listing all five metrics
        cancelled are excluded from. Pins the five-metric list so a
        regression that adds / drops one shows up."""
        notes = NotesCollector()
        notes.add_cancelled(4)
        out = notes.finalize()
        cancelled_lines = [line for line in out if "cancelled in window" in line]
        assert len(cancelled_lines) == 1
        line = cancelled_lines[0]
        assert "4" in line
        for metric in ("throughput", "cycle_time", "lead_time", "flow_efficiency", "flow_distribution"):
            assert metric in line, "cancelled note missing metric {!r}: {!r}".format(metric, line)

    def test_notes_include_defect_ratio_disclaimer(self) -> None:
        """Plan line 880: defect_ratio disclaimer pair.

        Spec § "Outputs" example (lines 440-441) shows TWO disclaimer
        lines — the CFR disambiguation and the denominator clarification.
        Both must appear from one :meth:`add_defect_ratio_disclaimer`
        call so the disclaimer pair stays atomic.
        """
        notes = NotesCollector()
        notes.add_defect_ratio_disclaimer()
        out = notes.finalize()
        # Two lines, distinct.
        cfr_line = next((line for line in out if "Change Failure Rate" in line), None)
        denom_line = next((line for line in out if "flow_distribution denominator" in line), None)
        assert cfr_line is not None, "CFR disclaimer missing: {}".format(out)
        assert denom_line is not None, "denominator disclaimer missing: {}".format(out)

    def test_notes_include_flow_load_sample_count_and_weekend_policy(self) -> None:
        """Plan line 881: flow_load sample count + weekend policy line.
        Spec example: ``"flow_load: 91 samples, weekends included."``."""
        notes = NotesCollector()
        notes.add_flow_load_sample_count(91, "included")
        out = notes.finalize()
        assert any("flow_load" in line and "91 samples" in line and "weekends included" in line for line in out)

    def test_notes_include_field_level_permission_undercount(self) -> None:
        """Plan line 882. Spec § "Permission undercounting" line 647-656:
        per_team field-level undercount surfaces N as the count of
        in-scope issues with no readable team_field value."""
        notes = NotesCollector()
        notes.add_field_permission_undercount("customfield_10001", 5)
        out = notes.finalize()
        assert any(
            "per_team" in line and "5" in line and "readable team_field value" in line
            for line in out
        )


# ---------------------------------------------------------------------------
# Collector behaviour (dedup, idempotency, non-destructive finalize)
# ---------------------------------------------------------------------------
class TestCollectorBehaviour:
    def test_dedup_by_full_string(self) -> None:
        """Plan: dedup by full final string, not by counter-method-name.
        Two calls with the same args collapse; two calls with different
        N produce two lines (caller bug, but the collector keeps both)."""
        notes = NotesCollector()
        notes.add_cancelled(5)
        notes.add_cancelled(5)
        out = notes.finalize()
        assert len([line for line in out if "5" in line and "cancelled" in line]) == 1

        notes2 = NotesCollector()
        notes2.add_cancelled(5)
        notes2.add_cancelled(3)
        out2 = notes2.finalize()
        # Both lines kept — different inputs render different strings.
        assert len([line for line in out2 if "cancelled" in line]) == 2

    def test_finalize_idempotent(self) -> None:
        """Plan: ``finalize()`` is non-destructive; repeated calls return
        equivalent sorted lists. T10's renderer also sorts defensively;
        both passes must be idempotent."""
        notes = NotesCollector()
        notes.add_window_edge_count(3)
        notes.add_cancelled(2)
        first = notes.finalize()
        second = notes.finalize()
        assert first == second
        # Caller can keep adding after finalize.
        notes.add_skipped_commitment(1)
        third = notes.finalize()
        assert len(third) == len(first) + 1

    def test_finalize_returns_fresh_list(self) -> None:
        """Mutating the returned list must not affect the collector."""
        notes = NotesCollector()
        notes.add_window_edge_count(3)
        first = notes.finalize()
        first.clear()
        second = notes.finalize()
        assert len(second) == 1

    def test_unmapped_issuetype_per_name(self) -> None:
        """One line per distinct unmapped issuetype name: ``"Spike"``
        and ``"Bug-Plus"`` produce two lines."""
        notes = NotesCollector()
        notes.add_unmapped_issuetype("Spike", 3)
        notes.add_unmapped_issuetype("Bug-Plus", 1)
        out = notes.finalize()
        spike_lines = [line for line in out if "Spike" in line]
        plus_lines = [line for line in out if "Bug-Plus" in line]
        assert len(spike_lines) == 1
        assert len(plus_lines) == 1


# ---------------------------------------------------------------------------
# meta.build_meta
# ---------------------------------------------------------------------------
class TestBuildMeta:
    def test_cohort_jql_omitted_when_absent(self) -> None:
        """Spec § "Cohort behaviour" line 1128-1131: key absent when
        --cohort-jql not provided. Not null, not ""."""
        meta = _build()
        assert "cohort_jql" not in meta

    def test_cohort_jql_present_when_set(self) -> None:
        meta = _build(cohort_jql="labels = ai-assisted")
        assert meta["cohort_jql"] == "labels = ai-assisted"

    def test_cohort_jql_dropped_when_empty(self) -> None:
        """Empty string is the same wire shape as missing — key absent."""
        meta = _build(cohort_jql="")
        assert "cohort_jql" not in meta
        # Whitespace-only too.
        meta2 = _build(cohort_jql="   ")
        assert "cohort_jql" not in meta2

    def test_sources_sorted_lex(self) -> None:
        """Spec § "Outputs" line 492 + ``test_meta_sources_reflects_skills_called``.
        Build-time sort so the on-wire shape is obvious without relying
        on T10's defensive resort."""
        meta = _build(sources=["jira-align", "jira"])
        assert meta["sources"] == ["jira", "jira-align"]

    def test_metrics_requested_canonical_order(self) -> None:
        """Spec line 490-491: canonical --metrics enumeration order, not
        lex. Mirrors T10's ``test_meta_metrics_requested_canonical_order``."""
        meta = _build(metrics_requested=["wip", "throughput", "cycle_time"])
        assert meta["metrics_requested"] == ["cycle_time", "throughput", "wip"]

    def test_metrics_requested_dedupes_and_drops_unknown(self) -> None:
        """Same safety nets as T10's renderer: a metric repeated in the
        caller's list emits once; an unknown name (typo'd CLI flag that
        slipped past validation) is dropped so meta doesn't lie."""
        meta = _build(
            metrics_requested=["wip", "wip", "throughput", "made_up_metric"]
        )
        assert meta["metrics_requested"] == ["throughput", "wip"]

    def test_scope_passthrough(self) -> None:
        """``scope`` passes through as a dict — T1's argparse produces
        the right shape; build_meta doesn't re-shape it."""
        scope = {"project": "PROJ", "team": "Foo"}
        meta = _build(scope=scope)
        assert meta["scope"] == scope

    def test_window_from_window_object(self) -> None:
        """``window`` accepts a :class:`flow_metrics.Window` and
        renders ``{from, to}`` as ISO date strings."""
        from flow_metrics import Window

        win = Window(
            from_date=date(2026, 2, 19),
            to_date=date(2026, 5, 19),
            from_utc=datetime(2026, 2, 19, tzinfo=timezone.utc),
            to_exclusive_utc=datetime(2026, 5, 20, tzinfo=timezone.utc),
        )
        meta = _build(window=win)
        assert meta["window"] == {"from": "2026-02-19", "to": "2026-05-19"}

    def test_window_from_dict(self) -> None:
        meta = _build(window={"from": "2026-02-19", "to": "2026-05-19"})
        assert meta["window"] == {"from": "2026-02-19", "to": "2026-05-19"}

    def test_schema_version_pinned(self) -> None:
        meta = _build()
        assert meta["schema_version"] == SCHEMA_VERSION == "1.0"

    def test_generated_at_utc_z_suffix(self) -> None:
        """Spec example line 380: ``"generated_at": "2026-05-19T14:00:00Z"``.
        Both naive UTC and ``+00:00``-suffixed datetimes render with the
        ``Z`` suffix."""
        meta_aware = _build(
            generated_at=datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc)
        )
        assert meta_aware["generated_at"] == "2026-05-19T14:00:00Z"
        meta_naive = _build(generated_at=datetime(2026, 5, 19, 14, 0))
        assert meta_naive["generated_at"] == "2026-05-19T14:00:00Z"

    def test_per_team_double_counted_passthrough(self) -> None:
        meta = _build(per_team_double_counted=True)
        assert meta["per_team_double_counted"] is True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _build(**overrides):
    """Build a meta dict with sensible defaults; override individual
    fields per test. Keeps the per-test fixture noise minimal."""
    defaults = {
        "caller": "5b10ac8d82e05b22cc7d4ef5",
        "scope": {"project": "PROJ", "team": "Foo"},
        "window": {"from": "2026-02-19", "to": "2026-05-19"},
        "sources": ["jira"],
        "metrics_requested": [
            "cycle_time", "lead_time", "throughput", "wip", "flow_load",
            "rework_rate", "flow_time", "flow_efficiency",
            "flow_distribution", "defect_ratio",
        ],
        "state_config_sha": "abc",
        "issuetype_config_sha": "def",
        "generated_at": datetime(2026, 5, 19, 14, 0, tzinfo=timezone.utc),
        "per_team_double_counted": False,
    }
    defaults.update(overrides)
    return build_meta(**defaults)
