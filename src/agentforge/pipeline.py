"""Deterministic coding pipeline for fixture repos (LLM optional later)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from agentforge.domain.runs import Run, RunStatus, RunStep, RunStore
from agentforge.policy import PolicyDenied
from agentforge.sandbox.client import AgentboxClient
from agentforge.tools import list_files, read_file, run_pytest_in_sandbox, write_file
from agentforge.workspace import WorkspaceError, resolve_workspace

if TYPE_CHECKING:
    from platformkit import PlatformKit

    from agentforge.config import Settings

log = structlog.get_logger()


def _fix_broken_counter(workspace: Path, issue: str) -> str:
    """Rule-based fixer for the broken_counter fixture."""
    del issue  # keyword matching reserved for future LLM planner
    target = "counter.py"
    src = read_file(workspace, target)
    if "return n - 1" in src:
        write_file(workspace, target, src.replace("return n - 1", "return n + 1"))
        return "Replaced `return n - 1` with `return n + 1` in counter.py"
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
) -> None:
    work_root = Path(settings.work_root)
    work_root.mkdir(parents=True, exist_ok=True)

    try:
        _maybe_deny_injection(run.issue)
        store.update(run.id, status=RunStatus.PLANNING)
        plan = [
            "Prepare isolated workspace",
            "List repository files",
            "Apply minimal fix for the reported issue",
            "Run tests in agentbox sandbox",
            "Await human approval",
        ]
        store.update(run.id, plan=plan)
        store.append_step(run.id, RunStep(name="plan", status="ok", detail={"steps": plan}))

        workspace = resolve_workspace(run.repo_url, work_root, run.id)
        store.update(run.id, workspace_path=str(workspace), status=RunStatus.CODING)
        files = list_files(workspace)
        store.append_step(run.id, RunStep(name="list_files", status="ok", detail={"files": files}))

        summary = _fix_broken_counter(workspace, run.issue)
        store.update(run.id, patch_summary=summary)
        store.append_step(run.id, RunStep(name="patch", status="ok", detail={"summary": summary}))

        store.update(run.id, status=RunStatus.TESTING)
        client = AgentboxClient(settings.agentbox_url)
        try:
            result = run_pytest_in_sandbox(
                client,
                workspace,
                timeout_seconds=settings.sandbox_timeout_seconds,
                memory_mb=settings.sandbox_memory_mb,
            )
        finally:
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
            store.update(
                run.id,
                status=RunStatus.FAILED,
                error="sandbox tests failed",
            )
            kit.audit.emit(
                actor="system:worker",
                action="run.tests_failed",
                payload={"exit_code": exit_code},
                resource_type="run",
                resource_id=run.id,
                tenant_id=run.tenant_id,
            )
            return

        # Draft PR placeholder URL (GitHub App later)
        pr_url = f"local://draft-pr/{run.id}"
        store.update(
            run.id,
            status=RunStatus.AWAITING_APPROVAL,
            pr_url=pr_url,
        )
        kit.audit.emit(
            actor="system:worker",
            action="run.awaiting_approval",
            payload={"pr_url": pr_url, "patch_summary": summary},
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
