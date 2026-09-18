"""Run domain model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from threading import Lock
from typing import Any


class RunStatus(StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    CODING = "coding"
    TESTING = "testing"
    AWAITING_APPROVAL = "awaiting_approval"
    FAILED = "failed"
    DONE = "done"


@dataclass
class RunStep:
    name: str
    status: str
    detail: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


@dataclass
class Run:
    id: str
    tenant_id: str
    issue: str
    repo_url: str
    status: RunStatus = RunStatus.QUEUED
    plan: list[str] = field(default_factory=list)
    steps: list[RunStep] = field(default_factory=list)
    patch_summary: str | None = None
    test_exit_code: int | None = None
    test_stdout: str | None = None
    test_stderr: str | None = None
    sandbox_backend: str | None = None
    network_isolated: bool | None = None
    pr_url: str | None = None
    pr_mode: str | None = None  # github | local
    error: str | None = None
    workspace_path: str | None = None
    latency_ms: int = 0
    estimated_cost_usd: float = 0.0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    finished_at: datetime | None = None


class RunStore:
    """Thread-safe in-process store (API + worker share one process in Docker)."""

    def __init__(self) -> None:
        self._runs: dict[str, Run] = {}
        self._lock = Lock()

    def create(self, *, tenant_id: str, issue: str, repo_url: str) -> Run:
        run = Run(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            issue=issue,
            repo_url=repo_url,
        )
        with self._lock:
            self._runs[run.id] = run
        return run

    def get(self, run_id: str) -> Run | None:
        with self._lock:
            return self._runs.get(run_id)

    def update(self, run_id: str, **fields: object) -> Run | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            for key, value in fields.items():
                if not hasattr(run, key):
                    raise AttributeError(key)
                setattr(run, key, value)
            run.updated_at = datetime.now(UTC)
            return run

    def append_step(self, run_id: str, step: RunStep) -> Run | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run.steps.append(step)
            run.updated_at = datetime.now(UTC)
            return run

    def list_for_tenant(self, tenant_id: str) -> list[Run]:
        with self._lock:
            return [r for r in self._runs.values() if r.tenant_id == tenant_id]

    def list_recent(self, *, limit: int = 20) -> list[Run]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.updated_at, reverse=True)
            return runs[: max(1, limit)]

    def clear(self) -> None:
        with self._lock:
            self._runs.clear()
