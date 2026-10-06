from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _ensure_submodule(path: Path, init: bool = True) -> Path | None:
    """Init+update a submodule at *path* if it is inside this repo.

    Returns the submodule root on success, ``None`` if *path* is absent
    and git determined it isn't a tracked submodule.

    Tries the **fast-path** (depth-1) first; falls back to a full clone
    when the fast clone is missing files the parent commit needs.

    Side-effects (on success)
    ---------------------------
    * Git worktree for the submodule is populated on disk.
    * *path* is returned so callers can patch ``sys.path``.
    """
    root = Path(__file__).resolve().parents[2]
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return None  # outside the repo

    def _try_update(depth: int) -> bool:
        cmd = [
            "git",
            "-C",
            str(root),
            "submodule",
            "update",
            "--init",
            "--depth",
            str(depth),
            "--",
            rel,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 and "missing file(s) expected" not in (
            result.stderr + result.stdout
        ):
            return bool(path.exists())
        return path.exists()

    if not init:
        return path if path.exists() else None

    if not _try_update(1):
        _try_update(0)  # full clone fallback

    return path if path.exists() else None


def bootstrap() -> None:
    """Register project root + src/ on sys.path so pipeline imports work."""
    root = Path(__file__).resolve().parents[2]
    src = root / "src"
    for path in (root, src):
        value = str(path)
        if value not in sys.path:
            sys.path.insert(0, value)


def inject_src(project_root: Path) -> Path | None:
    """Return the *project_root*/src path, inserting it into ``sys.path``.

    Silent no-op if ``src/`` does not exist (zero-config friendly).
    """
    src = project_root / "src"
    if src.is_dir() and str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return src if src.is_dir() else None
