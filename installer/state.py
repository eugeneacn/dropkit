from __future__ import annotations

import json
import os
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class InstalledFile:
    path: str
    sha256: str


@dataclass
class InstalledSkill:
    version: str
    files: List[InstalledFile] = field(default_factory=list)


@dataclass
class State:
    installer_version: str = ""
    scope: str = ""
    scope_root: str = ""
    installed_at: str = ""
    skills: Dict[str, InstalledSkill] = field(default_factory=dict)


def resolve_scope_root(scope: str, path: Optional[Path] = None) -> Path:
    """Return the directory where skills are installed."""
    base = path if path is not None else Path.cwd()
    if scope == "claude-code-user":
        return Path.home() / ".claude" / "skills"
    elif scope == "claude-code-project":
        return base / ".claude" / "skills"
    else:
        print(f"Error: unknown scope '{scope}'", file=sys.stderr)
        sys.exit(2)


def resolve_state_root(scope: str, path: Optional[Path] = None) -> Path:
    """Return the directory where installed.json lives."""
    if scope.endswith("-project"):
        base = path if path is not None else Path.cwd()
        return base / ".dropkit"
    # user scope — XDG / Windows / default
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "dropkit"
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "dropkit"
    return Path.home() / ".config" / "dropkit"


def recover_scope_roots(path: Optional[Path] = None):
    """
    Recover (scope_root, state_root) for --list / --update without --scope.
    Tries user-scope first, then project-scope. Per the spec, if installed.json
    is found but scope_root is missing or the path doesn't exist, exit 2
    (do not fall through to the next candidate).
    Returns (scope_root, state_root, scope) or calls sys.exit(2).
    """
    candidates = [
        ("claude-code-user", resolve_state_root("claude-code-user")),
        ("claude-code-project", resolve_state_root("claude-code-project", path)),
    ]
    for scope, state_root in candidates:
        p = state_root / "installed.json"
        if not p.exists():
            continue  # not installed in this scope — try next
        try:
            with open(p, encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue  # corrupt — treat as absent, try next
        sr = data.get("scope_root", "")
        if not sr:
            print(
                f"Error: installed.json at {p} has no scope_root field. "
                "Pass --scope explicitly.",
                file=sys.stderr,
            )
            sys.exit(2)
        scope_root = Path(sr)
        if not scope_root.exists():
            print(
                f"Error: scope_root '{scope_root}' from installed.json does not exist. "
                "Pass --scope explicitly.",
                file=sys.stderr,
            )
            sys.exit(2)
        return scope_root, state_root, scope
    print(
        "Error: no installed.json found. Pass --scope to specify where to look.",
        file=sys.stderr,
    )
    sys.exit(2)


def load_state(state_root: Path) -> State:
    path = state_root / "installed.json"
    if not path.exists():
        return State()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Warning: installed.json is unreadable ({e}); treating as empty.", file=sys.stderr)
        return State()

    skills: Dict[str, InstalledSkill] = {}
    for sid, sdata in data.get("skills", {}).items():
        files = [
            InstalledFile(path=fi["path"], sha256=fi["sha256"])
            for fi in sdata.get("files", [])
        ]
        skills[sid] = InstalledSkill(version=sdata.get("version", ""), files=files)

    return State(
        installer_version=data.get("installer_version", ""),
        scope=data.get("scope", ""),
        scope_root=data.get("scope_root", ""),
        installed_at=data.get("installed_at", ""),
        skills=skills,
    )


def save_state(state_root: Path, state: State, installer_version: str = "") -> None:
    state_root.mkdir(parents=True, exist_ok=True)
    target = state_root / "installed.json"
    tmp = state_root / "installed.json.tmp"

    data: dict = {
        "installer_version": installer_version or state.installer_version,
        "scope": state.scope,
        "scope_root": state.scope_root,
        "installed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "skills": {},
    }
    for sid, iskill in state.skills.items():
        data["skills"][sid] = {
            "version": iskill.version,
            "files": [{"path": f.path, "sha256": f.sha256} for f in iskill.files],
        }

    try:
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError as e:
        print(f"Error writing installed.json: {e}", file=sys.stderr)
        sys.exit(3)
