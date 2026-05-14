from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

from installer.discovery import Skill


class CycleError(Exception):
    def __init__(self, ids: List[str]) -> None:
        self.ids = ids
        super().__init__(f"Dependency cycle detected among: {', '.join(sorted(ids))}")


def resolve_install_order(
    requested_ids: List[str],
    all_skills: Dict[str, Skill],
) -> List[Skill]:
    """
    Return skills in topological install order, auto-including internal deps.
    Raises CycleError on cycles. Raises sys.exit(2) if cycle detected.
    """
    needed: Dict[str, Skill] = {}
    _collect_deps(requested_ids, all_skills, needed)

    # Kahn's algorithm
    in_degree: Dict[str, int] = {sid: 0 for sid in needed}
    dependents: Dict[str, List[str]] = {sid: [] for sid in needed}

    for sid, skill in needed.items():
        for dep in skill.deps_skills:
            if dep.name in needed:
                dependents[dep.name].append(sid)
                in_degree[sid] += 1

    queue = sorted(sid for sid, deg in in_degree.items() if deg == 0)
    order: List[str] = []

    while queue:
        node = queue.pop(0)
        order.append(node)
        for neighbor in sorted(dependents[node]):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(order) != len(needed):
        remaining = [sid for sid in needed if sid not in order]
        print(f"Error: {CycleError(remaining)}", file=sys.stderr)
        sys.exit(2)

    return [needed[sid] for sid in order]


def _collect_deps(
    ids: List[str],
    all_skills: Dict[str, Skill],
    collected: Dict[str, Skill],
) -> None:
    for sid in ids:
        if sid in collected or sid not in all_skills:
            continue
        skill = all_skills[sid]
        collected[sid] = skill
        internal = [d.name for d in skill.deps_skills if d.name in all_skills]
        _collect_deps(internal, all_skills, collected)


def check_external_deps(
    skills: List[Skill],
    all_skills: Dict[str, Skill],
    scope_root: Path,
) -> None:
    """Emit INFO or WARN for external (cross-repo) skill dependencies."""
    for skill in skills:
        for dep in skill.deps_skills:
            if dep.name in all_skills:
                continue  # internal — already handled
            skill_md = scope_root / dep.name / "SKILL.md"
            if skill_md.exists():
                print(
                    f"INFO: external dep '{dep.name}' appears installed at "
                    f"'{skill_md.parent}'. Not installed by this installer; not version-checked."
                )
            else:
                source = f" Source: {dep.source}." if dep.source else ""
                print(
                    f"WARN: skill '{skill.id}' depends on external skill '{dep.name}'.{source} "
                    f"Install it separately."
                )
