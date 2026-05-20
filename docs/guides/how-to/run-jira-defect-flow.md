# How to run jira-defect-flow

Take a single Jira defect from "here's a ticket key" to "PR open,
Jira ticket transitioned and commented." The skill is **pure
choreography** — it composes three other things you already have
(or need to install):

- the [`jira` skill](set-up-jira-skill.md) for every Jira read,
  comment, attachment, and transition;
- the `bug-fix` skill (from
  [agent-ready-repo](https://github.com/eugenelim/agent-ready-repo))
  for the actual fix — reproduction-first, failing test, root vs
  symptom, minimum diff, regression test;
- reviewer subagents (`adversarial-reviewer` and, when warranted,
  `security-reviewer` / `quality-engineer`) from the consumer
  repo's work-loop.

This guide is task-oriented: how to invoke the skill, what each stage
does, and where it stops. The full skill contract lives in
[`SKILL.md`](../../../skills/workflows/jira-defect-flow/SKILL.md);
common transition-name shapes live in
[`references/transitions.md`](../../../skills/workflows/jira-defect-flow/references/transitions.md);
canonical worked examples live in
[`references/examples.md`](../../../skills/workflows/jira-defect-flow/references/examples.md).

**Scope.** This skill is for defects only — stories, tasks, and
feature work go through `new-spec`, not here. If you run it on a
non-defect, stage 1's intake check is supposed to catch it and stop.

## Before you start

Run through this checklist *once*, not per defect. The skill expects
all of it green before stage 1.

1. **The `jira` skill is set up.** Run
   `python skills/integrations/jira/scripts/jira.py check`. Exit 0 →
   proceed. Exit 2 → finish
   [Set up the jira skill](set-up-jira-skill.md) first. The
   defect-flow skill **will not** authenticate Jira for you.
2. **The `bug-fix` skill is installed.** It ships in
   [agent-ready-repo](https://github.com/eugenelim/agent-ready-repo)
   under `.claude/skills/bug-fix/`. Copy it into your IDE's skills
   location, same as any other skill. Defect-flow refuses to
   substitute a free-form fix if `bug-fix` is missing — surface the
   gap and install.
3. **`gh auth status` is green.** PR opening uses the GitHub CLI.
   Run `gh auth login` once if you haven't.
4. **`git config user.email` is correct for this repo.** If the
   consumer repo has a per-repo identity convention (e.g. a
   `noreply` GitHub email enforced by branch protection), don't
   override it.
5. **The consumer repo has a PR template** with the four canonical
   sections (*what / why / how to verify / what you did not
   change*). Defect-flow's PR body uses this template; if it's
   missing, stage 6 falls back to the four-question shape manually
   and flags the gap.

You do **not** need `jira-align`, `flow-metrics`, or anything else
in dropkit. The defect-flow skill is independent of the metrics
stack.

## Invoking the skill

In Claude Code, the simplest invocation is:

> *"Run jira-defect-flow on PROJ-123."*

or, if you have a slash binding:

```
/jira-defect-flow PROJ-123
```

In other IDEs, use whatever skill / rule dispatch mechanism applies.
The skill names its dependencies (`jira`, `bug-fix`,
`adversarial-reviewer`, etc.) **by name, never by path** — the IDE's
harness resolves names to install locations.

## What happens, stage by stage

The skill runs eight stages. You'll see the agent narrate progress
through each.

### Stage 1 — Intake

The skill pulls the ticket via `jira: get-issue $KEY --expand
renderedFields,attachments,changelog,transitions` and checks for
three things every defect should have:

| Requirement | Where it usually lives |
|---|---|
| **Environment** (version, OS, browser, tenant) | `environment`, `description`, custom fields |
| **Reproduction steps** | `description` |
| **Expected vs actual behavior** | `description`, attachments |

If any are missing or unclear, the skill **does not start work.** It
comments on the ticket asking for the missing piece and stops. It
never invents repro steps. This is intentional — a defect without
those three is a question, not a bug.

### Stage 2 — Triage and start

When intake is clean, the skill writes a short triage brief to
`.context/defects/$KEY.md`: severity (its read, with reasoning),
defect class (regression / data / perf / UI / integration / other),
suspect file paths or modules (no fix yet), and any open questions.

It then **asks you to confirm before transitioning the ticket**.
"In Progress" is visible to the whole team and may reassign the
ticket — the skill never moves it speculatively. After you confirm,
it discovers available transitions via `jira: list-transitions $KEY`
and applies the user-chosen "start work" transition by name.

Transition names vary per project ("Start Progress", "In
Development", "Start Work" all appear in the wild). The skill never
hardcodes names — it always lists and picks.

### Stage 3 — Hand off to `bug-fix`

Everything from here through "regression test in suite" is owned by
the `bug-fix` skill. Defect-flow hands it the triage brief and the
ticket text as context. `bug-fix` is responsible for:

- reproducing the bug locally (failing test, manual steps, or a
  captured error);
- writing the failing test (red) that pins the **observable
  contract**, not the implementation;
- identifying root vs symptom — which call site is actually wrong
  and whether the same class of bug exists elsewhere;
- the minimum fix that turns red green, refusing adjacent cleanup;
- keeping the regression test in the suite;
- a commit body that explains *what was wrong, why, and why this
  shape of fix*.

If `bug-fix` is missing, the skill surfaces the gap and stops. It
does not improvise.

### Stage 4 — Branch

The skill generates a branch name deterministically from the Jira
key and issue summary (via its bundled `scripts/branch_name.py`),
so two agents working the same ticket land on the same branch. You
don't run the helper yourself — it executes from inside the skill's
install directory. The resulting branch looks like
`fix/proj-123-null-pointer-in-cart-checkout-when`.

If your repo's convention is `bugfix/` or `hotfix/` instead of the
default `fix/`, set `JIRA_DEFECT_FIX_PREFIX` in the environment
before invoking the skill (or pass `--prefix` if you're driving
`branch_name.py` manually).

### Stage 5 — Review

The skill runs the consumer repo's review pass before opening the
PR. At minimum `adversarial-reviewer`; `security-reviewer` is added
when the diff crosses a security boundary (auth, secrets, user
input, deserialization, file/network I/O, dependencies, LLM/agent
code); `quality-engineer` is added when there's meaningful new test
surface or new logic.

This step is not in this skill — it's in the consumer repo's
`work-loop`. The skill iterates until each reviewer returns
`Clean — ready to commit.`

### Stage 6 — PR

The skill opens a PR with `gh`. The PR title carries the Jira key so
it shows up in notifications; the body uses the consumer repo's
template (the four-question shape) and the **`Why?` section
includes `Closes: $KEY`** — the loopback contract.

```bash
gh pr create \
  --base main \
  --title "fix($SCOPE): <subject> ($KEY)" \
  --body-file .context/defects/$KEY-pr-body.md
```

The skill generates `$KEY-pr-body.md` from the template — never a
freeform paste. The *"What you did not change"* section is the most
useful field; the skill fills it honestly.

### Stage 7 — Jira loopback

Back to Jira via the `jira` skill: a comment with the PR URL and
the reproduction test path, then a workflow transition (commonly to
"In Review" or "Code Review" — discovered, not guessed).

```
jira: comment $KEY --body "PR: <pr-url>. Reproduction test at <test-path>. Awaiting review."
jira: list-transitions $KEY
jira: transition $KEY --to "In Review"
```

Stages 6 and 7 are the Jira-specific implementation of `bug-fix`
step 8 ("loop back to the tracker"). They are not separate
obligations.

### Stage 8 — Deploy to dev (optional)

This stage only runs if the consumer repo provides a deploy hook.
There is no universal "deploy to dev" command, and the skill won't
invent one. It looks, in order, for:

1. `$DEPLOY_DEV_CMD` environment variable;
2. an executable `.context/deploy_dev.sh` in the repo root;
3. neither — in which case it **stops and asks how to deploy.** It
   does not run `gh workflow run`, `kubectl apply`, `terraform
   apply`, or any deploy-shaped command on speculation.

If the deploy succeeds, the skill loops back to Jira one more time
with the dev URL and the next transition ("Ready for QA", "Dev
Deployed", etc.).

## Where it stops by default

By default the skill stops at **stage 7** — PR open, Jira
transitioned to "In Review" (or your project's equivalent),
reproduction test path posted as a comment. From here:

- the team's reviewer process takes the PR;
- QA owns any further transitions ("Done", "Closed", "Resolved" are
  **not** the skill's call); and
- if you want a dev deploy, configure `$DEPLOY_DEV_CMD` or
  `.context/deploy_dev.sh` before the next run, or do it manually.

## Configuration knobs

| Variable / flag | What it does | Default |
|---|---|---|
| `JIRA_DEFECT_FIX_PREFIX` | Branch prefix override. Set to `bugfix` or `hotfix` if your repo's convention differs from `fix`. | `fix` |
| `DEPLOY_DEV_CMD` | Shell command the skill runs at stage 8 to deploy to dev. If unset, the skill checks for `.context/deploy_dev.sh`; if neither exists it stops and asks. | unset |
| `.context/deploy_dev.sh` | Executable script the skill invokes at stage 8 when `$DEPLOY_DEV_CMD` is unset. | not present |

Set the env vars in your shell before invoking the skill, or in your
CI job's environment. The skill does not read them from a config
file.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| Skill stops at stage 1 with a Jira comment listing missing intake | The ticket lacks environment, repro, or expected-vs-actual. | Not an error. The reporter needs to fill in the missing fields; the skill won't proceed without them. |
| `jira: check` exits 2 at the start | The `jira` skill is not authenticated. | Finish [Set up the jira skill](set-up-jira-skill.md). |
| Skill stops with "the `bug-fix` skill is not installed" | `bug-fix` from agent-ready-repo isn't in your IDE's skills location. | Install it. Defect-flow refuses to free-form a fix. |
| Stage 5 reviewer loops indefinitely | `adversarial-reviewer` keeps finding issues. | Read the reviewer's notes; iterate or, if you disagree, address the disagreement in the work-loop — not by skipping the reviewer. |
| Stage 6 fails: `gh pr create` 403 | GitHub auth is wrong for the target repo. | `gh auth status`; switch accounts with `gh auth switch` if needed. |
| Stage 7 `list-transitions` returns `[]` | The current Jira user lacks permission to move the ticket from its current state. | Surface to your team — either get permission, or ask someone to move the ticket. Don't try to backdoor via `update-issue` (the skill won't anyway). |
| Stage 8 stops asking "how do you deploy?" | No `$DEPLOY_DEV_CMD` and no `.context/deploy_dev.sh`. | Either provide a hook now, or accept the stop and deploy manually. The skill will not guess. |
| The ticket turns out to be a feature, not a defect | Stage 1 didn't catch it (or you skipped the check). | Stop, comment on the ticket explaining it should be re-typed or split, and hand off to `new-spec`. |
| The fix needs a spec (multiple files, new behavior, architectural change) | What looked like a defect is actually a refactor. | Stop. Hand off to `new-spec`. Defect-flow is for defects only. |

## Don'ts (load-bearing)

The skill enforces these — they're listed here so you know what to
expect:

- **Never** transition past your scope. "Done" / "Closed" / "Resolved"
  is QA's call, not the agent's.
- **Never** write the fix before `bug-fix` has produced a failing
  test. The ordering is what makes "minimum diff" verifiable.
- **Never** delete a Jira ticket via `delete-issue` from inside this
  flow. Wrong tickets get transitioned to "Won't Fix" or
  "Duplicate" — they don't get deleted.
- **Never** invent a deploy command at stage 8.

## End-to-end example

A concrete walk-through of the happy path, an intake-blocked case,
and the no-deploy-hook case lives in
[`references/examples.md`](../../../skills/workflows/jira-defect-flow/references/examples.md).
For Jira workflow names the skill encounters in the wild, see
[`references/transitions.md`](../../../skills/workflows/jira-defect-flow/references/transitions.md).

## How this fits with the rest of dropkit

| You want to… | Use |
|---|---|
| Take a defect from ticket to PR end-to-end | `jira-defect-flow` (this skill) |
| Read or write Jira directly in chat | The [`jira` skill](set-up-jira-skill.md) |
| Measure flow / DORA / Flow Framework numbers | [`flow-metrics`](run-flow-metrics.md) — separate stack, also needs the `jira` skill |
| Compare metrics across windows or cohorts | [`ai-adoption-report`](run-ai-adoption-report.md) — consumes `flow-metrics` output |

Defect-flow and the metrics stack don't share state — they share the
same data layer (the `jira` skill), but otherwise run independently.
