"""Golden evaluation cases and runner."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentforge.config import Settings
from agentforge.domain.runs import RunStore
from agentforge.github import LocalDraftPRPublisher
from agentforge.pipeline import execute_pipeline
from agentforge.platform import build_kit

CASES_PATH = Path(__file__).resolve().parents[3] / "evals" / "cases.json"


@dataclass
class EvalCase:
    id: str
    issue: str
    repo_url: str
    expect_status: str
    expect_error_contains: str | None = None
    expect_pr_mode: str | None = None
    sandbox_exit_code: int = 0


@dataclass
class EvalResult:
    case_id: str
    passed: bool
    actual_status: str
    detail: str


class _FakeSandbox:
    def __init__(self, exit_code: int) -> None:
        self._exit_code = exit_code

    def run(self, code: str, **_kwargs: object) -> dict[str, object]:
        del code
        return {
            "stdout": "ok" if self._exit_code == 0 else "",
            "stderr": "" if self._exit_code == 0 else "FAIL",
            "exit_code": self._exit_code,
            "backend": "eval-mock",
            "network_isolated": True,
            "oom_killed": False,
        }

    def close(self) -> None:
        return None


def load_cases(path: Path | None = None) -> list[EvalCase]:
    data = json.loads((path or CASES_PATH).read_text(encoding="utf-8"))
    return [EvalCase(**row) for row in data]


def run_eval_suite(
    *,
    cases: list[EvalCase] | None = None,
    work_root: Path | None = None,
    fixtures_env: bool = True,
) -> tuple[list[EvalResult], float]:
    """Run golden cases with mocked sandbox + local draft PR publisher."""
    import os

    if fixtures_env:
        fixtures = Path(__file__).resolve().parents[3] / "fixtures"
        os.environ["AGENTFORGE_FIXTURES_ROOT"] = str(fixtures)

    settings = Settings(
        auth_driver="api_key",
        audit_driver="memory",
        queue_driver="memory",
        work_root=str(work_root or Path("/tmp/agentforge-eval")),
        github_token="",
    )
    kit = build_kit(settings)
    store = RunStore()
    results: list[EvalResult] = []

    for case in cases or load_cases():
        run = store.create(
            tenant_id="eval",
            issue=case.issue,
            repo_url=case.repo_url,
        )
        execute_pipeline(
            kit=kit,
            store=store,
            settings=settings,
            run=run,
            publisher=LocalDraftPRPublisher(),
            sandbox_client=_FakeSandbox(case.sandbox_exit_code),
        )
        updated = store.get(run.id)
        assert updated is not None
        ok = updated.status.value == case.expect_status
        detail = ""
        if case.expect_error_contains:
            err = updated.error or ""
            if case.expect_error_contains not in err:
                ok = False
                detail = f"error missing {case.expect_error_contains!r}: {err!r}"
        if case.expect_pr_mode and updated.pr_mode != case.expect_pr_mode:
            ok = False
            detail = f"pr_mode={updated.pr_mode!r}"
        results.append(
            EvalResult(
                case_id=case.id,
                passed=ok,
                actual_status=updated.status.value,
                detail=detail or ("ok" if ok else f"expected {case.expect_status}"),
            )
        )

    passed = sum(1 for r in results if r.passed)
    rate = passed / len(results) if results else 0.0
    return results, rate


def results_as_dict(results: list[EvalResult], rate: float) -> dict[str, Any]:
    return {
        "pass_rate": rate,
        "passed": sum(1 for r in results if r.passed),
        "total": len(results),
        "results": [
            {
                "id": r.case_id,
                "passed": r.passed,
                "status": r.actual_status,
                "detail": r.detail,
            }
            for r in results
        ],
    }
