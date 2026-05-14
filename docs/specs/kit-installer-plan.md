# Plan: kit-installer

- **Spec:** [`docs/specs/kit-installer.md`](kit-installer.md)
- **Status:** Drafting <!-- Drafting | Executing | Done -->

> **Plan contract:** this is the implementation strategy. Unlike the spec, this
> document is allowed to change as you learn. When it changes substantially
> (a different approach, not just a re-ordering), note why in the changelog
> at the bottom.

## Approach

Twelve sequentially-ordered tasks, each sized to be a coherent commit. The
first two tasks establish the scaffold and discovery layer independently. The
state-root (T3) and path-safety (T5) tasks are independent of each other and
of the feature tasks, making them safe to land early. T6 (install core) is the
load-bearing task — every command (`--update`, `--uninstall`, `--dry-run`) adds
a layer on top of it. Dep resolution (T7) is a post-install extension, not a
pre-install gate, so it slots in after core is tested. Wrappers and CI land
last. No third-party libraries at any point; `pathlib`, `shutil`, `hashlib`,
`json`, `argparse`, `os`, `sys`, and `subprocess` only.

The 500-line budget is enforced at every task. If `install.py` approaches
the limit, overflow into `installer/` submodules (keeping `install.py` as
the entry point).

## Constraints

No ADRs exist in dropkit yet. The decisions recorded in the spec's "Decisions"
section govern all ambiguous cases. The most binding:

- Scope names are exactly `claude-code-user` and `claude-code-project` in v1.
- State root: XDG → `~/.config/dropkit/` → `%APPDATA%\dropkit\` for user
  scope; `<project>/.dropkit/` for project scope. Honor `XDG_CONFIG_HOME`.
- Outdated detection is string equality on the `version` field; no semver.
- External dep handling is INFO/WARN only; no `git clone` suggestion.
- `install.py` ≤ 500 lines; split into `installer/` if needed.

## Construction tests

Cross-cutting tests that span multiple tasks. Per-task tests are listed under
each Task below.

**Integration tests:**

- `test_full_happy_path_user_scope` — fixture repo with two skills (A, B,
  where B's `deps.skills` lists A); `--scope claude-code-user --yes` installs
  both in dep order to a temp home; `--list` reports both `installed`; mutate
  one file in the temp home; `--update` re-copies only the drifted file;
  `--uninstall --yes` removes all tracked files; `--list` reports both
  `not installed`. All filesystem writes use a monkeypatched home.
- `test_full_happy_path_project_scope` — same fixture, `--scope
  claude-code-project --path /tmp/proj --yes`; asserts writes under
  `/tmp/proj/.claude/skills/`.
- `test_windows_path_separators` — on non-Windows, mock
  `platform.system()` → `"Windows"` and `os.environ["APPDATA"]`; verify
  `installed.json` is written to the mocked `%APPDATA%\dropkit\` path.
  Paths stored in `installed.json` use forward slashes for portability.

**Manual verification:**

- After `test_full_happy_path_user_scope`, diff the installed skill directory
  against a manual `cp -R` result — zero file-content differences.

## Tasks

### T1: Scaffold — entry point, argparse, Python version guard

**Depends on:** none

**Tests:**

- `test_runs_on_python_3_8` — contract test; see spec. Verified here by
  invoking `install.py` with a Python 3.8 interpreter via `subprocess`.
- `test_python_version_guard_exits_2` — monkeypatch `sys.version_info` to
  `(3, 7)`; calling `main()` exits 2 and prints a message to stderr.
- `test_help_exits_0` — `python install.py --help` exits 0 and mentions
  `--scope`, `--skill`, `--list`, `--update`, `--uninstall` in output.
- `test_unknown_flag_exits_2` — `python install.py --bogus` exits 2.
- `test_scope_required_for_plain_invocation` — `python install.py` with no
  flags exits 2 with a message naming `--scope`.

**Approach:**

- Create `install.py` at repo root with `__version__ = "0.1.0"`.
- Version check at module top: `sys.version_info < (3, 8)` → stderr + `sys.exit(2)`.
- `build_parser()` returns a configured `ArgumentParser` with all flags from
  the spec. Stubs: every path calls `sys.exit(0)` with "not yet implemented".
- `if __name__ == "__main__": main()` guard.

**Done when:** all five tests green on Python 3.8 and 3.12.

---

### T2: Skill discovery — walk `skills/*/*/manifest.json`

**Depends on:** T1

**Tests:**

- `test_discover_all_skills` — fixture tree with three skills in two
  categories; `discover_skills(repo_root)` returns three `Skill` objects
  with correct `id`, `version`, `category`, `description`.
- `test_discover_skips_non_skill_dirs` — dirs under `skills/<cat>/` without
  `manifest.json` are silently skipped.
- `test_discover_exits_2_on_bad_json` — malformed `manifest.json` → stderr
  message naming line/column → exit 2.
- `test_discover_exits_2_on_missing_id` — `manifest.json` without `id`
  field → exit 2.
- `test_discover_resolves_files_list` — skill with `targets.default.file`
  produces a `Skill.files` list resolved relative to the skill dir. Skills
  without that field include all files under the skill dir recursively.

**Approach:**

- `Skill` dataclass: `id`, `version`, `description`, `category`,
  `source_dir: Path`, `files: list[Path]`, `deps_skills: list[str]`,
  `deps_pip: list[str]`, `deps_npm: list[str]`.
- Walk `Path(repo_root) / "skills"` two levels deep for `manifest.json`.
  Wrap `json.JSONDecodeError` → exit 2 with line/column from the exception.
- Required: `id`. Optional (with safe defaults): `version`, `description`,
  `category`, `deps.skills`, `deps.pip`, `deps.npm`, `targets.default.file`.

**Done when:** all five tests green; `python install.py --list` discovers the
real skills in the repo without crashing (even with "not yet implemented"
command body).

---

### T3: State-root resolution and `installed.json` R/W

**Depends on:** T1

**Tests:**

- `test_state_root_project_under_dropkit_dir` — `resolve_state_root(
  "claude-code-project", path=Path("/tmp/proj"))` → `Path("/tmp/proj/.dropkit")`.
- `test_state_root_user_xdg_when_set` — `XDG_CONFIG_HOME=/tmp/xdg` in env,
  user scope → `Path("/tmp/xdg/dropkit")`.
- `test_state_root_user_xdg_default_on_unix` — `XDG_CONFIG_HOME` unset,
  `platform.system()` returns `"Linux"` → `Path.home() / ".config/dropkit"`.
- `test_state_root_user_appdata_on_windows` — `platform.system()` returns
  `"Windows"`, `APPDATA=/tmp/appdata` in env → `Path("/tmp/appdata/dropkit")`.
- `test_installed_json_roundtrip` — write a `State` object; read it back;
  all fields match exactly.
- `test_installed_json_corrupt_treated_as_empty` — corrupt `installed.json`
  (truncated JSON) → `load_state()` returns empty `State` and logs a warning
  to stderr.
- `test_installed_json_atomic_write` — `save_state()` writes to a `.tmp`
  sibling then calls `os.replace`; patch `os.replace` to raise after the
  temp write; original `installed.json` (if it existed) is intact.

**Approach:**

- `installer/state.py` (or inline if under budget): `resolve_state_root`,
  `load_state`, `save_state`.
- Atomic write: write to `<state_root>/installed.json.tmp` then
  `os.replace(tmp, target)` (atomic on POSIX; best-effort on Windows given
  same-drive assumption — acceptable for v1).
- `State` dataclass mirrors the `installed.json` shape from the spec.

**Done when:** all seven tests green.

---

### T4: `--list` command

**Depends on:** T2, T3

**Tests (contract tests from spec):**

- `test_list_shows_all_skills` — N skills discovered → N rows, each with
  name, version, category, and status.
- `test_list_status_not_installed_by_default` — no `installed.json` → all
  rows `not installed`.
- `test_list_status_installed_after_install` — after a successful install →
  those skills `installed`.
- `test_list_status_outdated` — `version` in repo manifest differs from
  `installed.json` by string comparison → `outdated`.
- `test_list_status_modified` — sha256 of any installed file differs from
  recorded → `modified`.
- `test_list_status_orphaned` — skill in `installed.json` but no matching
  dir in repo → `orphaned`.

**Approach:**

- `cmd_list(skills, state, scope_root)` — status logic:
  - Not in state → `not installed`
  - In state, version mismatch → `outdated`
  - In state, any sha256 mismatch → `modified`
  - In state but not in discovered skills → `orphaned`
  - Otherwise → `installed`
- Left-aligned columns; ANSI color only when `sys.stdout.isatty()`.
- `--list` does not require `--scope`; `scope_root` is only needed for the
  sha256 check (file existence + hash).

**Done when:** all six tests green; `python install.py --list` shows the
real catalog with correct statuses. All test assertions strip ANSI escape
sequences before comparing column content (so tests pass regardless of
whether stdout is a TTY).

---

### T5: Path safety

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_rejects_absolute_target` — `validate_target(Path("/etc/passwd"),
  scope_root)` raises `PathEscapeError` (caught in main → exit 2).
- `test_rejects_target_escaping_scope_root` — target `../../etc/passwd`
  resolves outside `scope_root` → raises `PathEscapeError`.
- `test_dotdot_within_scope_allowed` — target `a/../b` resolves to
  `<scope_root>/b` → accepted.

**Approach:**

- `validate_target(target_rel: Path, scope_root: Path)` — resolves
  `(scope_root / target_rel).resolve()` and asserts the result is
  `scope_root.resolve()` or a descendant. Raises `PathEscapeError` otherwise.
- Called for every target before any write in T6.

**Done when:** all three tests green.

---

### T6: Install core — file copy, checksums, `installed.json` write

**Depends on:** T2, T3, T5

**Tests (contract tests from spec):**

- `test_install_user_scope_writes_to_claude_skills` — file content and mode
  bits match source after install.
- `test_install_project_scope_writes_under_path` — writes to
  `<path>/.claude/skills/<id>/`.
- `test_install_records_installed_json` — version and per-file sha256 in
  `installed.json` after install.
- `test_install_all_skills_by_default` — no `--skill` → all discovered
  skills installed.
- `test_prompt_overwrite_aborts_without_tty` — collision + no `--yes` +
  stdin from `/dev/null` → exit 1, no write.

**Construction tests:**

- `test_install_collision_prompt_overwrite` — collision + TTY + user types
  `o` → file overwritten, sha256 refreshed.
- `test_install_collision_prompt_skip` — user types `s` → file unchanged,
  summary shows skip count.
- `test_install_collision_prompt_abort` — user types `a` → exit 1.
- `test_install_creates_parent_dirs` — target `a/b/c.md`, parent `a/b/`
  absent → created before write.
- `test_install_mode_bits_preserved` — source mode `0o755` → target mode
  `0o755` (Unix only; skip on Windows).
- `test_install_sha256_correct` — sha256 in `installed.json` matches
  `hashlib.sha256` over 64KB chunks of the written file.
- `test_install_exit_3_on_permission_error` — patch `shutil.copy2` to raise
  `PermissionError` → exit 3.

**Approach:**

- `cmd_install(skills, scope, scope_root, state, args)`.
- For each skill's file: `validate_target`, resolve target path, compare
  sha256 with existing file if it exists, prompt if content differs and
  neither `--yes` nor `--update` is set.
- `shutil.copy2` (preserves mtime and mode). Wrap `OSError` → exit 3.
- Update `state` in memory after each file; single `save_state` after all
  writes.
- Prompt: one char from stdin (`o` / `s` / `a`); `sys.stdin.isatty()` guard.

**Done when:** all twelve tests green; `python install.py --scope
claude-code-user --skill jira --yes` installs the jira skill to a temp home.

---

### T7: Dep resolution — internal topological sort + external INFO/WARN

**Depends on:** T6

**Tests (contract tests from spec):**

- `test_install_dropkit_dep_pulled_in` — installing `jira-defect-flow`
  (which lists `jira` in `deps.skills`) auto-installs `jira` first.
- `test_install_external_dep_warns_when_absent` — external dep not in scope
  root → `WARN` line names the dep and its `source` field; install exits 0.
- `test_install_external_dep_info_when_present_in_scope` — external dep's
  `SKILL.md` found in scope root → `INFO` line with discovered path;
  install exits 0.

**Construction tests:**

- `test_dep_resolution_topological_order` — skill B depends on A; installing
  B alone → install order is [A, B].
- `test_dep_resolution_cycle_exits_2` — skills A → B → A → exit 2 with
  cycle message naming the skills involved.
- `test_dep_resolution_already_installed_not_reinstalled` — A already in
  `installed.json` with the same version; installing B (dep on A) does not
  re-copy A's files unless version drifted.
- `test_external_dep_warn_no_clone_suggestion` — WARN message does not
  contain the word "clone".

**Approach:**

- `installer/deps.py`: `resolve_install_order(requested: list[str],
  all_skills: dict[str, Skill]) -> list[Skill]` — Kahn's algorithm;
  raises `CycleError` (exit 2) on cycle.
- Internal dep: id exists in `all_skills`. External dep: id absent from
  `all_skills`.
- External dep check runs after topological sort, before first file write:
  probe `scope_root / dep_name / "SKILL.md"`. Emit INFO or WARN to stdout.

**Done when:** all seven tests green.

---

### T8: `--update` flow

**Depends on:** T6

**Tests (contract tests from spec):**

- `test_update_overwrites_changed_files` — drifted file re-copied; sha256
  refreshed in `installed.json`.
- `test_update_does_not_install_new_skills` — new skill in repo but absent
  from `installed.json` → not installed.
- `test_update_no_op_when_clean` — no drift → zero writes, exit 0.

**Construction tests:**

- `test_update_orphaned_skill_skipped` — skill in `installed.json` but
  no longer in repo → skipped with an `INFO` line.
- `test_update_summary_line` — stdout ends with a summary like
  `Updated 2 files across 1 skill` (or `Nothing to update` on no-op).

**Approach:**

- `cmd_update(all_skills, state, scope_root, args)`: iterate
  `state.installed` keys; look up each in `all_skills` (skip + INFO if
  absent); compare per-file sha256 against repo source; copy only drifted
  files; `save_state`.

**Done when:** all five tests green.

---

### T9: `--uninstall` flow

**Depends on:** T6

**Tests (contract tests from spec):**

- `test_uninstall_removes_tracked_files` — tracked files removed; skill
  entry cleared from `installed.json`.
- `test_uninstall_refuses_modified_without_force` — modified file → exit 1,
  no removal.
- `test_uninstall_force_overrides` — `--force` → modified file removed.
- `test_uninstall_removes_empty_parents` — empty parent dirs under scope
  root removed after uninstall.
- `test_uninstall_leaves_unrelated_files` — untracked files in scope root
  untouched.

**Construction tests:**

- `test_uninstall_all_when_no_skill_flag` — `--uninstall` with no `--skill`
  removes all tracked skills.
- `test_uninstall_nonexistent_skill_exits_2` — `--uninstall --skill
  nonexistent` exits 2 with a message naming the skill.
- `test_uninstall_already_gone_file_handled_gracefully` — file in
  `installed.json` but already deleted from disk → treated as removed,
  no error.

**Approach:**

- `cmd_uninstall(skills_to_remove, state, scope_root, args)`: collect
  modified files first (sha256 check); if any and not `--force`, list all
  and exit 1 before removing anything. Otherwise `Path.unlink()` each;
  then walk upward from each removed file's parent to scope root, calling
  `Path.rmdir()` on empty dirs.

**Done when:** all eight tests green.

---

### T10: `--dry-run`, TTY prompts, pip/npm surfacing

**Depends on:** T6

**Tests (contract tests from spec):**

- `test_dry_run_writes_nothing` — `--dry-run` with any operation → directory
  hash unchanged before/after; exit 0; actions printed to stdout.
- `test_pip_deps_surfaced_after_install` — skill with `deps.pip` installed →
  post-install summary contains the exact `pip install` command with the
  resolved path to `requirements.txt`.
- `test_installer_never_runs_pip` — subprocess monitor that fails on any
  invocation matching `pip|npm|yarn|pnpm` passes during install.

**Construction tests:**

- `test_dry_run_shows_would_write` — stdout contains `would write: <target>`
  for each file.
- `test_dry_run_shows_would_skip` — collision with same-content file →
  `would skip: <target>`.
- `test_dry_run_shows_would_remove` — `--dry-run --uninstall` → `would
  remove: <target>` lines.
- `test_no_pip_surfaced_when_no_deps` — skill with no `deps.pip` → no pip
  line in post-install summary.

**Approach:**

- Thread `dry_run: bool` through `cmd_install`, `cmd_update`, `cmd_uninstall`.
  When true, print `would <action>: <target>` instead of acting; skip
  `save_state`.
- Post-install surfacing: collect `deps.pip` / `deps.npm` from installed
  skills; print each as the literal command (e.g.,
  `pip install -r ~/.claude/skills/jira/requirements.txt`).

**Done when:** all seven tests green.

---

### T11: Wrappers and README update

**Depends on:** T1

**Tests (contract tests from spec):**

- `test_install_sh_passes_args_through` — `bash install.sh --list` stdout
  matches `python install.py --list` stdout.
- `test_install_ps1_passes_args_through` — same, PowerShell (skipped on CI
  runners without PowerShell).

**Approach:**

- Write `install.sh` exactly as in the spec (shebang, `set -euo pipefail`,
  `SCRIPT_DIR`, `exec python3`).
- Write `install.ps1` exactly as in the spec (Stop, ScriptDir, forward args,
  `exit $LASTEXITCODE`).
- Update `README.md`: add an "Install dropkit skills" section with the three
  primary patterns (user install, project install, `--list` + selective
  install). Demote existing `cp -R` to "Alternative: manual copy".

**Done when:** wrapper tests green; README diff shows three patterns present
and `cp -R` instructions demoted.

---

### T12: CI matrix

**Depends on:** T1–T11

**Tests:**

- All contract tests pass in a GitHub Actions matrix:
  `os × [ubuntu-latest, macos-latest, windows-latest]`,
  `python-version × [3.8, 3.12]` (6 combinations).
- `install.py` line count verified ≤ 500: add a CI step
  `python -c "assert len(open('install.py').readlines()) <= 500,
  f'install.py is {len(open(\"install.py\").readlines())} lines'"` so
  the budget is enforced mechanically, not by reviewer eyeballing.

**Approach:**

- Add `.github/workflows/test-installer.yml` with a `matrix` job.
- Steps: checkout, `python -m pytest tests/test_installer.py -v`.
- No `pip install` in the workflow — all test deps are stdlib only; `pytest`
  is assumed available (`python -m pytest` works if pytest is installed at
  the system/runner level; document this in the workflow file's comment).

**Done when:** CI matrix green on all 6 combinations.

## Rollout

New tool, no existing behavior changed. Ships as `v0.1.0`. The manual
`cp -R` install continues to work and remains documented. No feature flag
needed.

Ship checklist before tagging: README three-pattern section present, CI
green, `install.py` ≤ 500 lines, acceptance criteria in spec all checked.

## Risks

- **Windows path handling.** `shutil.copy2` mode-bit preservation is a no-op
  on Windows. T6's mode-bits test must be skipped on Windows, not failed.
  Catch in CI (T12) before tagging.
- **Partial `installed.json` write.** Mitigated by atomic temp-then-rename
  in T3. The corrupt-file fallback in T3 covers the residual gap.
- **`os.replace` on Windows with cross-drive paths.** Acceptable for v1:
  scope roots are always under home or cwd (same drive in practice). If this
  surfaces in CI, fall back to a copy-then-delete approach on Windows.
- **Test isolation.** Tests must never write to the real `~/.claude/skills/`
  or `~/.config/dropkit/`. Every test using `cmd_install` must monkeypatch
  `Path.home()` to a temp dir. Flag in code review if any test touches a
  non-temp path.
- **pytest availability.** The CI matrix assumes `pytest` is available as a
  module. If a runner lacks it, add a `pip install pytest` step (only dep
  in CI, not in the installer itself).

## Changelog

- 2026-05-14: initial plan
