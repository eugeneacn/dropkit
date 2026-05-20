# proj_alpha — synthetic Jira fixture

Hand-authored. **Not** recorded from a real Jira instance — no real
account ids, no real issue keys, no real assignee names.

## Scenario

- **Project key:** `ALPHA`
- **Window:** `[2026-01-01, 2026-01-07]` inclusive (7 days)
- **Team field:** `customfield_10001` (single_value, default config)
- **State / issuetype config:** shipped defaults (`references/states.default.json`,
  `references/issuetypes.default.json`).

## Issues

| Key       | Type  | Team | Pattern                                                            |
|-----------|-------|------|--------------------------------------------------------------------|
| ALPHA-1   | Story | Foo  | Standard delivered: BL→IP@2026-01-02T09→Done@2026-01-04T09         |
| ALPHA-2   | Story | Bar  | Wait-state: BL→IP@2026-01-02T12→IR@2026-01-03T18→Done@2026-01-05T12 |
| ALPHA-3   | Bug   | Foo  | Rework: BL→IP→BL→IP→Done within window (one rework edge pre-delivery)|
| ALPHA-4   | Story | Foo  | WIP-only: pre-window IP, never delivered                           |
| ALPHA-5   | Story | Bar  | Cancelled-in-window: 2026-01-03T15 IP→Cancelled                    |
| ALPHA-6   | Bug   | Bar  | Skipped commitment: BL→Done@2026-01-02T10 (no IP transition)       |
| ALPHA-7   | Story | Foo  | Cloud-pagination case: >200 changelog entries, paginated drain     |

ALPHA-7 exercises the T4 Cloud changelog regression — its inline
changelog returns 100 entries plus `nextPageToken: "p2"`, and two
follow-up pages drain the rest. The state transitions that matter for
metrics live in the inline page; the follow-up pages are filler
status-flip noise that doesn't change cycle/lead/rework.

## Files

- `search.jsonl` — line-delimited issue payloads (the parent
  `jira: search` response).
- `changelog/ALPHA-7.p2.json`, `changelog/ALPHA-7.p3.json` — the two
  follow-up pages for ALPHA-7's pagination drain.
- `whoami.json` — `{"accountId": "test-account-alpha"}`.
- `search.cohort.jsonl` — cohort-jql search result (subset of issue
  keys matching `labels = ai-assisted`).
- `golden.json` / `golden.csv` — expected canonical outputs for the
  default `flow-metrics --project ALPHA --from 2026-01-01 --to 2026-01-07`
  invocation, with `__GENERATED_AT__` substituted for the timestamp.
- `golden.cohort.json` — expected output with `--cohort-jql 'labels = ai-assisted'`.
- `golden.metrics_filter.json` — expected output with
  `--metrics throughput,cycle_time` (asserts unrequested metrics are
  absent, not null).
- `golden.per_issue.jsonl` — expected `--per-issue` output.
