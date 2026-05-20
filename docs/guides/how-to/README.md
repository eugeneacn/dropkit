# How-to guides

Task-oriented. Each guide solves one concrete problem with a real
command, in the order you'd run them.

## The dependency picture (read first)

Two skill stacks share one foundation. Every guide below assumes
you've finished any guide it points back to.

```
                ┌──────────────────────────────────────────────┐
                │  jira skill  (auth, REST, JQL)               │
                │  → set-up-jira-skill.md   ← start here       │
                └──────────────────────────────────────────────┘
                              │
              ┌───────────────┼────────────────────┐
              ▼               ▼                    ▼
   ┌──────────────────┐  ┌────────────────┐  ┌────────────────────┐
   │ prepare-jira-    │  │ jira-defect-   │  │ (jira skill direct │
   │ for-flow-metrics │  │ flow workflow  │  │  use — see README) │
   └────────┬─────────┘  └────────────────┘  └────────────────────┘
            ▼
   ┌──────────────────┐    (optional, only for program / portfolio scopes)
   │ run-flow-metrics │ ◄── set-up-jira-align-skill.md
   └────────┬─────────┘
            ▼
   ┌──────────────────────┐
   │ run-ai-adoption-     │
   │ report               │
   └──────────────────────┘
```

In words:

- **The `jira` skill is the foundation.** Nothing in this directory
  works without its credentials configured. `flow-metrics`,
  `jira-defect-flow`, and `ai-adoption-report` (transitively, via the
  JSON `flow-metrics` produces) all assume it.
- **The `jira-align` skill is only for Jira Align scopes.** It is
  optional, and only matters if you run `flow-metrics --program-id`
  or `--portfolio-id`.
- **`jira-defect-flow` does not depend on the metrics stack** and
  vice-versa. They share the `jira` skill, nothing else.

## Available guides

### Skill setup (one-time)

- [Set up the jira skill](set-up-jira-skill.md) — credentials,
  token, verification. **Required for everything else on this
  page.**
- [Set up the jira-align skill](set-up-jira-align-skill.md) —
  separate product, separate token. Only needed for `flow-metrics`
  Jira Align scopes (program / portfolio).

### Metrics stack (`flow-metrics` + `ai-adoption-report`)

- [Prepare Jira for flow-metrics](prepare-jira-for-flow-metrics.md)
  — one-time preflight per team: status audit, team field,
  cohort-label convention, smoke test. Assumes the `jira` skill is
  set up.
- [Run flow-metrics for a team, program, or portfolio](run-flow-metrics.md)
  — compute DORA / Flow Framework numbers and write the JSON output
  that everything else consumes.
- [Run ai-adoption-report (baseline, cohort, program)](run-ai-adoption-report.md)
  — pair `flow-metrics` JSONs and produce a Markdown delta report.

### Defect lifecycle workflow

- [Run jira-defect-flow](run-jira-defect-flow.md) — take a single
  defect from ticket to PR end-to-end via the `jira` + `bug-fix`
  skills. Independent of the metrics stack.

### Confluence export

Independent of the Jira stack. The `confluence-crawler` skill is
self-contained — it does not consume or produce anything that the
other guides use.

- [Set up the confluence-crawler skill](set-up-confluence-crawler-skill.md)
  — credentials, token, verification. One-time per environment.
- [Crawl a Confluence space](crawl-a-confluence-space.md) — invoke
  the crawler for the common shapes (whole space, subtree,
  refresh, on-prem), and interpret what it writes.

## Suggested reading order

If you're new to dropkit and want to measure flow:

1. [Set up the jira skill](set-up-jira-skill.md)
2. (Only for program / portfolio scopes)
   [Set up the jira-align skill](set-up-jira-align-skill.md)
3. [Prepare Jira for flow-metrics](prepare-jira-for-flow-metrics.md)
4. [Run flow-metrics](run-flow-metrics.md)
5. [Run ai-adoption-report](run-ai-adoption-report.md) (once you
   have two windows of JSON)

If you're new to dropkit and want to ship defect fixes:

1. [Set up the jira skill](set-up-jira-skill.md)
2. Install `bug-fix` from
   [agent-ready-repo](https://github.com/eugenelim/agent-ready-repo)
3. [Run jira-defect-flow](run-jira-defect-flow.md)

If you only want to mirror Confluence to Markdown:

1. [Set up the confluence-crawler skill](set-up-confluence-crawler-skill.md)
2. [Crawl a Confluence space](crawl-a-confluence-space.md)

For the formal contracts that govern each skill, see
[`docs/specs/`](../../specs/). Specs are normative; these guides are
derived from them.
