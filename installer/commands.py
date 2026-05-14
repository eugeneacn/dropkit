from __future__ import annotations

import hashlib
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

from installer.discovery import Skill
from installer.safety import PathEscapeError, validate_target
from installer.state import InstalledFile, InstalledSkill, State, save_state

__all__ = ["cmd_list", "cmd_install", "cmd_update", "cmd_uninstall"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _use_color() -> bool:
    return sys.stdout.isatty()


def strip_ansi(s: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def _colorize(text: str, code: str) -> str:
    if not _use_color() or not code:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"


_STATUS_COLOR = {
    "installed": "32",
    "not installed": "",
    "outdated": "33",
    "modified": "33",
    "orphaned": "31",
}


def _any_file_modified(inst: InstalledSkill, scope_root: Path) -> bool:
    for fi in inst.files:
        p = scope_root / fi.path
        if not p.exists() or sha256_file(p) != fi.sha256:
            return True
    return False


def _prompt_overwrite(target_display: str) -> str:
    """
    Prompt user for overwrite / skip / abort.
    Returns 'o', 's', or 'a'. Exits 1 if no TTY.
    """
    if not sys.stdin.isatty():
        print("Error: target file exists and no --yes; aborting (no TTY).", file=sys.stderr)
        sys.exit(1)
    while True:
        sys.stdout.write(f"  File exists: {target_display}\n  [o]verwrite / [s]kip / [a]bort? ")
        sys.stdout.flush()
        choice = sys.stdin.readline().strip().lower()
        if not choice:  # EOF
            print("Aborted (EOF).", file=sys.stderr)
            sys.exit(1)
        if choice in ("o", "s", "a"):
            return choice
        print("  Please enter o, s, or a.")


def _surface_pip_npm(skills: List[Skill], scope_root: Path) -> None:
    lines: List[str] = []
    for skill in skills:
        install_dir = scope_root / skill.id
        if skill.deps_pip:
            names = []
            for entry in skill.deps_pip:
                # Treat entries ending in .txt as requirements files
                if entry.endswith(".txt"):
                    req_path = install_dir / entry
                    lines.append(f"  pip install -r {req_path}")
                else:
                    names.append(entry)
            if names:
                lines.append(f"  pip install {' '.join(names)}")
        elif (skill.source_dir / "requirements.txt").exists():
            lines.append(f"  pip install -r {install_dir / 'requirements.txt'}")
        if skill.deps_npm:
            names = []
            for entry in skill.deps_npm:
                if entry.endswith(".json") or entry.endswith(".txt"):
                    lines.append(f"  npm install --prefix {install_dir}")
                else:
                    names.append(entry)
            if names:
                lines.append(f"  npm install {' '.join(names)}")
    if lines:
        print("\nRun these commands to install skill dependencies (not run automatically):")
        for line in lines:
            print(line)


# ---------------------------------------------------------------------------
# --list
# ---------------------------------------------------------------------------

def cmd_list(
    all_skills: Dict[str, Skill],
    state: State,
    scope_root: Optional[Path],
) -> None:
    rows = []
    for sid in sorted(all_skills):
        skill = all_skills[sid]
        if sid in state.skills:
            inst = state.skills[sid]
            if inst.version != skill.version:
                status = "outdated"
            elif scope_root and _any_file_modified(inst, scope_root):
                status = "modified"
            else:
                status = "installed"
        else:
            status = "not installed"
        rows.append((skill.id, skill.version, skill.category, status))

    for sid in sorted(state.skills):
        if sid not in all_skills:
            inst = state.skills[sid]
            rows.append((sid, inst.version, "?", "orphaned"))

    header = ("name", "version", "category", "status")
    all_rows = [header] + rows
    widths = [max(len(r[i]) for r in all_rows) for i in range(4)]

    def fmt(row: tuple, status: str = "") -> str:
        cells = [row[i].ljust(widths[i]) for i in range(4)]
        line = "  ".join(cells)
        return _colorize(line, _STATUS_COLOR.get(status, ""))

    print(fmt(header))
    for row in rows:
        print(fmt(row, status=row[3]))


# ---------------------------------------------------------------------------
# --install (core)
# ---------------------------------------------------------------------------

def cmd_install(
    skills: List[Skill],
    scope: str,
    scope_root: Path,
    state_root: Path,
    state: State,
    args,
    dry_run: bool = False,
    is_update: bool = False,
) -> None:
    yes = getattr(args, "yes", False)
    verbose = getattr(args, "verbose", False)

    written = 0
    skipped = 0

    for skill in skills:
        installed_files: List[InstalledFile] = []

        for rel_path in skill.files:
            source = skill.source_dir / rel_path
            if not source.exists():
                print(f"Error: source file missing: {source}", file=sys.stderr)
                sys.exit(2)

            target_rel = Path(skill.id) / rel_path
            try:
                target = validate_target(target_rel, scope_root)
            except PathEscapeError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)

            rel_str = target_rel.as_posix()

            if dry_run:
                if target.exists() and sha256_file(target) == sha256_file(source):
                    print(f"would skip: {rel_str}")
                else:
                    print(f"would write: {rel_str}")
                continue

            if verbose:
                print(f"  {source} -> {target}")

            if target.exists():
                src_sum = sha256_file(source)
                tgt_sum = sha256_file(target)
                if src_sum == tgt_sum:
                    installed_files.append(InstalledFile(path=rel_str, sha256=tgt_sum))
                    skipped += 1
                    continue
                if not yes and not is_update:
                    choice = _prompt_overwrite(rel_str)
                    if choice == "s":
                        installed_files.append(InstalledFile(path=rel_str, sha256=tgt_sum))
                        skipped += 1
                        continue
                    elif choice == "a":
                        print("Aborted.", file=sys.stderr)
                        sys.exit(1)

            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(source), str(target))
            except OSError as e:
                print(f"Error writing {target}: {e}", file=sys.stderr)
                sys.exit(3)

            checksum = sha256_file(target)
            installed_files.append(InstalledFile(path=rel_str, sha256=checksum))
            written += 1
            print(f"  wrote: {rel_str}")

        if not dry_run:
            state.skills[skill.id] = InstalledSkill(
                version=skill.version, files=installed_files
            )
            state.scope = scope
            state.scope_root = scope_root.as_posix()

    if not dry_run:
        from install import __version__
        save_state(state_root, state, __version__)
        _surface_pip_npm(skills, scope_root)
        noun = "skill" if len(skills) == 1 else "skills"
        print(
            f"\nInstalled {len(skills)} {noun} "
            f"({written} file(s) written, {skipped} skipped) to {scope_root}"
        )


# ---------------------------------------------------------------------------
# --update
# ---------------------------------------------------------------------------

def cmd_update(
    all_skills: Dict[str, Skill],
    scope_root: Path,
    state_root: Path,
    state: State,
    args,
    dry_run: bool = False,
) -> None:
    verbose = getattr(args, "verbose", False)
    updated_files = 0
    updated_skills = 0

    for sid in list(state.skills.keys()):
        if sid not in all_skills:
            print(f"INFO: '{sid}' is no longer in the repo (orphaned); skipping.")
            continue

        skill = all_skills[sid]
        inst = state.skills[sid]
        new_files: List[InstalledFile] = []
        skill_updated = 0

        for rel_path in skill.files:
            source = skill.source_dir / rel_path
            target_rel = Path(skill.id) / rel_path
            rel_str = target_rel.as_posix()
            try:
                target = validate_target(target_rel, scope_root)
            except PathEscapeError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(2)

            if not source.exists():
                print(f"Error: source file missing: {source}", file=sys.stderr)
                sys.exit(2)

            src_sum = sha256_file(source)

            # Find recorded checksum
            recorded = next((f.sha256 for f in inst.files if f.path == rel_str), None)

            if recorded == src_sum and target.exists() and sha256_file(target) == src_sum:
                new_files.append(InstalledFile(path=rel_str, sha256=src_sum))
                continue

            if dry_run:
                print(f"would write: {rel_str}")
                continue

            if verbose:
                print(f"  {source} -> {target}")

            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(str(source), str(target))
            except OSError as e:
                print(f"Error writing {target}: {e}", file=sys.stderr)
                sys.exit(3)

            new_files.append(InstalledFile(path=rel_str, sha256=sha256_file(target)))
            print(f"  updated: {rel_str}")
            skill_updated += 1
            updated_files += 1

        if not dry_run:
            state.skills[sid] = InstalledSkill(version=skill.version, files=new_files)
            if skill_updated:
                updated_skills += 1

    if dry_run:
        return

    from install import __version__
    save_state(state_root, state, __version__)
    updated_skill_objs = [all_skills[sid] for sid in state.skills if sid in all_skills]
    _surface_pip_npm(updated_skill_objs, scope_root)
    if updated_files:
        print(f"\nUpdated {updated_files} file(s) across {updated_skills} skill(s).")
    else:
        print("\nNothing to update.")


# ---------------------------------------------------------------------------
# --uninstall
# ---------------------------------------------------------------------------

def cmd_uninstall(
    skill_ids: Optional[List[str]],
    scope_root: Path,
    state_root: Path,
    state: State,
    args,
    dry_run: bool = False,
) -> None:
    force = getattr(args, "force", False)

    targets = list(skill_ids) if skill_ids else list(state.skills.keys())

    # Validate requested IDs exist in state
    for sid in targets:
        if sid not in state.skills:
            print(f"Error: '{sid}' is not installed.", file=sys.stderr)
            sys.exit(2)

    # Check for user-modified files before touching anything (skip on dry-run)
    if not force and not dry_run:
        modified: List[str] = []
        for sid in targets:
            inst = state.skills[sid]
            for fi in inst.files:
                p = scope_root / fi.path
                if p.exists() and sha256_file(p) != fi.sha256:
                    modified.append(fi.path)
        if modified:
            print(
                "Error: the following files have been modified since install "
                "(use --force to remove anyway):",
                file=sys.stderr,
            )
            for m in modified:
                print(f"  {m}", file=sys.stderr)
            sys.exit(1)

    removed_dirs: set = set()

    for sid in targets:
        inst = state.skills[sid]
        for fi in inst.files:
            p = scope_root / fi.path
            if dry_run:
                print(f"would remove: {fi.path}")
                continue
            if p.exists():
                p.unlink()
                print(f"  removed: {fi.path}")
                removed_dirs.add(p.parent)
            # File already gone — treat as removed silently
        if not dry_run:
            del state.skills[sid]

    if dry_run:
        return

    # Prune empty parent directories up to scope_root
    scope_resolved = scope_root.resolve()
    for d in sorted(removed_dirs, reverse=True):
        try:
            p = d.resolve()
            while p != scope_resolved and p.is_dir() and not any(p.iterdir()):
                p.rmdir()
                p = p.parent
        except OSError:
            pass

    from install import __version__
    save_state(state_root, state, __version__)
    noun = "skill" if len(targets) == 1 else "skills"
    print(f"\nUninstalled {len(targets)} {noun}.")
