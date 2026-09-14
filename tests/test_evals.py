"""Golden eval suite tests."""

from __future__ import annotations

from agentforge.evals.runner import load_cases, results_as_dict, run_eval_suite


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
