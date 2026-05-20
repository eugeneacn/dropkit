# The cohort model

A discussion of how `flow-metrics` represents an "AI-assisted cohort"
and why the representation looks the way it does. This page is about
understanding, not action — for the steps to set up cohort tracking,
see [Prepare Jira for flow-metrics](../how-to/prepare-jira-for-flow-metrics.md).

## What a cohort is in this tool

A *cohort* is "the set of issues, delivered in this window, that
match a JQL expression." The JQL is supplied at run-time via
`--cohort-jql`. Everything else delivered in the window is the
*control*. Each issue is either in the cohort or in the control —
never both, never missing, never tri-state.

That's it. There's no semantic content beyond "these issues match the
JQL, those don't." The tool doesn't know what the JQL means; it
doesn't care whether you tagged AI-assisted work, late-arriving work,
or work touched by a specific component. It applies the filter and
splits.

## Why cohort identity is manual

A team adopting this tool to measure AI uptake reasonably asks: why
do I have to label issues by hand? Can't you detect AI-assisted work
from commits or PR metadata?

We considered four sources and rejected all of them:

- **Commit messages or PR descriptions.** Requires every contributor
  to mention AI usage consistently — a stronger labelling discipline
  than just tagging the ticket, and harder to audit. Most teams that
  could maintain this convention can also maintain a Jira label, and
  the Jira label gives a clean join key.
- **File-path heuristics or tool fingerprints.** "If the diff
  contains a Claude-generated marker, count it." Brittle; trivial to
  game; misses paste-and-edit usage. Would produce numbers that
  *look* objective and aren't.
- **Time-of-day or velocity inference.** "Stories closed 3× faster
  than baseline are probably AI-assisted." Circular: now your AI
  metric is "stories closed fast," which is what you wanted to
  measure as a *consequence* of AI adoption.
- **CI integration with a coding-assistant audit log.** Plausible
  long-term, but requires every assistant to expose an audit log and
  every CI to forward it. Vendor-coupled. Out of scope for v1.

A manual label is *boring*. It's also auditable, vendor-neutral, and
puts the labelling discipline in one place (the issue tracker) where
your team already operates.

The trade is real: if your team forgets to label half the
AI-assisted work, your cohort under-counts and the control over-counts.
That's a *practice* problem the tool can't solve. It can, however,
report numbers honestly given whatever labelling discipline you
maintain.

## The label is your choice, not a contract

The spec's example is `--cohort-jql "labels = ai-assisted"`. That has
become the de-facto convention in dropkit documentation, but the tool
doesn't know about `ai-assisted` as a string. Any JQL clause works:

```
--cohort-jql "labels = ai-assisted"
--cohort-jql "labels in (ai, ai-assisted, claude-touched)"
--cohort-jql "\"AI Contribution\" is not EMPTY"   # custom field
--cohort-jql "component = experimental-ai"
```

Pick one convention per team. Different conventions across teams in
the same program are technically allowed (`ai-adoption-report`
program mode will emit a `mixed-cohort-jql` note and proceed) but
make the rollup hard to defend — you're aggregating cohort identities
that mean different things.

## Why cohort + control don't average to global

This is the property that trips up most readers of cohort reports the
first time.

Say a window delivered 100 issues. 10 are tagged AI-assisted (the
cohort); 90 are the control. The cohort's rework rate is 0.5 (5
backward transitions across 10 issues). The control's rework rate is
0.1 (9 backward transitions across 90 issues).

A reader expects the global rework rate to be the size-weighted
average: `(0.5 × 10 + 0.1 × 90) / 100 = 0.14`. And mathematically
that's correct.

But `flow-metrics` reports the global rework rate using **global
numerator over global denominator**: `(5 + 9) / 100 = 0.14`. Same
answer here, because we restricted ourselves to a tidy case.

Now run the same numbers but report the cohort and control separately:

- `cohort_breakdown.cohort.rework_rate` = 5 / 10 = **0.5**
- `cohort_breakdown.control.rework_rate` = 9 / 90 = **0.1**

Each side uses *its own* denominator. The cohort number tells you "of
AI-assisted issues, this is the rework rate." The control tells you
"of non-AI-assisted issues, this is the rework rate."

If you want to recover the global, you weight-average the two sides
by their throughputs: `(0.5 × 10 + 0.1 × 90) / 100 = 0.14`. The
report gives you the inputs; it doesn't do that weighting for you,
because *the comparison the report exists to surface is the cohort vs
control delta*, not the cohort's contribution to the global.

The same logic applies to every metric in `cohort_breakdown`:
percentiles, defect ratio, flow efficiency. Each side is computed
against its own population. This is intentional, documented in the
flow-metrics spec, and the program-mode aggregator preserves the
property by rolling up cohort and control sides independently.

## What goes wrong when labelling drifts

The model assumes the label means the same thing for the duration of
the window. Three drift patterns produce misleading reports:

1. **Mid-window convention change.** The team starts labelling more
   aggressively in week 8 of a 12-week window. The early cohort is
   under-tagged relative to the late cohort. Cycle-time deltas
   between early-window and late-window cohorts are then partly an
   artefact of the labelling discipline, not the AI usage.
2. **Retro-labelling.** A burst of labels gets applied at quarter
   end. Issues you'd have considered borderline get labelled because
   "we used Claude to read the spec" and that feels close enough. The
   cohort balloons; its average cycle time looks worse because you've
   diluted with marginal cases.
3. **Inconsistent application across teams.** Two teams in the same
   program use the same label name but different thresholds.
   `ai-adoption-report` program mode's `mixed-cohort-jql` note
   doesn't catch this — the JQL strings are identical; the
   *practices behind them* aren't.

There's no tool-side fix for any of these. The honest mitigation is
to write down the labelling threshold (step 4 of the preflight
how-to) and audit a sample of labelled and unlabelled issues every
few weeks.

## What cohort mode is and isn't measuring

It's measuring: "Among issues delivered in this window, how does the
cohort's behaviour compare to the control's behaviour on the metrics
we computed?"

It's not measuring:

- Whether AI *caused* the cohort to behave differently. Same time,
  same team, same project — but the cohort and control are
  self-selected by your labelling discipline. Cohort issues may be
  systematically smaller, simpler, or assigned to faster engineers.
  The report doesn't know.
- Whether AI is helping the team overall. That's the global metrics
  question, answered by baseline mode (pre-AI window vs current
  window). Cohort and baseline are complementary, not redundant.
- Whether individual contributors are more productive with AI. The
  unit of analysis is the issue, not the person.

DORA 2025's central finding — that AI inflates individual throughput
while organisational metrics stay flat or worsen on stability — only
becomes visible when you run **both** cohort *and* baseline against
the same data, and read the two reports together.
