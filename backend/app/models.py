from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Tenant(Base, TimestampMixin):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE", nullable=False)


class TenantConfigurationVersion(Base, TimestampMixin):
    """Immutable, tenant-scoped effective configuration and provenance."""

    __tablename__ = "tenant_configuration_versions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "version", name="uq_tenant_configuration_tenant_version"
        ),
        Index("ix_tenant_configuration_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("cfg"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(128), nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    effective_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    source_layers: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False, default="VALID")
    audit_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="DRAFT")
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_version: Mapped[str | None] = mapped_column(String(128))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EdgeGateway(Base, TimestampMixin):
    __tablename__ = "edge_gateways"
    __table_args__ = (
        UniqueConstraint("tenant_id", "gateway_id", name="uq_edge_gateway_tenant_gateway"),
        Index("ix_edge_gateway_tenant_heartbeat", "tenant_id", "last_heartbeat_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("gw"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    gateway_id: Mapped[str] = mapped_column(String(128), nullable=False)
    gateway_version: Mapped[str] = mapped_column(String(64), nullable=False)
    station_code: Mapped[str] = mapped_column(String(128), nullable=False)
    reported_status: Mapped[str] = mapped_column(String(32), nullable=False, default="ONLINE")
    queue_depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_upload_succeeded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_upload_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    upload_success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    upload_failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    deployment_pack_key: Mapped[str | None] = mapped_column(String(128))
    deployment_pack_version: Mapped[str | None] = mapped_column(String(64))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)


class DeploymentPack(Base, TimestampMixin):
    __tablename__ = "deployment_packs"
    __table_args__ = (
        UniqueConstraint("tenant_id", "version", name="uq_deployment_tenant_version"),
        Index(
            "uq_deployment_one_active",
            "tenant_id",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("dep"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    model_config_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    policy_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    connector_config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Canonical v1 manifest.  The legacy snapshots above remain for backwards
    # compatible reads and for existing migrations; new workflow decisions use
    # this immutable configuration bundle.
    manifest: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    configuration_version: Mapped[str | None] = mapped_column(String(128))
    configuration_schema_version: Mapped[str | None] = mapped_column(String(64))
    configuration_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    configuration_snapshot: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    configuration_layers: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    configuration_sources: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    configuration_validation_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="VALID", server_default="VALID"
    )
    configuration_audit: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    approved_by: Mapped[str | None] = mapped_column(String(128))
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ModelQualification(Base, TimestampMixin):
    """Tenant/product-scoped model evidence and release lifecycle."""

    __tablename__ = "model_qualifications"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_code",
            "model_id",
            "model_version",
            name="uq_model_qualification_identity",
        ),
        Index(
            "uq_model_qualification_one_active",
            "tenant_id",
            "product_code",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
            sqlite_where=text("status = 'ACTIVE'"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("qual"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_bank_version: Mapped[str] = mapped_column(String(128), nullable=False)
    package_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence_path: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    deployment_pack_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    qualification_status: Mapped[str] = mapped_column(
        String(32), default="INSUFFICIENT_EVIDENCE", nullable=False
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    gates: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    dataset_registration_id: Mapped[str | None] = mapped_column(String(64), index=True)
    dataset_source_type: Mapped[str | None] = mapped_column(String(32))
    dataset_fingerprint: Mapped[str | None] = mapped_column(String(64))
    evaluated_by: Mapped[str | None] = mapped_column(String(128))
    approved_by: Mapped[str | None] = mapped_column(String(128))
    activated_by: Mapped[str | None] = mapped_column(String(128))
    decision_reason: Mapped[str | None] = mapped_column(Text)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DatasetRegistrationRecord(Base, TimestampMixin):
    """Tenant-scoped immutable dataset source registration and lifecycle."""

    __tablename__ = "dataset_registrations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "dataset_fingerprint", name="uq_dataset_tenant_fingerprint"),
        Index("ix_dataset_registration_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ds"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="DRAFT", nullable=False)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_sha256: Mapped[str | None] = mapped_column(String(64))
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    manifest_uri: Mapped[str] = mapped_column(Text, nullable=False)
    license_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    risk_labels: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    revoked_by: Mapped[str | None] = mapped_column(String(128))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("tenant_id", "product_code", name="uq_product_code"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("prd"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    revision: Mapped[str | None] = mapped_column(String(64))


class Batch(Base, TimestampMixin):
    __tablename__ = "batches"
    __table_args__ = (UniqueConstraint("tenant_id", "batch_no", name="uq_batch_no"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("bat"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    batch_no: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="OPEN", nullable=False)


class Workpiece(Base, TimestampMixin):
    """Generic physical item identity; industry fields stay in metadata."""

    __tablename__ = "workpieces"
    __table_args__ = (UniqueConstraint("tenant_id", "workpiece_id", name="uq_workpiece_identity"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("wp"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    workpiece_id: Mapped[str] = mapped_column(String(128), nullable=False)
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    product_revision: Mapped[str | None] = mapped_column(String(64))
    batch_no: Mapped[str | None] = mapped_column(String(128))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default=text("'{}'")
    )


class Inspection(Base, TimestampMixin):
    __tablename__ = "inspections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_inspection_idempotency"),
        Index("ix_inspection_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("insp"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    deployment_pack_id: Mapped[str] = mapped_column(
        ForeignKey("deployment_packs.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(48), nullable=False, default="RECEIVED")
    product_code: Mapped[str] = mapped_column(String(128), nullable=False)
    product_revision: Mapped[str | None] = mapped_column(String(64))
    workpiece_id: Mapped[str | None] = mapped_column(String(128), index=True)
    batch_no: Mapped[str] = mapped_column(String(128), nullable=False)
    station_code: Mapped[str] = mapped_column(String(128), nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(64), default="api", nullable=False)
    # Optional site-specific context stays generic and tenant-scoped.  It is
    # deliberately not promoted to customer-specific columns so every
    # Deployment Pack keeps the same workflow contract.
    context_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSON, nullable=False, default=dict, server_default=text("'{}'")
    )
    quality_flags: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    failure_reason: Mapped[str | None] = mapped_column(Text)

    image_assets: Mapped[list[ImageAsset]] = relationship(back_populates="inspection")
    inference_results: Mapped[list[InferenceResult]] = relationship(back_populates="inspection")
    policy_decisions: Mapped[list[PolicyDecision]] = relationship(back_populates="inspection")
    review_task: Mapped[ReviewTask | None] = relationship(
        back_populates="inspection", uselist=False
    )
    incident: Mapped[QualityIncident | None] = relationship(
        back_populates="inspection", uselist=False
    )


class ImageAsset(Base):
    __tablename__ = "image_assets"
    __table_args__ = (
        UniqueConstraint("tenant_id", "uri", name="uq_image_asset_uri"),
        CheckConstraint("width > 0 AND height > 0", name="ck_image_dimensions"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("img"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("inspections.id"), index=True, nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int] = mapped_column(Integer, nullable=False)
    height: Mapped[int] = mapped_column(Integer, nullable=False)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    inspection: Mapped[Inspection] = relationship(back_populates="image_assets")


class InferenceResult(Base):
    __tablename__ = "inference_results"
    __table_args__ = (
        UniqueConstraint("inspection_id", "attempt", name="uq_inference_attempt"),
        CheckConstraint("score >= 0 AND score <= 1", name="ck_inference_score"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("inf"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("inspections.id"), index=True, nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_bank_version: Mapped[str] = mapped_column(String(64), nullable=False)
    runtime_device: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    heatmap_uri: Mapped[str] = mapped_column(Text, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    semantic_defect_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    inspection: Mapped[Inspection] = relationship(back_populates="inference_results")


class PolicyDecision(Base):
    __tablename__ = "policy_decisions"
    __table_args__ = (UniqueConstraint("inspection_id", name="uq_policy_inspection"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("pol"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("inspections.id"), index=True, nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    policy_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    inspection: Mapped[Inspection] = relationship(back_populates="policy_decisions")


class ReviewTask(Base, TimestampMixin):
    __tablename__ = "review_tasks"
    __table_args__ = (UniqueConstraint("inspection_id", name="uq_review_inspection"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rev"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("inspections.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), default="OPEN", nullable=False)
    assignee: Mapped[str | None] = mapped_column(String(128))
    sla_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    inspection: Mapped[Inspection] = relationship(back_populates="review_task")
    decision: Mapped[ReviewDecision | None] = relationship(
        back_populates="review_task", uselist=False
    )


class ReviewDecision(Base):
    __tablename__ = "review_decisions"
    __table_args__ = (UniqueConstraint("review_task_id", name="uq_review_decision_task"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("rdec"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    review_task_id: Mapped[str] = mapped_column(ForeignKey("review_tasks.id"), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    model_feedback: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    review_task: Mapped[ReviewTask] = relationship(back_populates="decision")


class QualityIncident(Base, TimestampMixin):
    __tablename__ = "quality_incidents"
    __table_args__ = (UniqueConstraint("inspection_id", name="uq_incident_inspection"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("inc"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    inspection_id: Mapped[str] = mapped_column(
        ForeignKey("inspections.id"), index=True, nullable=False
    )
    status: Mapped[str] = mapped_column(String(48), default="ACTION_PENDING", nullable=False)
    disposition: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), default="MAJOR", nullable=False)
    owner: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str | None] = mapped_column(Text)
    verification_record: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON, nullable=False, default=dict, server_default=text("'{}'")
    )

    inspection: Mapped[Inspection] = relationship(back_populates="incident")
    external_actions: Mapped[list[ExternalAction]] = relationship(back_populates="incident")


# The storage table keeps its historical name for compatibility; the generic
# domain term exposed to new code is quality case.
QualityCase = QualityIncident


class ExternalAction(Base, TimestampMixin):
    __tablename__ = "external_actions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_external_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("ext"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    incident_id: Mapped[str] = mapped_column(
        ForeignKey("quality_incidents.id"), index=True, nullable=False
    )
    connector: Mapped[str] = mapped_column(String(32), nullable=False)
    operation: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_summary: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    response_summary: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    external_reference: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)

    incident: Mapped[QualityIncident] = relationship(back_populates="external_actions")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_tenant_target", "tenant_id", "target_type", "target_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("aud"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StateTransition(Base):
    __tablename__ = "state_transitions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("trn"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    from_state: Mapped[str] = mapped_column(String(48), nullable=False)
    to_state: Mapped[str] = mapped_column(String(48), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class OutboxEvent(Base):
    __tablename__ = "outbox_events"
    __table_args__ = (Index("ix_outbox_pending", "status", "available_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=lambda: new_id("evt"))
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)
    topic: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="PENDING", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _reject_immutable_change(_mapper: Any, _connection: Any, target: Any) -> None:
    raise ValueError(f"{target.__class__.__name__} is append-only")


for immutable_model in (
    AuditEvent,
    StateTransition,
    InferenceResult,
    PolicyDecision,
    ReviewDecision,
):
    event.listen(immutable_model, "before_update", _reject_immutable_change)
    event.listen(immutable_model, "before_delete", _reject_immutable_change)
