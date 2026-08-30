from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VQC_", env_file=".env", extra="ignore")

    environment: Literal["local", "test", "demo", "production"] = "local"
    database_url: str = "postgresql+psycopg://visionqc:visionqc@postgres:5432/visionqc"
    auth_secret: SecretStr = SecretStr("change-me-in-non-test-environments")
    auth_algorithm: str = "HS256"
    auth_issuer: str = "visionqc"
    access_token_minutes: int = 60

    storage_backend: Literal["local", "s3"] = "local"
    local_storage_path: Path = Path("/tmp/visionqc-assets")
    dataset_max_upload_bytes: int = 5 * 1024 * 1024 * 1024
    dataset_max_uncompressed_bytes: int = 20 * 1024 * 1024 * 1024
    dataset_max_files: int = 200_000
    dataset_max_compression_ratio: float = 200.0
    dataset_import_roots: str = ""
    s3_endpoint_url: str | None = None
    s3_bucket: str = "visionqc"
    s3_access_key: SecretStr | None = None
    s3_secret_key: SecretStr | None = None
    s3_region: str = "us-east-1"

    max_upload_bytes: int = 20 * 1024 * 1024
    max_image_pixels: int = 40_000_000
    image_quality_enabled: bool = True
    image_quality_min_sharpness: float = Field(default=2.0, ge=0)
    image_quality_dark_mean_threshold: float = Field(default=24.0, ge=0, le=255)
    image_quality_overexposed_mean_threshold: float = Field(default=245.0, ge=0, le=255)
    image_quality_overexposed_pixel_ratio: float = Field(default=0.35, ge=0, le=1)
    image_quality_min_contrast: float = Field(default=5.0, ge=0, le=255)
    process_inline: bool = False
    worker_poll_seconds: float = 0.5
    connector_max_attempts: int = 3
    connector_backoff_seconds: float = 0.05
    gateway_stale_seconds: int = 30
    gateway_offline_seconds: int = 120
    mes_base_url: str = "http://mock-external:8081/mes"
    qms_base_url: str = "http://mock-external:8081/qms"

    model_backend: Literal["stub", "patchcore"] = "stub"
    model_package_path: Path | None = None
    model_device: str = "auto"
    cors_origins: str = "http://localhost:3000,http://localhost:4173"

    # Defaults are deliberately tenant-neutral.  Example tenants are enabled
    # only by an explicit deployment/test setting.
    bootstrap_tenant_id: str = "default-tenant"
    bootstrap_tenant_name: str = "VisionQC Platform Tenant"
    bootstrap_review_threshold: float = Field(default=0.4, ge=0, le=1)
    bootstrap_hold_threshold: float = Field(default=0.8, ge=0, le=1)
    bootstrap_enabled: bool = True
    bootstrap_tenant_ids: str = ""
    demo_switchable_tenant_ids: str = ""
    deployment_manifest_dir: Path | None = None

    @model_validator(mode="after")
    def reject_insecure_production_defaults(self) -> Settings:
        if (
            self.environment == "production"
            and self.auth_secret.get_secret_value() == "change-me-in-non-test-environments"
        ):
            raise ValueError("production requires an explicit VQC_AUTH_SECRET")
        if self.model_backend == "patchcore" and self.model_package_path is None:
            raise ValueError("patchcore backend requires VQC_MODEL_PACKAGE_PATH")
        return self

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def parsed_bootstrap_tenant_ids(self) -> list[str]:
        return [item.strip() for item in self.bootstrap_tenant_ids.split(",") if item.strip()]

    @property
    def parsed_demo_switchable_tenant_ids(self) -> list[str]:
        return [item.strip() for item in self.demo_switchable_tenant_ids.split(",") if item.strip()]

    @property
    def parsed_dataset_import_roots(self) -> list[Path]:
        return [
            Path(item.strip()).expanduser().resolve()
            for item in self.dataset_import_roots.split(",")
            if item.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
