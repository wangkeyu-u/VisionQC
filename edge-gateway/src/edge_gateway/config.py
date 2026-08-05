from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class GatewaySettings(BaseSettings):
    """Runtime configuration for one tenant-scoped gateway process.

    The Deployment Pack remains the source of truth for tenant, station,
    product, field mapping and file naming rules.  Environment variables only
    select the pack and provide runtime paths/credentials.
    """

    model_config = SettingsConfigDict(env_prefix="VQC_GATEWAY_", env_file=".env", extra="ignore")

    mode: Literal["demo", "production"] = "demo"
    version: str = "0.1.0"
    gateway_id: str = "gateway-local"
    backend_url: str = "http://localhost:8000/api/v1"
    pack_path: Path = Path("../backend/deployment-packs/manifests/factory-a-transistor.json")
    data_dir: Path = Path("./.visionqc-gateway")
    # A relative default keeps importing the demo app safe on a developer
    # laptop; Compose/production supplies an explicit persistent mount.
    watch_root: Path | None = Path("./.visionqc-gateway/incoming")
    database_path: Path | None = None
    poll_interval_seconds: float = Field(default=1.0, gt=0, le=60)
    heartbeat_interval_seconds: float = Field(default=10.0, gt=0, le=300)
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    stable_for_seconds: float | None = Field(default=None, ge=0, le=3600)
    status_host: str = "127.0.0.1"
    status_port: int = Field(default=8090, ge=1, le=65535)
    status_token: SecretStr | None = None

    # A production gateway must receive a token minted by the customer's IdP
    # or secret provider.  The shared secret is only used to mint a short-lived
    # demo token when ``mode=demo``.
    auth_token: SecretStr | None = None
    auth_secret: SecretStr = SecretStr("visionqc-local-jwt-secret-change-me")
    auth_issuer: str = "visionqc"
    auth_algorithm: str = "HS256"

    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_image_pixels: int = Field(default=40_000_000, gt=0)
    min_width: int = Field(default=32, gt=0)
    min_height: int = Field(default=32, gt=0)
    dark_mean_threshold: float = Field(default=24.0, ge=0, le=255)
    overexposed_mean_threshold: float = Field(default=245.0, ge=0, le=255)
    overexposed_pixel_ratio: float = Field(default=0.35, ge=0, le=1)
    min_sharpness: float = Field(default=2.0, ge=0)

    @property
    def resolved_database_path(self) -> Path:
        return self.database_path or self.data_dir / "gateway.sqlite3"

    def resolved_watch_root(self, pack_root: str) -> Path:
        return (self.watch_root or Path(pack_root)).resolve()

    def validate_mode(self) -> None:
        if self.mode == "production" and self.auth_token is None:
            raise ValueError("production edge gateway requires VQC_GATEWAY_AUTH_TOKEN")
        if self.mode == "production" and self.status_token is None:
            raise ValueError("production edge gateway requires VQC_GATEWAY_STATUS_TOKEN")


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
