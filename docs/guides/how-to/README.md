# How-to guides

Task-oriented. Each guide solves one concrete problem with a real
command, in the order you'd run them. They assume you've installed
dropkit, configured credentials for the `jira` skill (which owns
`~/.config/dropkit/credentials.env`), and can run a skill from your
shell.

## Available guides

- [Prepare Jira for flow-metrics](prepare-jira-for-flow-metrics.md)
  — one-time preflight for a team's first run: status audit, team
  field, cohort-label convention, smoke test.
- [Run flow-metrics for a team, program, or portfolio](run-flow-metrics.md)
  — compute DORA / Flow Framework numbers for a Jira scope and write
  the JSON output that everything else consumes.
- [Run ai-adoption-report (baseline, cohort, program)](run-ai-adoption-report.md)
  — pair flow-metrics JSONs and produce a Markdown delta report.

If you're new to dropkit, start with
`prepare-jira-for-flow-metrics.md`, then move to
`run-flow-metrics.md`. Every other measurement in the AI-adoption
stack feeds off `flow-metrics` output.
