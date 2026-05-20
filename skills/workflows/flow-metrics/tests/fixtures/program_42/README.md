# program_42 — synthetic Jira + Jira Align fixture

Hand-authored. Exercises the program-scope code path:

1. Pipeline calls ``jira-align: raw GET programs/42/teams`` to enumerate
   teams.
2. Pipeline composes JQL ``"<align_join_field>" in (<team_ids>)`` and
   issues a single ``jira: search`` against it.
3. Pipeline drains per-issue changelogs and runs the standard
   aggregation + per_team rollup.

## Scenario

- **Program id:** `42`
- **Align join field:** `customfield_10001` (same field that carries the
  team name on Jira issues — keeps the fixture minimal).
- **Window:** `[2026-01-01, 2026-01-07]` inclusive.
- **Teams returned by Jira Align:** `Alpha`, `Beta`.

## Issues

| Key     | Type  | customfield_10001 | Pattern                          |
|---------|-------|-------------------|----------------------------------|
| PROG-1  | Story | Alpha             | Delivered: BL→IP→Done in window  |
| PROG-2  | Bug   | Beta              | Delivered: BL→IP→Done in window  |
| PROG-3  | Story | Alpha             | WIP-only: pre-window IP          |
| PROG-4  | Story | (missing)         | Delivered, exercises `(no team)` |

PROG-4's missing team field surfaces the field-level permission-undercount
notes line `per_team: 1 issues had no readable team_field value; bucketed
as '(no team)'`.

## Files

- `whoami.json` — caller identity.
- `align/programs_42_teams.json` — Jira Align response listing two teams.
- `search.jsonl` — Jira issue list (with inline changelogs).
- `golden.json` — expected canonical output. `meta.per_team_double_counted`
  is **false** (the default state config's `team_field.kind` is
  `single_value`). The companion `golden.array.json` covers the
  `team_field.kind: "array"` case and asserts the same field flips to
  **true** — together they exercise both branches.
- `state.array.json` — state config override that sets
  `team_field.kind = "array"`, otherwise identical to the shipped
  default.
- `golden.array.json` — expected output when run with
  `--state-config state.array.json`.
