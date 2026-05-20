# smoke_real_team — synthetic stand-in for a real-team fixture

**The brief asks for a real team's anonymised fixture.** None was
provided in this PR, so this directory ships a hand-crafted synthetic
fixture sized like a real team's monthly cadence (14 in-scope issues,
28-day window) with hand-computable percentiles.

The test in ``tests/test_smoke_real_team.py`` runs against this fixture
and asserts every contract metric lands within ±1% of the hand-
computed reference in ``reference_values.json``. When the user supplies
a real-team fixture, drop it in this directory (overwriting these
files) — the test logic is fixture-driven and needs no code changes.

## Scenario

- **Project:** `PROJ`
- **Window:** `[2026-02-01, 2026-02-28]` inclusive (28 days)
- **Team:** all 14 issues are on team `Atlas` (single team; the smoke
  test targets the project-scope aggregate, not the per-team rollup)
- **State / issuetype config:** shipped defaults

## Issues

10 fast-to-medium delivered Stories / Bugs with clean cycle-time
values, plus four edge-case issues that the spec calls out:

| Key       | Type  | Cycle (h) | Lead (h) | Notes                          |
|-----------|-------|-----------|----------|--------------------------------|
| PROJ-001  | Story | 12        | 24       | Direct BL→IP→Done              |
| PROJ-002  | Story | 18        | 30       | Direct BL→IP→Done              |
| PROJ-003  | Bug   | 24        | 36       | Direct BL→IP→Done              |
| PROJ-004  | Story | 36        | 48       | Direct BL→IP→Done              |
| PROJ-005  | Bug   | 48        | 60       | Direct BL→IP→Done              |
| PROJ-006  | Story | 60        | 72       | Direct BL→IP→Done              |
| PROJ-007  | Story | 72        | 84       | Direct BL→IP→Done              |
| PROJ-008  | Bug   | 96        | 108      | Direct BL→IP→Done              |
| PROJ-009  | Story | 120       | 132      | Direct BL→IP→Done              |
| PROJ-010  | Story | 144       | 156      | Direct BL→IP→Done              |
| PROJ-011  | Story | 48        | 60       | Rework (IP→BL→IP→Done, 1 edge) |
| PROJ-012  | Bug   | —         | 24       | Skipped commitment (BL→Done)   |
| PROJ-013  | Story | —         | —        | Cancelled in-window            |
| PROJ-014  | Story | —         | —        | WIP-only (pre-window IP)       |

## Files

- ``whoami.json`` — caller identity (sanitized: ``smoke-account-001``).
- ``search.jsonl`` — issue payloads with inline changelogs. Generated
  by ``_build_smoke.py`` from a tabular spec; re-run the generator
  after editing timestamps.
- ``invocation.json`` — exact CLI argv the smoke test invokes
  (``--project PROJ --from 2026-02-01 --to 2026-02-28``).
- ``reference_values.json`` — hand-computed contract metrics. Derived
  step-by-step in ``SHOW_YOUR_WORK.md``.
- ``SHOW_YOUR_WORK.md`` — line-by-line derivation of every reference
  number, including the ``statistics.quantiles(method="exclusive")``
  arithmetic so a reviewer can verify the percentiles without running
  the implementation.

## Replacing with a real-team fixture

When you have anonymised real-team data ready:

1. Replace ``search.jsonl`` with the real (anonymised) issues. Strip
   ``displayName``, ``name``, ``accountId`` everywhere; replace
   issue keys with ``PROJ-001`` … ``PROJ-NNN``.
2. Rewrite ``reference_values.json`` and ``SHOW_YOUR_WORK.md`` against
   the new data — the reference must come from the same data the test
   runs (spec § "Validation step before claiming done").
3. Update ``invocation.json`` if the project key / window changes.
4. Delete this synthetic scaffolding section from the README.
