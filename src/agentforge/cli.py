"""CLI entrypoints."""

from __future__ import annotations

import argparse
import threading

import uvicorn

from agentforge.config import Settings
from agentforge.worker.loop import run_worker_loop


def main() -> None:
    parser = argparse.ArgumentParser(prog="agentforge")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run API + in-process worker")
    serve.add_argument("--host", default=None)
    serve.add_argument("--port", type=int, default=None)

    sub.add_parser("worker", help="Run worker only (same process store required for memory queue)")

    args = parser.parse_args()
    settings = Settings()

    if args.cmd == "serve":
        host = args.host or settings.host
        port = args.port or settings.port
        # Import app before worker so kit/store exist once.
        import agentforge.api.app  # noqa: F401

        thread = threading.Thread(
            target=run_worker_loop,
            kwargs={"poll_seconds": 0.25},
            daemon=True,
        )
        thread.start()
        uvicorn.run("agentforge.api.app:app", host=host, port=port, reload=False)
    elif args.cmd == "worker":
        run_worker_loop()


if __name__ == "__main__":
    main()
