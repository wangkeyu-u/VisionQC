"""Canonical dataset source and registration contracts.

The ML workflow intentionally keeps source type separate from evaluation
outcome.  In particular, an official benchmark can produce useful lab
evidence but can never become customer or production evidence by renaming a
report.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from .hashing import sha256_file, sha256_json
from .schemas import StrictModel

DEFAULT_MAX_FILES = 200_000
DEFAULT_MAX_BYTES = 20 * 1024 * 1024 * 1024
OFFICIAL_SUFFIXES = {".png"}
CUSTOMER_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".json", ".csv"}


class DatasetSourceType(StrEnum):
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"
    OFFICIAL_BENCHMARK = "OFFICIAL_BENCHMARK"
    CUSTOMER_PILOT = "CUSTOMER_PILOT"


class DatasetRegistrationStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REVOKED = "REVOKED"


class CustomerDataProvenance(StrictModel):
    """Required provenance before customer data can enter Pilot approval."""

    tenant: str = Field(min_length=1, max_length=128)
    site: str = Field(min_length=1, max_length=128)
    line: str = Field(min_length=1, max_length=128)
    camera: str = Field(min_length=1, max_length=256)
    product: str = Field(min_length=1, max_length=128)
    capture_window_start: datetime
    capture_window_end: datetime
    label_source: str = Field(min_length=1, max_length=512)
    approver: str = Field(min_length=1, max_length=128)
    consent: bool
    retention_policy: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def validate_capture_window(self) -> CustomerDataProvenance:
        if self.capture_window_end <= self.capture_window_start:
            raise ValueError("capture_window_end must be after capture_window_start")
        return self


class DatasetSource(StrictModel):
    """Immutable source identity bound into evidence and audit records."""

    schema_version: str = "visionqc.dataset-source.v1"
    source_type: DatasetSourceType
    registration_id: str | None = None
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    status: DatasetRegistrationStatus
    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_acknowledged: bool = False
    customer_provenance: CustomerDataProvenance | None = None
    risk_labels: list[str] = Field(default_factory=list, max_length=20)


class DatasetRegistration(StrictModel):
    """Portable registration payload shared by CLI/API adapters."""

    schema_version: str = "visionqc.dataset-registration.v1"
    source: DatasetSource
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    revoked_at: datetime | None = None


def demo_dataset_source(category: str) -> DatasetSource:
    """Return the stable built-in fixture identity without requiring files."""
    fingerprint = sha256_json({"source_type": DatasetSourceType.DEMO_SYNTHETIC.value, "fixture": "v1"})
    return DatasetSource(
        source_type=DatasetSourceType.DEMO_SYNTHETIC,
        name="VisionQC built-in demo fixture",
        category=category,
        status=DatasetRegistrationStatus.VALIDATED,
        dataset_fingerprint=fingerprint,
        license_acknowledged=True,
        risk_labels=["DEMO_ONLY", "NO_EFFECT_CLAIM"],
    )


def fingerprint_directory(
    path: Any,
    *,
    source_type: DatasetSourceType,
    category: str,
    max_files: int = DEFAULT_MAX_FILES,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> DatasetSource:
    """Create a content-only source identity for a mounted directory.

    The caller remains responsible for source-specific layout validation.  No
    image or archive bytes are copied by this helper.
    """
    requested = path.expanduser()
    if requested.is_symlink():
        raise ValueError("dataset source root symlinks are not allowed")
    root = requested.resolve()
    if not root.is_dir():
        raise ValueError("dataset source directory does not exist")
    allowed_suffixes = (
        OFFICIAL_SUFFIXES if source_type == DatasetSourceType.OFFICIAL_BENCHMARK else CUSTOMER_SUFFIXES
    )
    files: list[dict[str, Any]] = []
    total_bytes = 0
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise ValueError(f"dataset symlink is not allowed: {item}")
        if item.is_file():
            if item.suffix.lower() not in allowed_suffixes:
                raise ValueError(f"dataset file extension is not allowed: {item}")
            if len(files) >= max_files:
                raise ValueError("dataset directory contains too many files")
            size_bytes = item.stat().st_size
            total_bytes += size_bytes
            if total_bytes > max_bytes:
                raise ValueError("dataset directory exceeds the configured size limit")
            files.append(
                {
                    "path": item.relative_to(root).as_posix(),
                    "sha256": sha256_file(item),
                    "size_bytes": size_bytes,
                }
            )
    if not files:
        raise ValueError("dataset directory contains no files")
    manifest_sha256 = sha256_json(files)
    fingerprint = sha256_json({"source_type": source_type.value, "category": category, "manifest": files})
    return DatasetSource(
        source_type=source_type,
        name=f"{source_type.value} {category}",
        category=category,
        status=DatasetRegistrationStatus.VALIDATED,
        dataset_fingerprint=fingerprint,
        manifest_sha256=manifest_sha256,
        risk_labels=(
            ["NON_COMMERCIAL_BENCHMARK", "NOT_FACTORY_DATA"]
            if source_type == DatasetSourceType.OFFICIAL_BENCHMARK
            else []
        ),
    )
