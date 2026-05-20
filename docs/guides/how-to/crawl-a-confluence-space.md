# How to crawl a Confluence space

Export an authenticated Confluence space — or a subtree of one —
to local Markdown files with YAML frontmatter. The crawler walks
the page hierarchy from a root, converts each page's storage-format
XHTML to Markdown, downloads attachments, and rewrites internal
links to relative `.md` paths where it can.

This guide is task-oriented: how to invoke the crawler for the
common shapes (whole space, subtree, refresh) and how to interpret
what it writes. The full skill contract lives in
[`SKILL.md`](../../../skills/crawlers/confluence-crawler/SKILL.md);
the auth and one-time setup live in
[Set up the confluence-crawler skill](set-up-confluence-crawler-skill.md).

## Before you start

1. **The skill is set up.** Run
   `python skills/crawlers/confluence-crawler/scripts/crawl_space.py --check`.
   Exit 0 → proceed. Exit 2 → finish
   [Set up the confluence-crawler skill](set-up-confluence-crawler-skill.md)
   first.
2. **You know which space to crawl** and have browse permission on
   it. A token that authenticates against `whoami` but doesn't have
   the space's browse permission will fail with 403 once the crawl
   actually reads pages — the failure is per-page and the run
   continues, but the output will be empty.
3. **You have somewhere to put the output.** The default is
   `./confluence-out` under the current working directory. The
   crawler creates parents as needed.

This skill is independent of every other dropkit skill. You do not
need `jira`, `jira-align`, or anything else set up to use it.

## Invoking the skill

In Claude Code, the simplest invocation is:

> *"Crawl the ENG space to `./out` at depth 3."*

or, if you have a slash binding:

```
/confluence-crawler --space ENG --depth 3 --output ./out
```

In other IDEs, use whatever skill / rule dispatch mechanism applies.
The agent runs the underlying CLI for you:

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py \
  --space ENG --depth 3 --output ./out
```

## Common shapes

### Crawl an entire space

The default root is the space homepage. The default depth is
unlimited.

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py --space ENG --output ./eng
```

For thousands of pages, the discovery walk is the slow part:
Confluence doesn't tell you in advance whether a page has children,
so the crawler issues at least one `child/page` listing call per
*visited* page that isn't already at the depth cap, plus a follow-up
call for every additional batch of 50 children. (Pages popped at
`--depth N` are recorded but not listed further.) Expect a minute
or two before the first page is written. Fetching itself runs
concurrently, bounded by `--concurrency` (default 4) and
`--min-delay-ms` (default 100 ms) for rate-limit-friendly
behaviour.

### Crawl a subtree from a specific page

When you only want a portion of the space — a single product area, a
runbook collection — pass `--root PAGE_ID` and (optionally)
`--depth N` to cap how far down the hierarchy you go.

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py \
  --space ENG --root 818193 --depth 2 --output ./runbooks
```

`--depth` is measured in **page hierarchy hops** (parent → child),
not in link hops. Depth `0` means just the root page; depth `1`
adds its direct children; and so on.

### Refresh an existing crawl

Re-running with the same `--output` directory is idempotent:

- The crawler reads each existing `*.md` file's frontmatter.
- It compares the recorded `version` to Confluence's current
  `version.number`.
- Unchanged pages are skipped entirely (no fetch).
- Changed pages are re-fetched and overwritten.

For a typical large space, a refresh is dominated by the discovery
walk — the cost of finding out *which* pages changed. Once that's
done, only changed pages cost network time.

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py --space ENG --output ./eng
```

To bypass the version check and re-fetch every page (e.g. after
upgrading the skill and wanting a fresh conversion run):

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py --space ENG --output ./eng --force
```

### Skip attachments

Attachment downloads can dominate runtime on image-heavy spaces. If
you only need the text:

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py --space ENG --output ./eng --no-attachments
```

`--no-attachments` skips the per-page attachment listing call as
well as the downloads, so it's also faster on the discovery side.

### Get debug logs

Add `--verbose` (or `-v`) to switch logging from `INFO` to `DEBUG`.
Useful when discovery looks stuck, individual pages fail without a
clear reason, or you want to see every REST call:

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py \
  --space ENG --output ./eng --verbose
```

The token never appears in the log output at any level.

### Crawl an on-prem Server / DC space with a self-signed cert

`--insecure` disables TLS verification. **Use only when the user
explicitly accepts the risk** — typically a private network with an
internal CA the local machine doesn't trust:

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py \
  --space ENG --output ./eng --insecure
```

The right long-term fix is to install the internal CA into the
machine's trust store, not to keep `--insecure` on.

## What gets written

The output directory uses a flat layout — one Markdown file per
page, regardless of hierarchy depth. Hierarchy is preserved in
frontmatter (`parent_id`), not in directory structure.

```
./out/
├── architecture-overview.md
├── deployment-runbook.md
├── postmortems-q3-2026.md
├── ...
└── attachments/
    ├── 818193/
    │   └── topology.png
    └── 818240/
        └── postmortem-2026-09-12.pdf
```

Each `*.md` file starts with a YAML frontmatter block:

```yaml
---
title: Architecture Overview
confluence_id: '818193'
space_key: ENG
version: 7
updated: '2026-04-18T13:22:01.000Z'
author: e.lim
parent_id: '818100'
labels:
  - architecture
  - reference
url: https://acme.atlassian.net/wiki/spaces/ENG/pages/818193/Architecture+Overview
slug: architecture-overview
---

# Architecture Overview

…page body in Markdown…
```

The full field set is `title`, `confluence_id`, `space_key`,
`version`, `updated`, `author`, `parent_id`, `labels`, `url`,
`slug`. A few of them carry behaviour worth calling out:

| Field | Notes |
|---|---|
| `confluence_id` | The page's stable Confluence ID. Used as the idempotency key on re-crawls. |
| `version` | The Confluence `version.number`. A refresh re-fetches only when the server's number is **greater than** this. |
| `slug` | Derived from `title` via `python-slugify`, with the *base* slug capped at 80 characters. If multiple pages produce the same base slug, the first claims it and the rest get a `-<page_id>` suffix appended — that suffix can push the final filename past 80 characters. |
| `parent_id` | The page's immediate parent in the Confluence hierarchy, or `null` for the root of the crawl. |
| `url` | The original Confluence webui URL, useful when the Markdown is later ingested into a search index. |

The final log line reports something like:

```
wrote 247 pages (failed: 3, skipped: 18)
```

Relay this to the user if they're driving you through chat. The
exit code is `0` if `failed` is zero, `1` otherwise.

## Macros, links, and attachments

These are the three areas where Confluence storage format is
lossy when projected into Markdown. The crawler's defaults are:

- **Macros.** An allowlist (`code`, `info`, `warning`, `note`,
  `tip`, `panel`, `expand`, `status`) are converted to Markdown
  equivalents:
  - `code` becomes a fenced code block (the language attribute is
    preserved when present).
  - `info` / `warning` / `note` / `tip` / `panel` become a
    blockquote led by a bold `[LABEL]` (and the macro's title, if
    any) — `markdownify` doesn't emit GFM admonitions, so this is
    the closest faithful shape.
  - `expand` becomes a bold title line followed by a blockquote
    body. `<details>` / `<summary>` would be ideal but
    `markdownify` strips them, so the converter renders an
    equivalent that survives.
  - `status` becomes a **bold** `[LABEL]` inline, where the label
    is the macro's title, or its colour (Confluence's storage
    format uses the British spelling `colour`), or the literal word
    `STATUS` as a last resort.

  Anything outside the allowlist is replaced with a visible italic
  marker — `*[confluence macro not rendered: NAME]*` — so a human
  reviewer can spot the gap. The page does not silently lose
  content.
- **Internal links** to pages that are also in this crawl set become
  relative `.md` paths (e.g. `[Architecture Overview](architecture-overview.md)`).
  Internal links to pages **outside** the crawl set remain as
  absolute Confluence URLs. This is by design — a relative `.md`
  link to a file that doesn't exist would be a broken local link.
- **Attachments** are downloaded into `attachments/<page_id>/<filename>`
  and rewritten to relative paths in the Markdown body. Skipped
  entirely with `--no-attachments`.

## Re-crawl semantics worth knowing

A few corners that surprise people:

- **Title changes leave behind the old file.** Slugs derive from
  the current title. If a page is renamed, the next run writes a
  new `<new-slug>.md` but does **not** delete the old
  `<old-slug>.md` — the crawler only adds and updates, never deletes
  on its own. Clean up manually if you care.
- **Orphan pages are skipped.** A page that isn't reachable from the
  crawl root (parent-of-parent-of-…) is not visited, even if you
  can browse it. If you need orphans, run the crawler again with
  `--root` pointing at the orphan.
- **Page deletions on the server don't propagate.** If Confluence
  deletes a page, its `.md` file stays in `./out` until you remove
  it. The crawler has no opinion about old files it didn't write
  this run.
- **Per-page failures don't abort the run.** 403s, 401s, 5xxs (after
  retries are exhausted), and conversion errors on individual pages
  are caught per-task, logged, and counted in the `failed:` number;
  the run continues. Two paths *do* abort early because they happen
  before per-task fetching: missing credentials (clean exit `2`)
  and an auth error on the very first REST call (homepage lookup or
  the root page's `get_page`) — that one currently escapes as an
  uncaught `AuthError` traceback rather than a clean exit code, so
  if you see a Python stack trace on startup, treat it as "the
  token authenticated for `whoami` but not for reading the space's
  root." If your `whoami` works *and* the root page reads, but every
  subsequent page 401s, you'll see a clean exit `1` with all pages
  marked failed — re-check the token's permissions rather than the
  token itself.

## Common failure modes

| Symptom | Likely cause | Fix |
|---|---|---|
| `space X has no homepage; pass --root <page_id>` and exit 2 | The space has no homepage configured. | Pick a page in the space manually and pass it via `--root`. |
| Lots of `attachment X on page Y failed` warnings | A specific attachment is unreadable (size limit, expired CDN URL, deleted between listing and download). | These don't fail the run. If you need 100% attachment coverage, re-run after the warnings — Confluence often heals these transiently. |
| `wrote 0 pages (failed: N, skipped: 0)` | Token authenticates but lacks browse on the space's pages. Every fetch 403s and is logged. | Grant the principal browse, or use a service account that already has it. |
| `*[confluence macro not rendered: …]*` markers scattered through the output | The page uses a macro outside the allowlist. | Decide whether the missing content matters. If it's something common in your environment, propose adding it to `ALLOWED_MACROS` in `scripts/_convert.py`. |
| Hangs on discovery for a long time | Very large space; discovery issues at least one `child/page` listing call per visited page that isn't already at the depth cap, plus a follow-up call per additional batch of 50 children. | Wait, or scope down with `--root` + `--depth`. |
| `429 Too Many Requests` warnings, retried automatically | You're sharing the API quota with other consumers, or the default 4-way concurrency is too high for your tier. | Drop `--concurrency` or raise `--min-delay-ms`. The retries respect `Retry-After`. |
| TLS error on Server / DC | Self-signed / internal-CA cert not in the trust store. | Add the CA, or use `--insecure` only with explicit user consent. |

## What this does **not** do

- **Write to Confluence.** The skill is read-only. There is no
  flag, subcommand, or code path that creates or edits pages.
- **Full-text search across what it crawled.** The crawler writes
  Markdown; indexing and search are a downstream concern. The
  frontmatter is designed to be ingestion-friendly for tools that
  do.
- **Crawl other Atlassian products** — Jira issues, Compass, Jira
  Service Management, etc. Those have their own skills (see
  [`jira`](set-up-jira-skill.md)) or no skill at all.
- **Diff or summarise changes between two runs.** A refresh updates
  files in place. If you want a changelog, run the crawler against
  a versioned output directory or commit the output into git and
  diff there.

## CI usage

Set environment variables instead of relying on the config file:

```yaml
env:
  CONFLUENCE_BASE_URL: ${{ secrets.CONFLUENCE_BASE_URL }}
  CONFLUENCE_EMAIL:    ${{ secrets.CONFLUENCE_EMAIL }}   # Cloud only
  CONFLUENCE_API_TOKEN: ${{ secrets.CONFLUENCE_API_TOKEN }}
```

A typical CI pattern is to commit the output directory and let the
crawler keep it in sync on a schedule — the version-aware
idempotency means each run only fetches what changed.

```bash
python skills/crawlers/confluence-crawler/scripts/crawl_space.py \
  --space ENG --output ./docs/imports/confluence-eng
```

The exit code is `0` on a clean run and `1` when at least one page
failed. Fail the build on `1` if you treat a missing page as a
hard error; tolerate `1` if you're happy to log warnings and move
on.
