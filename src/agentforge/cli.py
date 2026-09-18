"""CLI entrypoints."""

from __future__ import annotations

import argparse
import json
import sys

import uvicorn

from agentforge.config import Settings
from agentforge.evals.runner import results_as_dict, run_eval_suite
from agentforge.worker.loop import run_worker_loop


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentforge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run API (+ inline worker via app lifespan)")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    sub.add_parser("worker", help="Run worker only (shares process store when co-imported)")

    ev = sub.add_parser("eval", help="Run golden eval suite (CI gate)")
    ev.add_argument(
        "--min-pass-rate",
        type=float,
        default=None,
        help="Fail if pass rate is below this (default: settings / 1.0)",
    )

    args = parser.parse_args()
    settings = Settings()

    if args.cmd == "serve":
        # Lifespan starts the inline worker when AGENTFORGE_INLINE_WORKER=true (default).
        uvicorn.run(
            "agentforge.api.app:app",
            host=args.host or settings.host,
            port=args.port or settings.port,
            reload=False,
        )
    elif args.cmd == "worker":
        run_worker_loop()
    elif args.cmd == "eval":
        results, rate = run_eval_suite()
        payload = results_as_dict(results, rate)
        print(json.dumps(payload, indent=2))
        minimum = (
            args.min_pass_rate
            if args.min_pass_rate is not None
            else settings.eval_min_pass_rate
        )
        if rate < minimum:
            print(f"EVAL GATE FAILED: pass_rate={rate:.2f} < min={minimum:.2f}", file=sys.stderr)
            raise SystemExit(1)
        print(f"EVAL GATE PASSED: pass_rate={rate:.2f}", file=sys.stderr)


if __name__ == "__main__":
    main()
