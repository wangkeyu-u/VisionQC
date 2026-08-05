"""Versioned inference and model-package contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared fields."""

    model_config = ConfigDict(extra="forbid")


class PolicyDecision(str, Enum):
    """Deterministic routing outcomes; none is a semantic defect verdict."""

    AUTO_RELEASE = "AUTO_RELEASE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BATCH_HOLD_AND_REVIEW = "BATCH_HOLD_AND_REVIEW"


class ModelReference(StrictModel):
    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    feature_bank_version: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter: Literal["anomalib.patchcore.v2"] = "anomalib.patchcore.v2"
    runtime: str = Field(min_length=1)
    device: str = Field(min_length=1)


class InputReference(StrictModel):
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["image/jpeg", "image/png"]
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ImageReference(StrictModel):
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: Literal["image/png"] = "image/png"
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class AnomalyEvidence(StrictModel):
    score: float = Field(ge=0.0, le=1.0)
    heatmap: ImageReference
    overlay: ImageReference | None = None
    claim_scope: Literal["anomaly_and_region_only"] = "anomaly_and_region_only"
    semantic_defect_confirmed: Literal[False] = False
    root_cause_confirmed: Literal[False] = False
    statement: Literal["Anomaly evidence only; defect semantics and root cause require human confirmation."] = (
        "Anomaly evidence only; defect semantics and root cause require human confirmation."
    )


class PolicyEvidence(StrictModel):
    version: str = Field(min_length=1)
    review_threshold: float = Field(ge=0.0, le=1.0)
    hold_threshold: float = Field(ge=0.0, le=1.0)
    decision: PolicyDecision
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def thresholds_are_ordered(self) -> PolicyEvidence:
        if self.review_threshold >= self.hold_threshold:
            raise ValueError("review_threshold must be less than hold_threshold")
        return self


class LatencyEvidence(StrictModel):
    preprocess_ms: float = Field(ge=0.0)
    inference_ms: float = Field(ge=0.0)
    postprocess_ms: float = Field(ge=0.0)
    total_ms: float = Field(ge=0.0)
    warm: bool


class InferenceResult(StrictModel):
    """Backend-facing immutable result for one successfully scored image."""

    schema_version: Literal["visionqc.inference.v1"] = "visionqc.inference.v1"
    inspection_id: str = Field(min_length=1)
    status: Literal["SCORED"] = "SCORED"
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    model: ModelReference
    input: InputReference
    anomaly: AnomalyEvidence
    policy: PolicyEvidence
    latency: LatencyEvidence
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def policy_matches_score(self) -> InferenceResult:
        score = self.anomaly.score
        if score < self.policy.review_threshold:
            expected = PolicyDecision.AUTO_RELEASE
        elif score < self.policy.hold_threshold:
            expected = PolicyDecision.REVIEW_REQUIRED
        else:
            expected = PolicyDecision.BATCH_HOLD_AND_REVIEW
        if self.policy.decision != expected:
            raise ValueError(f"policy decision {self.policy.decision} does not match score routing {expected}")
        return self


class PackageFile(StrictModel):
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class ModelPackageManifest(StrictModel):
    """Integrity and provenance index stored as model-package.json."""

    package_format: Literal["visionqc.model-package.v1"] = "visionqc.model-package.v1"
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    feature_bank_version: str = Field(min_length=1)
    category: str = Field(default="unknown", min_length=1)
    adapter: Literal["anomalib.patchcore.v2"] = "anomalib.patchcore.v2"
    created_at: datetime
    lifecycle_status: Literal["DRAFT", "EVALUATED", "APPROVED", "ACTIVE", "RETIRED"]
    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    training_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    code_commit: str
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    feature_bank_file: str | None = None
    feature_bank_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    files: dict[str, PackageFile]
    limitations: list[str]


def inference_json_schema() -> dict[str, object]:
    """Return the published JSON Schema for backend code generation/validation."""
    return InferenceResult.model_json_schema()
