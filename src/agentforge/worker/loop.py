"""Background worker — runs the coding pipeline per queued job."""

from __future__ import annotations

import time

import structlog

from agentforge.config import Settings
from agentforge.domain.runs import RunStore
from agentforge.pipeline import execute_pipeline

log = structlog.get_logger()


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
    execute_pipeline(kit=kit, store=store, settings=settings, run=run)
    updated = store.get(run_id)
    log.info(
        "run_finished",
        run_id=run_id,
        status=updated.status if updated else None,
        error=updated.error if updated else None,
    )
    return True


def run_worker_loop(*, poll_seconds: float = 0.5) -> None:
    # Import app first so API + worker share one kit/store (avoids schema races).
    from agentforge.api import app as app_module

    settings = app_module.settings
    kit = app_module.kit
    store = app_module.store

    log.info(
        "worker_start",
        queue=settings.queue_driver,
        topic=settings.queue_topic,
        agentbox=settings.agentbox_url,
    )
    while True:
        worked = process_once(kit, store, settings)
        if not worked:
            time.sleep(poll_seconds)
