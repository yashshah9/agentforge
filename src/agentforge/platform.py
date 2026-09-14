"""Build platformkit from settings (swappable drivers)."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

from platformkit import PlatformKit

from agentforge.config import Settings


def build_kit(settings: Settings) -> PlatformKit:
    auth: dict[str, Any] = {"driver": settings.auth_driver}
    if settings.auth_driver == "api_key":
        auth["keys"] = settings.api_key_map()
        auth["admin_keys"] = settings.admin_key_list()
    elif settings.auth_driver == "memory":
        pass
    else:
        # custom entry-point driver — pass through known env knobs only
        pass

    audit: dict[str, Any] = {"driver": settings.audit_driver}
    if settings.audit_driver == "postgres":
        audit["dsn"] = settings.postgres_dsn

    queue: dict[str, Any] = {"driver": settings.queue_driver}
    if settings.queue_driver == "redis":
        queue["url"] = settings.redis_url

    return PlatformKit.from_config({"auth": auth, "audit": audit, "queue": queue})


@lru_cache(maxsize=1)
def get_kit() -> PlatformKit:
    return build_kit(Settings())
