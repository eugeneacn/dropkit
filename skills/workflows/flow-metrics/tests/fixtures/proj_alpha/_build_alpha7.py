"""Generates the >200-changelog-entry fixture pieces for ALPHA-7.

The Cloud changelog-pagination regression (spec § Edge cases — Changelog
pagination) requires draining via ``jira: raw GET issue/<KEY>/changelog``
when the inline page reports more entries available. ALPHA-7's fixture
exercises that: 100 entries inline + 100 on page ``p2`` + 50 on page ``p3``
= 250 total, with two real status transitions buried inline and the rest
filler ``assignee`` items (which the changelog walker drops via the
``_KEPT_FIELDS = {"status", "issuetype"}`` filter).

This generator is hand-edited; the integration tests run the generated
output, never the generator. Re-run after editing the timing of ALPHA-7's
real transitions or the page sizes:

    python tests/fixtures/proj_alpha/_build_alpha7.py
"""
from __future__ import annotations

import json
from pathlib import Path


FIXTURE_DIR = Path(__file__).resolve().parent
CHANGELOG_DIR = FIXTURE_DIR / "changelog"


# ALPHA-7: Story, team "Foo", created 2025-12-30. Two real transitions:
#   2026-01-02T10:00:00Z  Backlog -> In Progress
#   2026-01-05T10:00:00Z  In Progress -> Done
# Cycle = 72h. Lead = 2025-12-30T10:00 → 2026-01-05T10:00 = 144h.
# Rework = 0.

_REAL_TRANSITIONS = [
    {
        "id": "7001",
        "created": "2026-01-02T10:00:00.000+0000",
        "author": {"displayName": "u7"},
        "items": [{"field": "status", "fromString": "Backlog", "toString": "In Progress"}],
    },
    {
        "id": "7002",
        "created": "2026-01-05T10:00:00.000+0000",
        "author": {"displayName": "u7"},
        "items": [{"field": "status", "fromString": "In Progress", "toString": "Done"}],
    },
]


def _filler(idx: int, day: str) -> dict:
    """One filler 'assignee' history record — kept-field filter drops it."""
    return {
        "id": "7{:04d}".format(idx),
        "created": "2026-01-{}T08:00:00.000+0000".format(day),
        "author": {"displayName": "u7"},
        "items": [{"field": "assignee", "fromString": "alice", "toString": "bob"}],
    }


def main() -> None:
    # Inline page (returned with the parent ``jira: search ... --expand changelog``):
    # 100 entries (2 real + 98 filler), nextPageToken=p2, isLast=false.
    inline_filler = [_filler(i, "06") for i in range(98)]
    inline_histories = _REAL_TRANSITIONS + inline_filler

    # Page p2 — 100 filler.
    p2_histories = [_filler(100 + i, "06") for i in range(100)]
    # Page p3 — 50 filler, isLast=true.
    p3_histories = [_filler(200 + i, "06") for i in range(50)]

    # Update the search.jsonl entry for ALPHA-7 — overwrites any prior line.
    alpha7_record = {
        "key": "ALPHA-7",
        "fields": {
            "created": "2025-12-30T10:00:00.000+0000",
            "status": {"name": "Done"},
            "issuetype": {"name": "Story"},
            "customfield_10001": "Foo",
        },
        "changelog": {
            "histories": inline_histories,
            "nextPageToken": "p2",
            "isLast": False,
        },
    }

    search_path = FIXTURE_DIR / "search.jsonl"
    lines = []
    if search_path.is_file():
        for ln in search_path.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            obj = json.loads(ln)
            if obj.get("key") == "ALPHA-7":
                continue
            lines.append(json.dumps(obj))
    lines.append(json.dumps(alpha7_record))
    search_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    CHANGELOG_DIR.mkdir(parents=True, exist_ok=True)
    (CHANGELOG_DIR / "ALPHA-7.p2.json").write_text(
        json.dumps({"histories": p2_histories, "nextPageToken": "p3", "isLast": False}),
        encoding="utf-8",
    )
    (CHANGELOG_DIR / "ALPHA-7.p3.json").write_text(
        json.dumps({"histories": p3_histories, "isLast": True}),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
