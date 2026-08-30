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
    # The selected pack is the only tenant-specific runtime input.  The
    # checked-in default is a neutral electronics example; production uses an
    # absolute path supplied by the deployment environment.
    pack_path: Path = Path(
        "../backend/deployment-packs/examples/electronics-transistor/resolved-deployment-pack.json"
    )
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

    # Privacy boundary: a laptop gateway is local-only unless an operator
    # explicitly enables transfer and records consent for this purpose.
    upload_enabled: bool = False
    data_consent: bool = False
    data_purpose: str = "本地工业质量检测与人工复核"
    retention_days: int = Field(default=30, ge=1, le=3650)
    delete_after_upload: bool = False
    quality_failure_mode: Literal["REJECT", "SAFE_REVIEW"] = "REJECT"

    # Optional USB camera capture.  OpenCV is lazy/optional; the folder
    # watcher remains usable when the dependency or hardware is missing.
    camera_enabled: bool = False
    camera_index: int = Field(default=0, ge=0, le=32)
    camera_output_dir: Path | None = None
    camera_product_code: str | None = None
    camera_batch_no: str | None = None
    camera_station_code: str | None = None
    camera_captured_at_format: str = "%Y%m%dT%H%M%S"
    camera_paint_shop: str = "PAINT_SHOP_UNSPECIFIED"
    camera_line: str = "LINE_UNSPECIFIED"
    camera_model_variant: str = "MODEL_UNSPECIFIED"
    camera_color_code: str = "COLOR_UNSPECIFIED"
    camera_paint_recipe: str = "RECIPE_UNSPECIFIED"
    camera_shift: str = "SHIFT_UNSPECIFIED"

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
    min_contrast: float = Field(default=5.0, ge=0, le=255)

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
        if self.upload_enabled and not self.data_consent:
            raise ValueError(
                "上传客户原图前必须显式设置 VQC_GATEWAY_DATA_CONSENT=true；默认保持本地处理。"
            )


@lru_cache
def get_settings() -> GatewaySettings:
    return GatewaySettings()
