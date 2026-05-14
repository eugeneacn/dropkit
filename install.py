#!/usr/bin/env python3
"""dropkit skill installer — stdlib only, Python 3.8+."""

from __future__ import annotations

import argparse
import os
import sys

if sys.version_info < (3, 8):
    print("Error: install.py requires Python 3.8 or later.", file=sys.stderr)
    sys.exit(2)

from pathlib import Path
from typing import List, Optional

__version__ = "0.1.0"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="install.py",
        description="Install dropkit skills into your IDE's skill directory.",
    )
    p.add_argument(
        "--scope",
        metavar="SCOPE",
        choices=["claude-code-user", "claude-code-project"],
        help="Target scope: claude-code-user or claude-code-project.",
    )
    p.add_argument(
        "--path",
        metavar="PATH",
        help="Project root for *-project scopes (default: cwd).",
    )
    p.add_argument(
        "--skill",
        metavar="ID",
        dest="skills",
        action="append",
        help="Restrict to one or more skills by id (repeatable).",
    )

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--list", action="store_true", help="Print the skill catalog with install status.")
    mode.add_argument("--update", action="store_true", help="Re-install currently-installed skills only.")
    mode.add_argument("--uninstall", action="store_true", help="Remove installer-tracked files.")

    p.add_argument("--dry-run", action="store_true", help="Print actions; perform no writes.")
    p.add_argument("--yes", action="store_true", help="Skip confirmation prompts.")
    p.add_argument("--force", action="store_true", help="Allow --uninstall to remove modified files.")
    p.add_argument("--verbose", action="store_true", help="Print source→target trace per file.")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Determine repo root — env var override for testing
    _repo_env = os.environ.get("DROPKIT_REPO_ROOT", "")
    repo_root = Path(_repo_env).resolve() if _repo_env else Path(__file__).parent.resolve()

    from installer.discovery import discover_skills
    from installer.state import (
        load_state,
        recover_scope_roots,
        resolve_scope_root,
        resolve_state_root,
    )
    from installer.deps import resolve_install_order, check_external_deps
    from installer.commands import cmd_list, cmd_install, cmd_update, cmd_uninstall

    # --list
    if args.list:
        all_skills = discover_skills(repo_root)
        if args.scope:
            path = Path(args.path) if args.path else None
            scope_root = resolve_scope_root(args.scope, path)
            state_root = resolve_state_root(args.scope, path)
            state = load_state(state_root)
        else:
            scope_root, state_root, _scope = recover_scope_roots(
                Path(args.path) if args.path else None
            )
            state = load_state(state_root)
        cmd_list(all_skills, state, scope_root)
        return 0

    # --scope required for install / uninstall
    if not args.update and not args.scope:
        parser.error("--scope is required (choose claude-code-user or claude-code-project)")

    path = Path(args.path) if args.path else None

    # --update: derive roots from installed.json if --scope not given
    if args.update:
        if args.scope:
            scope_root = resolve_scope_root(args.scope, path)
            state_root = resolve_state_root(args.scope, path)
            scope = args.scope
        else:
            scope_root, state_root, scope = recover_scope_roots(path)
        all_skills = discover_skills(repo_root)
        state = load_state(state_root)
        cmd_update(
            all_skills, scope_root, state_root, state, args, dry_run=args.dry_run
        )
        return 0

    scope_root = resolve_scope_root(args.scope, path)
    state_root = resolve_state_root(args.scope, path)
    state = load_state(state_root)

    # --uninstall
    if args.uninstall:
        cmd_uninstall(
            args.skills, scope_root, state_root, state, args, dry_run=args.dry_run
        )
        return 0

    # Install
    all_skills = discover_skills(repo_root)
    requested = args.skills if args.skills else list(all_skills.keys())

    # Validate requested skill ids
    for sid in requested:
        if sid not in all_skills:
            print(f"Error: unknown skill '{sid}'", file=sys.stderr)
            sys.exit(2)

    skills = resolve_install_order(requested, all_skills)

    # Announce auto-included deps
    requested_set = set(requested)
    for skill in skills:
        if skill.id not in requested_set:
            print(f"  (auto-including dep '{skill.id}')")

    check_external_deps(skills, all_skills, scope_root)

    cmd_install(
        skills, args.scope, scope_root, state_root, state, args, dry_run=args.dry_run
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
