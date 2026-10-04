"""Build RunStore with optional durable backend."""

from __future__ import annotations

from agentforge.config import Settings
from agentforge.domain.persist import build_backend
from agentforge.domain.runs import RunStore


def build_store(settings: Settings) -> RunStore:
    backend = build_backend(settings.store_driver, postgres_dsn=settings.postgres_dsn)
    store = RunStore(backend=backend)
    store.load()
    return store
