from __future__ import annotations

import os
from pathlib import Path


def ensure_within_root(root: Path, target: Path) -> Path:
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    if os.path.commonpath([str(root_resolved), str(target_resolved)]) != str(root_resolved):
        raise ValueError(f"Path escapes workspace root: {target}")
    return target_resolved


def safe_join(root: Path, relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise ValueError(f"Absolute paths are not allowed: {relative_path}")
    if ".." in Path(relative_path).parts:
        raise ValueError(f"Parent path segments are not allowed: {relative_path}")
    return ensure_within_root(root, root / relative_path)

