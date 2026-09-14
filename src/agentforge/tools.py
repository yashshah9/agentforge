"""Allowlisted tools used by the coding pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentforge.policy import PolicyDenied, assert_safe_code, assert_safe_relpath
from agentforge.sandbox.client import AgentboxClient


def list_files(workspace: Path, rel_dir: str = ".") -> list[str]:
    root = assert_safe_relpath(workspace, rel_dir) if rel_dir != "." else workspace.resolve()
    if not root.is_dir():
        raise FileNotFoundError(rel_dir)
    out: list[str] = []
    for path in sorted(root.rglob("*")):
        if path.is_file() and path.name != "README.md":
            out.append(str(path.relative_to(workspace.resolve())))
    return out


def read_file(workspace: Path, relpath: str) -> str:
    path = assert_safe_relpath(workspace, relpath)
    if not path.is_file():
        raise FileNotFoundError(relpath)
    return path.read_text(encoding="utf-8")


def write_file(workspace: Path, relpath: str, content: str) -> None:
    path = assert_safe_relpath(workspace, relpath)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def run_pytest_in_sandbox(
    client: AgentboxClient,
    workspace: Path,
    *,
    timeout_seconds: int = 30,
    memory_mb: int = 256,
) -> dict[str, Any]:
    """Embed workspace .py files and run unittest inside agentbox."""
    files = list_files(workspace)
    py_files = [f for f in files if f.endswith(".py")]
    if not py_files:
        raise RuntimeError("no python files in workspace")

    parts: list[str] = [
        "import pathlib, sys, unittest",
        "root = pathlib.Path('/tmp/agentforge_ws')",
        "root.mkdir(parents=True, exist_ok=True)",
    ]
    for rel in py_files:
        text = read_file(workspace, rel)
        assert_safe_code(text)
        parts.append(f"p = root / {rel!r}")
        parts.append("p.parent.mkdir(parents=True, exist_ok=True)")
        parts.append(f"p.write_text({text!r}, encoding='utf-8')")

    parts.extend(
        [
            "sys.path.insert(0, str(root))",
            "suite = unittest.defaultTestLoader.discover(str(root), pattern='test_*.py')",
            "result = unittest.TextTestRunner(verbosity=2).run(suite)",
            "raise SystemExit(0 if result.wasSuccessful() else 1)",
        ]
    )
    code = "\n".join(parts)
    if "os.system" in code or "socket" in code:
        raise PolicyDenied("generated sandbox harness failed policy")
    return client.run(code, timeout_seconds=timeout_seconds, memory_mb=memory_mb)
