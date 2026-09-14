"""Application settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTFORGE_", env_file=".env", extra="ignore")

    host: str = "0.0.0.0"
    port: int = 8090
    api_keys: str = "dev-key:demo-tenant,other-key:other-tenant"
    admin_keys: str = "admin-key"
    queue_topic: str = "agentforge.runs"
    auth_driver: str = "api_key"
    audit_driver: str = "memory"
    queue_driver: str = "memory"
    redis_url: str = "redis://localhost:6379/0"
    postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/agentforge"
    agentbox_url: str = "http://127.0.0.1:8080"
    work_root: str = "/tmp/agentforge-work"
    sandbox_timeout_seconds: int = 30
    sandbox_memory_mb: int = 256

    def api_key_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in self.api_keys.split(","):
            part = part.strip()
            if not part:
                continue
            if ":" not in part:
                raise ValueError(f"api_keys entries must be key:tenant, got {part!r}")
            key, tenant = part.split(":", 1)
            out[key.strip()] = tenant.strip()
        return out

    def admin_key_list(self) -> list[str]:
        return [k.strip() for k in self.admin_keys.split(",") if k.strip()]
