"""Generates the smoke_real_team fixture from a compact tabular spec.

Re-run after editing the ISSUES table or timing constants below. The
output (``search.jsonl``) is checked in alongside the generator so the
fixture is auditable without running this script — the generator only
exists to keep the per-issue JSON consistent under edits.

Stdlib only.
"""
from __future__ import annotations

import json
from pathlib import Path


HERE = Path(__file__).resolve().parent


# (key, issuetype_name, created_iso, [(transition_iso, fromStatus, toStatus), ...])
# Times chosen so cycle / lead values land on integer hours and percentiles
# land on round numbers — see SHOW_YOUR_WORK.md for the arithmetic.
ISSUES = [
    # 10 cycle-eligible delivered issues with cycle ∈ {12, 18, 24, 36, 48,
    # 60, 72, 96, 120, 144} and lead = cycle + 12.
    ("PROJ-001", "Story", "2026-02-02T00:00:00.000+0000", [
        ("2026-02-02T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-03T00:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-002", "Story", "2026-02-03T00:00:00.000+0000", [
        ("2026-02-03T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-04T06:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-003", "Bug", "2026-02-04T00:00:00.000+0000", [
        ("2026-02-04T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-05T12:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-004", "Story", "2026-02-05T00:00:00.000+0000", [
        ("2026-02-05T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-07T00:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-005", "Bug", "2026-02-06T00:00:00.000+0000", [
        ("2026-02-06T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-08T12:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-006", "Story", "2026-02-07T00:00:00.000+0000", [
        ("2026-02-07T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-10T00:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-007", "Story", "2026-02-08T00:00:00.000+0000", [
        ("2026-02-08T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-11T12:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-008", "Bug", "2026-02-10T00:00:00.000+0000", [
        ("2026-02-10T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-14T12:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-009", "Story", "2026-02-12T00:00:00.000+0000", [
        ("2026-02-12T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-17T12:00:00.000+0000", "In Progress", "Done"),
    ]),
    ("PROJ-010", "Story", "2026-02-15T00:00:00.000+0000", [
        ("2026-02-15T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-21T12:00:00.000+0000", "In Progress", "Done"),
    ]),
    # PROJ-011: rework — IP→BL is a "from in_progress to backlog" rework
    # signal in the default state config. The edge fires at
    # 2026-02-16T00:00:00Z, which is ≤ first_delivery_at — so
    # rework_count = 1. cycle = first_commit (02-15T12) → first_delivery
    # (02-17T12) = 48h. flow_efficiency = active(42h) / total(48h) = 0.875.
    ("PROJ-011", "Story", "2026-02-15T00:00:00.000+0000", [
        ("2026-02-15T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-16T00:00:00.000+0000", "In Progress", "Backlog"),
        ("2026-02-16T06:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-17T12:00:00.000+0000", "In Progress", "Done"),
    ]),
    # PROJ-012: skipped commitment — BL→Done direct. Counts toward
    # throughput, lead_time, defect_ratio; NOT cycle / flow_efficiency.
    ("PROJ-012", "Bug", "2026-02-19T00:00:00.000+0000", [
        ("2026-02-20T00:00:00.000+0000", "Backlog", "Done"),
    ]),
    # PROJ-013: cancelled-in-window.
    ("PROJ-013", "Story", "2026-02-22T00:00:00.000+0000", [
        ("2026-02-22T12:00:00.000+0000", "Backlog", "In Progress"),
        ("2026-02-23T00:00:00.000+0000", "In Progress", "Cancelled"),
    ]),
    # PROJ-014: WIP-only — pre-window IP, still IP at --to.
    ("PROJ-014", "Story", "2026-01-15T00:00:00.000+0000", [
        ("2026-01-20T00:00:00.000+0000", "Backlog", "In Progress"),
    ]),
]


def _build_issue(key: str, itype: str, created: str, transitions: list) -> dict:
    histories = []
    for i, (ts, from_s, to_s) in enumerate(transitions):
        histories.append({
            "id": "{}-{}".format(key, i + 1),
            "created": ts,
            "author": {"displayName": "smoke-user"},
            "items": [{"field": "status", "fromString": from_s, "toString": to_s}],
        })
    # Final status = "to_s" of the last transition, or "Backlog" if none.
    final_status = transitions[-1][2] if transitions else "Backlog"
    return {
        "key": key,
        "fields": {
            "created": created,
            "status": {"name": final_status},
            "issuetype": {"name": itype},
            "customfield_10001": "Atlas",
        },
        "changelog": {"histories": histories},
    }


def main() -> None:
    out_path = HERE / "search.jsonl"
    lines = []
    for record in ISSUES:
        issue = _build_issue(*record)
        lines.append(json.dumps(issue))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
