"""T4 contract + construction tests for per-issue changelog pagination.

Covers every test enumerated in docs/specs/flow-metrics-plan.md § T4 and
the corresponding contract tests in docs/specs/flow-metrics.md
§ "Changelog pagination" / § "Changelog pagination (Cloud regression)".

The wrapper is tested in isolation against a stub :class:`_FakeJira` that
records every ``raw_get`` call and returns canned page payloads. No
``subprocess`` ever runs; T3's allowlist enforcement is exercised
indirectly (path goes through ``JiraClient.raw_get``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

from flow_metrics.changelog import ChangelogEntry, iter_issue_changelog


# ---------------------------------------------------------------------------
# Stub jira client
# ---------------------------------------------------------------------------
class _FakeJira:
    """Records every ``raw_get`` call; returns the next canned page.

    Acts as both ``JiraClient`` and a call-counter for tests that need
    to assert "no follow-up call was made" or check the exact
    ``params`` shape of the follow-up.
    """

    def __init__(self, pages: Optional[List[dict]] = None) -> None:
        self.calls: List[Dict[str, Any]] = []
        self._pages = list(pages or [])

    def raw_get(self, path: str, params: Optional[Mapping[str, str]] = None) -> Any:
        self.calls.append({"path": path, "params": dict(params or {})})
        if not self._pages:
            return {"histories": [], "isLast": True}
        return self._pages.pop(0)


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------
def _ts(year: int, month: int, day: int, hour: int = 12, *, offset: str = "+0000") -> str:
    """Build a Jira-shaped timestamp string. ``offset`` matches the raw
    no-colon shape Cloud emits (``+0000``, ``+0530``)."""
    return "{:04d}-{:02d}-{:02d}T{:02d}:00:00.000{}".format(year, month, day, hour, offset)


def _history(created: str, field: str, frm: str, to: str, *, author: str = "alice") -> dict:
    return {
        "id": "hist-{}-{}".format(field, created),
        "created": created,
        "author": {"displayName": author},
        "items": [{"field": field, "fromString": frm, "toString": to}],
    }


def _status_histories(n: int, *, start_day: int = 1, start_offset: int = 0) -> List[dict]:
    """``n`` status-transition history records on consecutive days.

    ``start_offset`` lets a fixture build a follow-up page that
    continues the day sequence from the previous page.
    """
    out = []
    for i in range(n):
        day = start_day + start_offset + i
        # Wrap through months so the day always remains valid; tests
        # only care that timestamps strictly increase.
        month, day_in_month = 1 + (day - 1) // 28, 1 + (day - 1) % 28
        if month > 12:
            month = 12
            day_in_month = 28
        out.append(
            _history(
                _ts(2026, month, day_in_month),
                "status",
                "S{}".format(start_offset + i),
                "S{}".format(start_offset + i + 1),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Contract tests (from spec)
# ---------------------------------------------------------------------------
def test_changelog_pagination_drained():
    """50 inline + 100 behind ``isLast: false``; follow-up drains all 150.

    Spec fixture: ``histories.length (50) < total (150)`` AND
    ``isLast: false``. Priority-order rule selects Server-style
    pagination (``startAt``), per the spec test's expected follow-up:
    ``raw GET issue/PROJ-1/changelog?startAt=50``.

    Pages are arranged so the chronologically earliest entry lives in
    a follow-up page (page 2), not in the inline 50. The "earliest of
    all 150, not the inline 50" assertion would pass vacuously if we
    placed the earliest in inline; this fixture makes the assertion
    load-bearing — it fails iff the follow-up wasn't drained.
    """
    # Inline: days 51..100 / values S50→S51 .. S99→S100 (middle slice).
    inline = {
        "histories": _status_histories(50, start_day=51, start_offset=50),
        "total": 150,
        "maxResults": 50,
        "startAt": 0,
        "isLast": False,
    }
    # Page 2 (fetched at startAt=50): days 1..50, S0→S1 .. S49→S50.
    # Contains the chronologically earliest entry.
    page_2 = {
        "histories": _status_histories(50, start_day=1, start_offset=0),
        "total": 150,
        "maxResults": 50,
        "startAt": 50,
        "isLast": False,
    }
    # Page 3 (fetched at startAt=100): days 101..150, S100→S101 .. S149→S150.
    page_3 = {
        "histories": _status_histories(50, start_day=101, start_offset=100),
        "total": 150,
        "maxResults": 50,
        "startAt": 100,
        "isLast": True,
    }
    jira = _FakeJira(pages=[page_2, page_3])

    entries = list(iter_issue_changelog(jira, "PROJ-1", inline))

    assert len(entries) == 150
    # First follow-up is exactly startAt=50, as the spec test asserts.
    assert jira.calls[0]["path"] == "issue/PROJ-1/changelog"
    assert jira.calls[0]["params"] == {"startAt": "50"}
    # Earliest is day 1 (S0 → S1), which lives in page 2. If the
    # follow-up wasn't drained, the earliest would be from the inline
    # slice (day 51, S50 → S51), and this assertion would fail.
    status_entries = [e for e in entries if e.field == "status"]
    earliest = min(status_entries, key=lambda e: e.timestamp)
    assert earliest.to_value == "S1", (
        "expected earliest from page 2 (S0->S1); got {} — follow-up not drained?".format(
            earliest.to_value
        )
    )
    # Every expected ``to_value`` from S1..S150 is present exactly once.
    to_values = sorted(e.to_value for e in status_entries)
    assert to_values == sorted("S{}".format(i) for i in range(1, 151))


def test_no_follow_up_when_changelog_complete():
    """10 inline entries with ``isLast: true`` → zero ``raw_get`` calls."""
    inline = {
        "histories": _status_histories(10),
        "total": 10,
        "isLast": True,
    }
    jira = _FakeJira()
    entries = list(iter_issue_changelog(jira, "PROJ-2", inline))
    assert len(entries) == 10
    assert jira.calls == []


# ---------------------------------------------------------------------------
# Construction tests (from plan)
# ---------------------------------------------------------------------------
def test_changelog_pagination_cloud_format():
    """Cloud shape: ``isLast`` / ``nextPageToken`` → paginate with ``pageToken``."""
    inline = {
        "histories": _status_histories(3),
        "isLast": False,
        "nextPageToken": "tok-1",
    }
    page_2 = {
        "histories": _status_histories(3, start_offset=3),
        "isLast": False,
        "nextPageToken": "tok-2",
    }
    page_3 = {
        "histories": _status_histories(2, start_offset=6),
        "isLast": True,
    }
    jira = _FakeJira(pages=[page_2, page_3])

    entries = list(iter_issue_changelog(jira, "PROJ-3", inline))

    assert len(entries) == 8
    # Each follow-up uses ``pageToken`` (not ``startAt``).
    assert jira.calls[0]["params"] == {"pageToken": "tok-1"}
    assert jira.calls[1]["params"] == {"pageToken": "tok-2"}
    assert len(jira.calls) == 2


def test_changelog_pagination_server_format():
    """Server shape: ``total`` vs ``histories.length`` → paginate with ``startAt``.

    No ``isLast`` / ``nextPageToken`` on the envelope; only ``total``.
    """
    inline = {
        "histories": _status_histories(2),
        "total": 5,
        "maxResults": 2,
        "startAt": 0,
    }
    page_2 = {
        "histories": _status_histories(2, start_offset=2),
        "total": 5,
        "maxResults": 2,
        "startAt": 2,
    }
    page_3 = {
        "histories": _status_histories(1, start_offset=4),
        "total": 5,
        "maxResults": 2,
        "startAt": 4,
    }
    jira = _FakeJira(pages=[page_2, page_3])

    entries = list(iter_issue_changelog(jira, "PROJ-4", inline))

    assert len(entries) == 5
    assert jira.calls[0]["params"] == {"startAt": "2"}
    assert jira.calls[1]["params"] == {"startAt": "4"}
    assert len(jira.calls) == 2


def test_changelog_pagination_memory_bounded():
    """5000 transitions paginated; pages fetched lazily, not pre-buffered.

    Verifies the load-bearing perf guarantee: the walker yields each
    entry as it goes, and the next page isn't requested until the
    previous page's entries are consumed.
    """
    page_size = 100
    total_pages = 50  # 50 pages of 100 = 5000 entries

    pages: List[dict] = []
    for p in range(1, total_pages):
        pages.append(
            {
                "histories": _status_histories(page_size, start_offset=p * page_size),
                "total": page_size * total_pages,
                "maxResults": page_size,
                "startAt": p * page_size,
                "isLast": (p == total_pages - 1),
            }
        )

    inline = {
        "histories": _status_histories(page_size, start_offset=0),
        "total": page_size * total_pages,
        "maxResults": page_size,
        "startAt": 0,
        "isLast": False,
    }

    jira = _FakeJira(pages=pages)
    it = iter_issue_changelog(jira, "PROJ-5", inline)

    # Consume only the first 50 entries (less than one page worth
    # beyond inline). The walker must NOT have eagerly fetched all
    # subsequent pages. Zero follow-up calls expected so far — the
    # inline page alone has 100 entries.
    for _ in range(50):
        next(it)
    assert len(jira.calls) == 0, (
        "iterator pre-fetched follow-up pages before consuming inline"
    )

    # Consume past the inline page; exactly one follow-up call should
    # fire (lazy pagination, one page at a time).
    for _ in range(100):
        next(it)
    assert len(jira.calls) == 1, (
        "iterator fetched more than one follow-up page after crossing one boundary"
    )

    # Drain the rest; total entries == 5000; total follow-ups == 49.
    rest = list(it)
    assert 50 + 100 + len(rest) == 5000
    assert len(jira.calls) == total_pages - 1


def test_changelog_pagination_handles_empty_histories():
    """Issue with no changelog entries → empty iterator, not None, no error."""
    jira = _FakeJira()
    # Empty envelope: no histories, no signals → no pagination.
    assert list(iter_issue_changelog(jira, "PROJ-6", {"histories": []})) == []
    assert list(iter_issue_changelog(jira, "PROJ-6", {})) == []
    assert jira.calls == []


def test_changelog_filters_to_status_and_issuetype():
    """Only ``status`` / ``issuetype`` items survive; others filtered out."""
    inline = {
        "histories": [
            {
                "id": "h1",
                "created": _ts(2026, 1, 1),
                "author": {"displayName": "alice"},
                "items": [
                    {"field": "status", "fromString": "A", "toString": "B"},
                    {"field": "assignee", "fromString": "x", "toString": "y"},
                    {"field": "issuetype", "fromString": "Story", "toString": "Bug"},
                    {"field": "labels", "fromString": "", "toString": "urgent"},
                    {"field": "Custom_Field", "fromString": "1", "toString": "2"},
                ],
            }
        ],
        "isLast": True,
    }
    jira = _FakeJira()
    entries = list(iter_issue_changelog(jira, "PROJ-7", inline))
    assert {e.field for e in entries} == {"status", "issuetype"}
    assert len(entries) == 2


def test_changelog_timestamps_are_utc():
    """Mixed ``+0000`` / ``+0530`` / no-offset inputs all yield UTC instants
    with the absolute instant preserved.
    """
    inline = {
        "histories": [
            _history(_ts(2026, 1, 1, 12, offset="+0000"), "status", "A", "B"),
            _history(_ts(2026, 1, 1, 12, offset="+0530"), "status", "B", "C"),
            # No-offset shape (older Server). Build manually since
            # ``_ts`` always appends an offset.
            {
                "id": "h-no-offset",
                "created": "2026-01-01T12:00:00.000",
                "author": {"displayName": "alice"},
                "items": [{"field": "status", "fromString": "C", "toString": "D"}],
            },
        ],
        "isLast": True,
    }
    jira = _FakeJira()
    entries = list(iter_issue_changelog(jira, "PROJ-8", inline))
    assert len(entries) == 3
    for e in entries:
        # Spec-allowed: ``timezone.utc`` or any tzinfo with zero offset.
        assert e.timestamp.tzinfo is not None
        assert e.timestamp.utcoffset() == timezone.utc.utcoffset(None)

    # Absolute instants preserved: +0530 12:00 == 06:30 UTC.
    by_to = {e.to_value: e.timestamp for e in entries}
    assert by_to["B"] == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)
    assert by_to["C"] == datetime(2026, 1, 1, 6, 30, tzinfo=timezone.utc)
    # No-offset interpreted as UTC, per spec § Decisions (UTC throughout).
    assert by_to["D"] == datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Construction edge cases
# ---------------------------------------------------------------------------
def test_iter_issue_changelog_accepts_bare_list():
    """The plan documents the param as ``list[dict]``; bare-list inputs
    are tolerated (treated as complete, unpaginated changelog).
    """
    histories = _status_histories(3)
    jira = _FakeJira()
    entries = list(iter_issue_changelog(jira, "PROJ-9", histories))
    assert len(entries) == 3
    assert jira.calls == []


def test_iter_issue_changelog_handles_missing_author():
    """Histories with no ``author`` block yield an empty author string,
    not ``None`` (keeps the dataclass field strictly typed).
    """
    inline = {
        "histories": [
            {
                "id": "h-no-author",
                "created": _ts(2026, 1, 1),
                "items": [{"field": "status", "fromString": "A", "toString": "B"}],
            }
        ],
        "isLast": True,
    }
    jira = _FakeJira()
    entries = list(iter_issue_changelog(jira, "PROJ-10", inline))
    assert len(entries) == 1
    assert entries[0].author == ""


def test_iter_issue_changelog_history_with_multiple_kept_items():
    """A single history record with both a status AND an issuetype item
    yields two entries with the same timestamp.
    """
    inline = {
        "histories": [
            {
                "id": "h-multi",
                "created": _ts(2026, 2, 1),
                "author": {"displayName": "bob"},
                "items": [
                    {"field": "status", "fromString": "A", "toString": "B"},
                    {"field": "issuetype", "fromString": "Story", "toString": "Bug"},
                ],
            }
        ],
        "isLast": True,
    }
    jira = _FakeJira()
    entries = list(iter_issue_changelog(jira, "PROJ-11", inline))
    assert len(entries) == 2
    assert {e.field for e in entries} == {"status", "issuetype"}
    assert entries[0].timestamp == entries[1].timestamp


def test_pagination_uses_allowed_raw_get_path():
    """Every follow-up call targets ``issue/<KEY>/changelog`` — the
    pattern T3's allowlist permits.
    """
    inline = {
        "histories": _status_histories(2),
        "total": 4,
        "isLast": False,
    }
    page_2 = {"histories": _status_histories(2, start_offset=2), "total": 4, "isLast": True}
    jira = _FakeJira(pages=[page_2])
    list(iter_issue_changelog(jira, "ABC-123", inline))
    for call in jira.calls:
        assert call["path"] == "issue/ABC-123/changelog"
