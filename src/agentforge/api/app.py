"""HTTP API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from platformkit.protocols import Principal
from pydantic import BaseModel, Field

from agentforge.__version__ import __version__
from agentforge.config import Settings
from agentforge.domain.runs import Run, RunStatus, RunStore
from agentforge.platform import build_kit
from agentforge.worker.loop import start_inline_worker, stop_inline_worker

settings = Settings()
kit = build_kit(settings)
store = RunStore()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    if settings.inline_worker:
        start_inline_worker(kit=kit, store=store, settings=settings)
    try:
        yield
    finally:
        stop_inline_worker()


app = FastAPI(title="agentforge", version=__version__, lifespan=lifespan)


class CreateRunRequest(BaseModel):
    issue: str = Field(..., min_length=1, max_length=20_000)
    repo_url: str = Field(..., min_length=1, max_length=2000)


class RunResponse(BaseModel):
    id: str
    tenant_id: str
    issue: str
    repo_url: str
    status: RunStatus
    plan: list[str]
    steps: list[dict[str, Any]]
    patch_summary: str | None
    test_exit_code: int | None
    test_stdout: str | None
    test_stderr: str | None
    sandbox_backend: str | None
    network_isolated: bool | None
    pr_url: str | None
    pr_mode: str | None
    error: str | None
    latency_ms: int
    estimated_cost_usd: float

    @classmethod
    def from_run(cls, run: Run) -> RunResponse:
        return cls(
            id=run.id,
            tenant_id=run.tenant_id,
            issue=run.issue,
            repo_url=run.repo_url,
            status=run.status,
            plan=run.plan,
            steps=[
                {
                    "name": s.name,
                    "status": s.status,
                    "detail": s.detail,
                    "latency_ms": s.latency_ms,
                }
                for s in run.steps
            ],
            patch_summary=run.patch_summary,
            test_exit_code=run.test_exit_code,
            test_stdout=run.test_stdout,
            test_stderr=run.test_stderr,
            sandbox_backend=run.sandbox_backend,
            network_isolated=run.network_isolated,
            pr_url=run.pr_url,
            pr_mode=run.pr_mode,
            error=run.error,
            latency_ms=run.latency_ms,
            estimated_cost_usd=run.estimated_cost_usd,
        )


class ApprovalRequest(BaseModel):
    approve: bool
    reason: str | None = None


def _bearer_token(authorization: Annotated[str | None, Header()] = None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    return authorization.split(" ", 1)[1].strip()


def require_principal(token: Annotated[str, Depends(_bearer_token)]) -> Principal:
    principal = kit.auth.authenticate(token)
    if principal is None:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return principal


@app.get("/health")
def health() -> dict[str, Any]:
    depth = 0
    try:
        depth = kit.queue.depth(settings.queue_topic)
    except Exception:  # noqa: BLE001 — health should stay up
        depth = -1
    return {
        "status": "ok",
        "version": __version__,
        "auth": settings.auth_driver,
        "audit": settings.audit_driver,
        "queue": settings.queue_driver,
        "queue_depth": depth,
        "inline_worker": settings.inline_worker,
        "agentbox_url": settings.agentbox_url,
        "runs": len(store.list_recent(limit=500)),
    }


@app.get("/v1/traces")
def list_traces(
    principal: Annotated[Principal, Depends(require_principal)],
    limit: int = 20,
) -> dict[str, Any]:
    tenant_id = principal.tenant_id or principal.id
    limit = max(1, min(limit, 100))
    if "admin" in principal.roles:
        runs = store.list_recent(limit=limit)
    else:
        runs = sorted(
            store.list_for_tenant(tenant_id),
            key=lambda r: r.updated_at,
            reverse=True,
        )[:limit]
    total_cost = sum(r.estimated_cost_usd for r in runs)
    return {
        "count": len(runs),
        "total_estimated_cost_usd": round(total_cost, 6),
        "traces": [
            {
                "run_id": r.id,
                "status": r.status.value,
                "repo_url": r.repo_url,
                "latency_ms": r.latency_ms,
                "estimated_cost_usd": r.estimated_cost_usd,
                "step_count": len(r.steps),
                "steps": [
                    {"name": s.name, "status": s.status, "latency_ms": s.latency_ms}
                    for s in r.steps
                ],
                "pr_mode": r.pr_mode,
                "test_exit_code": r.test_exit_code,
            }
            for r in runs
        ],
    }


@app.post("/v1/runs", response_model=RunResponse)
def create_run(
    body: CreateRunRequest,
    principal: Annotated[Principal, Depends(require_principal)],
) -> RunResponse:
    tenant_id = principal.tenant_id or principal.id
    if not kit.auth.authorize(principal, "runs:create"):
        raise HTTPException(status_code=403, detail="Forbidden")

    run = store.create(tenant_id=tenant_id, issue=body.issue, repo_url=body.repo_url)
    kit.queue.enqueue(settings.queue_topic, {"run_id": run.id})
    kit.audit.emit(
        actor=principal.id,
        action="run.create",
        payload={"issue": body.issue[:200], "repo_url": body.repo_url},
        resource_type="run",
        resource_id=run.id,
        tenant_id=tenant_id,
    )
    return RunResponse.from_run(run)


@app.get("/v1/runs/{run_id}", response_model=RunResponse)
def get_run(
    run_id: str,
    principal: Annotated[Principal, Depends(require_principal)],
) -> RunResponse:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    tenant_id = principal.tenant_id or principal.id
    if run.tenant_id != tenant_id and "admin" not in principal.roles:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse.from_run(run)


@app.post("/v1/runs/{run_id}/approval", response_model=RunResponse)
def approve_run(
    run_id: str,
    body: ApprovalRequest,
    principal: Annotated[Principal, Depends(require_principal)],
) -> RunResponse:
    run = store.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    tenant_id = principal.tenant_id or principal.id
    if run.tenant_id != tenant_id and "admin" not in principal.roles:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.status != RunStatus.AWAITING_APPROVAL:
        raise HTTPException(status_code=409, detail=f"Run status is {run.status}")

    if body.approve:
        updated = store.update(run_id, status=RunStatus.DONE)
        action = "run.approve"
    else:
        updated = store.update(run_id, status=RunStatus.FAILED, error=body.reason or "rejected")
        action = "run.reject"

    assert updated is not None
    kit.audit.emit(
        actor=principal.id,
        action=action,
        payload={"reason": body.reason},
        resource_type="run",
        resource_id=run_id,
        tenant_id=tenant_id,
    )
    return RunResponse.from_run(updated)


@app.get("/v1/audit")
def list_audit(
    principal: Annotated[Principal, Depends(require_principal)],
) -> list[dict[str, object]]:
    tenant_id = principal.tenant_id or principal.id
    events = kit.audit.list(tenant_id=tenant_id, limit=50)
    return [
        {
            "actor": e.actor,
            "action": e.action,
            "payload": e.payload,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            "created_at": e.created_at.isoformat(),
        }
        for e in events
    ]
