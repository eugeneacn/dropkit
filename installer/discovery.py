from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class SkillDep:
    name: str
    source: str = ""


@dataclass
class Skill:
    id: str
    version: str
    description: str
    category: str
    source_dir: Path
    files: List[Path]  # relative to source_dir
    deps_skills: List[SkillDep] = field(default_factory=list)
    deps_pip: List[str] = field(default_factory=list)
    deps_npm: List[str] = field(default_factory=list)


def discover_skills(repo_root: Path) -> Dict[str, Skill]:
    """Walk skills/*/*/manifest.json and return skills keyed by id."""
    skills_dir = repo_root / "skills"
    result: Dict[str, Skill] = {}
    if not skills_dir.is_dir():
        return result
    for category_dir in sorted(skills_dir.iterdir()):
        if not category_dir.is_dir():
            continue
        for skill_dir in sorted(category_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            manifest_path = skill_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            skill = _parse_manifest(manifest_path, skill_dir, category_dir.name)
            result[skill.id] = skill
    return result


def _parse_manifest(manifest_path: Path, skill_dir: Path, category: str) -> Skill:
    try:
        with open(manifest_path, encoding="utf-8") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as e:
        print(
            f"Error: invalid JSON in {manifest_path} at line {e.lineno}, col {e.colno}: {e.msg}",
            file=sys.stderr,
        )
        sys.exit(2)

    skill_id = data.get("id")
    if not skill_id:
        print(f"Error: {manifest_path} is missing required field 'id'", file=sys.stderr)
        sys.exit(2)

    version = str(data.get("version", "0.0.0"))
    description = str(data.get("description", ""))
    cat = str(data.get("category", category))

    files = _collect_files(skill_dir)

    deps_raw = data.get("deps", {})
    deps_skills: List[SkillDep] = []
    if isinstance(deps_raw.get("skills"), list):
        for s in deps_raw["skills"]:
            if isinstance(s, dict) and "name" in s:
                deps_skills.append(SkillDep(name=str(s["name"]), source=str(s.get("source", ""))))

    deps_pip: List[str] = []
    if isinstance(deps_raw.get("pip"), list):
        deps_pip = [str(p) for p in deps_raw["pip"]]

    deps_npm: List[str] = []
    if isinstance(deps_raw.get("npm"), list):
        deps_npm = [str(p) for p in deps_raw["npm"]]

    return Skill(
        id=skill_id,
        version=version,
        description=description,
        category=cat,
        source_dir=skill_dir,
        files=files,
        deps_skills=deps_skills,
        deps_pip=deps_pip,
        deps_npm=deps_npm,
    )


def _collect_files(skill_dir: Path) -> List[Path]:
    result = []
    for f in sorted(skill_dir.rglob("*")):
        if f.is_file() and not f.is_symlink():
            result.append(f.relative_to(skill_dir))
    return result
