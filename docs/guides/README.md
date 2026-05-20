# dropkit guides

User-facing documentation, organised by the [Diátaxis](https://diataxis.fr/)
framework. Each quadrant has a distinct purpose; pick by what you need
right now.

| Quadrant | Purpose | When to read |
|---|---|---|
| [Tutorials](tutorials/) | Learning-oriented. Walk through a worked example end-to-end. | First contact with a skill. You want to be led. |
| [How-to guides](how-to/) | Task-oriented. Solve a specific real-world problem. | You already know what you want to do. You need the steps. |
| [Reference](reference/) | Information-oriented. Exhaustive description of flags, schemas, exit codes. | You need the precise behaviour of a flag or field. |
| [Explanation](explanation/) | Understanding-oriented. Discuss the *why* behind design choices. | You want context, trade-offs, history. |

Today, the [how-to](how-to/) quadrant carries most of the weight;
[explanation](explanation/) has one starter page (the cohort model)
that the how-tos forward-reference for design rationale. The
[reference](reference/) and [tutorials](tutorials/) quadrants are
scaffolded with pointers to authoritative material and will be
filled in as the docs grow.

If you're new, start at the
[how-to index](how-to/README.md#the-dependency-picture-read-first)
— it shows which skill underpins which workflow and the order to
read the guides in. The short version: the `jira` skill is the
foundation for everything else, so set it up first.

The how-to set currently covers two stacks:

- **Skill setup** — [`jira`](how-to/set-up-jira-skill.md) (required
  for everything below) and
  [`jira-align`](how-to/set-up-jira-align-skill.md) (only for
  program / portfolio metrics scopes).
- **Metrics stack** —
  [`flow-metrics`](how-to/run-flow-metrics.md) and
  [`ai-adoption-report`](how-to/run-ai-adoption-report.md), preceded
  by the per-team
  [Jira preflight](how-to/prepare-jira-for-flow-metrics.md).
- **Defect lifecycle workflow** —
  [`jira-defect-flow`](how-to/run-jira-defect-flow.md).

For the formal contracts that govern each skill, see
[`docs/specs/`](../specs/). Specs are normative; these guides are
derived from them.
