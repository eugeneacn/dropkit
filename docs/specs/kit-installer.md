# Spec: kit-installer

- **Status:** Approved
- **Owner:** eugeneacn
- **Plan:** [`docs/specs/kit-installer-plan.md`](kit-installer-plan.md)
- **Constrained by:** none (dropkit has no ADRs yet)

> **Spec contract:** this document defines what "done" means for the dropkit
> installer. The implementing PR must match this spec, or update it. Tests
> must be derivable from it.

## What this is

A self-contained, network-free, stdlib-only Python script that copies dropkit
skills from the repo into the user's IDE skill location. The user runs
`python install.py --scope claude-code-user` (or any other supported scope)
and ends up with the dropkit skills available to their IDE. The installer
also supports listing, updating, dry-running, and uninstalling, with
checksums tracked in a small bookkeeping file. It never touches the network,
never asks for admin rights, never runs `pip` or `npm`, and never writes
outside its declared scope root.

## Why

Today dropkit installs via `cp -R skills/<category>/<name> ~/.claude/skills/`
— one command per skill per IDE, manually executed. That works for first-time
single-skill installs but breaks down for: installing many skills, switching
IDEs, keeping installs in sync with `git pull`, uninstalling cleanly, and
auditing what was installed. A manifest-driven installer fixes all five
without forcing dropkit's audience (often locked-down corporate environments
with no PyPI access) to install anything else first.

## Users and use cases

In priority order — the first one is the one we will not compromise on:

1. **First-time user installs all dropkit skills to Claude Code (user scope).**
   `python install.py --scope claude-code-user`. Result: every skill lives
   under `~/.claude/skills/<skill-id>/` and is invocable from any project.
   Pip / npm deps for skills that need them are *surfaced* in the post-install
   summary but not installed (user runs the surfaced commands themselves —
   they may be on an air-gapped or proxied network).
2. **Returning user updates installed skills after `git pull`.**
   `python install.py --update`. Result: previously-installed skills get their
   files overwritten where the checksum drifted; nothing new is added; nothing
   not previously installed is touched.
3. **Selective install into a project.**
   `python install.py --scope claude-code-project --skill jira --skill jira-defect-flow`.
   Result: those two skills live under `<cwd>/.claude/skills/` (and any
   cross-skill dep in dropkit is auto-included, e.g. `jira` gets pulled in
   if defect-flow lists it).
4. **Audit what's installed and whether it's current.**
   `python install.py --list`. Result: a table showing each available skill,
   its repo version, and one of `installed`, `not installed`, `outdated`,
   or `modified` (locally edited since install).
5. **Clean uninstall.** `python install.py --uninstall --skill jira` (or
   `--uninstall` for everything). Removes only files the installer wrote;
   refuses to remove files the user has modified unless `--force`.

## Behavior

### Inputs

CLI flags only — no input files, no env vars beyond `HOME`:

```
python install.py --scope <SCOPE> [--path PATH]
                  [--skill ID [--skill ID ...]]
                  [--list | --update | --uninstall]
                  [--dry-run] [--yes] [--force] [--verbose]
```

| Flag | Meaning |
|---|---|
| `--scope` | One of: `claude-code-user`, `claude-code-project`. Required for install and `--uninstall`. Optional for `--list` and `--update` — see scope recovery below. (Cursor / Kiro / Codex / Copilot scopes are deferred to v2; see "Deferred to v2".) |
| `--path` | Project root for `*-project` scopes. Defaults to `cwd`. |
| `--skill ID` | Restrict to named skills (repeatable). If omitted, all skills are in scope. |
| `--list` | Print the catalog with install status. Does not write. |
| `--update` | Re-install currently-installed skills only. Does not install new ones. |
| `--uninstall` | Remove installer-tracked files for the named skills (or all). |
| `--dry-run` | Print actions; perform no writes. |
| `--yes` | Skip confirmation prompts (used for overwrite, uninstall). |
| `--force` | Allow uninstall to remove user-modified files. |
| `--verbose` | Print source→target trace per file. |

Skills are auto-discovered by walking `skills/<category>/<name>/manifest.json`
from the repo root (where `install.py` lives). There is no separate top-level
manifest — each skill's existing `manifest.json` is the source of truth for
its `id`, `version`, `description`, `category`, pip / npm deps, and any
declared cross-skill dependencies.

**Manifest fields the installer reads:**

| Field | Type | Required | Used for |
|---|---|---|---|
| `id` | string | yes | skill identity and scope-root subdir name |
| `version` | string | no (default `"0.0.0"`) | outdated detection (string compare) |
| `description` | string | no | `--list` output |
| `category` | string | no | `--list` output |
| `deps.skills` | `[{name: string, source: string}]` | no | dep resolution |
| `deps.pip` | `string[]` | no | post-install surfacing (see below) |
| `deps.npm` | `string[]` | no | post-install surfacing |
| `targets.default.file` | string | no | explicit single-file install target |

If `targets.default.file` is absent, all files under the skill dir are
included recursively (`SKILL.md`, `manifest.json`, `scripts/`, etc.).

**Scope recovery for `--list` and `--update`.** When run without `--scope`,
both commands derive the scope root from the `scope_root` field recorded in
`installed.json`. The state-root is located via the same XDG / Windows /
project resolution order. If `installed.json` is absent, its `scope_root`
field is missing, or that path does not exist, exit 2 with a message
instructing the user to pass `--scope` explicitly.

### Outputs

**Filesystem writes**, scoped to one of:

| Scope | Resolved root |
|---|---|
| `claude-code-user` | `~/.claude/skills/` |
| `claude-code-project` | `<--path or cwd>/.claude/skills/` |

Each installed skill produces a directory tree mirroring its repo layout:
`<scope-root>/<skill-id>/SKILL.md`, `<scope-root>/<skill-id>/manifest.json`,
`<scope-root>/<skill-id>/scripts/...`, etc. Mode bits are preserved.

**Bookkeeping** in `<state-root>/installed.json`, where the state root is
deliberately *outside* the IDE skill directory so the IDE never sees it.
Resolution order:

- For `*-project` scopes: `<--path or cwd>/.dropkit/installed.json`.
- For `claude-code-user`:
  1. `$XDG_CONFIG_HOME/dropkit/installed.json` if `XDG_CONFIG_HOME` is set.
  2. Otherwise on Unix-like systems (macOS, Linux): `~/.config/dropkit/installed.json`.
  3. On Windows: `%APPDATA%\dropkit\installed.json`.

The user-scope path is intentionally co-located with the existing
`~/.config/dropkit/credentials.env` that the `jira`, `jira-align`, and
`confluence-crawler` skills already use — one dropkit config directory
per user, XDG-compliant on Unix.

`installed.json` shape:

```json
{
  "installer_version": "0.1.0",
  "scope": "claude-code-user",
  "scope_root": "/Users/.../.claude/skills",
  "installed_at": "2026-05-14T10:30:00Z",
  "skills": {
    "jira": {
      "version": "1.0.0",
      "files": [
        { "path": "jira/SKILL.md", "sha256": "..." },
        { "path": "jira/manifest.json", "sha256": "..." }
      ]
    }
  }
}
```

**stdout** carries one line per file written and a summary line at the
end (`Installed 7 skills (32 files) to ~/.claude/skills/`). `--verbose`
adds source→target traces. All errors go to **stderr**.

**Post-install summary** lists pip / npm install commands surfaced from each
installed skill's `manifest.json` `deps.pip` / `deps.npm`. Each line is the
exact command the user should run themselves (e.g.
`pip install -r ~/.claude/skills/jira/requirements.txt`). The installer does
**not** execute these.

`deps.pip` is an array of strings. Each entry is either a bare package name
(`"requests"`) or a path to a requirements file relative to the skill dir
(`"requirements.txt"`). Requirements-file entries surface as
`pip install -r <resolved-install-path>`; bare package names surface as
`pip install <names joined by space>`. If a skill dir contains a
`requirements.txt` and `deps.pip` is absent, the installer surfaces it
automatically. `deps.npm` follows the same shape; file entries surface as
`npm install --prefix <skill-install-dir>`.

`installed.json` writes are atomic: the installer writes to a sibling
`installed.json.tmp` then renames it, so no partial state is visible to
concurrent readers or if the process is interrupted mid-write.

**Exit codes:**

- `0` success (including `--dry-run` and `--list`)
- `1` user aborted at a prompt
- `2` validation error (bad manifest, missing source, path escape, bad flag)
- `3` filesystem error (permissions, disk full)

### Errors and edge cases

- **Path escape.** After resolving every target with `pathlib.Path.resolve()`,
  verify the result is a descendant of the scope root. Reject otherwise →
  exit 2. (Raw `..` segments in target strings are fine if they cancel out
  before resolution; what matters is the post-resolution check.)
- **Source file missing.** A manifest declares a skill, but a file under that
  skill is missing on disk → exit 2 with the offending path.
- **Existing file with different content.** Without `--yes` or `--update`,
  prompt: `overwrite / skip / abort`. Without a TTY, treat as abort → exit 1.
- **Cross-skill dep within dropkit.** Skill A declares `deps.skills: [{name: B}]`.
  Auto-include B in the install set, install B before A. Topological order;
  cycle → exit 2.
- **Cross-skill dep outside dropkit.** Skill A declares a dep on `bug-fix`
  (which lives in agent-ready-repo). Installer cannot satisfy it. Continue
  installing A. Then check the resolved scope root for a directory matching
  the dep's name:
  - If `<scope-root>/<dep-name>/SKILL.md` exists, emit an `INFO`:
    *"external dep 'bug-fix' appears installed at `<path>`. Not installed
    by this installer; not version-checked."*
  - If not, emit a `WARN` naming the external skill and its `source` field
    from the manifest: *"skill X depends on external skill 'bug-fix'.
    Source: agent-ready-repo (.claude/skills/bug-fix/). Install it
    separately."* The installer does not derive or suggest a `git clone`
    command — `source` is install guidance only.
- **`installed.json` corrupt or unreadable.** Treat as "nothing installed";
  proceed; rewrite cleanly on completion. Log a warning.
- **Locally modified file at uninstall time.** A file's current checksum
  differs from `installed.json`'s recorded checksum. Refuse to remove unless
  `--force` is passed. Without `--force`, exit 1.
- **Python < 3.8.** Detect at startup; print a clear message; exit 2.
- **No TTY for prompts.** Treat any prompt as aborted (exit 1) unless `--yes`.
- **Orphaned skill in `installed.json` (stale entry).** A skill that was
  installed but has since been deleted from the repo. `--list` shows it as
  `orphaned`. `--update` ignores it with an `INFO` line. `--uninstall` still
  works using the recorded file list.
- **`--uninstall` with an unknown skill.** `--uninstall --skill <id>` where
  `<id>` is not in `installed.json` → exit 2 naming the unknown skill.

### Wrappers

Two thin wrapper scripts live at repo root. Their only job is to locate the
repo dir and delegate to `install.py`. They must forward all arguments and
propagate the exit code.

```bash
# install.sh
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/install.py" "$@"
```

```powershell
# install.ps1
$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
& python "$ScriptDir\install.py" @args
exit $LASTEXITCODE
```

## Contract tests

The gate for "done". Black-box; any valid implementation must pass all of
them. Each bullet is one test.

### Discovery and listing

- **`test_list_shows_all_skills`** — Given the repo with N skills under
  `skills/*/*/manifest.json`, when `--list` runs, then exactly N non-header
  rows are printed. A header row is printed first and does not count toward N.
  Each row contains the columns `name`, `version`, `category`, and `status`
  in that order (space-aligned). The test strips ANSI escape sequences before
  asserting on column content.
- **`test_list_status_not_installed_by_default`** — Given no `installed.json`,
  when `--list` runs, then every row's status is `not installed`.
- **`test_list_status_installed_after_install`** — Given a successful
  `--scope claude-code-user` install, when `--list` runs again, then those
  skills' status is `installed`.
- **`test_list_status_outdated`** — Given a skill's repo `manifest.json`
  `version` field differs from the recorded version in `installed.json`
  by string comparison (any mismatch, no semver parsing), then `--list`
  shows that skill as `outdated`.
- **`test_list_status_modified`** — Given a previously-installed file whose
  current sha256 differs from the recorded sha256, then `--list` shows that
  skill as `modified`.
- **`test_list_status_orphaned`** — Given a skill in `installed.json` whose
  directory no longer exists in the repo, then `--list` shows it as
  `orphaned`.

### Install (project + user scopes)

- **`test_install_user_scope_writes_to_claude_skills`** — Given
  `--scope claude-code-user --skill jira`, when the install runs, then
  `~/.claude/skills/jira/SKILL.md` exists and matches the repo source byte
  for byte, and mode bits are preserved.
- **`test_install_project_scope_writes_under_path`** — Given
  `--scope claude-code-project --path /tmp/proj --skill jira`, when the
  install runs, then `/tmp/proj/.claude/skills/jira/SKILL.md` exists.
- **`test_install_records_installed_json`** — After a successful install,
  the state-root `installed.json` lists the installed skill, its version,
  and a sha256 per installed file.
- **`test_install_all_skills_by_default`** — Given no `--skill` flag, every
  auto-discovered skill is installed.
- **`test_install_dropkit_dep_pulled_in`** — Given installing
  `jira-defect-flow` whose `deps.skills` lists `jira`, when no explicit
  `--skill jira` is passed, then `jira` is also installed, before
  `jira-defect-flow`.
- **`test_install_external_dep_warns_when_absent`** — Given installing a
  skill whose `deps.skills` references a skill not present in this repo
  AND not present at `<scope-root>/<dep-name>/SKILL.md`, then a `WARN`
  line names the external skill and its `source` field, and the install
  completes successfully (does not refuse).
- **`test_install_external_dep_info_when_present_in_scope`** — Same
  precondition, but `<scope-root>/<dep-name>/SKILL.md` exists. The line
  is `INFO` (not `WARN`) and mentions the discovered path. The installer
  does not read or version-check the discovered SKILL.md.

### State-root resolution

- **`test_state_root_project_under_dropkit_dir`** — Given any `*-project`
  scope with `--path /tmp/proj`, the `installed.json` is written to
  `/tmp/proj/.dropkit/installed.json` regardless of which IDE scope was
  chosen.
- **`test_state_root_user_xdg_when_set`** — Given `XDG_CONFIG_HOME=/tmp/xdg`
  and `--scope claude-code-user`, the `installed.json` is written to
  `/tmp/xdg/dropkit/installed.json`.
- **`test_state_root_user_xdg_default_on_unix`** — On Unix-like platforms
  with `XDG_CONFIG_HOME` unset and `--scope claude-code-user`, the
  `installed.json` is written to `~/.config/dropkit/installed.json`.
- **`test_state_root_user_appdata_on_windows`** — On Windows with
  `--scope claude-code-user`, the `installed.json` is written to
  `%APPDATA%\dropkit\installed.json`.

### Path safety

- **`test_rejects_absolute_target`** — Given a (synthetic) manifest with an
  absolute target path, the installer exits 2 without writing.
- **`test_rejects_target_escaping_scope_root`** — Given a target string that
  resolves outside the scope root (`../etc/passwd`, etc.), the installer
  exits 2.
- **`test_dotdot_within_scope_allowed`** — Given a target like `a/../b`
  that resolves to `<scope>/b`, the installer accepts it.

### Update

- **`test_update_overwrites_changed_files`** — Given a previously-installed
  skill whose repo file now differs from the installed file, `--update`
  overwrites the installed file and refreshes its sha256 in `installed.json`.
- **`test_update_does_not_install_new_skills`** — Given a new skill that
  exists in the repo but is not in `installed.json`, `--update` does **not**
  install it.
- **`test_update_no_op_when_clean`** — Given no drift, `--update` writes zero
  files and exits 0.

### Uninstall

- **`test_uninstall_removes_tracked_files`** — Given an installed skill,
  `--uninstall --skill jira --yes` removes every file tracked in
  `installed.json` and clears that skill's entry.
- **`test_uninstall_refuses_modified_without_force`** — Given an installed
  file whose current sha256 differs from the recorded one,
  `--uninstall --skill jira` exits 1 without removing it.
- **`test_uninstall_force_overrides`** — Same precondition,
  `--uninstall --skill jira --force` removes the file.
- **`test_uninstall_removes_empty_parents`** — After removal, empty parent
  directories under the scope root are removed.
- **`test_uninstall_leaves_unrelated_files`** — Files in the scope root
  that the installer did not write are untouched.
- **`test_uninstall_nonexistent_skill_exits_2`** — Given `--uninstall
  --skill <id>` where `<id>` is not present in `installed.json`, the
  installer exits 2 and names the unknown skill in the error message.

### Dry-run

- **`test_dry_run_writes_nothing`** — `--dry-run` combined with any operation
  (`install`, `--update`, `--uninstall`) makes zero filesystem changes
  (verified by directory hash before/after), exits 0, and prints the actions
  it *would* have taken.

### Pip / npm surfacing

- **`test_pip_deps_surfaced_after_install`** — When a skill with
  `deps.pip` is installed, the post-install summary contains the exact
  `pip install` command needed (with the install path of the skill's
  `requirements.txt` if present).
- **`test_installer_never_runs_pip`** — A test harness that fails on
  any subprocess invocation matching `pip|npm|yarn|pnpm` passes during
  install.

### Wrappers

- **`test_install_sh_passes_args_through`** — `bash install.sh --list`
  produces the same stdout as `python install.py --list`.
- **`test_install_ps1_passes_args_through`** — same, on Windows.

### Prompts and non-TTY

- **`test_prompt_overwrite_aborts_without_tty`** — Given a target collision
  and no `--yes`, with stdin piped from `/dev/null`, the installer exits 1
  without writing.

### Python compatibility

- **`test_runs_on_python_3_8`** — Installer module imports and `--list`
  works on Python 3.8 without `SyntaxError` or stdlib AttributeError.

## Non-goals

Explicit anti-scope — the installer **will not**:

- Run `pip install`, `npm install`, or any other package manager.
- Resolve, download, or install dependencies from outside dropkit (e.g.
  the `bug-fix` skill in agent-ready-repo).
- Modify `~/.bashrc`, `~/.zshrc`, `~/.profile`, `PATH`, or any shell config.
- Require admin / `sudo` / elevated privileges.
- Manage multiple dropkit checkouts on the same machine (each clone's
  installer manages its own state).
- Run `setup_credentials.sh` for skills with secrets (jira, jira-align,
  confluence-crawler). The skills' own SKILL.md tells the user to run it
  themselves — that contract stays.
- Auto-update from a remote (no network). `git pull` followed by
  `--update` is the upgrade path.
- Replace the manual `cp -R` install. That continues to work and is
  documented as the alternative for users who don't want a Python script.
- Validate skill content (SKILL.md schema, eval pass rate, etc.) — that's
  a CI concern, not an installer concern.
- Install skills from arbitrary file paths or URLs. Source is always
  `skills/*/*/` under the installer's own repo root.

## Decisions

These are the resolved answers to the open questions raised during spec
review. Each became part of the Behavior or Contract tests above.

1. **v1 IDE scopes: Claude Code only** (`claude-code-user` and
   `claude-code-project`). Cursor, Kiro, Codex, and Copilot all deferred
   to v2 — see "Deferred to v2".
2. **State-root: `~/.config/dropkit/` (XDG-compliant), `%APPDATA%\dropkit\`
   on Windows.** Co-located with the existing `credentials.env`. Honor
   `XDG_CONFIG_HOME` if set.
3. **"Outdated" detection: string mismatch on the `version` field.** No
   semver parser. If the strings don't match, the skill is outdated.
   Direction (upgrade vs. downgrade) is irrelevant — `--update` re-copies
   in either case.
4. **Cross-skill deps:**
   - **Dropkit-internal**: auto-include, topologically ordered. Print the
     pulled-in skill name in the install summary so the user can see what
     was added on their behalf.
   - **External (e.g. `bug-fix` in agent-ready-repo)**: never install,
     never fetch. Check `<scope-root>/<dep-name>/SKILL.md` for presence:
     emit `INFO` if found (with the discovered path), `WARN` with the
     manifest's `source` field if not. The installer does not suggest a
     `git clone` command or any other remediation step.
5. **No sidecar files for Kiro / Codex in v1** — they're deferred
   entirely. When added in v2, ship as skill-dir-only first; add steering
   / sidecar generators only if users request them.
6. **Cursor `.mdc` body** (v2): `description` from the skill manifest,
   `globs:` empty, `alwaysApply: false`, body references
   `.cursor/skills/<skill-id>/SKILL.md`. Matches the README guidance.
7. **Copilot scope dropped from v1.** No equivalent of Claude Code's
   skill directory exists in Copilot today. Re-spec when GitHub
   publishes a stable skill / agent layout.

## Deferred to v2

Captured here so the design context isn't lost:

- **Additional IDE scopes:** `cursor-project`, `kiro-project`,
  `codex-project`, `copilot-project`. The two with sidecar generators
  (Cursor's `.mdc` rule, Copilot's `.prompt.md` reusable prompt) carry
  the most extra complexity; Kiro / Codex are mostly skill-dir copies.
- **Strict semver outdated detection.** Replace the v1 string-mismatch
  rule with a stdlib-only MAJOR.MINOR.PATCH parser if direction-aware
  status (`upgrade-available` vs `downgrade-available`) becomes useful.
- **Linked-repo support** for cross-repo cross-skill deps:
  ```
  python install.py --link-repo agent-ready-repo=/path/to/agent-ready-repo
  python install.py --scope claude-code-user --skill jira-defect-flow
  # would auto-install bug-fix from the linked repo
  ```
  Brings real complexity: link-config persistence, schema requirements
  for linked repos, name-collision resolution, version conflicts across
  links. Defer until at least one user asks.
- **`copilot-user` scope.** VS Code's user-level Copilot configuration
  isn't a filesystem path the installer can write to today. Revisit if
  that changes.

## Acceptance criteria

The non-test checklist for "done":

- [ ] All Contract tests above pass on macOS, Linux, and Windows (CI matrix).
- [ ] `install.py` is ≤ 500 lines. If it exceeds 500, split into helper
      modules under `installer/` but keep `install.py` as the entry point.
- [ ] `install.sh` and `install.ps1` shipped as shown in the source
      instruction.
- [ ] `README.md` updated with three primary usage patterns: clone + install
      (user), clone + install (project), and `--list` + selective install.
      The existing `cp -R` instructions stay, demoted to "alternative".
- [ ] String-mismatch outdated detection used (no semver parser added).
- [ ] User-scope state at `$XDG_CONFIG_HOME/dropkit/` →
      `~/.config/dropkit/` → `%APPDATA%\dropkit\` (in that resolution
      order); project-scope state at `<project>/.dropkit/`.
- [ ] No new top-level repo dirs beyond `docs/` (already added for this
      spec) — installer lives at repo root; bookkeeping at the per-scope
      state-root described above.
- [ ] Existing skills install identically to current manual `cp -R` —
      diffing `~/.claude/skills/jira/` after installer-install vs
      manual-install shows zero file content differences.
