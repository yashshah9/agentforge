"""Deterministic coding pipeline for fixture repos (LLM optional later)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import structlog

from agentforge.domain.runs import Run, RunStatus, RunStep, RunStore
from agentforge.github import DraftPRPublisher, build_publisher
from agentforge.policy import PolicyDenied
from agentforge.sandbox.client import AgentboxClient
from agentforge.tools import list_files, run_pytest_in_sandbox, write_file
from agentforge.tools import read_file as read_workspace_file
from agentforge.workspace import WorkspaceError, resolve_workspace

if TYPE_CHECKING:
    from platformkit import PlatformKit

    from agentforge.config import Settings

log = structlog.get_logger()


class SandboxClient(Protocol):
    def run(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int | None = None,
        memory_mb: int | None = None,
    ) -> dict[str, Any]: ...

    def close(self) -> None: ...


def _fix_broken_counter(workspace: Path, issue: str) -> str:
    """Rule-based fixer for the broken_counter fixture."""
    del issue
    target = "counter.py"
    src = read_workspace_file(workspace, target)
    if "return n - 1" in src:
        write_file(workspace, target, src.replace("return n - 1", "return n + 1"))
        return "Replaced `return n - 1` with `return n + 1` in counter.py"
    return "No automatic patch applied"


def apply_fix(workspace: Path, repo_url: str, issue: str) -> str:
    """Dispatch known fixture fixers. Extend here as fixtures grow."""
    if repo_url.endswith("broken_counter") or "broken_counter" in repo_url:
        return _fix_broken_counter(workspace, issue)
    return "No automatic patch applied"


def _maybe_deny_injection(issue: str) -> None:
    lowered = issue.lower()
    if "ignore previous" in lowered or "exfiltrate" in lowered or "cat /etc/passwd" in lowered:
        raise PolicyDenied("issue text failed security policy")


def execute_pipeline(
    *,
    kit: PlatformKit,
    store: RunStore,
    settings: Settings,
    run: Run,
    publisher: DraftPRPublisher | None = None,
    sandbox_client: SandboxClient | None = None,
) -> None:
    work_root = Path(settings.work_root)
    work_root.mkdir(parents=True, exist_ok=True)
    pub = publisher or build_publisher(settings)

    try:
        _maybe_deny_injection(run.issue)
        store.update(run.id, status=RunStatus.PLANNING)
        plan = [
            "Prepare isolated workspace",
            "List repository files",
            "Apply minimal fix for the reported issue",
            "Run tests in agentbox sandbox",
            "Open draft pull request",
            "Await human approval",
        ]
        store.update(run.id, plan=plan)
        store.append_step(run.id, RunStep(name="plan", status="ok", detail={"steps": plan}))

        workspace = resolve_workspace(run.repo_url, work_root, run.id)
        store.update(run.id, workspace_path=str(workspace), status=RunStatus.CODING)
        files = list_files(workspace)
        store.append_step(run.id, RunStep(name="list_files", status="ok", detail={"files": files}))

        summary = apply_fix(workspace, run.repo_url, run.issue)
        store.update(run.id, patch_summary=summary)
        store.append_step(run.id, RunStep(name="patch", status="ok", detail={"summary": summary}))

        store.update(run.id, status=RunStatus.TESTING)
        owns_client = False
        client: SandboxClient
        if sandbox_client is None:
            client = AgentboxClient(settings.agentbox_url)
            owns_client = True
        else:
            client = sandbox_client
        try:
            result = run_pytest_in_sandbox(
                client,
                workspace,
                timeout_seconds=settings.sandbox_timeout_seconds,
                memory_mb=settings.sandbox_memory_mb,
            )
        finally:
            if owns_client:
                client.close()

        exit_code = int(result.get("exit_code", 1))
        store.update(
            run.id,
            test_exit_code=exit_code,
            test_stdout=str(result.get("stdout", ""))[:8000],
            test_stderr=str(result.get("stderr", ""))[:8000],
            sandbox_backend=str(result.get("backend", "")),
            network_isolated=bool(result.get("network_isolated", False)),
        )
        store.append_step(
            run.id,
            RunStep(
                name="sandbox_tests",
                status="ok" if exit_code == 0 else "failed",
                detail={
                    "exit_code": exit_code,
                    "network_isolated": result.get("network_isolated"),
                    "oom_killed": result.get("oom_killed"),
                },
            ),
        )

        if exit_code != 0:
            store.update(run.id, status=RunStatus.FAILED, error="sandbox tests failed")
            kit.audit.emit(
                actor="system:worker",
                action="run.tests_failed",
                payload={"exit_code": exit_code},
                resource_type="run",
                resource_id=run.id,
                tenant_id=run.tenant_id,
            )
            return

        draft = pub.publish(
            run_id=run.id,
            issue=run.issue,
            patch_summary=summary,
            workspace=workspace,
            repo_url=run.repo_url,
        )
        store.append_step(
            run.id,
            RunStep(
                name="draft_pr",
                status="ok",
                detail={
                    "url": draft.url,
                    "mode": draft.mode,
                    "number": draft.number,
                    "branch": draft.branch,
                    "repo": draft.repo,
                },
            ),
        )
        store.update(
            run.id,
            status=RunStatus.AWAITING_APPROVAL,
            pr_url=draft.url,
            pr_mode=draft.mode,
        )
        kit.audit.emit(
            actor="system:worker",
            action="run.awaiting_approval",
            payload={
                "pr_url": draft.url,
                "pr_mode": draft.mode,
                "patch_summary": summary,
            },
            resource_type="run",
            resource_id=run.id,
            tenant_id=run.tenant_id,
        )
    except PolicyDenied as exc:
        store.update(run.id, status=RunStatus.FAILED, error=f"policy_denied: {exc}")
        kit.audit.emit(
            actor="system:worker",
            action="run.policy_denied",
            payload={"error": str(exc)},
            resource_type="run",
            resource_id=run.id,
            tenant_id=run.tenant_id,
        )
        log.warning("policy_denied", run_id=run.id, error=str(exc))
    except (WorkspaceError, FileNotFoundError, RuntimeError, OSError) as exc:
        store.update(run.id, status=RunStatus.FAILED, error=str(exc))
        kit.audit.emit(
            actor="system:worker",
            action="run.failed",
            payload={"error": str(exc)},
            resource_type="run",
            resource_id=run.id,
            tenant_id=run.tenant_id,
        )
        log.exception("pipeline_failed", run_id=run.id)
