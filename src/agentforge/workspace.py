"""Workspace preparation for fixture and local repos."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


class WorkspaceError(ValueError):
    pass


def fixtures_root() -> Path:
    env = os.environ.get("AGENTFORGE_FIXTURES_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "fixtures"


def resolve_workspace(repo_url: str, work_root: Path, run_id: str) -> Path:
    """Copy fixture://name or local path into an isolated work dir."""
    dest = work_root / run_id
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    if repo_url.startswith("fixture://"):
        name = repo_url.removeprefix("fixture://").strip("/")
        root = fixtures_root()
        src = root / name
        if not src.is_dir():
            known = (
                sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
            )
            raise WorkspaceError(f"Unknown fixture {name!r}. Known: {known}")
        shutil.copytree(src, dest, dirs_exist_ok=True)
        return dest

    if repo_url.startswith("file://"):
        src = Path(repo_url.removeprefix("file://"))
    else:
        src = Path(repo_url)

    if src.is_dir():
        shutil.copytree(src, dest, dirs_exist_ok=True)
        return dest

    raise WorkspaceError(
        "repo_url must be fixture://<name> or a local directory path "
        "(GitHub clone lands in a later phase)"
    )
