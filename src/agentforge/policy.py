"""Tool policy — deny dangerous paths and shell escape patterns."""

from __future__ import annotations

from pathlib import Path

DENIED_PATH_PARTS = {".git", ".ssh", ".env", "id_rsa", "secrets"}
DENIED_READ_SUFFIXES = {".pem", ".key"}


class PolicyDenied(PermissionError):
    pass


def assert_safe_relpath(workspace: Path, relpath: str) -> Path:
    if relpath.startswith("/") or ".." in Path(relpath).parts:
        raise PolicyDenied(f"path escapes workspace: {relpath}")
    lower_parts = {p.lower() for p in Path(relpath).parts}
    if lower_parts & DENIED_PATH_PARTS:
        raise PolicyDenied(f"path not allowed: {relpath}")
    if Path(relpath).suffix.lower() in DENIED_READ_SUFFIXES:
        raise PolicyDenied(f"suffix not allowed: {relpath}")
    full = (workspace / relpath).resolve()
    try:
        full.relative_to(workspace.resolve())
    except ValueError as exc:
        raise PolicyDenied(f"path escapes workspace: {relpath}") from exc
    return full


def assert_safe_code(code: str) -> None:
    banned = ("os.system", "subprocess", "socket", "ctypes", "__import__('os')")
    for token in banned:
        if token in code:
            raise PolicyDenied(f"code contains banned token: {token}")
