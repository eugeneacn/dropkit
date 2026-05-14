# jira-defect-flow — canonical examples

Three end-to-end shapes you'll see most often. Replace `PROJ-123`,
`jira-skill-path`, etc. with the values from your environment.

---

## 1. Full happy path

User: *"Take PROJ-123 from triage to PR on dev."*

```bash
# Stage 1 — intake
python ~/.claude/skills/jira/scripts/jira.py check
python ~/.claude/skills/jira/scripts/jira.py get-issue PROJ-123 \
  --expand renderedFields,attachments,changelog,transitions \
  > .context/defects/PROJ-123.raw.json

# (agent reads env / repro / expected-vs-actual — all present)

# Stage 2 — triage + start
# (agent writes .context/defects/PROJ-123.md with severity, class, suspects)
# (user confirms start)
python ~/.claude/skills/jira/scripts/jira.py list-transitions PROJ-123
python ~/.claude/skills/jira/scripts/jira.py transition PROJ-123 --to "In Progress"

# Stage 3 — hand to bug-fix skill
# (bug-fix writes failing test, identifies root cause, applies minimum fix)

# Stage 4 — branch
BRANCH=$(python skills/workflows/jira-defect-flow/scripts/branch_name.py \
  PROJ-123 "Null pointer in cart checkout when coupon expired")
git checkout -b "$BRANCH"
# -> fix/proj-123-null-pointer-in-cart-checkout-when

# Stage 5 — review (in consumer repo's work-loop)
# (adversarial-reviewer + security-reviewer return Clean — ready to commit)

# Stage 6 — PR
gh pr create --base main \
  --title "fix(checkout): null-pointer on expired coupon (PROJ-123)" \
  --body-file .context/defects/PROJ-123-pr-body.md
# PR body's Why? section contains: Closes: PROJ-123

# Stage 7 — Jira loopback
python ~/.claude/skills/jira/scripts/jira.py comment PROJ-123 \
  --body "PR: https://github.com/acme/web/pull/4321. Repro test: tests/checkout/coupon_expiry_test.py::test_expired_coupon_does_not_crash"
python ~/.claude/skills/jira/scripts/jira.py transition PROJ-123 --to "In Review"

# Stage 8 — dev deploy (only because DEPLOY_DEV_CMD is set)
"$DEPLOY_DEV_CMD"
python ~/.claude/skills/jira/scripts/jira.py comment PROJ-123 \
  --body "Deployed to dev: https://dev.acme.example/checkout. Ready for QA."
python ~/.claude/skills/jira/scripts/jira.py transition PROJ-123 --to "Ready for QA"
```

---

## 2. Intake blocked by missing info

User: *"Fix PROJ-456."*

```bash
python ~/.claude/skills/jira/scripts/jira.py get-issue PROJ-456 \
  --expand renderedFields,attachments,changelog
```

Agent reads the ticket — description is one line: *"Search is broken,
please fix."* No environment, no repro, no expected-vs-actual.

**Do not proceed.** Comment and stop:

```bash
python ~/.claude/skills/jira/scripts/jira.py comment PROJ-456 \
  --body "Before picking this up I need: (1) environment — which deployment / build, on which browser; (2) reproduction steps — what query did you run; (3) expected vs actual behavior — what should have happened vs what did. Once those are in I'll start."
```

No branch created, no transition applied. Surface to the user that the
ticket was blocked back to the reporter.

---

## 3. No deploy hook (stops at PR-merged)

User: *"Ship the fix for PROJ-789 to dev."*

All stages 1–7 run normally. At stage 8:

```bash
[ -n "$DEPLOY_DEV_CMD" ] && echo "have env hook" || echo "no env hook"
# -> no env hook
[ -x .context/deploy_dev.sh ] && echo "have file hook" || echo "no file hook"
# -> no file hook
```

Stop. Tell the user:

> The PR for PROJ-789 is open and Jira is moved to *In Review*. I don't
> see a `DEPLOY_DEV_CMD` env var or a `.context/deploy_dev.sh` script in
> this repo, so I won't guess at a deploy command. How is dev deployed
> here? Once I know, I can add a `.context/deploy_dev.sh` so the next
> run of this skill can do it automatically.

Do not run `gh workflow run`, `kubectl apply`, or any deploy-shaped
command on speculation.
