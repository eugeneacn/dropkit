# How to set up the jira skill

The `jira` skill is the data layer for every other Jira-touching skill
in dropkit. Two workflow skills consume it directly:

- [`flow-metrics`](run-flow-metrics.md) — every Jira read goes through
  the `jira` skill. No `jira` skill, no metrics.
- [`jira-defect-flow`](run-jira-defect-flow.md) — uses the `jira` skill
  for issue intake, comments, attachments, and workflow transitions.

If you plan to use either of those, finish this guide first. Allow
about ten minutes — most of it is generating an API token in the
Atlassian UI.

The skill never writes to Jira on its own. Browse permission on the
target project is enough to read; a write permission is only required
if you intend to use `create-issue` / `update-issue` / `transition` /
`comment` / `attach`.

## Step 1: install the skill

The skill lives at `skills/integrations/jira/` in the dropkit repo.
Two install layouts are supported; pick the one that matches how you
use dropkit.

**Drop-in (Claude Code, user scope):**

```bash
mkdir -p ~/.claude/skills
cp -R skills/integrations/jira ~/.claude/skills/
```

**Project scope** (tracked with the consumer repo):

```bash
mkdir -p .claude/skills
cp -R skills/integrations/jira .claude/skills/
```

**Other IDEs** (Cursor, Kiro, Continue, etc.): see the
[install matrix](../../../README.md#installing-a-skill-into-your-ide)
in the top-level README. The skill folder is portable; the
discovery mechanism differs per IDE.

## Step 2: install Python dependencies

From the install location (or the dropkit clone, if you're running
the skill from there):

```bash
python -m pip install -r skills/integrations/jira/requirements.txt
```

The skill is pure-Python and pulls in `requests` and a small set of
helpers. No native extensions, no global daemons.

## Step 3: generate an API token

The flow differs by Jira flavor — Atlassian Cloud and self-hosted
Server / Data Center use different auth schemes. The skill
auto-detects the flavor from the base URL.

**Atlassian Cloud** (`*.atlassian.net`):

1. Open https://id.atlassian.com/manage-profile/security/api-tokens.
2. Click **Create API token**, give it a label like `dropkit`, click
   **Create**.
3. Copy the value — it's only shown once. You'll paste it in step 4.

On Cloud, auth is HTTP Basic with `email:token`, so the setup script
also asks for your Atlassian account email.

**Server / Data Center (on-prem)**:

1. In Jira, click your avatar → **Profile** → **Personal Access
   Tokens** → **Create token**.
2. Name it, set an expiry, click **Create**.
3. Copy the value shown — only displayed once.

On Server / DC, auth is bearer-token; no email is needed.

## Step 4: run the setup script

The script is interactive — it prompts for the base URL, your email
(Cloud only), and the token. The token is read with echo off and
never appears on the command line or in shell history.

```bash
bash skills/integrations/jira/scripts/setup_credentials.sh
```

It writes `~/.config/dropkit/credentials.env` at mode 0600, merging
`JIRA_*` keys into any existing dropkit credentials. If you also use
the [`jira-align` skill](set-up-jira-align-skill.md), its
`JIRAALIGN_*` keys are preserved by this run, and vice-versa.

The file is the only place secrets land. The skill scripts read
from it; the agent is instructed not to (see the `Don't` rules in
the skill's `SKILL.md`) and the CLI refuses tokens passed as
command-line flags. The latter is enforced in code; the former is a
contractual rule the agent is meant to follow.

## Step 5: verify connectivity

```bash
python skills/integrations/jira/scripts/jira.py check
```

| Exit | Meaning | Next step |
|---|---|---|
| `0` | Authenticated. You're done. | Move on to the workflow you want to run. |
| `2` | Auth failure. Covers credentials missing, invalid, expired (401), or rejected for permission / CAPTCHA reasons (403). The client raises `AuthError` for both 401 and 403 — `check` doesn't distinguish them at the exit code, only in the stderr message. | Re-run `setup_credentials.sh` if the token is wrong. If the message mentions 403, the token is valid but the user lacks access; switch principals rather than rotating the token. |
| `3` | Auth succeeded; a non-auth downstream call failed (network, 5xx, malformed response, etc.). | Read the relayed stderr. Usually transient — re-run. |

A successful `check` also implicitly validates `whoami`. If you want
to confirm your principal explicitly:

```bash
python skills/integrations/jira/scripts/jira.py whoami
```

On Cloud you'll see a 24-char `accountId`; on Server, a `name`
(username). Workflow skills that build JQL on your behalf use this
to disambiguate `currentUser()`-equivalent clauses.

## Step 6: prove it with a real query (optional)

A one-off JQL search confirms the token has the project access you
expect:

```bash
python skills/integrations/jira/scripts/jira.py search \
  "project = PROJ AND created >= -7d" \
  --fields "summary,status" --limit 5
```

Replace `PROJ` with a project key you can browse. If you get an empty
result, the token works but you may lack browse permission on that
project; pick a different key. If you get exit 2 (the script's auth
bucket — covers 401 and 403), re-check the token or your permissions.

## What this unlocks

Once `check` returns 0, you can:

- Use the `jira` skill directly in chat — *"show me PROJ-123",
  *"export all bugs in PROJ touched this week to bugs.jsonl"*, etc.
  See the [skill's README section](../../../README.md#jira) for the
  full subcommand inventory.
- Run [`flow-metrics`](run-flow-metrics.md). If you're new to that
  skill, start with
  [Prepare Jira for flow-metrics](prepare-jira-for-flow-metrics.md)
  — it covers the status-mapping and team-field setup that sits
  *on top of* this credential layer.
- Run [`jira-defect-flow`](run-jira-defect-flow.md) to take a
  defect end-to-end from intake to PR.

## What this does **not** unlock

- **Jira Align scopes** (`flow-metrics --program-id` /
  `--portfolio-id`). Jira Align is a separate product with a separate
  token and base URL. Set it up via
  [Set up the jira-align skill](set-up-jira-align-skill.md).
- **GitHub operations** (`jira-defect-flow`'s PR-opening stage). That
  uses `gh`; authenticate it independently with `gh auth login`.

## Rotating or replacing the token

Tokens are revoked by Atlassian when you regenerate them. To rotate:

1. Generate a new token (step 3).
2. Re-run `setup_credentials.sh` (step 4). It rewrites only the
   `JIRA_*` keys in the shared file; other skills' credentials are
   untouched.
3. Re-run `check` to confirm.

There's no in-place edit path on purpose — the setup script is the
only thing that writes to `credentials.env`.

## In CI

The shared file is not required in CI. Set environment variables
with the same names the file uses and the skill scripts pick them up:

| Variable | Required | Notes |
|---|---|---|
| `JIRA_BASE_URL` | yes | Same value as the prompt. |
| `JIRA_EMAIL` | Cloud only | Account email. |
| `JIRA_API_TOKEN` | yes | The token. |
| `JIRA_FLAVOR` | no | `cloud` or `server`. Auto-detected if unset. |

Environment variables always win over the file, so a developer with
both set sees the env vars used. This makes CI runs and per-shell
overrides straightforward.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `check` exits 2 immediately | `credentials.env` doesn't exist or is unreadable. | Re-run `setup_credentials.sh`. Check the file is at `~/.config/dropkit/credentials.env` (or `$XDG_CONFIG_HOME/dropkit/`) with mode 0600. |
| `check` exits 2 with 401 | Token rejected. | On Cloud: token doesn't match the email — confirm both with `id.atlassian.com → API tokens`. On Server: PAT may be revoked or expired. Regenerate and re-run setup. |
| `check` exits 2 with 403 + `X-Seraph-LoginReason: AUTHENTICATION_DENIED` (Cloud) | CAPTCHA was triggered by repeated failures. Both 401 and 403 surface here as exit 2 — the client raises `AuthError` on either, so `check` doesn't distinguish "bad creds" from "good creds, no permission" at this layer. | Log in to Jira through the web UI to clear it, then retry. |
| `check` works, but JQL searches return zero issues | Token's user lacks browse permission on the queried project. | Ask the project lead to add browse; or use a service account. `flow-metrics` records permission undercount as a note in its output. |
| TLS error on self-hosted Server / DC | Self-signed cert. | `--insecure` is supported but **only when the user explicitly asks for it.** Prefer fixing the cert chain. |
| Token pasted as a shell argument never gets captured | The setup script ignores command-line arguments — it only reads from its interactive prompt (with echo off). Tokens passed as argv land in shell history and are silently dropped by the script. | Re-run with no arguments; paste the token at the hidden prompt. The CLI-level argv block (`--token`, `--api-token`, etc.) is in `jira.py`, not in the setup script — don't rely on the setup script to refuse misuse. |

## Security boundary

This is worth stating explicitly because every downstream skill
inherits it:

- The setup script is the only thing that writes the token.
- The skill's scripts are the only things that read it.
- The agent is contractually instructed not to read
  `credentials.env` or print the token — this is a `Don't` rule in
  the skill's `SKILL.md`, enforced by agent compliance rather than
  by code.
- The CLI **does** refuse tokens passed as flags: `--token`,
  `--api-token`, `--bearer`, `--pat` cause it to exit. This is
  enforced in code.

If you are reviewing dropkit before adopting it, those four points
are the boundary that keeps the agent out of your secrets — the
first three rely on agent compliance with the skill contract, the
fourth is a hard runtime block.
