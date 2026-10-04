"""Optional durable backends for RunStore."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from agentforge.domain.runs import Run, RunStatus, RunStep

_SCHEMA = """
CREATE TABLE IF NOT EXISTS agentforge_runs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    issue TEXT NOT NULL,
    repo_url TEXT NOT NULL,
    status TEXT NOT NULL,
    plan JSONB NOT NULL DEFAULT '[]',
    steps JSONB NOT NULL DEFAULT '[]',
    patch_summary TEXT,
    test_exit_code INTEGER,
    test_stdout TEXT,
    test_stderr TEXT,
    sandbox_backend TEXT,
    network_isolated BOOLEAN,
    pr_url TEXT,
    pr_mode TEXT,
    error TEXT,
    workspace_path TEXT,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    estimated_cost_usd DOUBLE PRECISION NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS agentforge_runs_updated_idx
    ON agentforge_runs (updated_at DESC);
CREATE INDEX IF NOT EXISTS agentforge_runs_tenant_idx
    ON agentforge_runs (tenant_id);
"""


@runtime_checkable
class RunBackend(Protocol):
    def ensure_schema(self) -> None: ...

    def save_run(self, run: Run) -> None: ...

    def get_run(self, run_id: str) -> Run | None: ...

    def load_recent(self, *, limit: int = 500) -> list[Run]: ...

    def clear(self) -> None: ...


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _step_to_dict(step: RunStep) -> dict[str, Any]:
    return {
        "name": step.name,
        "status": step.status,
        "detail": step.detail,
        "latency_ms": step.latency_ms,
    }


def _step_from_dict(d: dict[str, Any]) -> RunStep:
    detail = d.get("detail") or {}
    if not isinstance(detail, dict):
        detail = {}
    return RunStep(
        name=str(d.get("name") or ""),
        status=str(d.get("status") or ""),
        detail=dict(detail),
        latency_ms=int(d.get("latency_ms") or 0),
    )


def _run_to_row(run: Run) -> tuple[Any, ...]:
    return (
        run.id,
        run.tenant_id,
        run.issue,
        run.repo_url,
        run.status.value,
        json.dumps(run.plan),
        json.dumps([_step_to_dict(s) for s in run.steps]),
        run.patch_summary,
        run.test_exit_code,
        run.test_stdout,
        run.test_stderr,
        run.sandbox_backend,
        run.network_isolated,
        run.pr_url,
        run.pr_mode,
        run.error,
        run.workspace_path,
        run.latency_ms,
        run.estimated_cost_usd,
        run.created_at,
        run.updated_at,
        run.started_at,
        run.finished_at,
    )


def _run_from_row(row: Any) -> Run:
    plan_raw = row[5]
    steps_raw = row[6]
    if isinstance(plan_raw, str):
        plan_raw = json.loads(plan_raw)
    if isinstance(steps_raw, str):
        steps_raw = json.loads(steps_raw)
    created = _parse_dt(row[19])
    updated = _parse_dt(row[20])
    assert created is not None and updated is not None
    return Run(
        id=str(row[0]),
        tenant_id=str(row[1]),
        issue=str(row[2]),
        repo_url=str(row[3]),
        status=RunStatus(str(row[4])),
        plan=[str(x) for x in (plan_raw or [])],
        steps=[_step_from_dict(s) for s in (steps_raw or [])],
        patch_summary=str(row[7]) if row[7] is not None else None,
        test_exit_code=int(row[8]) if row[8] is not None else None,
        test_stdout=str(row[9]) if row[9] is not None else None,
        test_stderr=str(row[10]) if row[10] is not None else None,
        sandbox_backend=str(row[11]) if row[11] is not None else None,
        network_isolated=bool(row[12]) if row[12] is not None else None,
        pr_url=str(row[13]) if row[13] is not None else None,
        pr_mode=str(row[14]) if row[14] is not None else None,
        error=str(row[15]) if row[15] is not None else None,
        workspace_path=str(row[16]) if row[16] is not None else None,
        latency_ms=int(row[17] or 0),
        estimated_cost_usd=float(row[18] or 0.0),
        created_at=created,
        updated_at=updated,
        started_at=_parse_dt(row[21]),
        finished_at=_parse_dt(row[22]),
    )


_SELECT = (
    "id, tenant_id, issue, repo_url, status, plan, steps, patch_summary, "
    "test_exit_code, test_stdout, test_stderr, sandbox_backend, network_isolated, "
    "pr_url, pr_mode, error, workspace_path, latency_ms, estimated_cost_usd, "
    "created_at, updated_at, started_at, finished_at"
)


class PostgresRunStore:
    def __init__(self, dsn: str) -> None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "Postgres runs require psycopg. Install agentforge[postgres]."
            ) from exc
        self._psycopg = psycopg
        self._dsn = dsn

    def ensure_schema(self) -> None:
        with self._psycopg.connect(self._dsn) as conn:
            conn.execute(_SCHEMA)
            conn.commit()

    def save_run(self, run: Run) -> None:
        with self._psycopg.connect(self._dsn) as conn:
            conn.execute(
                "INSERT INTO agentforge_runs ("
                "id, tenant_id, issue, repo_url, status, plan, steps, patch_summary, "
                "test_exit_code, test_stdout, test_stderr, sandbox_backend, "
                "network_isolated, pr_url, pr_mode, error, workspace_path, "
                "latency_ms, estimated_cost_usd, created_at, updated_at, "
                "started_at, finished_at"
                ") VALUES ("
                "%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,"
                "%s,%s,%s,%s,%s,%s"
                ") ON CONFLICT (id) DO UPDATE SET "
                "tenant_id=EXCLUDED.tenant_id, issue=EXCLUDED.issue, "
                "repo_url=EXCLUDED.repo_url, status=EXCLUDED.status, "
                "plan=EXCLUDED.plan, steps=EXCLUDED.steps, "
                "patch_summary=EXCLUDED.patch_summary, "
                "test_exit_code=EXCLUDED.test_exit_code, "
                "test_stdout=EXCLUDED.test_stdout, test_stderr=EXCLUDED.test_stderr, "
                "sandbox_backend=EXCLUDED.sandbox_backend, "
                "network_isolated=EXCLUDED.network_isolated, "
                "pr_url=EXCLUDED.pr_url, pr_mode=EXCLUDED.pr_mode, "
                "error=EXCLUDED.error, workspace_path=EXCLUDED.workspace_path, "
                "latency_ms=EXCLUDED.latency_ms, "
                "estimated_cost_usd=EXCLUDED.estimated_cost_usd, "
                "updated_at=EXCLUDED.updated_at, started_at=EXCLUDED.started_at, "
                "finished_at=EXCLUDED.finished_at",
                _run_to_row(run),
            )
            conn.commit()

    def get_run(self, run_id: str) -> Run | None:
        with self._psycopg.connect(self._dsn) as conn:
            row = conn.execute(
                f"SELECT {_SELECT} FROM agentforge_runs WHERE id = %s",
                (run_id,),
            ).fetchone()
        if row is None:
            return None
        return _run_from_row(row)

    def load_recent(self, *, limit: int = 500) -> list[Run]:
        with self._psycopg.connect(self._dsn) as conn:
            rows = conn.execute(
                f"SELECT {_SELECT} FROM agentforge_runs "
                "ORDER BY updated_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [_run_from_row(r) for r in rows]

    def clear(self) -> None:
        with self._psycopg.connect(self._dsn) as conn:
            conn.execute("DELETE FROM agentforge_runs")
            conn.commit()


def build_backend(driver: str, *, postgres_dsn: str) -> RunBackend | None:
    if driver in {"", "memory", "none"}:
        return None
    if driver == "postgres":
        store = PostgresRunStore(postgres_dsn)
        store.ensure_schema()
        return store
    raise ValueError(f"Unknown run store driver {driver!r}")
