# How to set up the confluence-crawler skill

The `confluence-crawler` skill mirrors an authenticated Confluence
space to local Markdown files with YAML frontmatter. It is the only
thing in dropkit that talks to Confluence — nothing else in the
skill catalogue consumes its output today, so you only need this
guide if you actually want to export, ingest, or back up Confluence
content.

The setup itself takes about ten minutes. Most of it is generating an
API token in the Atlassian UI.

The skill is read-only against Confluence. There is no write path —
no flag, no subcommand, nothing in the contract creates or edits
pages on the server. Browse permission on the space (and on each
page you want to crawl) is sufficient.

## Step 1: install the skill

The skill lives at `skills/crawlers/confluence-crawler/` in the
dropkit repo. Pick the install layout that matches how you use
dropkit.

**Drop-in (Claude Code, user scope):**

```bash
mkdir -p ~/.claude/skills
cp -R skills/crawlers/confluence-crawler ~/.claude/skills/
```

**Project scope** (tracked with the consumer repo):

```bash
mkdir -p .claude/skills
cp -R skills/crawlers/confluence-crawler .claude/skills/
```

**Other IDEs** (Cursor, Kiro, Continue, etc.): see the
[install matrix](../../../README.md#installing-a-skill-into-your-ide)
in the top-level README. The skill folder is portable; the
discovery mechanism differs per IDE.

## Step 2: install Python dependencies

From the install location (or the dropkit clone, if you're running
the skill from there):

```bash
python -m pip install -r skills/crawlers/confluence-crawler/requirements.txt
```

The skill is pure-Python: `httpx` for the async REST client,
`beautifulsoup4` and `markdownify` for storage-format → Markdown
conversion, `python-slugify` for filename derivation,
`python-dotenv` to read the config file, and `PyYAML` for the
frontmatter block.

## Step 3: generate an API token

The flow differs by Confluence flavor — Atlassian Cloud and
self-hosted Server / Data Center use different auth schemes. The
skill auto-detects the flavor from the base URL host.

**Atlassian Cloud** (`*.atlassian.net`):

1. Open https://id.atlassian.com/manage-profile/security/api-tokens.
2. Click **Create API token**, give it a label like
   `dropkit-confluence`, click **Create**.
3. Copy the value — it's only shown once. You'll paste it in step 4.

On Cloud, auth is HTTP Basic with `email:token`, so the setup script
also asks for your Atlassian account email. The same token works
across Atlassian products (Jira, Confluence, etc.) but a label per
use site makes rotation less destructive.

**Server / Data Center (on-prem)**:

1. In Confluence, click your avatar → **Profile** → **Personal
   Access Tokens** → **Create token**.
2. Name it, set an expiry, click **Create**.
3. Copy the value shown — only displayed once.

On Server / DC, auth is bearer-token; no email is needed.

## Step 4: run the setup script

The script is interactive — it prompts for the base URL, your email
(Cloud only), and the token. The token is read with echo off and
never appears on the command line or in shell history.

```bash
bash skills/crawlers/confluence-crawler/scripts/setup_credentials.sh
```

It writes `~/.config/confluence-crawler/config.env` at mode 0600.
A few flavor-specific things the script does for you:

- **Detects Atlassian Cloud** when the host ends in
  `.atlassian.net` and appends `/wiki` to the base URL if you didn't
  include it. (The Cloud Confluence REST API lives under `/wiki`;
  missing it produces 404s.)
- **Sets `CONFLUENCE_FLAVOR`** explicitly in the file, so a later
  run never has to re-detect.
- **Ignores tokens passed as arguments.** The script reads the
  token only from its interactive prompt (with echo off); anything
  passed on argv is silently dropped. This is intentional — argv
  values land in shell history. The script doesn't raise an error;
  it just won't capture them.

> **Where the file lands, vs. the dropkit shared credential store**
> Most dropkit skills (e.g. `jira`, `jira-align`) write to a
> shared `~/.config/dropkit/credentials.env`. The
> confluence-crawler setup script writes to its own per-skill
> file at `~/.config/confluence-crawler/config.env`
> (`$XDG_CONFIG_HOME/confluence-crawler/config.env` if you set
> `XDG_CONFIG_HOME`). The client still **reads** the shared
> dropkit file first, then falls back to the per-skill file, so
> if you maintain credentials in `~/.config/dropkit/credentials.env`
> by hand the skill will use them. Resolution order is env vars >
> shared file > per-skill file.
>
> **Footgun.** Because the shared file wins over the per-skill
> file, a stale `CONFLUENCE_API_TOKEN` in
> `~/.config/dropkit/credentials.env` will mask whatever fresh
> token `setup_credentials.sh` just wrote to the per-skill file.
> If `--check` still returns 2 after a successful re-run of setup,
> grep the shared file for `CONFLUENCE_` keys and either remove
> them or update them by hand.

## Step 5: verify connectivity

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py --check
```

| Exit | Meaning | Next step |
|---|---|---|
| `0` | Authenticated. `whoami` returned a principal. | Move on to [Crawl a Confluence space](crawl-a-confluence-space.md). |
| `2` | Credentials missing or invalid. The client raises `AuthError` for both 401 (bad / expired token) and 403 (token valid, no permission); `--check` doesn't distinguish them at the exit code, only in the stderr message. | Re-run `setup_credentials.sh` if the token is wrong. If the message mentions 403, the token is valid but the user lacks access to `/rest/api/user/current`; switch principals rather than rotating the token. |
| `1` | Reserved for a crawl with at least one failed page. Not produced by `--check`. | Not applicable here — see [Crawl a Confluence space](crawl-a-confluence-space.md). |
| `130` | You pressed Ctrl-C. | Re-run when ready. |

A successful `--check` also logs the principal it authenticated as.
The identifier is the first non-empty field from the cascade
`username` → `displayName` → `publicName` → `email` → `accountId`,
so on Cloud you'll usually see your `displayName`, and on Server
you'll see your `username`. If you need to confirm *which* identity
the token belongs to before crawling a sensitive space, this is
where to look.

If `--check` doesn't tell you enough about *why* it's failing, add
`--verbose` (alias `-v`) to switch logging to `DEBUG` — it prints
every REST call the client makes. The token itself never appears
in the log output at any level.

## Step 6: prove it with a real crawl (optional)

The smallest useful smoke test is a one-page crawl from a known
root, with a depth of zero:

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py \
  --space ENG --root 12345 --depth 0 --output ./smoke-out
```

Replace `ENG` with a space key you can browse and `12345` with a
page ID inside it. A depth of zero crawls just the root page (and
its attachments unless you also pass `--no-attachments`), so this
finishes in a couple of seconds and you can throw away `./smoke-out`
when you're done.

If the page renders to Markdown and a frontmatter block, you're set.
For the full set of flags and behaviours, see
[Crawl a Confluence space](crawl-a-confluence-space.md).

## What this unlocks

Once `--check` returns 0, you can:

- Use the `confluence-crawler` skill in chat —
  *"crawl the ENG space to `./out` at depth 3"*, *"re-crawl ENG and
  force-refresh every page"*, etc. See the
  [skill's README section](../../../README.md#confluence-crawler)
  for the example-prompt catalogue.
- Run any of the crawl flag combinations end-to-end. The full
  walkthrough lives in
  [Crawl a Confluence space](crawl-a-confluence-space.md).

## What this does **not** unlock

- **Jira read or write access.** Confluence and Jira tokens are
  separate even on Cloud, and the `jira` skill stores its own keys.
  Set it up via [Set up the jira skill](set-up-jira-skill.md) if you
  also need it.
- **Confluence write operations.** This skill is read-only by
  design. There is no create / edit / move / delete page path.
- **Orphan-page or full-space "everything" crawls.** Discovery
  walks the page hierarchy from a root (the space homepage by
  default, or a `--root` you pass). Pages outside that hierarchy
  are not visited.

## Rotating or replacing the token

Tokens are revoked by Atlassian when you regenerate them. To rotate:

1. Generate a new token (step 3).
2. Re-run `setup_credentials.sh` (step 4). It writes a fresh
   `config.env` from scratch — the file is a single skill's
   credentials, not a shared store, so there's no merge step to
   worry about.
3. Re-run `--check` to confirm.

There's no in-place edit path on purpose — the setup script is the
only thing that writes to the per-skill `config.env`.

## In CI

The shared file is not required in CI. Set environment variables
with the same names the file uses and the skill scripts pick them
up:

| Variable | Required | Notes |
|---|---|---|
| `CONFLUENCE_BASE_URL` | yes | Cloud: include `/wiki` (e.g. `https://acme.atlassian.net/wiki`). Server: bare host. |
| `CONFLUENCE_EMAIL` | Cloud only | Atlassian account email. |
| `CONFLUENCE_API_TOKEN` | yes | Cloud API token or Server PAT. |
| `CONFLUENCE_FLAVOR` | no | `cloud` or `server`. Auto-detected from the URL host if unset. |

Environment variables always win over the file, so a developer with
both set sees the env vars used. This makes CI runs and per-shell
overrides straightforward.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `--check` exits 2 immediately, message mentions missing credentials | Neither `~/.config/dropkit/credentials.env` nor `~/.config/confluence-crawler/config.env` is readable, and no `CONFLUENCE_*` env vars are set. | Re-run `setup_credentials.sh`. Confirm the resulting file is at mode 0600. |
| `--check` exits 2 with `401 Unauthorized` | Token rejected. On Cloud: token doesn't match the email — re-confirm both at `id.atlassian.com → API tokens`. On Server: PAT may be revoked or expired. | Regenerate and re-run setup. |
| `--check` exits 2 with `403 Forbidden` | Token is valid but the user can't read `/rest/api/user/current`. Rare for normal accounts; common for service accounts with very narrow permissions. | Use a principal with at least "see your own profile" permission, or grant it. |
| `--check` works, but a crawl exits 2 saying *"space X has no homepage; pass --root <page_id>"* | The space has no homepage configured. The crawler refuses to guess. | Re-run with an explicit `--root PAGE_ID`. See the [crawl guide](crawl-a-confluence-space.md). |
| `--check` works, but `403` on a real crawl | Token's principal lacks browse permission on the target space or on specific pages within it. | Ask the space admin to add browse for your user, or use a service principal. Individual page 403s log as failures and the run continues. |
| TLS error on self-hosted Server / DC | Self-signed or internal-CA cert not in the trust store. | `--insecure` disables verification but **only when the user explicitly asks for it.** Prefer fixing the cert chain. |
| Token pasted as a shell argument never gets captured | The setup script ignores command-line arguments — it only reads from its interactive prompt (with echo off). | Re-run with no arguments; paste the token at the hidden prompt. |
| Cloud base URL missing `/wiki` (you hand-edited the config) | Setup auto-appends `/wiki`, but a manual edit can drop it. All REST calls then 404. | Re-run setup, or restore `/wiki` in the `CONFLUENCE_BASE_URL` line. |

## Security boundary

This is worth stating explicitly because it's the same shape as the
other dropkit secret-handling skills:

- The setup script is the only thing that writes the token.
- The skill's scripts are the only things that read it.
- The agent is contractually instructed not to read `config.env`
  or print the token — this is a `Don't` rule in the skill's
  `SKILL.md`, enforced by agent compliance rather than by code.
- The CLI refuses tokens passed as flags. There is no `--token`
  / `--api-token` / `--bearer` / `--pat` argument, so a misuse
  attempt can't accidentally succeed.

If you are reviewing dropkit before adopting it, those four points
are the boundary that keeps the agent out of your secrets — the
first three rely on agent compliance with the skill contract, the
fourth is the absence of a code path that would even accept the
secret on argv.
