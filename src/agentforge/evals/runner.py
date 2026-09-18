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
    data = json.loads(resolve_cases_path(path).read_text(encoding="utf-8"))
    return [EvalCase(**row) for row in data]


def resolve_cases_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    if CASES_PATH.is_file():
        return CASES_PATH
    docker = Path("/app/evals/cases.json")
    if docker.is_file():
        return docker
    raise FileNotFoundError("evals/cases.json not found")


def resolve_baseline_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    bundled = Path(__file__).resolve().parent / "data" / "baseline.json"
    if bundled.is_file():
        return bundled
    repo = Path(__file__).resolve().parents[3] / "evals" / "baseline.json"
    if repo.is_file():
        return repo
    docker = Path("/app/evals/baseline.json")
    if docker.is_file():
        return docker
    raise FileNotFoundError("evals/baseline.json not found")


def snapshot_from_results(results: list[EvalResult], *, pass_rate: float) -> dict[str, object]:
    return {
        "pass_rate": round(pass_rate, 4),
        "cases": {
            r.case_id: {
                "passed": r.passed,
                "status": r.actual_status,
                "detail": r.detail,
            }
            for r in results
        },
    }


def write_baseline(path: Path, results: list[EvalResult], *, pass_rate: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot_from_results(results, pass_rate=pass_rate), indent=2) + "\n",
        encoding="utf-8",
    )


def load_baseline(path: Path | None = None) -> dict[str, object]:
    raw: object = json.loads(resolve_baseline_path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise TypeError("baseline root must be an object")
    return raw


def compare_to_baseline(results: list[EvalResult], baseline: dict[str, object]) -> list[str]:
    """Return regression messages (empty = ok)."""
    regressions: list[str] = []
    prior_cases = baseline.get("cases", {})
    if not isinstance(prior_cases, dict):
        return ["baseline.cases missing or invalid"]
    current = {r.case_id: r for r in results}
    for case_id, prior in prior_cases.items():
        if not isinstance(prior, dict):
            continue
        now = current.get(str(case_id))
        if now is None:
            regressions.append(f"{case_id}: missing from current suite")
            continue
        if prior.get("passed") is True and not now.passed:
            regressions.append(f"{case_id}: was pass, now fail ({now.detail})")
            continue
        prior_status = prior.get("status")
        if (
            prior.get("passed") is True
            and prior_status
            and now.actual_status != prior_status
        ):
            regressions.append(
                f"{case_id}: status changed {prior_status!r} → {now.actual_status!r}"
            )
    return regressions


def run_eval_suite(
    *,
    cases: list[EvalCase] | None = None,
    work_root: Path | None = None,
    fixtures_env: bool = True,
) -> tuple[list[EvalResult], float]:
    """Run golden cases with mocked sandbox + local draft PR publisher."""
    import os

    if fixtures_env:
        repo_fixtures = Path(__file__).resolve().parents[3] / "fixtures"
        docker_fixtures = Path("/app/fixtures")
        if repo_fixtures.is_dir():
            os.environ["AGENTFORGE_FIXTURES_ROOT"] = str(repo_fixtures)
        elif docker_fixtures.is_dir():
            os.environ["AGENTFORGE_FIXTURES_ROOT"] = str(docker_fixtures)

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
