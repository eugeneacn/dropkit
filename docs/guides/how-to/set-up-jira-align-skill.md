# How to set up the jira-align skill

The `jira-align` skill is the data layer for Jira **Align** — the
portfolio product, distinct from the Jira issue tracker. It is not a
universal prerequisite. You only need it when:

- you want to use `jira-align` directly in chat (fetch epics,
  features, themes, programs, portfolios, teams; create / update /
  delete records); or
- you want to run [`flow-metrics`](run-flow-metrics.md) with
  `--program-id` or `--portfolio-id`, where Jira Align is used to
  resolve which teams belong to a program or portfolio.

For project-scope or team-scope `flow-metrics` runs (`--project` /
`--team`), only the [`jira` skill](set-up-jira-skill.md) is needed —
not this one.

Allow about ten minutes. The skill is independent of the `jira` skill
and uses a different base URL and a different token.

## Step 1: install the skill

Same pattern as every other dropkit skill — copy the folder into your
IDE's skills location.

**Drop-in (Claude Code, user scope):**

```bash
mkdir -p ~/.claude/skills
cp -R skills/integrations/jira-align ~/.claude/skills/
```

**Project scope:**

```bash
mkdir -p .claude/skills
cp -R skills/integrations/jira-align .claude/skills/
```

For other IDEs see the
[install matrix](../../../README.md#installing-a-skill-into-your-ide).

## Step 2: install Python dependencies

```bash
python -m pip install -r skills/integrations/jira-align/requirements.txt
```

Pure-Python, `requests`-based — no native extensions.

## Step 3: generate an API token

Cloud and on-prem use the same token flow. Both are bearer tokens
generated on each user's Jira Align profile page.

1. Sign in to your Jira Align instance — Cloud at
   `https://<site>.jiraalign.com`, or your self-hosted URL.
2. Click your avatar in the top navigation → **Profile**.
3. On the Profile page, locate the **API Token** section. Click
   **Generate** (or **Regenerate** if one already exists).
4. Copy the token value — it's only displayed once.

Tokens do not expire by elapsed time. They remain valid until
regenerated or until the user is deactivated.

If you're on a self-hosted install and the **API Token** section is
missing, an administrator needs to enable `EnableApiTokens` in the
system configuration. Ask the admin; this is not something a regular
user can flip.

## Step 4: run the setup script

```bash
bash skills/integrations/jira-align/scripts/setup_credentials.sh
```

The script is interactive — it prompts for the base URL and the
token. The token is read with echo off; it never appears on the
command line or in shell history.

It writes `~/.config/dropkit/credentials.env` at mode 0600, merging
`JIRAALIGN_*` keys into the same shared file used by the `jira` skill
and any other dropkit skill that authenticates against a remote
service. Your existing `JIRA_*` keys are preserved by this run, and
vice-versa.

## Step 5: verify connectivity

```bash
python skills/integrations/jira-align/scripts/jira_align.py check
```

| Exit | Meaning | Next step |
|---|---|---|
| `0` | Authenticated. | Move on. |
| `2` | Auth failure. The client raises `AuthError` for both 401 (credentials wrong) and 403 (token valid but no Align role) — both return exit 2; the stderr message distinguishes them. | If the stderr says 401, re-run `setup_credentials.sh`. If 403, your user has no Jira Align role assigned — ask an admin. |
| `3` | Auth succeeded; a non-auth downstream call failed (network, 5xx, malformed response). | Read the relayed stderr. Usually transient. |

For an extra sanity check:

```bash
python skills/integrations/jira-align/scripts/jira_align.py whoami
```

confirms the principal the token resolves to.

## Step 6: prove it with a real query (optional)

A small read confirms the token has access to something. Replace
the resource name with one you know exists on your instance:

```bash
python skills/integrations/jira-align/scripts/jira_align.py list teams \
  --select "id,title" --limit 5
```

If you get exit 2 with a 403 on `teams` but `whoami` works, the
token is valid but your Jira Align role doesn't cover that resource —
401 and 403 both bucket into exit 2; the stderr message is what
tells them apart. Switch to a resource you do have access to.

## What this unlocks

Once `check` returns 0:

- The `jira-align` skill works in chat — see the
  [skill's README section](../../../README.md#jira-align) for the
  subcommand inventory and OData filter syntax.
- The Jira Align scopes of `flow-metrics` work, **provided** you also
  configure the `align_join_field` (see below). You don't get
  Align scopes for free just by setting up auth.

## Wiring up flow-metrics' Jira Align scopes

`flow-metrics --program-id` and `--portfolio-id` ask Jira Align
*which teams belong to this program / portfolio?* and then fetch
those teams' issues from Jira. The bridge between the two systems is
a Jira custom field that holds the Jira Align team ID. There is no
default — picking one wrong silently returns wrong answers, so the
skill refuses to compute without an explicit choice.

Two ways to configure it:

- **Persistent**: add `"align_join_field": "customfield_NNNNN"` to
  your `flow-metrics` state config (see
  [Customising the state config](run-flow-metrics.md#customising-the-state-config)
  for where that file lives).
- **One-off**: pass `--align-join-field customfield_NNNNN` on the
  command line.

To find the right field on your instance, look at a Jira issue that
belongs to a Jira Align team and inspect which custom field carries
the team ID. The `jira` skill's `raw GET field` returns the full
custom-field catalog if you need to enumerate.

Forgetting both `align_join_field` and `--align-join-field` exits 2
with a clear message — you cannot accidentally compute against the
wrong field.

## In CI

Set environment variables with the same names the file uses; the
skill scripts read them in preference to the file.

| Variable | Required | Notes |
|---|---|---|
| `JIRAALIGN_BASE_URL` | yes | `https://<site>.jiraalign.com` (Cloud) or your on-prem URL. |
| `JIRAALIGN_API_TOKEN` | yes | Bearer token. |
| `JIRAALIGN_FLAVOR` | no | `cloud` or `onprem`. Auto-detected if unset. |

## Rotating or replacing the token

The flow is symmetric with the `jira` skill:

1. Click **Regenerate** on your Jira Align Profile page. The
   previous token stops working immediately.
2. Re-run `setup_credentials.sh`. It rewrites only the `JIRAALIGN_*`
   keys.
3. Re-run `check`.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `check` exits 2 immediately | `credentials.env` missing the `JIRAALIGN_*` keys. | Re-run `setup_credentials.sh`. |
| `check` exits 2 with 401 | Token rejected. Most commonly: the token was regenerated since setup, or the base URL is for a different tenant. | Confirm the URL, regenerate, re-run setup. |
| `check` exits 2 with a 403-flavored stderr | Token is valid but the user has no Align role. (`check` only calls `whoami` — if that 403s, every other resource will too.) | An admin needs to assign a role on the Jira Align instance. |
| `flow-metrics --program-id` exits 2 with "join field is missing" | `align_join_field` not configured and `--align-join-field` not passed. | See [Wiring up flow-metrics' Jira Align scopes](#wiring-up-flow-metrics-jira-align-scopes). |
| TLS error on self-hosted | Self-signed cert. | `--insecure` exists but is opt-in. Prefer fixing the cert chain. |
| The API Token section is missing on the Profile page (on-prem) | Tokens are disabled in the instance configuration. | An admin needs to enable `EnableApiTokens`. |

## Security boundary

Same rules as the `jira` skill (see
[Set up the jira skill](set-up-jira-skill.md#security-boundary) for
the long version):

- The setup script is the only thing that writes the token.
- The skill scripts are the only things that read it.
- The agent is contractually instructed not to read
  `credentials.env` or print the token — a `Don't` rule in
  `SKILL.md`, agent-compliance level, not code-enforced.
- The CLI does refuse tokens passed as flags (`--token`,
  `--api-token`, `--bearer`) and exits — this is code-enforced.

## Distinct from the jira skill

Don't conflate the two skills:

| | `jira` | `jira-align` |
|---|---|---|
| Product | Jira (issue tracker) | Jira Align (portfolio) |
| Base URL host | `*.atlassian.net` or your Server URL | `*.jiraalign.com` or your on-prem URL |
| Cloud auth | Basic `email:token` | Bearer token |
| Server auth | Bearer PAT | Bearer token |
| Credential keys | `JIRA_*` | `JIRAALIGN_*` |
| API prefix | `/rest/api/3` (Cloud) or `/2` (Server) | `/rest/align/api/2` |

They share the credentials file but nothing else. Tokens are not
interchangeable — generating one does not give you the other.
