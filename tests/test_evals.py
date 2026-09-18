"""Golden eval suite tests."""

from __future__ import annotations

from agentforge.evals.runner import (
    EvalResult,
    compare_to_baseline,
    load_cases,
    results_as_dict,
    run_eval_suite,
    snapshot_from_results,
)


def test_load_cases() -> None:
    cases = load_cases()
    assert len(cases) >= 8
    assert {c.id for c in cases}


def test_eval_suite_passes_gate(tmp_path) -> None:  # type: ignore[no-untyped-def]
    results, rate = run_eval_suite(work_root=tmp_path / "work")
    payload = results_as_dict(results, rate)
    assert payload["total"] == len(results)
    failed = [r for r in results if not r.passed]
    assert failed == [], failed
    assert rate == 1.0


def test_baseline_compare_detects_regression(tmp_path) -> None:  # type: ignore[no-untyped-def]
    results, rate = run_eval_suite(work_root=tmp_path / "work")
    baseline = snapshot_from_results(results, pass_rate=rate)
    assert compare_to_baseline(results, baseline) == []
    broken = [
        EvalResult(
            case_id=results[0].case_id,
            passed=False,
            actual_status="failed",
            detail="forced",
        ),
        *results[1:],
    ]
    regs = compare_to_baseline(broken, baseline)
    assert any(results[0].case_id in m and "was pass, now fail" in m for m in regs)
