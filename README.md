# dropkit

A portable registry of AI skills and agents. Install into Claude Code, Kiro, Cursor, or any AI-powered IDE by copying a directory.

Each skill is a self-contained folder under `skills/<category>/<skill-name>/` with:

- `SKILL.md` — the agent playbook (what the agent reads and follows)
- `manifest.json` — machine-readable metadata (id, deps, I/O)
- `scripts/` — the code the agent invokes; heavy lifting lives here
- optional `requirements.txt` / package install line declared in the manifest

## Catalog

| Skill | Category | Purpose | Deps |
|---|---|---|---|
| [api-contract](skills/contracts/api-contract/) | contracts | Generate OpenAPI 3.1 contracts from natural language, code, or SQL, enforcing 138 Zalando RESTful API Guidelines rules. | none |
| [kafka-event-schema](skills/contracts/kafka-event-schema/) | contracts | Generate Avro, JSON Schema, or Protobuf event schemas with metadata envelopes, compatibility rules, and Schema Registry integration. | none |
| [docx-to-markdown](skills/converters/docx-to-markdown/) | converters | Convert Word `.docx` files to clean Markdown preserving headings, lists, tables, and formatting. | npm `mammoth` |
| [markdown-to-html](skills/converters/markdown-to-html/) | converters | Convert Markdown to styled, self-contained HTML with syntax highlighting, TOC, and responsive layout. | npm `marked`, `highlight.js` |
| [msg-to-markdown](skills/converters/msg-to-markdown/) | converters | Convert Outlook `.msg` emails to structured Markdown preserving headers, body, and attachment metadata. | npm `@nicecode/msg-reader` |
| [pdf-to-markdown](skills/converters/pdf-to-markdown/) | converters | Convert PDF files to structured Markdown using positional text extraction to detect headings, paragraphs, lists, and tables. | npm `pdfjs-dist` |
| [pptx-to-markdown](skills/converters/pptx-to-markdown/) | converters | Convert PowerPoint files to Markdown preserving slide hierarchy, titles, bullet nesting, tables, and speaker notes. | npm `jszip`, `fast-xml-parser` |
| [xlsx-to-markdown](skills/converters/xlsx-to-markdown/) | converters | Convert Excel spreadsheets to Markdown tables with multi-sheet support, header detection, and date formatting. | npm `xlsx` |
| [confluence-crawler](skills/crawlers/confluence-crawler/) | crawlers | Crawl an authenticated Confluence space (Cloud or Server/DC) by hierarchy and convert pages to Markdown with frontmatter. Handles macros, attachments, link rewriting, depth limits, and idempotent re-crawling. | pip (see `requirements.txt`) |
| [jira-align](skills/integrations/jira-align/) | integrations | Read and mutate Jira Align REST API 2.0 (Cloud or self-hosted) — get/list/search, create/update (PUT or PATCH)/delete, and raw calls. OData `$filter` / `$select` / `$orderby` / `expand`, automatic pagination, JSON-parsed `--field KEY=VALUE` inputs, JSON/JSONL/CSV output. Bearer-token auth; agent never sees the token; `delete` requires `--yes`. | pip (see `requirements.txt`) |

---

## Installing a skill into your IDE

Each skill is a plain directory. Installation is always the same two steps: **(1) copy the skill folder into your IDE's skills location**, then **(2) install the skill's dependencies** (the commands are in `manifest.json` under `deps`).

### Claude Code

Claude Code reads skills from two locations:

- **User-scope** (available in every project): `~/.claude/skills/<skill-name>/`
- **Project-scope** (tracked with the repo): `<project>/.claude/skills/<skill-name>/`

Install a skill by copying its folder — drop the directory directly into the skills location, not its parent category folder:

```bash
# user-scope (recommended)
mkdir -p ~/.claude/skills
cp -R skills/converters/pdf-to-markdown ~/.claude/skills/

# project-scope
mkdir -p .claude/skills
cp -R skills/converters/pdf-to-markdown .claude/skills/
```

Claude Code discovers the skill via its `SKILL.md` frontmatter `name` field. Invoke it in chat with `/<skill-name>` or by describing the task — Claude will route to the matching skill automatically.

### Cursor

Cursor does not have a native "skills" concept, but you can install a skill as a project rule:

1. Copy the skill folder somewhere in the repo (e.g. `.cursor/skills/<skill-name>/`).
2. Create `.cursor/rules/<skill-name>.mdc` that references `SKILL.md`:

   ```
   ---
   description: <paste the skill's description from manifest.json>
   globs:
   alwaysApply: false
   ---
   Follow the instructions in .cursor/skills/<skill-name>/SKILL.md when the user requests this task.
   ```

3. In chat, attach `SKILL.md` with `@` or invoke the rule by describing the task.

### Kiro

Kiro supports agent instructions via steering files and custom agents:

1. Copy the skill folder to `.kiro/skills/<skill-name>/`.
2. Add a steering file at `.kiro/steering/<skill-name>.md` that points Kiro to the skill's `SKILL.md` when the matching task is requested.

Alternatively, paste the contents of `SKILL.md` into a custom Kiro agent definition.

### Other IDEs (Continue, Cline, Aider, etc.)

These tools don't have a standard skills directory. Use one of these patterns:

- **Context attachment**: copy the skill folder anywhere in the repo, then attach `SKILL.md` to your prompt and ask the agent to follow it.
- **Custom prompt/agent**: paste `SKILL.md` into the IDE's custom-agent or system-prompt configuration.

In all cases, the scripts are invoked from the copied folder, so keep the directory structure intact.

### Installing dependencies

Each skill declares its deps in `manifest.json`:

- `deps.npm` — run `npm install <packages>` before using the skill (or let `SKILL.md` Step 1 install them on demand).
- `deps.pip` — run `python -m pip install -r <skill>/requirements.txt`.

Most skills' `SKILL.md` includes a verify-and-install step so dependencies are handled on first use.

---

## Skill usage

All skills are invoked in chat. Arguments are passed as plain text after the skill's trigger phrase (or via `$ARGUMENTS` when invoked as a slash command in Claude Code).

### api-contract

Generate an OpenAPI 3.1 contract.

- **Input**: natural language description, or a path to source code / SQL that describes the API surface.
- **Output**: `.yaml` or `.json` OpenAPI document.
- **Example prompt**: *"Generate an OpenAPI contract for a users CRUD API with pagination and idempotent POST."*

### kafka-event-schema

Generate a Kafka event schema (Avro / JSON Schema / Protobuf).

- **Input**: event description, or path to existing schema / source code.
- **Output**: `.avsc`, `.json`, `.proto`, or `.yaml` (AsyncAPI).
- **Example prompt**: *"Generate an Avro schema for an OrderPlaced event with a standard metadata envelope."*

### docx-to-markdown

Convert a Word document to Markdown.

- **Install deps**: `npm install mammoth`
- **Example prompt**: *"Convert docs/spec.docx to Markdown."*

### markdown-to-html

Convert a Markdown file to styled HTML.

- **Install deps**: `npm install marked highlight.js`
- **Example prompt**: *"Render notes/weekly.md as a self-contained HTML page with TOC."*

### msg-to-markdown

Convert an Outlook `.msg` email to Markdown.

- **Install deps**: `npm install @nicecode/msg-reader`
- **Example prompt**: *"Convert inbox/2026-03-customer-escalation.msg to Markdown."*

### pdf-to-markdown

Convert a PDF to Markdown using positional text extraction.

- **Install deps**: `npm install pdfjs-dist@4.7.76`
- **Example prompt**: *"Convert docs/whitepaper.pdf to Markdown."*

### pptx-to-markdown

Convert a PowerPoint deck to Markdown, preserving slide structure.

- **Install deps**: `npm install jszip fast-xml-parser`
- **Example prompt**: *"Convert decks/q2-review.pptx to Markdown."*

### xlsx-to-markdown

Convert an Excel spreadsheet to Markdown tables.

- **Install deps**: `npm install xlsx`
- **Example prompt**: *"Convert data/sales.xlsx to Markdown, one table per sheet."*

### confluence-crawler

Crawl an authenticated Confluence space and write each page as Markdown with YAML frontmatter. Supports Atlassian Cloud and on-prem Server/Data Center.

- **Install deps**: `python -m pip install -r skills/crawlers/confluence-crawler/requirements.txt`
- **Get an access token** (required before running setup):

  - **Atlassian Cloud** — go to https://id.atlassian.com/manage-profile/security/api-tokens, click **Create API token**, name it, and copy the value. Authentication uses your Atlassian account email plus this token.
  - **Server / Data Center (on-prem)** — in Confluence, click your avatar → **Profile** → **Personal Access Tokens** → **Create token**. Name the token, set an expiry, click **Create**, and copy the value shown (it is only displayed once). Authentication uses the token as a bearer credential; no email is required.

- **One-time setup** (interactive — prompts for base URL, email if Cloud, and the token from the step above; writes `~/.config/confluence-crawler/config.env` at mode 0600):

  ```bash
  bash skills/crawlers/confluence-crawler/scripts/setup_credentials.sh
  ```

- **Verify connectivity**:

  ```bash
  python skills/crawlers/confluence-crawler/scripts/crawl_space.py --check
  ```

- **Example prompts**:
  - *"Crawl the ENG space to ./out at depth 3."*
  - *"Re-crawl ENG, forcing a refresh of every page."* (uses `--force`)

Flags: `--space KEY` (required), `--root PAGE_ID`, `--depth N`, `--output DIR`, `--force`, `--no-attachments`, `--concurrency N`, `--insecure`, `--check`, `--verbose`. The API token is never accepted on the command line.

### jira-align

Read and mutate Jira Align (Cloud or self-hosted) via the REST API 2.0 — fetch, list, filter, create, update, and delete records. Returns results as JSON/JSONL/CSV; automatic pagination; OData-style filtering.

- **Install deps**: `python -m pip install -r skills/integrations/jira-align/requirements.txt`
- **Get an access token** (required before running setup; same flow for both flavors):

  1. Sign in to your Jira Align instance (Cloud at `https://<site>.jiraalign.com`, or your self-hosted URL).
  2. Click your avatar in the top navigation bar → **Profile**.
  3. On the Profile page, find the **API Token** section and click **Generate** (or **Regenerate** if one already exists).
  4. Copy the token value — it is only shown once. Tokens do not expire by time; they remain valid until regenerated or until the user is deactivated.

  If you are on self-hosted and the API Token section is missing, ask an administrator: some on-prem installs require `EnableApiTokens` to be turned on in the system configuration before users can generate tokens.

- **One-time setup** (interactive — prompts for base URL and the token; writes `~/.config/dropkit/credentials.env` at mode 0600, merged with any existing dropkit credentials):

  ```bash
  bash skills/integrations/jira-align/scripts/setup_credentials.sh
  ```

- **Verify connectivity**:

  ```bash
  python skills/integrations/jira-align/scripts/jira_align.py check
  ```

- **Example prompts**:
  - *"Show me the 20 most recently modified in-progress features in program 42."*
  - *"Export every team to `teams.jsonl`."*
  - *"Fetch epic 1001 with the owner and milestones expanded."*
  - *"Create a new feature titled 'Onboarding revamp' in program 42 owned by user 77 at 8 points."*
  - *"Change feature 789's state to In Progress and set points to 13."*

Subcommands: `check`, `whoami`, `get RESOURCE ID`, `list RESOURCE [--filter --select --orderby --expand --limit --page-size]`, `search RESOURCE QUERY`, `create RESOURCE [--data-file FILE] [--field KEY=VALUE]`, `update RESOURCE ID [--method PUT|PATCH] [--data-file FILE] [--field KEY=VALUE]`, `delete RESOURCE ID --yes`, `raw METHOD PATH [--param k=v] [--data-file FILE]`. Global flags: `--format json|jsonl|csv`, `--output FILE`, `--insecure`, `--verbose`. `--field` values are JSON-parsed (so `--field points=8` sends an integer). The API token is never accepted on the command line; `delete` refuses to run without `--yes`.

---

## Shared credential file

Skills that call authenticated third-party APIs read their secrets from a shared file at `~/.config/dropkit/credentials.env` (mode 0600). Each skill namespaces its keys (e.g. `JIRAALIGN_*` for jira-align). Re-running any skill's `setup_credentials.sh` only rewrites that skill's own keys — other skills' entries are preserved. The legacy per-skill path `~/.config/confluence-crawler/config.env` is still read for backward compatibility.

Environment variables of the same name always take precedence over the file, which makes CI use straightforward: set the vars in the job and skip the setup script entirely.

---

## Repository layout

```
dropkit/
  skills/
    <category>/
      <skill-name>/
        manifest.json     # metadata + deps + targets
        SKILL.md          # agent playbook
        scripts/          # executable logic
        requirements.txt  # (when pip-based)
  scripts/                # repo-level tooling
  targets/                # IDE-specific output helpers
```

Contributions: add a new skill under the appropriate category (or create one). Match the existing manifest shape and keep agent instructions in `SKILL.md` thin — the scripts should own the logic.
