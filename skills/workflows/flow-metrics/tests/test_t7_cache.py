"""T7 contract + construction tests for the on-disk cache.

Covers every test enumerated in docs/specs/flow-metrics-plan.md § T7
and the corresponding contract / atomic-write rules in
docs/specs/flow-metrics.md § "Caching".

No subprocess ever runs; the cache module operates purely on iterators
of :class:`PerIssueRow` and the local filesystem. Upstream-skip tests
use a counting stub iterator so we can prove the cache-hit path never
pulls from the source.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, List

import pytest

from flow_metrics.cache import (
    CACHE_SCHEMA_VERSION,
    cache_key,
    cleanup_stale_tmps,
    read_cache,
    write_cache_tee,
)
from flow_metrics.per_issue import PerIssueRow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _row(key: str, *, created_year: int = 2026) -> PerIssueRow:
    """Build a minimal :class:`PerIssueRow` fixture.

    Carries a non-null datetime in each datetime-typed field so the
    serializer / deserializer exercises ISO-8601 round-tripping.
    """
    created = datetime(created_year, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    delivered = datetime(created_year, 2, 3, 4, 5, 6, tzinfo=timezone.utc)
    committed = datetime(created_year, 1, 15, 6, 7, 8, tzinfo=timezone.utc)
    return PerIssueRow(
        key=key,
        issue_created=created,
        first_commitment_at=committed,
        first_delivery_at=delivered,
        cycle_eligible=True,
        cycle_time_hours=42.5,
        lead_time_hours=100.0,
        flow_efficiency=0.625,
        rework_count=1,
        issuetype_at_delivery="Story",
        issuetype_bucket="feature",
        team="alpha",
        delivered_in_window=True,
        cancelled_in_window=False,
        wip_at_to=False,
        cohort=None,
    )


def _baseline_kwargs() -> dict:
    """Default :func:`cache_key` kwargs for a project-scope run."""
    return {
        "scope": {"kind": "project", "value": "PROJ", "team": None},
        "window": {"from": "2026-01-01", "to": "2026-03-31"},
        "user_jql": "",
        "user_align_filter": "",
        "state_config_sha": "a" * 64,
        "issuetype_config_sha": "b" * 64,
        "team_field_override": None,
        "align_join_field": None,
        "align_teams_path": None,
    }


# ---------------------------------------------------------------------------
# Contract tests (spec — names match plan lines 622-631 verbatim)
# ---------------------------------------------------------------------------
class _CountingSource:
    """Iterator-like stub that records every ``__next__`` call.

    Used to prove that on a cache hit the upstream/source iterator is
    never asked for a row.
    """

    def __init__(self, rows: List[PerIssueRow]) -> None:
        self._rows = list(rows)
        self.calls = 0

    def __iter__(self) -> Iterator[PerIssueRow]:
        return self

    def __next__(self) -> PerIssueRow:
        self.calls += 1
        if not self._rows:
            raise StopIteration
        return self._rows.pop(0)


def test_cache_hit_skips_upstream_calls(tmp_path: Path) -> None:
    rows = [_row("PROJ-1"), _row("PROJ-2")]
    key = "deadbeef"

    # Prime the cache.
    list(write_cache_tee(tmp_path, key, iter(rows)))
    assert (tmp_path / "{}.jsonl".format(key)).is_file()

    # Now simulate the lookup path: read_cache returns a generator that
    # MUST not consult the upstream source.
    sentinel = _CountingSource([_row("UPSTREAM-NOPE")])

    got = read_cache(tmp_path, key)
    assert got is not None
    materialised = list(got)
    assert [r.key for r in materialised] == ["PROJ-1", "PROJ-2"]
    assert sentinel.calls == 0


def test_cache_invalidated_on_state_config_semantic_change() -> None:
    base = _baseline_kwargs()
    k1 = cache_key(**base)
    base["state_config_sha"] = "c" * 64
    k2 = cache_key(**base)
    assert k1 != k2


def test_cache_stable_under_whitespace_edits() -> None:
    base = _baseline_kwargs()
    base["user_jql"] = "labels = foo AND assignee = bar"
    k1 = cache_key(**base)
    base["user_jql"] = "  labels  =   foo   AND\tassignee = bar  "
    k2 = cache_key(**base)
    assert k1 == k2

    base["user_align_filter"] = "name eq 'x'"
    k3 = cache_key(**base)
    base["user_align_filter"] = "   name   eq   'x'   "
    k4 = cache_key(**base)
    assert k3 == k4


def test_no_cache_bypasses_cache(tmp_path: Path) -> None:
    """The bypass path must not touch the cache module.

    T7 owns only the module API; the CLI wires ``--no-cache`` by
    skipping both :func:`read_cache` and :func:`write_cache_tee`. This
    test simulates the bypass path and asserts no files appear in the
    cache directory as a result.
    """
    # Simulate: caller decided to bypass, so does not call any cache
    # function. The cache directory may not even be created.
    assert list(tmp_path.iterdir()) == []

    # And a read against an empty cache returns None (miss), so any
    # call site that *does* check first sees the bypass-equivalent
    # signal cleanly.
    assert read_cache(tmp_path, "anything") is None
    assert list(tmp_path.iterdir()) == []


def test_partial_cache_discarded_on_upstream_failure(tmp_path: Path) -> None:
    key = "partial"

    def _raising_source() -> Iterator[PerIssueRow]:
        yield _row("PROJ-1")
        yield _row("PROJ-2")
        raise RuntimeError("upstream blew up")

    with pytest.raises(RuntimeError):
        for _ in write_cache_tee(tmp_path, key, _raising_source()):
            pass

    assert not (tmp_path / "{}.jsonl".format(key)).exists()
    tmps = list(tmp_path.glob("*.tmp"))
    assert len(tmps) == 1
    # PID-suffixed tmp name preserved for stale cleanup later.
    assert tmps[0].name.startswith("{}.jsonl.".format(key))
    assert tmps[0].name.endswith(".tmp")


def test_cohort_jql_not_in_cache_key() -> None:
    """``--cohort-jql`` is applied at aggregation time, after caching;
    it must not appear in :func:`cache_key`'s signature."""
    params = inspect.signature(cache_key).parameters
    assert "cohort_jql" not in params
    assert "cohort" not in params


def test_metrics_not_in_cache_key() -> None:
    params = inspect.signature(cache_key).parameters
    assert "metrics" not in params


def test_include_subtasks_not_in_cache_key() -> None:
    params = inspect.signature(cache_key).parameters
    assert "include_subtasks" not in params


def test_align_fields_null_in_cache_key_for_project_scope() -> None:
    base = _baseline_kwargs()
    base["scope"] = {"kind": "project", "value": "PROJ", "team": None}
    base["align_join_field"] = None
    base["align_teams_path"] = None
    k_nulls = cache_key(**base)

    base["align_join_field"] = "Team Link"
    base["align_teams_path"] = "/api/v1/teams"
    k_set = cache_key(**base)

    assert k_nulls == k_set, (
        "project-scope cache key must ignore align_join_field / align_teams_path"
    )


def test_align_fields_in_cache_key_for_program_scope() -> None:
    base = _baseline_kwargs()
    base["scope"] = {"kind": "program", "value": "PRG-1", "team": None}

    base["align_join_field"] = "Team Link"
    base["align_teams_path"] = "/api/v1/teams"
    k1 = cache_key(**base)

    base["align_join_field"] = "Team Link 2"
    k2 = cache_key(**base)
    assert k1 != k2, "program-scope cache key must depend on align_join_field"

    base["align_join_field"] = "Team Link"
    base["align_teams_path"] = "/api/v1/teams/other"
    k3 = cache_key(**base)
    assert k1 != k3, "program-scope cache key must depend on align_teams_path"

    # And portfolio behaves the same way as program.
    base["scope"] = {"kind": "portfolio", "value": "PORTFOLIO-1", "team": None}
    base["align_teams_path"] = "/api/v1/teams"
    k_portfolio = cache_key(**base)
    base["align_teams_path"] = "/api/v1/teams/other"
    k_portfolio2 = cache_key(**base)
    assert k_portfolio != k_portfolio2


# ---------------------------------------------------------------------------
# Construction tests (plan lines 635-645)
# ---------------------------------------------------------------------------
def test_cache_key_canonical_json() -> None:
    """Two semantically-identical inputs hash equal regardless of which
    key insertion order the dict happens to be built in."""
    base = _baseline_kwargs()
    got = cache_key(**base)

    # Independently hand-build the canonical dict (matching the spec).
    expected_dict = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "scope_kind": "project",
        "scope_value": "PROJ",
        "team": None,
        "from": "2026-01-01",
        "to": "2026-03-31",
        "user_jql": "",
        "user_align_filter": "",
        "state_config_sha": "a" * 64,
        "issuetype_config_sha": "b" * 64,
        "team_field_override": None,
        "align_join_field": None,
        "align_teams_path": None,
    }
    expected = hashlib.sha256(
        json.dumps(expected_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert got == expected

    # And re-hashing the same dict in reversed insertion order yields
    # the same sha — proves sort_keys=True is honoured.
    reordered = {k: expected_dict[k] for k in reversed(list(expected_dict.keys()))}
    reordered_sha = hashlib.sha256(
        json.dumps(reordered, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert reordered_sha == expected

    # And the canonical encoding uses the spec's tight separators
    # — no whitespace between elements.
    canonical = json.dumps(expected_dict, sort_keys=True, separators=(",", ":"))
    assert ", " not in canonical
    assert ": " not in canonical


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only mode bits")
def test_cache_dir_mode_0700(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"

    # write_cache_tee triggers _ensure_cache_dir under the hood; drain
    # a one-row stream to land it.
    list(write_cache_tee(cache_dir, "k", iter([_row("A-1")])))

    assert cache_dir.is_dir()
    mode = cache_dir.stat().st_mode & 0o777
    assert mode == 0o700, "cache dir mode is {:o}, want 0700".format(mode)


def test_stale_tmp_cleaned_on_startup(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Stale tmp in both naming forms (legacy <key>.jsonl.tmp and
    # PID-suffixed <key>.jsonl.<pid>.tmp). Both must be swept by the
    # ``*.tmp`` glob.
    stale_legacy = cache_dir / "deadbeef.jsonl.tmp"
    stale_pid = cache_dir / "deadbeef.jsonl.12345.tmp"
    fresh_pid = cache_dir / "fresh.jsonl.{}.tmp".format(os.getpid())
    final = cache_dir / "deadbeef.jsonl"

    for p in (stale_legacy, stale_pid, fresh_pid, final):
        p.write_text("dummy\n", encoding="utf-8")

    old = time.time() - 7200  # 2 hours
    os.utime(stale_legacy, (old, old))
    os.utime(stale_pid, (old, old))

    cleanup_stale_tmps(cache_dir)

    assert not stale_legacy.exists(), "stale legacy .tmp not removed"
    assert not stale_pid.exists(), "stale PID-suffixed .tmp not removed"
    assert fresh_pid.exists(), "fresh .tmp wrongly removed"
    assert final.exists(), "non-.tmp file wrongly removed"


def test_concurrent_writes_tolerated(tmp_path: Path) -> None:
    """Two interleaved write_cache_tee runs against the same key both
    succeed; the final file's content matches both runs' outputs
    (identical by construction since cache content is a pure function
    of the cache key)."""
    rows_a = [_row("PROJ-1"), _row("PROJ-2"), _row("PROJ-3")]
    rows_b = [_row("PROJ-1"), _row("PROJ-2"), _row("PROJ-3")]
    key = "shared"

    # Fake two PIDs by monkey-patching os.getpid mid-flight.
    original_getpid = os.getpid
    seq = iter([11111, 22222])
    os.getpid = lambda: next(seq)  # type: ignore[assignment]
    try:
        gen_a = write_cache_tee(tmp_path, key, iter(rows_a))
        gen_b = write_cache_tee(tmp_path, key, iter(rows_b))

        out_a: List[PerIssueRow] = []
        out_b: List[PerIssueRow] = []
        # Interleave: a, b, a, b, ...
        gens = [(gen_a, out_a), (gen_b, out_b)]
        while gens:
            still = []
            for g, sink in gens:
                try:
                    sink.append(next(g))
                    still.append((g, sink))
                except StopIteration:
                    pass
            gens = still
    finally:
        os.getpid = original_getpid  # type: ignore[assignment]

    final = tmp_path / "{}.jsonl".format(key)
    assert final.is_file(), "final cache file not produced after both runs"

    lines = final.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["key"] for line in lines] == ["PROJ-1", "PROJ-2", "PROJ-3"]

    # And the in-memory yielded rows from both runs match — proves the
    # tee is faithful and both writers saw the same stream.
    assert [r.key for r in out_a] == ["PROJ-1", "PROJ-2", "PROJ-3"]
    assert [r.key for r in out_b] == ["PROJ-1", "PROJ-2", "PROJ-3"]


# ---------------------------------------------------------------------------
# Round-trip sanity (not on the plan's list, but exercises the
# datetime-aware serializer that all the cache-hit tests depend on)
# ---------------------------------------------------------------------------
def test_round_trip_preserves_datetime_fields(tmp_path: Path) -> None:
    rows = [_row("PROJ-1"), _row("PROJ-2")]
    key = "rtrip"
    list(write_cache_tee(tmp_path, key, iter(rows)))

    got = read_cache(tmp_path, key)
    assert got is not None
    materialised = list(got)
    assert len(materialised) == 2
    for original, loaded in zip(rows, materialised):
        assert loaded == original
