from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.deployment import DeploymentManifest
from app.domain import ReviewChoice
from app.policy import PolicyConfig


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class ErrorBody(APIModel):
    code: str
    message: str
    correlation_id: str
    details: dict[str, Any] | None = None


class InspectionContext(APIModel):
    product_code: str = Field(min_length=1, max_length=128)
    product_revision: str | None = Field(default=None, max_length=64)
    batch_no: str = Field(min_length=1, max_length=128)
    station_code: str = Field(min_length=1, max_length=128)
    captured_at: datetime
    source: str = Field(default="api", min_length=1, max_length=64)
    # Canonical workflow fields stay stable; site-specific values (for
    # example paint recipe or equipment alarm references) travel in this
    # auditable, tenant-scoped envelope.
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelEvidence(APIModel):
    model_id: str
    model_version: str
    feature_bank_version: str
    runtime_device: str
    score: float
    heatmap_uri: str
    latency_ms: int
    semantic_defect_confirmed: bool = False


class PolicyEvidence(APIModel):
    version: str
    decision: str
    reason: str
    snapshot: dict[str, Any]


class ImageEvidence(APIModel):
    id: str
    kind: str
    sha256: str
    uri: str
    mime_type: str
    width: int
    height: int


class InspectionResponse(APIModel):
    inspection_id: str
    tenant_id: str
    status: str
    correlation_id: str
    context: InspectionContext
    images: list[ImageEvidence]
    model: ModelEvidence | None = None
    policy: PolicyEvidence | None = None
    review_task_id: str | None = None
    incident_id: str | None = None
    failure_reason: str | None = None
    quality_flags: list[str] = Field(default_factory=list)
    idempotent_replay: bool = False
    created_at: datetime
    updated_at: datetime


class ReviewTaskResponse(APIModel):
    id: str
    inspection_id: str
    status: str
    assignee: str | None
    version: int
    sla_at: datetime | None
    priority: Literal["STANDARD", "HIGH", "CRITICAL"]
    route: Literal["GREY_ZONE", "HIGH_SCORE_HOLD", "SAFE_DEGRADE"]
    batch_no: str
    product_code: str
    station_code: str
    score: float | None
    thumbnail_asset_id: str | None
    held: bool


class ClaimReviewRequest(APIModel):
    expected_version: int = Field(ge=1)


class ReviewDecisionRequest(APIModel):
    expected_version: int = Field(ge=1)
    decision: ReviewChoice
    reason: str | None = Field(default=None, max_length=4000)
    notes: str | None = Field(default=None, max_length=8000)
    confirmed: bool = False
    model_feedback: Literal["FALSE_POSITIVE", "SUSPECTED_FALSE_NEGATIVE"] | None = None

    @model_validator(mode="after")
    def require_reason_for_nonconformance(self) -> ReviewDecisionRequest:
        if self.decision in {
            ReviewChoice.REWORK,
            ReviewChoice.SCRAP,
            ReviewChoice.INVESTIGATE,
            ReviewChoice.UNABLE_TO_DETERMINE,
        } and not (self.reason and self.reason.strip()):
            raise ValueError("reason is required for this decision")
        if (
            self.decision
            in {
                ReviewChoice.REWORK,
                ReviewChoice.SCRAP,
                ReviewChoice.INVESTIGATE,
            }
            and not self.confirmed
        ):
            raise ValueError("confirmed=true is required for high-risk decisions")
        return self


class ReviewDecisionResponse(APIModel):
    review_task_id: str
    decision_id: str
    inspection_id: str
    inspection_status: str
    incident_id: str | None
    task_version: int
    submitted_at: datetime
    actor: str
    correlation_id: str


class IncidentActionRequest(APIModel):
    connector: Literal["MES", "QMS", "DXQ_MOCK"]
    operation: Literal[
        "HOLD_BATCH",
        "RELEASE_BATCH",
        "CREATE_TICKET",
        "UPDATE_TICKET",
        "CLOSE_TICKET",
        "PUBLISH_QUALITY_EVENT",
        "LINK_PROCESS_CONTEXT",
        "ANALYZE_ROOT_CAUSE",
        "CLOSE_QUALITY_CASE",
    ]
    reason: str = Field(min_length=1, max_length=4000)
    payload: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False


class ExternalActionResponse(APIModel):
    id: str
    incident_id: str
    connector: str
    operation: str
    status: str
    attempts: int
    external_reference: str | None
    last_error: str | None
    idempotency_key: str
    updated_at: datetime


class ReplayRequest(APIModel):
    reason: str = Field(min_length=1, max_length=4000)


class CloseIncidentRequest(APIModel):
    owner: str = Field(min_length=1, max_length=128)
    outcome: str = Field(min_length=1, max_length=8000)
    verification_record: str = Field(min_length=1, max_length=8000)


class TimelineEntry(APIModel):
    occurred_at: datetime
    source: str
    action: str
    actor: str
    details: dict[str, Any]
    correlation_id: str


class IncidentEvidence(APIModel):
    score: float
    model_version: str
    policy_version: str
    decision_actor: str
    decision_reason: str


class QualityIncidentResponse(APIModel):
    id: str
    inspection_id: str
    status: str
    severity: str
    created_at: datetime
    updated_at: datetime
    owner: str | None
    disposition: str
    outcome: str | None
    verification_record: str | None
    batch_no: str
    product_code: str
    station_code: str
    evidence: IncidentEvidence
    external_actions: list[ExternalActionResponse]
    timeline: list[TimelineEntry]
    correlation_id: str


class DemoTokenResponse(APIModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    tenant_id: str
    actor_id: str
    roles: list[str]


class DeploymentCreateRequest(APIModel):
    # ``manifest`` is the preferred FDE contract.  The legacy fields remain
    # optional so existing automation can be upgraded without a flag day.
    manifest: DeploymentManifest | None = None
    version: str | None = Field(default=None, min_length=1, max_length=64)
    model: dict[str, Any] = Field(default_factory=dict)
    policy: PolicyConfig | None = None
    connectors: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def require_manifest_or_legacy_fields(self) -> DeploymentCreateRequest:
        if self.manifest is None and (self.version is None or self.policy is None):
            raise ValueError("manifest or version plus policy is required")
        return self


class DeploymentResponse(APIModel):
    id: str
    tenant_id: str
    version: str
    status: str
    model: dict[str, Any]
    policy: dict[str, Any]
    connectors: dict[str, Any]
    approved_by: str | None
    activated_at: datetime | None
    manifest: DeploymentManifest


class TenantSummary(APIModel):
    id: str
    name: str
    status: str


class TenantContextResponse(APIModel):
    tenant: TenantSummary
    current_deployment: DeploymentResponse | None
    available_tenants: list[TenantSummary]


class DatasetSourceType(StrEnum):
    DEMO_SYNTHETIC = "DEMO_SYNTHETIC"
    OFFICIAL_BENCHMARK = "OFFICIAL_BENCHMARK"
    CUSTOMER_PILOT = "CUSTOMER_PILOT"


class DatasetRegistrationStatus(StrEnum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    REVOKED = "REVOKED"


class CustomerDataProvenance(APIModel):
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


class DatasetSource(APIModel):
    schema_version: Literal["visionqc.dataset-source.v1"] = "visionqc.dataset-source.v1"
    source_type: DatasetSourceType
    registration_id: str | None = None
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    status: DatasetRegistrationStatus
    dataset_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_acknowledged: bool
    customer_provenance: CustomerDataProvenance | None = None
    risk_labels: list[str] = Field(default_factory=list)


class DatasetRegistrationRequest(APIModel):
    source_type: DatasetSourceType
    name: str = Field(min_length=1, max_length=256)
    category: str = Field(min_length=1, max_length=128)
    source_path: str | None = Field(default=None, min_length=1, max_length=2000)
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    license_acknowledged: bool = False
    customer_provenance: CustomerDataProvenance | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_source_contract(self) -> DatasetRegistrationRequest:
        if (
            self.source_type == DatasetSourceType.OFFICIAL_BENCHMARK
            and not self.license_acknowledged
        ):
            raise ValueError("OFFICIAL_BENCHMARK requires license_acknowledged=true")
        return self


class DatasetRegistration(APIModel):
    schema_version: Literal["visionqc.dataset-registration.v1"] = "visionqc.dataset-registration.v1"
    source: DatasetSource
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None
    revoked_at: datetime | None = None


class DatasetRegistrationResponse(DatasetRegistration):
    id: str
    tenant_id: str
    created_by: str
    created_at: datetime
    revoked_by: str | None = None
    revoke_reason: str | None = None


class OperationsSummaryResponse(APIModel):
    tenant_id: str
    generated_at: datetime
    window_hours: int = 24
    inspections_24h: int
    route_counts: dict[str, int]
    review_backlog: int
    review_high_risk: int
    incident_counts: dict[str, int]
    gateways_total: int
    gateways_online: int
    gateway_online_rate: float | None
    gateway_queue_depth: int
    upload_success_count: int
    upload_failure_count: int


class IncidentSummaryResponse(APIModel):
    id: str
    inspection_id: str
    status: str
    severity: str
    created_at: datetime
    updated_at: datetime
    owner: str | None
    disposition: str
    batch_no: str
    product_code: str
    station_code: str


class ModelOpsStatusResponse(APIModel):
    tenant_id: str
    pack_key: str
    deployment_version: str
    deployment_status: str
    product_code: str
    model_id: str
    model_version: str
    feature_bank_version: str
    package_verified: bool
    model_release_status: Literal[
        "DRAFT", "EVALUATED", "APPROVED", "ACTIVE", "RETIRED", "INSUFFICIENT_EVIDENCE", "REJECTED"
    ]
    synthetic_smoke: bool
    smoke_checks_passed: int
    smoke_checks_total: int
    test_samples: int
    mvtec_metrics_available: bool
    calibration_constraints_satisfied: bool
    report_generated_at: datetime
    evidence_source: str
    limitations: list[str]
    release_recommendation: list[str]
    qualification_status: str = "INSUFFICIENT_EVIDENCE"
    model_package_sha256: str | None = None
    evidence_package_sha256: str | None = None
    gate_results: dict[str, Any] = Field(default_factory=dict)
    activation_allowed: bool = False
    dataset_source_type: DatasetSourceType = DatasetSourceType.DEMO_SYNTHETIC
    dataset_source_status: DatasetRegistrationStatus | None = None
    dataset_registration_id: str | None = None
    dataset_fingerprint: str | None = None
    report_status: str = "DEMO_ONLY"
    customer_data_gate: str = "BLOCKED_NO_CUSTOMER_DATA"
    risk_labels: list[str] = Field(default_factory=list)


class QualificationCreateRequest(APIModel):
    product_code: str = Field(min_length=1, max_length=128)
    model_id: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=64)
    feature_bank_version: str = Field(min_length=1, max_length=128)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_path: str = Field(min_length=1, max_length=1000)
    evidence_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    deployment_pack_key: str = Field(min_length=1, max_length=128)
    dataset_registration_id: str | None = Field(default=None, min_length=1, max_length=64)
    dataset_source_type: DatasetSourceType | None = None
    dataset_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class QualificationDecisionRequest(APIModel):
    reason: str = Field(min_length=10, max_length=4000)


class ModelQualificationResponse(APIModel):
    id: str
    tenant_id: str
    product_code: str
    model_id: str
    model_version: str
    feature_bank_version: str
    package_sha256: str
    evidence_path: str
    evidence_sha256: str
    deployment_pack_key: str
    status: Literal["DRAFT", "EVALUATED", "APPROVED", "ACTIVE", "RETIRED"]
    qualification_status: str
    metrics: dict[str, Any]
    gates: dict[str, Any]
    evaluated_by: str | None
    approved_by: str | None
    activated_by: str | None
    decision_reason: str | None
    activated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    dataset_registration_id: str | None = None
    dataset_source_type: DatasetSourceType | None = None
    dataset_fingerprint: str | None = None


class SwitchTenantRequest(APIModel):
    tenant_id: str = Field(min_length=1, max_length=64)


class SwitchTenantResponse(DemoTokenResponse):
    switched_from: str


class ActivateDeploymentRequest(APIModel):
    reason: str = Field(min_length=1, max_length=4000)


class HealthResponse(APIModel):
    status: Literal["ok", "degraded"]
    checks: dict[str, bool]


class GatewayHeartbeatRequest(APIModel):
    """Heartbeat sent by a tenant-scoped edge_gateway role."""

    gateway_id: str = Field(min_length=1, max_length=128)
    gateway_version: str = Field(min_length=1, max_length=64)
    station_code: str = Field(min_length=1, max_length=128)
    reported_status: Literal["ONLINE", "DEGRADED", "STARTING", "STOPPING"] = "ONLINE"
    queue_depth: int = Field(ge=0)
    last_error: str | None = Field(default=None, max_length=1000)
    upload_success_count: int = Field(default=0, ge=0)
    upload_failure_count: int = Field(default=0, ge=0)
    deployment_pack_key: str | None = Field(default=None, max_length=128)
    deployment_pack_version: str | None = Field(default=None, max_length=64)
    metrics: dict[str, Any] = Field(default_factory=dict)


class GatewayStatusResponse(APIModel):
    tenant_id: str
    gateway_id: str
    gateway_version: str
    station_code: str
    status: Literal["ONLINE", "DEGRADED", "STALE", "OFFLINE", "STARTING", "STOPPING"]
    reported_status: str
    queue_depth: int
    last_error: str | None
    last_heartbeat_at: datetime
    last_upload_succeeded_at: datetime | None
    last_upload_failed_at: datetime | None
    upload_success_count: int
    upload_failure_count: int
    deployment_pack_key: str | None
    deployment_pack_version: str | None
    metrics: dict[str, Any]
