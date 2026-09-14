"""Thin HTTP client for agentbox (no hard dependency on the package)."""

from __future__ import annotations

from typing import Any, cast

import httpx


class AgentboxClient:
    def __init__(self, base_url: str, *, timeout: float = 60.0) -> None:
        self._client = httpx.Client(base_url=base_url.rstrip("/"), timeout=timeout)

    def health(self) -> dict[str, Any]:
        resp = self._client.get("/health")
        resp.raise_for_status()
        return cast(dict[str, Any], resp.json())

    def run(
        self,
        code: str,
        *,
        language: str = "python",
        timeout_seconds: int | None = None,
        memory_mb: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"code": code, "language": language}
        limits: dict[str, Any] = {}
        if timeout_seconds is not None:
            limits["timeout_seconds"] = timeout_seconds
        if memory_mb is not None:
            limits["memory_mb"] = memory_mb
        if limits:
            payload["limits"] = limits
        resp = self._client.post("/v1/run", json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"agentbox HTTP {resp.status_code}: {resp.text}")
        return cast(dict[str, Any], resp.json())

    def close(self) -> None:
        self._client.close()
