"""Background worker — runs the coding pipeline per queued job."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

import structlog

from agentforge.config import Settings
from agentforge.domain.runs import RunStore

if TYPE_CHECKING:
    from platformkit import PlatformKit

log = structlog.get_logger()

_stop = threading.Event()
_thread: threading.Thread | None = None
_lock = threading.Lock()


def process_once(kit: object, store: RunStore, settings: Settings) -> bool:
    """Dequeue one message and run the pipeline. Returns False if queue empty."""
    from platformkit import PlatformKit

    assert isinstance(kit, PlatformKit)
    msg = kit.queue.dequeue(settings.queue_topic, timeout_seconds=0)
    if msg is None:
        return False

    run_id = str(msg.get("run_id", ""))
    run = store.get(run_id)
    if run is None:
        log.warning("run_missing", run_id=run_id)
        return True

    log.info("run_start", run_id=run_id, repo=run.repo_url)
    from agentforge.pipeline import execute_pipeline

    execute_pipeline(kit=kit, store=store, settings=settings, run=run)
    updated = store.get(run_id)
    log.info(
        "run_finished",
        run_id=run_id,
        status=updated.status if updated else None,
        error=updated.error if updated else None,
    )
    return True


def drain(kit: object, store: RunStore, settings: Settings, *, limit: int = 100) -> int:
    """Process up to `limit` queued jobs; return how many ran."""
    n = 0
    for _ in range(limit):
        if not process_once(kit, store, settings):
            break
        n += 1
    return n


def _loop(kit: PlatformKit, store: RunStore, settings: Settings, poll_seconds: float) -> None:
    log.info(
        "worker_start",
        queue=settings.queue_driver,
        topic=settings.queue_topic,
        agentbox=settings.agentbox_url,
    )
    while not _stop.is_set():
        worked = process_once(kit, store, settings)
        if not worked:
            _stop.wait(poll_seconds)
    log.info("worker_stop")


def start_inline_worker(
    *,
    kit: PlatformKit,
    store: RunStore,
    settings: Settings,
    poll_seconds: float = 0.25,
) -> bool:
    """Start daemon worker once per process. Returns True if started now."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return False
        _stop.clear()
        _thread = threading.Thread(
            target=_loop,
            args=(kit, store, settings, poll_seconds),
            name="agentforge-worker",
            daemon=True,
        )
        _thread.start()
        return True


def stop_inline_worker(*, join_timeout: float = 2.0) -> None:
    global _thread
    with _lock:
        _stop.set()
        thread = _thread
        _thread = None
    if thread is not None:
        thread.join(timeout=join_timeout)


def run_worker_loop(*, poll_seconds: float = 0.5) -> None:
    """Blocking worker (CLI `agentforge worker`). Shares kit/store with API module."""
    from agentforge.api import app as app_module

    start_inline_worker(
        kit=app_module.kit,
        store=app_module.store,
        settings=app_module.settings,
        poll_seconds=poll_seconds,
    )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop_inline_worker()
