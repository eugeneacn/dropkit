from __future__ import annotations

from pathlib import Path


class PathEscapeError(Exception):
    def __init__(self, target: Path) -> None:
        self.target = target
        super().__init__(f"Target path escapes scope root: {target}")


def validate_target(target_rel: Path, scope_root: Path) -> Path:
    """
    Resolve target_rel against scope_root and verify it stays inside.
    Returns the resolved absolute target path.
    Raises PathEscapeError if the result escapes scope_root.
    """
    if target_rel.is_absolute():
        raise PathEscapeError(target_rel)

    resolved = (scope_root / target_rel).resolve()
    root_resolved = scope_root.resolve()

    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise PathEscapeError(target_rel)

    return resolved
