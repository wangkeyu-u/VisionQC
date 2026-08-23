from __future__ import annotations

import hashlib
import io
import json
import statistics
import tempfile
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy import Select, func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.audit import record_audit, redact
from app.auth import Principal, Role
from app.config import Settings
from app.connectors import Connector, RetryingConnectorExecutor
from app.dataset_sources import DatasetImportError, inspect_dataset_source, store_dataset_source
from app.deployment import DeploymentManifest, legacy_manifest
from app.domain import (
    DomainConflict,
    ExternalActionStatus,
    InspectionStatus,
    PolicyRoute,
    ReviewChoice,
    assert_inspection_transition,
)
from app.model_adapter import ModelAdapter, ModelUnavailable
from app.models import (
    AuditEvent,
    DatasetRegistrationRecord,
    DeploymentPack,
    EdgeGateway,
    ExternalAction,
    ImageAsset,
    InferenceResult,
    Inspection,
    ModelQualification,
    OutboxEvent,
    PolicyDecision,
    QualityIncident,
    ReviewDecision,
    ReviewTask,
    StateTransition,
    Tenant,
)
from app.policy import PolicyConfig, evaluate_policy
from app.qualification import verify_evidence_package
from app.schemas import (
    CloseIncidentRequest,
    DatasetRegistrationRequest,
    DatasetRegistrationResponse,
    DatasetRegistrationStatus,
    DatasetSource,
    DatasetSourceType,
    DeploymentCreateRequest,
    ExternalActionResponse,
    GatewayHeartbeatRequest,
    GatewayStatusResponse,
    ImageEvidence,
    IncidentActionRequest,
    IncidentEvidence,
    InspectionContext,
    InspectionResponse,
    ModelEvidence,
    ModelOpsStatusResponse,
    ModelQualificationResponse,
    OperationsSummaryResponse,
    PolicyEvidence,
    QualificationCreateRequest,
    QualityIncidentResponse,
    ReviewDecisionRequest,
    ReviewTaskResponse,
    TimelineEntry,
)
from app.storage import ObjectStorage


class ServiceError(RuntimeError):
    status_code = 400
    code = "service_error"

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFound(ServiceError):
    status_code = 404
    code = "not_found"


class Conflict(ServiceError):
    status_code = 409
    code = "conflict"


class Forbidden(ServiceError):
    status_code = 403
    code = "forbidden"


class InvalidInput(ServiceError):
    status_code = 422
    code = "invalid_input"


class DependencyUnavailable(ServiceError):
    status_code = 503
    code = "dependency_unavailable"


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    sha256: str
    mime_type: str
    extension: str
    width: int
    height: int
    quality_flags: list[str]


def _quality_flags(image: Image.Image, settings: Settings) -> list[str]:
    """Return abstain flags without rejecting a decodable customer image.

    Security failures are rejected before this function.  Operational quality
    failures are persisted and routed to human review so they can never become
    an automatic release.
    """
    if not settings.image_quality_enabled:
        return []
    gray = image.convert("L")
    if max(gray.size) > 256:
        scale = 256 / max(gray.size)
        gray = gray.resize(
            (max(2, int(gray.width * scale)), max(2, int(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    # ``tobytes`` is both deterministic for mode ``L`` and understood by the
    # Pillow type stubs; unlike ``getdata`` it does not rely on an untyped
    # ImagingCore iterator.
    values = list(gray.tobytes())
    if not values:
        return ["NO_TARGET_OR_EMPTY_FRAME"]
    mean = statistics.fmean(values)
    contrast = statistics.pstdev(values)
    width, height = gray.size
    horizontal = [
        abs(values[(y * width) + x] - values[(y * width) + x + 1])
        for y in range(height)
        for x in range(width - 1)
    ]
    vertical = [
        abs(values[(y * width) + x] - values[((y + 1) * width) + x])
        for y in range(height - 1)
        for x in range(width)
    ]
    sharpness = statistics.fmean(horizontal + vertical) if horizontal or vertical else 0.0
    flags: list[str] = []
    if mean <= settings.image_quality_dark_mean_threshold:
        flags.append("TOO_DARK")
    if (
        mean >= settings.image_quality_overexposed_mean_threshold
        or sum(value >= 250 for value in values) / len(values)
        >= settings.image_quality_overexposed_pixel_ratio
    ):
        flags.append("OVEREXPOSED")
    if sharpness < settings.image_quality_min_sharpness:
        flags.append("BLURRY")
    if contrast < settings.image_quality_min_contrast:
        flags.append("LOW_CONTRAST_OR_NO_TARGET")
    return flags


def validate_image(data: bytes, content_type: str | None, settings: Settings) -> ValidatedImage:
    if not data:
        raise InvalidInput("empty image upload")
    if len(data) > settings.max_upload_bytes:
        raise InvalidInput("image exceeds configured byte limit")
    allowed = {"image/jpeg": ("JPEG", "jpg"), "image/png": ("PNG", "png")}
    if content_type not in allowed:
        raise InvalidInput("only JPEG and PNG images are accepted")
    quality_flags: list[str]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                image.load()
                width, height = image.size
                detected_format = image.format
                quality_flags = _quality_flags(image, settings)
    except (UnidentifiedImageError, OSError, Image.DecompressionBombWarning) as exc:
        raise InvalidInput("image cannot be safely decoded") from exc
    expected_format, extension = allowed[content_type]
    if detected_format != expected_format:
        raise InvalidInput("declared content type does not match decoded image")
    if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
        raise InvalidInput("image dimensions exceed configured safety limits")
    return ValidatedImage(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        mime_type=content_type,
        extension=extension,
        width=width,
        height=height,
        quality_flags=quality_flags,
    )


def request_fingerprint(image: ValidatedImage, context: InspectionContext) -> str:
    payload = {"image_sha256": image.sha256, **context.model_dump(mode="json")}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class VisionQCService:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: sessionmaker[Session],
        storage: ObjectStorage,
        model_adapter: ModelAdapter,
        connectors: dict[str, Connector],
    ):
        self.settings = settings
        self.session_factory = session_factory
        self.storage = storage
        self.model_adapter = model_adapter
        self.connectors = connectors
        self.connector_executor = RetryingConnectorExecutor(
            max_attempts=settings.connector_max_attempts,
            backoff_seconds=settings.connector_backoff_seconds,
        )

    def active_deployment(self, session: Session, tenant_id: str) -> DeploymentPack:
        deployment = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.tenant_id == tenant_id,
                DeploymentPack.status == "ACTIVE",
            )
        )
        if deployment is None:
            raise DependencyUnavailable("no active deployment pack is configured for this tenant")
        return deployment

    def record_gateway_heartbeat(
        self,
        session: Session,
        *,
        principal: Principal,
        request: GatewayHeartbeatRequest,
        correlation_id: str,
    ) -> GatewayStatusResponse:
        """Persist a tenant-scoped heartbeat; tenant and gateway identity come from JWT."""

        if request.gateway_id != principal.actor_id:
            raise Forbidden("gateway identity does not match authenticated principal")
        deployment = self.active_deployment(session, principal.tenant_id)
        manifest = self.deployment_manifest(session, deployment)
        self._assert_gateway_pack_binding(principal, manifest)
        if request.deployment_pack_key and request.deployment_pack_key != manifest.pack_key:
            raise InvalidInput("gateway deployment pack does not match the active tenant pack")
        if request.deployment_pack_version and request.deployment_pack_version != manifest.version:
            raise InvalidInput(
                "gateway deployment pack version does not match the active tenant pack"
            )
        if manifest.resolve_station(request.station_code) is None:
            raise InvalidInput("gateway station is not enabled by the active deployment pack")

        now = datetime.now(UTC)
        gateway = session.scalar(
            select(EdgeGateway).where(
                EdgeGateway.tenant_id == principal.tenant_id,
                EdgeGateway.gateway_id == request.gateway_id,
            )
        )
        previous_status = gateway.reported_status if gateway else None
        previous_success_count = gateway.upload_success_count if gateway else 0
        previous_failure_count = gateway.upload_failure_count if gateway else 0
        if gateway is None:
            gateway = EdgeGateway(
                tenant_id=principal.tenant_id,
                gateway_id=request.gateway_id,
                gateway_version=request.gateway_version,
                station_code=request.station_code,
                reported_status=request.reported_status,
                queue_depth=request.queue_depth,
                last_error=request.last_error,
                last_heartbeat_at=now,
                upload_success_count=request.upload_success_count,
                upload_failure_count=request.upload_failure_count,
                deployment_pack_key=request.deployment_pack_key or manifest.pack_key,
                deployment_pack_version=request.deployment_pack_version or manifest.version,
                metrics=request.metrics,
            )
            session.add(gateway)
        else:
            gateway.gateway_version = request.gateway_version
            gateway.station_code = request.station_code
            gateway.reported_status = request.reported_status
            gateway.queue_depth = request.queue_depth
            gateway.last_error = request.last_error
            gateway.last_heartbeat_at = now
            gateway.upload_success_count = request.upload_success_count
            gateway.upload_failure_count = request.upload_failure_count
            gateway.deployment_pack_key = request.deployment_pack_key or manifest.pack_key
            gateway.deployment_pack_version = request.deployment_pack_version or manifest.version
            gateway.metrics = request.metrics
            if request.upload_success_count > previous_success_count:
                gateway.last_upload_succeeded_at = now
            if request.upload_failure_count > previous_failure_count:
                gateway.last_upload_failed_at = now
        session.flush()
        if gateway.last_error:
            gateway.last_upload_failed_at = gateway.last_upload_failed_at or now
        if gateway.id and (previous_status is None or previous_status != request.reported_status):
            record_audit(
                session,
                tenant_id=principal.tenant_id,
                actor=principal.actor_id,
                action="gateway.status_changed",
                target_type="edge_gateway",
                target_id=gateway.id,
                correlation_id=correlation_id,
                payload={
                    "gateway_id": gateway.gateway_id,
                    "station_code": gateway.station_code,
                    "reported_status": request.reported_status,
                    "queue_depth": request.queue_depth,
                },
            )
        return self.gateway_status_response(gateway)

    def _assert_gateway_pack_binding(
        self, principal: Principal, manifest: DeploymentManifest
    ) -> None:
        """Require edge credentials to name the gateway registered by the pack."""

        if Role.EDGE_GATEWAY not in principal.roles:
            return
        configured = manifest.edge_gateway
        if configured is None or configured.gateway_id != principal.actor_id:
            raise Forbidden("gateway identity is not registered by the active deployment pack")

    def gateway_status_response(self, gateway: EdgeGateway) -> GatewayStatusResponse:
        heartbeat = gateway.last_heartbeat_at
        if heartbeat.tzinfo is None:
            heartbeat = heartbeat.replace(tzinfo=UTC)
        age_seconds = (datetime.now(UTC) - heartbeat).total_seconds()
        if age_seconds > self.settings.gateway_offline_seconds:
            effective_status = "OFFLINE"
        elif age_seconds > self.settings.gateway_stale_seconds:
            effective_status = "STALE"
        elif gateway.reported_status in {"STARTING", "STOPPING"}:
            effective_status = gateway.reported_status
        elif gateway.reported_status == "DEGRADED" or gateway.queue_depth > 0:
            effective_status = "DEGRADED"
        else:
            effective_status = "ONLINE"
        return GatewayStatusResponse(
            tenant_id=gateway.tenant_id,
            gateway_id=gateway.gateway_id,
            gateway_version=gateway.gateway_version,
            station_code=gateway.station_code,
            status=effective_status,
            reported_status=gateway.reported_status,
            queue_depth=gateway.queue_depth,
            last_error=gateway.last_error,
            last_heartbeat_at=heartbeat,
            last_upload_succeeded_at=gateway.last_upload_succeeded_at,
            last_upload_failed_at=gateway.last_upload_failed_at,
            upload_success_count=gateway.upload_success_count,
            upload_failure_count=gateway.upload_failure_count,
            deployment_pack_key=gateway.deployment_pack_key,
            deployment_pack_version=gateway.deployment_pack_version,
            metrics=gateway.metrics,
        )

    def list_gateway_statuses(
        self, session: Session, tenant_id: str
    ) -> list[GatewayStatusResponse]:
        gateways = session.scalars(
            select(EdgeGateway)
            .where(EdgeGateway.tenant_id == tenant_id)
            .order_by(EdgeGateway.station_code, EdgeGateway.gateway_id)
        )
        return [self.gateway_status_response(item) for item in gateways]

    def operations_summary(self, session: Session, tenant_id: str) -> OperationsSummaryResponse:
        """Return tenant-scoped operational aggregates for the control room."""

        now = datetime.now(UTC)
        window_start = now - timedelta(hours=24)
        inspection_rows = session.execute(
            select(Inspection.status, func.count())
            .where(
                Inspection.tenant_id == tenant_id,
                Inspection.created_at >= window_start,
            )
            .group_by(Inspection.status)
        ).all()
        route_rows = session.execute(
            select(PolicyDecision.decision, func.count())
            .join(Inspection, Inspection.id == PolicyDecision.inspection_id)
            .where(
                PolicyDecision.tenant_id == tenant_id,
                Inspection.created_at >= window_start,
            )
            .group_by(PolicyDecision.decision)
        ).all()
        incident_rows = session.execute(
            select(QualityIncident.status, func.count())
            .where(QualityIncident.tenant_id == tenant_id)
            .group_by(QualityIncident.status)
        ).all()
        review_backlog = int(
            session.scalar(
                select(func.count())
                .select_from(ReviewTask)
                .where(ReviewTask.tenant_id == tenant_id, ReviewTask.status == "OPEN")
            )
            or 0
        )
        review_high_risk = int(
            session.scalar(
                select(func.count())
                .select_from(ReviewTask)
                .join(Inspection, Inspection.id == ReviewTask.inspection_id)
                .where(
                    ReviewTask.tenant_id == tenant_id,
                    ReviewTask.status == "OPEN",
                    Inspection.status == InspectionStatus.BATCH_HELD,
                )
            )
            or 0
        )
        gateways = self.list_gateway_statuses(session, tenant_id)
        online = sum(item.status == "ONLINE" for item in gateways)
        return OperationsSummaryResponse(
            tenant_id=tenant_id,
            generated_at=now,
            inspections_24h=sum(int(count) for _, count in inspection_rows),
            route_counts={str(route): int(count) for route, count in route_rows},
            review_backlog=review_backlog,
            review_high_risk=review_high_risk,
            incident_counts={str(status): int(count) for status, count in incident_rows},
            gateways_total=len(gateways),
            gateways_online=online,
            gateway_online_rate=(online / len(gateways)) if gateways else None,
            gateway_queue_depth=sum(item.queue_depth for item in gateways),
            upload_success_count=sum(item.upload_success_count for item in gateways),
            upload_failure_count=sum(item.upload_failure_count for item in gateways),
        )

    def list_incidents(self, session: Session, tenant_id: str) -> list[QualityIncident]:
        return list(
            session.scalars(
                select(QualityIncident)
                .where(QualityIncident.tenant_id == tenant_id)
                .order_by(QualityIncident.updated_at.desc())
            )
        )

    @staticmethod
    def dataset_response(item: DatasetRegistrationRecord) -> DatasetRegistrationResponse:
        provenance = item.metadata_json.get("customer_provenance")
        return DatasetRegistrationResponse(
            id=item.id,
            tenant_id=item.tenant_id,
            source=DatasetSource(
                source_type=item.source_type,
                registration_id=item.id,
                name=item.name,
                category=item.category,
                status=item.status,
                dataset_fingerprint=item.dataset_fingerprint,
                manifest_sha256=item.manifest_sha256,
                source_sha256=item.source_sha256,
                license_acknowledged=item.license_acknowledged,
                customer_provenance=provenance,
                risk_labels=item.risk_labels,
            ),
            metadata=item.metadata_json,
            created_by=item.created_by,
            created_at=item.created_at,
            revoked_by=item.revoked_by,
            revoked_at=item.revoked_at,
            revoke_reason=item.revoke_reason,
        )

    def _dataset_limits(self) -> dict[str, int | float]:
        return {
            "max_bytes": self.settings.dataset_max_upload_bytes,
            "max_files": self.settings.dataset_max_files,
            "max_uncompressed_bytes": self.settings.dataset_max_uncompressed_bytes,
            "max_compression_ratio": self.settings.dataset_max_compression_ratio,
        }

    def register_dataset(
        self,
        session: Session,
        *,
        principal: Principal,
        request: DatasetRegistrationRequest,
        source_path: Path | None = None,
        correlation_id: str,
    ) -> DatasetRegistrationRecord:
        tenant = session.get(Tenant, principal.tenant_id)
        if tenant is None or tenant.status != "ACTIVE":
            raise Forbidden("tenant is not active")
        if request.source_type == DatasetSourceType.DEMO_SYNTHETIC:
            raise InvalidInput(
                "DEMO_SYNTHETIC is built into the application and does not accept imported bytes"
            )
        path = source_path or (Path(request.source_path) if request.source_path else None)
        if path is None:
            raise InvalidInput(
                "a mounted source_path or upload is required for optional dataset registration"
            )
        if source_path is None:
            resolved_path = path.expanduser().resolve()
            allowed_roots = self.settings.parsed_dataset_import_roots
            if self.settings.environment == "production" and not allowed_roots:
                raise InvalidInput(
                    "mounted dataset imports require VQC_DATASET_IMPORT_ROOTS in production; "
                    "use the controlled upload endpoint otherwise"
                )
            if allowed_roots and not any(
                resolved_path.is_relative_to(root) for root in allowed_roots
            ):
                raise InvalidInput("dataset source is outside the configured import roots")
        provenance = request.customer_provenance
        metadata = dict(request.metadata)
        risk_labels: list[str] = []
        if provenance is not None:
            if provenance.tenant != principal.tenant_id:
                raise Forbidden(
                    "customer dataset provenance tenant does not match the authenticated tenant"
                )
            metadata["customer_provenance"] = provenance.model_dump(mode="json")
        if request.source_type == DatasetSourceType.CUSTOMER_PILOT and provenance is None:
            risk_labels.extend(["CUSTOMER_PROVENANCE_INCOMPLETE", "PILOT_APPROVAL_BLOCKED"])
        if (
            request.source_type == DatasetSourceType.CUSTOMER_PILOT
            and provenance is not None
            and not provenance.consent
        ):
            risk_labels.extend(["CUSTOMER_CONSENT_NOT_CONFIRMED", "PILOT_APPROVAL_BLOCKED"])
        if request.source_type == DatasetSourceType.OFFICIAL_BENCHMARK:
            risk_labels.extend(["NON_COMMERCIAL_BENCHMARK", "NOT_FACTORY_DATA"])
        try:
            limits = self._dataset_limits()
            inspection = inspect_dataset_source(
                path,
                source_type=request.source_type.value,
                category=request.category,
                max_bytes=int(limits["max_bytes"]),
                max_files=int(limits["max_files"]),
                max_uncompressed_bytes=int(limits["max_uncompressed_bytes"]),
                max_compression_ratio=float(limits["max_compression_ratio"]),
            )
        except (DatasetImportError, OSError) as exc:
            raise InvalidInput(
                "dataset source validation failed", details={"reason": str(exc)}
            ) from exc
        expected_sha = inspection["source_sha256"] or inspection["manifest_sha256"]
        if request.expected_sha256 and request.expected_sha256 != expected_sha:
            raise InvalidInput(
                "dataset source SHA-256 does not match the declared digest",
                details={"expected": request.expected_sha256, "actual": expected_sha},
            )
        registration_digest = hashlib.sha256(
            f"{principal.tenant_id}:{expected_sha}".encode()
        ).hexdigest()[:32]
        registration_id = f"ds_{registration_digest}"
        try:
            storage_uri, manifest_uri = store_dataset_source(
                path,
                tenant_id=principal.tenant_id,
                registration_id=registration_id,
                source_type=request.source_type.value,
                category=request.category,
                storage=self.storage,
                inspection=inspection,
                max_bytes=self.settings.dataset_max_upload_bytes,
            )
        except (DatasetImportError, OSError, ValueError) as exc:
            raise InvalidInput(
                "dataset source storage failed", details={"reason": str(exc)}
            ) from exc
        status = "VALIDATED"
        if request.source_type == DatasetSourceType.CUSTOMER_PILOT and (
            provenance is None or not provenance.consent
        ):
            status = "DRAFT"
        metadata.update(
            {
                "source_name": path.name,
                "import_mode": "upload" if source_path is not None else "mounted",
                "file_count": inspection["file_count"],
                "total_bytes": inspection["total_bytes"],
                "source_size_bytes": inspection["source_size_bytes"],
                "manifest_sha256": inspection["manifest_sha256"],
            }
        )
        item = DatasetRegistrationRecord(
            id=registration_id,
            tenant_id=principal.tenant_id,
            name=request.name,
            source_type=request.source_type.value,
            category=request.category,
            status=status,
            dataset_fingerprint=inspection["dataset_fingerprint"],
            manifest_sha256=inspection["manifest_sha256"],
            source_sha256=inspection["source_sha256"],
            storage_uri=storage_uri,
            manifest_uri=manifest_uri,
            license_acknowledged=request.license_acknowledged,
            metadata_json=metadata,
            risk_labels=sorted(set(risk_labels)),
            created_by=principal.actor_id,
        )
        session.add(item)
        try:
            session.flush()
        except IntegrityError as exc:
            raise Conflict("dataset fingerprint is already registered for this tenant") from exc
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="dataset_registration.created",
            target_type="dataset_registration",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={
                "source_type": item.source_type,
                "category": item.category,
                "status": item.status,
                "dataset_fingerprint": item.dataset_fingerprint,
                "manifest_sha256": item.manifest_sha256,
                "source_sha256": item.source_sha256,
                "risk_labels": item.risk_labels,
            },
        )
        return item

    def register_dataset_upload(
        self,
        session: Session,
        *,
        principal: Principal,
        request: DatasetRegistrationRequest,
        source: Any,
        filename: str,
        correlation_id: str,
    ) -> DatasetRegistrationRecord:
        suffix = Path(filename).suffix.lower()
        if not suffix or suffix not in {".zip", ".tar", ".gz", ".xz", ".tgz", ".txz"}:
            raise InvalidInput("dataset upload extension is not allowed")
        staging_root = self.settings.local_storage_path / "dataset-staging"
        staging_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix="dataset-", suffix=suffix, dir=staging_root, delete=False
        ) as handle:
            staging_path = Path(handle.name)
            size = 0
            try:
                while block := source.read(1024 * 1024):
                    size += len(block)
                    if size > self.settings.dataset_max_upload_bytes:
                        raise InvalidInput("dataset upload exceeds the configured size limit")
                    handle.write(block)
            except Exception:
                staging_path.unlink(missing_ok=True)
                raise
        try:
            return self.register_dataset(
                session,
                principal=principal,
                request=request,
                source_path=staging_path,
                correlation_id=correlation_id,
            )
        finally:
            staging_path.unlink(missing_ok=True)

    def list_dataset_registrations(
        self, session: Session, tenant_id: str
    ) -> list[DatasetRegistrationRecord]:
        return list(
            session.scalars(
                select(DatasetRegistrationRecord)
                .where(DatasetRegistrationRecord.tenant_id == tenant_id)
                .order_by(DatasetRegistrationRecord.created_at.desc())
            )
        )

    def revoke_dataset_registration(
        self,
        session: Session,
        *,
        principal: Principal,
        registration_id: str,
        reason: str,
        correlation_id: str,
    ) -> DatasetRegistrationRecord:
        item = session.scalar(
            select(DatasetRegistrationRecord).where(
                DatasetRegistrationRecord.id == registration_id,
                DatasetRegistrationRecord.tenant_id == principal.tenant_id,
            )
        )
        if item is None:
            raise NotFound("dataset registration not found")
        if item.status == "REVOKED":
            raise Conflict("dataset registration is already revoked")
        item.status = "REVOKED"
        item.revoked_by = principal.actor_id
        item.revoked_at = datetime.now(UTC)
        item.revoke_reason = reason
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="dataset_registration.revoked",
            target_type="dataset_registration",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={
                "reason": reason,
                "dataset_fingerprint": item.dataset_fingerprint,
                "evidence_binding_unchanged": True,
            },
        )
        return item

    def modelops_status(self, session: Session, tenant_id: str) -> ModelOpsStatusResponse:
        deployment = self.active_deployment(session, tenant_id)
        manifest = self.deployment_manifest(session, deployment)
        product = manifest.products[0] if manifest.products else None
        if product is None:
            raise DependencyUnavailable("active deployment pack has no product evidence")
        qualification = session.scalar(
            select(ModelQualification).where(
                ModelQualification.tenant_id == tenant_id,
                ModelQualification.product_code == product.code,
                ModelQualification.model_id == manifest.model.id,
                ModelQualification.model_version == manifest.model.version,
            )
        )
        dataset = session.scalar(
            select(DatasetRegistrationRecord)
            .where(
                DatasetRegistrationRecord.tenant_id == tenant_id,
                DatasetRegistrationRecord.category == product.code,
                DatasetRegistrationRecord.status != "REVOKED",
            )
            .order_by(DatasetRegistrationRecord.created_at.desc())
        )
        source_type = (
            DatasetSourceType(dataset.source_type) if dataset else DatasetSourceType.DEMO_SYNTHETIC
        )
        source_status = DatasetRegistrationStatus(dataset.status) if dataset else None
        customer_data_gate = (
            "PASS"
            if dataset
            and source_type == DatasetSourceType.CUSTOMER_PILOT
            and source_status == DatasetRegistrationStatus.VALIDATED
            and dataset.metadata_json.get("customer_provenance", {}).get("consent") is True
            else "BLOCKED_NO_CUSTOMER_DATA"
            if source_type != DatasetSourceType.CUSTOMER_PILOT
            else "BLOCKED_CUSTOMER_PROVENANCE_INCOMPLETE"
        )
        risk_labels = list(dataset.risk_labels) if dataset else ["DEMO_ONLY", "NO_EFFECT_CLAIM"]
        report_scope = {
            "factory-a": "Factory A",
            "factory-b": "Factory B",
            "duerr-demo": "Duerr Demo",
        }.get(tenant_id, tenant_id)
        report_dir = (
            Path(__file__).resolve().parents[2]
            / "reports"
            / "pilot-qualification"
            / report_scope
            / product.code
        )
        qualification_status = (
            qualification.qualification_status
            if qualification
            else "DEMO_ONLY"
            if dataset is None
            else "CUSTOMER_PILOT_INSUFFICIENT_EVIDENCE"
            if source_type == DatasetSourceType.CUSTOMER_PILOT
            else "BENCHMARK_INSUFFICIENT_EVIDENCE"
        )
        report_status = qualification_status
        release_status = qualification.status if qualification else "DRAFT"
        metrics: dict[str, Any] = {}
        gates: dict[str, Any] = {}
        evidence_package_sha256: str | None = None
        report_binding_matches = False
        report_decision: dict[str, Any] | None = None
        if dataset and (report_dir / "provenance.json").is_file():
            try:
                report_provenance = json.loads(
                    (report_dir / "provenance.json").read_text(encoding="utf-8")
                )
                report_binding_matches = (
                    report_provenance.get("source_type") == source_type.value
                    and report_provenance.get("dataset_fingerprint") == dataset.dataset_fingerprint
                )
            except (OSError, json.JSONDecodeError):
                report_binding_matches = False
        if dataset and report_binding_matches and (report_dir / "metrics.json").is_file():
            try:
                metrics_payload = json.loads(
                    (report_dir / "metrics.json").read_text(encoding="utf-8")
                )
                metrics = metrics_payload.get("metrics", {})
                gates = metrics_payload.get("gates", {})
            except (OSError, json.JSONDecodeError):
                qualification_status = (
                    "CUSTOMER_PILOT_INSUFFICIENT_EVIDENCE"
                    if source_type == DatasetSourceType.CUSTOMER_PILOT
                    else "BENCHMARK_INSUFFICIENT_EVIDENCE"
                )
                report_status = qualification_status
        if dataset and report_binding_matches and (report_dir / "release-decision.json").is_file():
            try:
                report_decision = json.loads(
                    (report_dir / "release-decision.json").read_text(encoding="utf-8")
                )
                evidence_package_sha256 = report_decision.get("evidence_package_sha256")
                if qualification is None:
                    report_status = str(report_decision.get("decision", report_status))
                    qualification_status = report_status
            except (OSError, json.JSONDecodeError):
                qualification_status = (
                    "CUSTOMER_PILOT_INSUFFICIENT_EVIDENCE"
                    if source_type == DatasetSourceType.CUSTOMER_PILOT
                    else "BENCHMARK_INSUFFICIENT_EVIDENCE"
                )
                report_status = qualification_status
        if dataset is None:
            report_status = "DEMO_ONLY"
            qualification_status = "DEMO_ONLY"
            metrics = {}
            gates = {}
        elif qualification is not None:
            report_status = qualification.qualification_status
        gate_checks = gates.get("checks", {}) if isinstance(gates, dict) else {}
        gate_values_are_safe = bool(gate_checks) and all(
            item.get("status") in {"PASS", "NOT_APPLICABLE"} for item in gate_checks.values()
        )
        pilot_gate_contract = {
            "version": "visionqc-pilot-gates.v3",
            "threshold_selection": {
                "allowed_source_split": "validation",
                "holdout_used_for_tuning": False,
                "holdout_usage": "one frozen final report only",
            },
            "checks": {
                "abnormal_auto_release_rate": {
                    "operator": "<=",
                    "threshold": 0.0,
                    "gate_class": "HARD_GATE",
                    "label": "异常样本自动放行必须为 0",
                },
                "review_hold_abnormal_recall": {
                    "operator": ">=",
                    "threshold": 0.95,
                    "gate_class": "HARD_GATE",
                    "label": "Review + Hold 异常召回率",
                },
                "hold_abnormal_recall": {
                    "operator": ">=",
                    "threshold": 0.80,
                    "gate_class": "HARD_GATE",
                    "label": "Hold 异常召回率",
                },
                "normal_manual_review_rate": {
                    "operator": "<=",
                    "threshold": 0.35,
                    "gate_class": "OPERATIONAL_TARGET",
                    "label": "正常样本进入人工复核目标",
                },
            },
            "safe_degrade": {
                "ood": "REVIEW_OR_HOLD",
                "image_quality_failure": "REVIEW_OR_HOLD",
                "abstain": "NEVER_AUTO_RELEASE",
            },
            "evaluation_status": (
                "PASS" if gate_values_are_safe else "NOT_EVALUATED" if not gate_checks else "FAIL"
            ),
        }
        gate_results = dict(gates) if isinstance(gates, dict) else {}
        gate_results["pilot_gate_contract"] = pilot_gate_contract
        # The endpoint reports the conservative release boundary.  A demo Pack
        # can remain ACTIVE for workflow smoke while the model is not qualified.
        return ModelOpsStatusResponse(
            tenant_id=tenant_id,
            pack_key=manifest.pack_key,
            deployment_version=manifest.version,
            deployment_status=deployment.status,
            product_code=product.code,
            model_id=manifest.model.id,
            model_version=manifest.model.version,
            feature_bank_version=manifest.model.feature_bank_version,
            package_verified=bool(manifest.model.package_sha256),
            model_release_status=release_status,
            synthetic_smoke=True,
            smoke_checks_passed=1,
            smoke_checks_total=1,
            test_samples=int(metrics.get("test_samples", metrics.get("sample_count", 0)) or 0),
            mvtec_metrics_available=source_type == DatasetSourceType.OFFICIAL_BENCHMARK
            and bool(metrics.get("image_auroc") is not None),
            calibration_constraints_satisfied=gate_values_are_safe,
            report_generated_at=datetime.fromtimestamp(report_dir.stat().st_mtime, tz=UTC)
            if report_dir.is_dir()
            else datetime(2026, 8, 4, 14, 38, tzinfo=UTC),
            evidence_source=(
                str(report_dir.relative_to(Path(__file__).resolve().parents[2]))
                if report_dir.is_dir()
                else "reports/pilot-qualification (not available)"
            ),
            limitations=[
                *manifest.model.limitations,
                "资格包与模型包摘要不匹配时必须拒绝发布。",
                "DEMO_SYNTHETIC 仅用于演示闭环，不得用于效果声明。",
                "MVTec AD 仅用于 Benchmark Qualification / Pre-Pilot Lab Validation，"
                "不代表任何工厂现场效果。",
                "只有 CUSTOMER_PILOT provenance 完整且通过客户数据 gate，才可进入 Pilot approval。",
            ],
            release_recommendation=[
                "没有可选数据时保持 DEMO_ONLY；不要把演示 fixture 当作效果证据。",
                "MVTec 结果最多为 BENCHMARK_PASS / READY_FOR_CUSTOMER_DATA，不能 APPROVED/ACTIVE。",
                "取得客户数据及完整 provenance 后，重新评测并校准阈值。",
                "完成 shadow 对比、人工复核回流与回滚条件审查后再申请发布。",
            ],
            qualification_status=qualification_status,
            model_package_sha256=manifest.model.package_sha256
            if manifest.model.package_sha256
            else None,
            evidence_package_sha256=evidence_package_sha256,
            gate_results=gate_results,
            activation_allowed=bool(
                qualification
                and qualification.status == "APPROVED"
                and qualification.gates.get("decision") == "GO"
                and source_type == DatasetSourceType.CUSTOMER_PILOT
                and customer_data_gate == "PASS"
            ),
            dataset_source_type=source_type,
            dataset_source_status=source_status,
            dataset_registration_id=dataset.id if dataset else None,
            dataset_fingerprint=dataset.dataset_fingerprint if dataset else None,
            report_status=report_status,
            customer_data_gate=customer_data_gate,
            risk_labels=risk_labels,
        )

    @staticmethod
    def _qualification_response(item: ModelQualification) -> ModelQualificationResponse:
        return ModelQualificationResponse.model_validate(item)

    def list_qualifications(self, session: Session, tenant_id: str) -> list[ModelQualification]:
        return list(
            session.scalars(
                select(ModelQualification)
                .where(ModelQualification.tenant_id == tenant_id)
                .order_by(ModelQualification.created_at.desc())
            )
        )

    def create_qualification(
        self,
        session: Session,
        *,
        principal: Principal,
        request: QualificationCreateRequest,
        correlation_id: str,
    ) -> ModelQualification:
        tenant = session.get(Tenant, principal.tenant_id)
        if tenant is None or tenant.status != "ACTIVE":
            raise Forbidden("tenant is not active")
        dataset = None
        if request.dataset_registration_id:
            dataset = session.scalar(
                select(DatasetRegistrationRecord).where(
                    DatasetRegistrationRecord.id == request.dataset_registration_id,
                    DatasetRegistrationRecord.tenant_id == principal.tenant_id,
                )
            )
            if dataset is None:
                raise NotFound("dataset registration not found")
            if dataset.status == "REVOKED":
                raise InvalidInput("revoked dataset registrations cannot bind new evidence")
            if (
                request.dataset_source_type
                and request.dataset_source_type.value != dataset.source_type
            ):
                raise InvalidInput("dataset source type does not match the registered dataset")
            if (
                request.dataset_fingerprint
                and request.dataset_fingerprint != dataset.dataset_fingerprint
            ):
                raise InvalidInput("dataset fingerprint does not match the registered dataset")
        elif request.dataset_source_type not in {None, DatasetSourceType.DEMO_SYNTHETIC}:
            raise InvalidInput("non-demo qualification evidence must bind a dataset registration")
        item = ModelQualification(
            tenant_id=principal.tenant_id,
            product_code=request.product_code,
            model_id=request.model_id,
            model_version=request.model_version,
            feature_bank_version=request.feature_bank_version,
            package_sha256=request.package_sha256,
            evidence_path=request.evidence_path,
            evidence_sha256=request.evidence_sha256,
            deployment_pack_key=request.deployment_pack_key,
            dataset_registration_id=dataset.id if dataset else None,
            dataset_source_type=(
                dataset.source_type
                if dataset
                else request.dataset_source_type.value
                if request.dataset_source_type
                else None
            ),
            dataset_fingerprint=(
                dataset.dataset_fingerprint if dataset else request.dataset_fingerprint
            ),
        )
        session.add(item)
        try:
            session.flush()
        except IntegrityError as exc:
            raise Conflict(
                "model qualification identity already exists for tenant/product"
            ) from exc
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="model_qualification.created",
            target_type="model_qualification",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={
                "product_code": item.product_code,
                "model_id": item.model_id,
                "model_version": item.model_version,
                "deployment_pack_key": item.deployment_pack_key,
                "dataset_registration_id": item.dataset_registration_id,
                "dataset_source_type": item.dataset_source_type,
                "dataset_fingerprint": item.dataset_fingerprint,
                "reason": "draft evidence candidate registered",
            },
        )
        return item

    def _qualification(
        self, session: Session, tenant_id: str, qualification_id: str
    ) -> ModelQualification:
        item = session.scalar(
            select(ModelQualification).where(
                ModelQualification.id == qualification_id,
                ModelQualification.tenant_id == tenant_id,
            )
        )
        if item is None:
            raise NotFound("model qualification not found")
        return item

    def evaluate_qualification(
        self,
        session: Session,
        *,
        principal: Principal,
        qualification_id: str,
        reason: str,
        correlation_id: str,
    ) -> ModelQualification:
        item = self._qualification(session, principal.tenant_id, qualification_id)
        if item.status != "DRAFT":
            raise Conflict(f"only DRAFT qualifications can be evaluated, got {item.status}")
        try:
            evidence = verify_evidence_package(
                Path(item.evidence_path), expected_model_package_sha256=item.package_sha256
            )
        except (OSError, ValueError) as exc:
            raise InvalidInput(
                "qualification evidence verification failed", details={"reason": str(exc)}
            ) from exc
        if evidence["evidence_package_sha256"] != item.evidence_sha256:
            raise InvalidInput("qualification evidence digest does not match registered digest")
        source_type = str(evidence.get("source_type") or item.dataset_source_type or "")
        if item.dataset_source_type and source_type != item.dataset_source_type:
            raise InvalidInput(
                "qualification evidence source type does not match the registered dataset"
            )
        evidence_fingerprint = evidence.get("dataset_fingerprint")
        if item.dataset_fingerprint and evidence_fingerprint != item.dataset_fingerprint:
            raise InvalidInput(
                "qualification evidence dataset fingerprint does not match the registration"
            )
        if source_type != "DEMO_SYNTHETIC" and not item.dataset_registration_id:
            raise InvalidInput("benchmark/customer evidence must bind a dataset registration")
        gate_decision = str(evidence.get("gate_decision") or "INSUFFICIENT_EVIDENCE")
        approval_status = str(evidence.get("approval_status") or "BLOCKED")
        item.status = (
            "EVALUATED"
            if gate_decision == "GO" and approval_status == "PENDING_APPROVAL"
            else "DRAFT"
        )
        item.qualification_status = str(evidence.get("decision") or "INSUFFICIENT_EVIDENCE")
        item.metrics = evidence.get("metrics", {})
        item.gates = evidence.get("gates", {})
        item.evaluated_by = principal.actor_id
        item.decision_reason = reason
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="model_qualification.evaluated",
            target_type="model_qualification",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={
                "reason": reason,
                "evidence_package_sha256": item.evidence_sha256,
                "decision": item.qualification_status,
                "gate_decision": gate_decision,
                "source_type": source_type,
                "dataset_fingerprint": item.dataset_fingerprint,
                "lifecycle_status": item.status,
            },
        )
        return item

    def approve_qualification(
        self,
        session: Session,
        *,
        principal: Principal,
        qualification_id: str,
        reason: str,
        correlation_id: str,
    ) -> ModelQualification:
        item = self._qualification(session, principal.tenant_id, qualification_id)
        if item.status != "EVALUATED":
            raise Conflict(f"only EVALUATED qualifications can be approved, got {item.status}")
        if item.evaluated_by == principal.actor_id:
            raise Forbidden("the evaluator cannot approve the same qualification")
        if (
            item.gates.get("decision") != "GO"
            or not item.gates
            or any(check.get("status") != "PASS" for check in item.gates.get("checks", {}).values())
            or item.dataset_source_type != "CUSTOMER_PILOT"
            or not item.dataset_registration_id
        ):
            raise InvalidInput(
                "all mandatory gates and CUSTOMER_PILOT provenance must pass before approval; "
                "benchmark/demo evidence is not approvable"
            )
        dataset = session.scalar(
            select(DatasetRegistrationRecord).where(
                DatasetRegistrationRecord.id == item.dataset_registration_id,
                DatasetRegistrationRecord.tenant_id == principal.tenant_id,
            )
        )
        if (
            dataset is None
            or dataset.status != "VALIDATED"
            or dataset.dataset_fingerprint != item.dataset_fingerprint
        ):
            raise InvalidInput(
                "customer dataset registration is missing, revoked, or fingerprint-mismatched"
            )
        provenance = dataset.metadata_json.get("customer_provenance", {})
        if provenance.get("tenant") != principal.tenant_id or provenance.get("consent") is not True:
            raise InvalidInput("customer data provenance gate is incomplete")
        verify_evidence_package(
            Path(item.evidence_path), expected_model_package_sha256=item.package_sha256
        )
        item.status = "APPROVED"
        item.approved_by = principal.actor_id
        item.decision_reason = reason
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="model_qualification.approved",
            target_type="model_qualification",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={"reason": reason, "evidence_package_sha256": item.evidence_sha256},
        )
        return item

    def activate_qualification(
        self,
        session: Session,
        *,
        principal: Principal,
        qualification_id: str,
        reason: str,
        correlation_id: str,
    ) -> ModelQualification:
        item = self._qualification(session, principal.tenant_id, qualification_id)
        if item.status != "APPROVED":
            raise Conflict(f"only APPROVED qualifications can be activated, got {item.status}")
        if principal.actor_id in {item.evaluated_by, item.approved_by}:
            raise Forbidden("evaluation, approval, and activation require distinct actors")
        active_pack = self.active_deployment(session, principal.tenant_id)
        manifest = self.deployment_manifest(session, active_pack)
        if manifest.pack_key != item.deployment_pack_key or not any(
            product.code == item.product_code for product in manifest.products
        ):
            raise Forbidden(
                "qualification deployment pack or product does not match the active tenant pack"
            )
        if (
            manifest.model.id != item.model_id
            or manifest.model.version != item.model_version
            or manifest.model.package_sha256 != item.package_sha256
        ):
            raise Forbidden(
                "active Deployment Pack model identity or package digest does not match "
                "qualification evidence"
            )
        if item.dataset_source_type != "CUSTOMER_PILOT" or not item.dataset_registration_id:
            raise Forbidden("only CUSTOMER_PILOT evidence with provenance can be activated")
        dataset = session.scalar(
            select(DatasetRegistrationRecord).where(
                DatasetRegistrationRecord.id == item.dataset_registration_id,
                DatasetRegistrationRecord.tenant_id == principal.tenant_id,
            )
        )
        if (
            dataset is None
            or dataset.status != "VALIDATED"
            or dataset.dataset_fingerprint != item.dataset_fingerprint
        ):
            raise Forbidden(
                "customer dataset registration is missing, revoked, or fingerprint-mismatched"
            )
        if dataset.metadata_json.get("customer_provenance", {}).get("consent") is not True:
            raise Forbidden("customer data provenance consent is not complete")
        verify_evidence_package(
            Path(item.evidence_path), expected_model_package_sha256=item.package_sha256
        )
        current = session.scalar(
            select(ModelQualification).where(
                ModelQualification.tenant_id == principal.tenant_id,
                ModelQualification.product_code == item.product_code,
                ModelQualification.status == "ACTIVE",
            )
        )
        if current and current.id != item.id:
            current.status = "RETIRED"
        item.status = "ACTIVE"
        item.activated_by = principal.actor_id
        item.activated_at = datetime.now(UTC)
        item.decision_reason = reason
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="model_qualification.activated",
            target_type="model_qualification",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={
                "reason": reason,
                "deployment_pack_key": item.deployment_pack_key,
                "package_sha256": item.package_sha256,
            },
        )
        return item

    def retire_qualification(
        self,
        session: Session,
        *,
        principal: Principal,
        qualification_id: str,
        reason: str,
        correlation_id: str,
    ) -> ModelQualification:
        item = self._qualification(session, principal.tenant_id, qualification_id)
        if item.status not in {"APPROVED", "ACTIVE"}:
            raise Conflict(
                f"only APPROVED or ACTIVE qualifications can be retired, got {item.status}"
            )
        item.status = "RETIRED"
        item.decision_reason = reason
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="model_qualification.retired",
            target_type="model_qualification",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={"reason": reason},
        )
        return item

    def rollback_qualification(
        self,
        session: Session,
        *,
        principal: Principal,
        qualification_id: str,
        reason: str,
        correlation_id: str,
    ) -> ModelQualification:
        item = self._qualification(session, principal.tenant_id, qualification_id)
        if item.status != "RETIRED":
            raise Conflict("rollback target must be RETIRED")
        if principal.actor_id in {item.evaluated_by, item.approved_by}:
            raise Forbidden("rollback requires an operator distinct from evaluation and approval")
        active_pack = self.active_deployment(session, principal.tenant_id)
        manifest = self.deployment_manifest(session, active_pack)
        if (
            manifest.pack_key != item.deployment_pack_key
            or manifest.model.package_sha256 != item.package_sha256
        ):
            raise Forbidden("rollback package is not bound to the active Deployment Pack")
        verify_evidence_package(
            Path(item.evidence_path), expected_model_package_sha256=item.package_sha256
        )
        current = session.scalar(
            select(ModelQualification).where(
                ModelQualification.tenant_id == principal.tenant_id,
                ModelQualification.product_code == item.product_code,
                ModelQualification.status == "ACTIVE",
            )
        )
        if current and current.id != item.id:
            current.status = "RETIRED"
        item.status = "ACTIVE"
        item.activated_by = principal.actor_id
        item.activated_at = datetime.now(UTC)
        item.decision_reason = f"rollback: {reason}"
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="model_qualification.rollback",
            target_type="model_qualification",
            target_id=item.id,
            correlation_id=correlation_id,
            payload={"reason": reason},
        )
        return item

    def deployment_manifest(
        self, session: Session, deployment: DeploymentPack
    ) -> DeploymentManifest:
        if deployment.manifest:
            try:
                return DeploymentManifest.model_validate(deployment.manifest)
            except ValidationError as exc:
                raise DependencyUnavailable(
                    "active deployment pack manifest is invalid",
                    details={"deployment_id": deployment.id},
                ) from exc
        tenant = session.get(Tenant, deployment.tenant_id)
        tenant_name = tenant.name if tenant else deployment.tenant_id
        try:
            return legacy_manifest(
                tenant_id=deployment.tenant_id,
                tenant_name=tenant_name,
                version=deployment.version,
                model=deployment.model_config_snapshot,
                policy=PolicyConfig.model_validate(deployment.policy_config),
                connectors=deployment.connector_config,
            )
        except ValidationError as exc:
            raise DependencyUnavailable(
                "legacy deployment pack configuration is invalid",
                details={"deployment_id": deployment.id},
            ) from exc

    def context_from_fields(
        self,
        session: Session,
        *,
        principal: Principal,
        fields: Mapping[str, Any],
    ) -> InspectionContext:
        """Parse customer fields using the authenticated tenant's active pack."""

        deployment = self.active_deployment(session, principal.tenant_id)
        manifest = self.deployment_manifest(session, deployment)

        def read_field(canonical_name: str, *, optional: bool = False) -> str | None:
            submitted_key = manifest.field_mapping.key_for(canonical_name)
            value = fields.get(submitted_key)
            if value is None or not isinstance(value, str) or not value.strip():
                if optional:
                    return None
                raise InvalidInput(
                    f"required deployment field {submitted_key!r} is missing",
                    details={
                        "canonical_field": canonical_name,
                        "submitted_field": submitted_key,
                        "deployment_pack": manifest.pack_key,
                    },
                )
            assert isinstance(value, str)
            return value.strip()

        context = InspectionContext(
            product_code=read_field("product_code") or "",
            product_revision=read_field("product_revision", optional=True),
            batch_no=read_field("batch_no") or "",
            station_code=read_field("station_code") or "",
            captured_at=read_field("captured_at") or "",
            source=read_field("source", optional=True) or "api",
            metadata=self._context_metadata(fields),
        )
        if manifest.resolve_product(context.product_code) is None:
            raise InvalidInput(
                "product is not enabled by the active deployment pack",
                details={
                    "product_code": context.product_code,
                    "allowed_products": [item.code for item in manifest.products],
                },
            )
        if manifest.resolve_station(context.station_code) is None:
            raise InvalidInput(
                "station is not enabled by the active deployment pack",
                details={
                    "station_code": context.station_code,
                    "allowed_stations": [item.code for item in manifest.stations],
                },
            )
        return context

    @staticmethod
    def _context_metadata(fields: Mapping[str, Any]) -> dict[str, Any]:
        raw = fields.get("context_metadata_json")
        if raw is None or raw == "":
            return {}
        if not isinstance(raw, str):
            raise InvalidInput("context metadata must be a JSON object")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidInput("context metadata is not valid JSON") from exc
        if not isinstance(value, dict):
            raise InvalidInput("context metadata must be a JSON object")
        # The metadata envelope is intentionally bounded and JSON-only.  It is
        # evidence context, not an unvalidated command channel.
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16_384:
            raise InvalidInput("context metadata is too large")
        return value

    def _record_security_rejection(
        self,
        *,
        principal: Principal,
        idempotency_key: str,
        correlation_id: str,
        reason: str,
    ) -> None:
        with self.session_factory() as audit_session:
            if audit_session.get(Tenant, principal.tenant_id) is None:
                return
            record_audit(
                audit_session,
                tenant_id=principal.tenant_id,
                actor=principal.actor_id,
                action="security.upload_rejected",
                target_type="upload",
                target_id=hashlib.sha256(idempotency_key.encode()).hexdigest()[:32],
                correlation_id=correlation_id,
                payload={"reason": reason},
            )
            audit_session.commit()

    def create_inspection(
        self,
        session: Session,
        *,
        principal: Principal,
        context: InspectionContext,
        image_bytes: bytes,
        content_type: str | None,
        idempotency_key: str,
        correlation_id: str,
    ) -> InspectionResponse:
        if Role.EDGE_GATEWAY in principal.roles:
            deployment = self.active_deployment(session, principal.tenant_id)
            self._assert_gateway_pack_binding(
                principal, self.deployment_manifest(session, deployment)
            )
        try:
            image = validate_image(image_bytes, content_type, self.settings)
        except InvalidInput as exc:
            self._record_security_rejection(
                principal=principal,
                idempotency_key=idempotency_key,
                correlation_id=correlation_id,
                reason=exc.message,
            )
            raise
        fingerprint = request_fingerprint(image, context)
        existing = session.scalar(
            select(Inspection).where(
                Inspection.tenant_id == principal.tenant_id,
                Inspection.idempotency_key == idempotency_key,
            )
        )
        if existing:
            if existing.request_fingerprint != fingerprint:
                raise Conflict("idempotency key was already used with a different request")
            return self.inspection_response(session, existing, idempotent_replay=True)

        tenant = session.get(Tenant, principal.tenant_id)
        if tenant is None or tenant.status != "ACTIVE":
            raise Forbidden("tenant is not active")
        deployment = self.active_deployment(session, principal.tenant_id)
        # The request parser normally performs this check.  Keep the service
        # boundary defensive for non-HTTP callers and legacy integrations.
        manifest = self.deployment_manifest(session, deployment)
        if manifest.resolve_product(context.product_code) is None:
            raise InvalidInput("product is not enabled by the active deployment pack")
        if manifest.resolve_station(context.station_code) is None:
            raise InvalidInput("station is not enabled by the active deployment pack")

        inspection = Inspection(
            tenant_id=principal.tenant_id,
            deployment_pack_id=deployment.id,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            correlation_id=correlation_id,
            status=InspectionStatus.RECEIVED,
            product_code=context.product_code,
            product_revision=context.product_revision,
            batch_no=context.batch_no,
            station_code=context.station_code,
            captured_at=context.captured_at,
            source=context.source,
            context_metadata=context.metadata,
            quality_flags=image.quality_flags,
        )
        session.add(inspection)
        try:
            session.flush()
        except IntegrityError:
            session.rollback()
            concurrent = session.scalar(
                select(Inspection).where(
                    Inspection.tenant_id == principal.tenant_id,
                    Inspection.idempotency_key == idempotency_key,
                )
            )
            if concurrent and concurrent.request_fingerprint == fingerprint:
                return self.inspection_response(session, concurrent, idempotent_replay=True)
            raise Conflict(
                "idempotency key was concurrently used with a different request"
            ) from None
        key = f"{principal.tenant_id}/originals/{inspection.id}/{image.sha256}.{image.extension}"
        uri = self.storage.put_immutable(key, image.data, image.mime_type)
        session.add(
            ImageAsset(
                tenant_id=principal.tenant_id,
                inspection_id=inspection.id,
                kind="ORIGINAL",
                sha256=image.sha256,
                uri=uri,
                mime_type=image.mime_type,
                width=image.width,
                height=image.height,
                source=context.source,
            )
        )
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="inspection.received",
            target_type="inspection",
            target_id=inspection.id,
            correlation_id=correlation_id,
            payload={"image_sha256": image.sha256, "source": context.source},
        )
        self._transition_inspection(
            session,
            inspection,
            InspectionStatus.VALIDATED,
            actor=principal.actor_id,
            reason="input and tenant context validated",
        )
        session.add(
            OutboxEvent(
                tenant_id=principal.tenant_id,
                topic="inspection.inference_requested",
                aggregate_id=inspection.id,
                correlation_id=correlation_id,
                payload={"inspection_id": inspection.id},
            )
        )
        session.flush()
        if self.settings.process_inline:
            self.process_inference(session, inspection.id, tenant_id=principal.tenant_id)
        return self.inspection_response(session, inspection)

    def get_inspection(
        self, session: Session, *, tenant_id: str, inspection_id: str
    ) -> InspectionResponse:
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == inspection_id, Inspection.tenant_id == tenant_id
            )
        )
        if inspection is None:
            raise NotFound("inspection not found")
        return self.inspection_response(session, inspection)

    def list_inspections(
        self, session: Session, *, tenant_id: str, limit: int = 20
    ) -> list[InspectionResponse]:
        inspections = session.scalars(
            select(Inspection)
            .where(Inspection.tenant_id == tenant_id)
            .order_by(Inspection.created_at.desc())
            .limit(limit)
        )
        return [self.inspection_response(session, item) for item in inspections]

    def get_image_asset(self, session: Session, *, tenant_id: str, asset_id: str) -> ImageAsset:
        asset = session.scalar(
            select(ImageAsset).where(ImageAsset.id == asset_id, ImageAsset.tenant_id == tenant_id)
        )
        if asset is None:
            raise NotFound("image asset not found")
        return asset

    def inspection_response(
        self, session: Session, inspection: Inspection, *, idempotent_replay: bool = False
    ) -> InspectionResponse:
        session.flush()
        images = list(
            session.scalars(
                select(ImageAsset)
                .where(
                    ImageAsset.inspection_id == inspection.id,
                    ImageAsset.tenant_id == inspection.tenant_id,
                )
                .order_by(ImageAsset.created_at)
            )
        )
        inference = session.scalar(
            select(InferenceResult)
            .where(
                InferenceResult.inspection_id == inspection.id,
                InferenceResult.tenant_id == inspection.tenant_id,
            )
            .order_by(InferenceResult.attempt.desc())
        )
        policy = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.inspection_id == inspection.id,
                PolicyDecision.tenant_id == inspection.tenant_id,
            )
        )
        review = session.scalar(
            select(ReviewTask).where(
                ReviewTask.inspection_id == inspection.id,
                ReviewTask.tenant_id == inspection.tenant_id,
            )
        )
        incident = session.scalar(
            select(QualityIncident).where(
                QualityIncident.inspection_id == inspection.id,
                QualityIncident.tenant_id == inspection.tenant_id,
            )
        )
        return InspectionResponse(
            inspection_id=inspection.id,
            tenant_id=inspection.tenant_id,
            status=inspection.status,
            correlation_id=inspection.correlation_id,
            context=InspectionContext(
                product_code=inspection.product_code,
                product_revision=inspection.product_revision,
                batch_no=inspection.batch_no,
                station_code=inspection.station_code,
                captured_at=inspection.captured_at,
                source=inspection.source,
                metadata=inspection.context_metadata,
            ),
            images=[
                ImageEvidence(
                    id=image.id,
                    kind=image.kind,
                    sha256=image.sha256,
                    uri=image.uri,
                    mime_type=image.mime_type,
                    width=image.width,
                    height=image.height,
                )
                for image in images
            ],
            model=(
                ModelEvidence(
                    model_id=inference.model_id,
                    model_version=inference.model_version,
                    feature_bank_version=inference.feature_bank_version,
                    runtime_device=inference.runtime_device,
                    score=inference.score,
                    heatmap_uri=inference.heatmap_uri,
                    latency_ms=inference.latency_ms,
                    semantic_defect_confirmed=inference.semantic_defect_confirmed,
                )
                if inference
                else None
            ),
            policy=(
                PolicyEvidence(
                    version=policy.policy_version,
                    decision=policy.decision,
                    reason=policy.reason,
                    snapshot=policy.policy_snapshot,
                )
                if policy
                else None
            ),
            review_task_id=review.id if review else None,
            incident_id=incident.id if incident else None,
            failure_reason=inspection.failure_reason,
            quality_flags=list(inspection.quality_flags or []),
            idempotent_replay=idempotent_replay,
            created_at=inspection.created_at,
            updated_at=inspection.updated_at,
        )

    def process_inference(
        self, session: Session, inspection_id: str, tenant_id: str | None = None
    ) -> None:
        inspection_query = select(Inspection).where(Inspection.id == inspection_id)
        if tenant_id is not None:
            inspection_query = inspection_query.where(Inspection.tenant_id == tenant_id)
        inspection = session.scalar(inspection_query)
        if inspection is None or inspection.status != InspectionStatus.VALIDATED:
            return
        self._transition_inspection(
            session,
            inspection,
            InspectionStatus.INFERENCING,
            actor="system:model-worker",
            reason="model invocation started",
        )
        if inspection.quality_flags:
            inspection.failure_reason = (
                "safe-degrade: image quality gate failed ("
                + ", ".join(inspection.quality_flags)
                + ")"
            )
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.INFERENCE_FAILED,
                actor="system:quality-gate",
                reason=inspection.failure_reason,
            )
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.REVIEW_REQUIRED,
                actor="system:policy",
                reason="image quality is insufficient; human review required",
            )
            self._ensure_review_task(session, inspection)
            self._mark_inference_outbox_processed(
                session, inspection.id, tenant_id=inspection.tenant_id
            )
            return
        original = session.scalar(
            select(ImageAsset).where(
                ImageAsset.inspection_id == inspection.id,
                ImageAsset.tenant_id == inspection.tenant_id,
                ImageAsset.kind == "ORIGINAL",
            )
        )
        deployment: DeploymentPack | None = None
        manifest: DeploymentManifest | None = None
        try:
            if original is None:
                raise ModelUnavailable("original image evidence missing")
            deployment = session.scalar(
                select(DeploymentPack).where(
                    DeploymentPack.id == inspection.deployment_pack_id,
                    DeploymentPack.tenant_id == inspection.tenant_id,
                )
            )
            if deployment is None or deployment.tenant_id != inspection.tenant_id:
                raise ModelUnavailable("deployment pack evidence missing")
            manifest = self.deployment_manifest(session, deployment)
            output = self.model_adapter.infer(self.storage.get(original.uri))
        except Exception as exc:
            inspection.failure_reason = f"model unavailable: {type(exc).__name__}"
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.INFERENCE_FAILED,
                actor="system:model-worker",
                reason=inspection.failure_reason,
            )
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.REVIEW_REQUIRED,
                actor="system:policy",
                reason="fail-safe routing; automatic release prohibited",
            )
            self._ensure_review_task(session, inspection)
            self._mark_inference_outbox_processed(
                session, inspection.id, tenant_id=inspection.tenant_id
            )
            return

        if output.ood:
            inspection.failure_reason = (
                "safe-degrade: model marked this image as out-of-distribution"
            )
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.INFERENCE_FAILED,
                actor="system:model-worker",
                reason=inspection.failure_reason,
            )
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.REVIEW_REQUIRED,
                actor="system:policy",
                reason="out-of-distribution evidence requires human review",
            )
            self._ensure_review_task(session, inspection)
            self._mark_inference_outbox_processed(
                session, inspection.id, tenant_id=inspection.tenant_id
            )
            return

        heatmap_hash = hashlib.sha256(output.heatmap_png).hexdigest()
        heatmap_key = f"{inspection.tenant_id}/heatmaps/{inspection.id}/{heatmap_hash}.png"
        heatmap_uri = self.storage.put_immutable(heatmap_key, output.heatmap_png, "image/png")
        session.add(
            ImageAsset(
                tenant_id=inspection.tenant_id,
                inspection_id=inspection.id,
                kind="HEATMAP",
                sha256=heatmap_hash,
                uri=heatmap_uri,
                mime_type="image/png",
                width=original.width,
                height=original.height,
                source="model",
            )
        )
        session.add(
            InferenceResult(
                tenant_id=inspection.tenant_id,
                inspection_id=inspection.id,
                attempt=1,
                model_id=manifest.model.id if manifest else output.model_id,
                model_version=manifest.model.version if manifest else output.model_version,
                feature_bank_version=(
                    manifest.model.feature_bank_version if manifest else output.feature_bank_version
                ),
                runtime_device=output.runtime_device,
                score=output.score,
                heatmap_uri=heatmap_uri,
                latency_ms=output.latency_ms,
                semantic_defect_confirmed=False,
            )
        )
        self._transition_inspection(
            session,
            inspection,
            InspectionStatus.SCORED,
            actor="system:model-worker",
            reason="immutable model result saved",
        )
        assert manifest is not None
        policy = manifest.policy
        evaluation = evaluate_policy(
            output.score,
            policy,
            product_code=inspection.product_code,
            station_code=inspection.station_code,
        )
        snapshot: dict[str, Any] = policy.model_dump(mode="json")
        snapshot["resolved_rule"] = {
            "review_threshold": evaluation.review_threshold,
            "hold_threshold": evaluation.hold_threshold,
        }
        session.add(
            PolicyDecision(
                tenant_id=inspection.tenant_id,
                inspection_id=inspection.id,
                policy_version=policy.version if policy else "unavailable",
                decision=evaluation.route,
                reason=evaluation.reason,
                policy_snapshot=snapshot,
            )
        )
        if evaluation.route == PolicyRoute.AUTO_RELEASE:
            target = InspectionStatus.AUTO_RELEASED
        elif evaluation.route == PolicyRoute.BATCH_HOLD_AND_REVIEW:
            target = InspectionStatus.BATCH_HELD
        else:
            target = InspectionStatus.REVIEW_REQUIRED
        self._transition_inspection(
            session,
            inspection,
            target,
            actor="system:policy",
            reason=evaluation.reason,
        )
        if target in {InspectionStatus.REVIEW_REQUIRED, InspectionStatus.BATCH_HELD}:
            self._ensure_review_task(session, inspection)
        self._mark_inference_outbox_processed(
            session, inspection.id, tenant_id=inspection.tenant_id
        )

    def _mark_inference_outbox_processed(
        self, session: Session, inspection_id: str, *, tenant_id: str
    ) -> None:
        event = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == inspection_id,
                OutboxEvent.tenant_id == tenant_id,
                OutboxEvent.topic == "inspection.inference_requested",
                OutboxEvent.status == "PENDING",
            )
        )
        if event:
            event.status = "PROCESSED"
            event.processed_at = datetime.now(UTC)

    def _ensure_review_task(self, session: Session, inspection: Inspection) -> ReviewTask:
        task = session.scalar(
            select(ReviewTask).where(
                ReviewTask.inspection_id == inspection.id,
                ReviewTask.tenant_id == inspection.tenant_id,
            )
        )
        if task is None:
            task = ReviewTask(
                tenant_id=inspection.tenant_id,
                inspection_id=inspection.id,
                status="OPEN",
                version=1,
            )
            session.add(task)
            session.flush()
            record_audit(
                session,
                tenant_id=inspection.tenant_id,
                actor="system:policy",
                action="review.required",
                target_type="review_task",
                target_id=task.id,
                correlation_id=inspection.correlation_id,
                payload={"inspection_status": inspection.status},
            )
        return task

    def list_reviews(self, session: Session, tenant_id: str) -> list[ReviewTask]:
        return list(
            session.scalars(
                select(ReviewTask)
                .where(ReviewTask.tenant_id == tenant_id, ReviewTask.status == "OPEN")
                .order_by(ReviewTask.created_at)
            )
        )

    def review_task_response(self, session: Session, task: ReviewTask) -> ReviewTaskResponse:
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == task.inspection_id,
                Inspection.tenant_id == task.tenant_id,
            )
        )
        if inspection is None:
            raise NotFound("inspection for review task not found")
        inference = session.scalar(
            select(InferenceResult)
            .where(
                InferenceResult.inspection_id == inspection.id,
                InferenceResult.tenant_id == task.tenant_id,
            )
            .order_by(InferenceResult.attempt.desc())
        )
        policy = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.inspection_id == inspection.id,
                PolicyDecision.tenant_id == task.tenant_id,
            )
        )
        original = session.scalar(
            select(ImageAsset).where(
                ImageAsset.inspection_id == inspection.id,
                ImageAsset.tenant_id == task.tenant_id,
                ImageAsset.kind == "ORIGINAL",
            )
        )
        held = inspection.status == InspectionStatus.BATCH_HELD
        safe_degrade = inference is None or policy is None
        return ReviewTaskResponse(
            id=task.id,
            inspection_id=task.inspection_id,
            status=task.status,
            assignee=task.assignee,
            version=task.version,
            sla_at=task.sla_at,
            priority="CRITICAL" if held else "HIGH" if safe_degrade else "STANDARD",
            route=("SAFE_DEGRADE" if safe_degrade else "HIGH_SCORE_HOLD" if held else "GREY_ZONE"),
            batch_no=inspection.batch_no,
            product_code=inspection.product_code,
            station_code=inspection.station_code,
            score=inference.score if inference else None,
            thumbnail_asset_id=original.id if original else None,
            held=held,
        )

    def claim_review(
        self,
        session: Session,
        *,
        principal: Principal,
        task_id: str,
        expected_version: int,
        correlation_id: str,
    ) -> ReviewTask:
        result = cast(
            CursorResult[Any],
            session.execute(
                update(ReviewTask)
                .where(
                    ReviewTask.id == task_id,
                    ReviewTask.tenant_id == principal.tenant_id,
                    ReviewTask.status == "OPEN",
                    ReviewTask.version == expected_version,
                    ReviewTask.assignee.is_(None),
                )
                .values(assignee=principal.actor_id, version=ReviewTask.version + 1)
            ),
        )
        if result.rowcount != 1:
            if not session.scalar(
                select(ReviewTask.id).where(
                    ReviewTask.id == task_id, ReviewTask.tenant_id == principal.tenant_id
                )
            ):
                raise NotFound("review task not found")
            raise Conflict("review task version or assignment changed")
        task = session.scalar(
            select(ReviewTask).where(
                ReviewTask.id == task_id, ReviewTask.tenant_id == principal.tenant_id
            )
        )
        assert task is not None
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="review.claimed",
            target_type="review_task",
            target_id=task.id,
            correlation_id=correlation_id,
            payload={"version": task.version},
        )
        return task

    def decide_review(
        self,
        session: Session,
        *,
        principal: Principal,
        task_id: str,
        request: ReviewDecisionRequest,
        correlation_id: str,
    ) -> tuple[ReviewDecision, Inspection, QualityIncident | None, int]:
        task = session.scalar(
            select(ReviewTask).where(
                ReviewTask.id == task_id, ReviewTask.tenant_id == principal.tenant_id
            )
        )
        if task is None:
            raise NotFound("review task not found")
        if task.assignee is not None and task.assignee != principal.actor_id:
            raise Forbidden("review task is assigned to another actor")
        high_risk = request.decision in {
            ReviewChoice.REWORK,
            ReviewChoice.SCRAP,
            ReviewChoice.INVESTIGATE,
        }
        if high_risk and Role.QUALITY_MANAGER not in principal.roles:
            raise Forbidden("quality_manager role is required for nonconformance disposition")
        result = cast(
            CursorResult[Any],
            session.execute(
                update(ReviewTask)
                .where(
                    ReviewTask.id == task_id,
                    ReviewTask.tenant_id == principal.tenant_id,
                    ReviewTask.status == "OPEN",
                    ReviewTask.version == request.expected_version,
                )
                .values(
                    status="COMPLETED",
                    assignee=principal.actor_id,
                    version=ReviewTask.version + 1,
                )
            ),
        )
        if result.rowcount != 1:
            raise Conflict("review task was already decided or its version changed")
        decision = ReviewDecision(
            tenant_id=principal.tenant_id,
            review_task_id=task.id,
            actor_id=principal.actor_id,
            decision=request.decision,
            reason=request.reason,
            notes=request.notes,
            model_feedback=request.model_feedback,
        )
        session.add(decision)
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == task.inspection_id,
                Inspection.tenant_id == principal.tenant_id,
            )
        )
        if inspection is None:
            raise NotFound("inspection for review task not found")
        incident: QualityIncident | None = None
        if request.decision == ReviewChoice.GOOD:
            target = InspectionStatus.RELEASE_APPROVED
            reason = "named inspector approved release"
        elif request.decision == ReviewChoice.UNABLE_TO_DETERMINE:
            target = InspectionStatus.ESCALATED
            reason = request.reason or "unable to determine"
        else:
            target = InspectionStatus.NONCONFORMANCE_CONFIRMED
            reason = request.reason or "nonconformance confirmed"
        self._transition_inspection(
            session,
            inspection,
            target,
            actor=principal.actor_id,
            reason=reason,
            correlation_id=correlation_id,
        )
        if high_risk:
            incident = self._create_incident(
                session,
                inspection=inspection,
                disposition=str(request.decision),
                actor=principal.actor_id,
                reason=reason,
                correlation_id=correlation_id,
            )
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="review.completed",
            target_type="review_task",
            target_id=task.id,
            correlation_id=correlation_id,
            payload={
                "decision": request.decision,
                "reason": request.reason,
                "model_feedback": request.model_feedback,
                "inspection_status": inspection.status,
            },
        )
        session.flush()
        return decision, inspection, incident, request.expected_version + 1

    def _create_incident(
        self,
        session: Session,
        *,
        inspection: Inspection,
        disposition: str,
        actor: str,
        reason: str,
        correlation_id: str,
    ) -> QualityIncident:
        existing = session.scalar(
            select(QualityIncident).where(
                QualityIncident.inspection_id == inspection.id,
                QualityIncident.tenant_id == inspection.tenant_id,
            )
        )
        if existing:
            return existing
        incident = QualityIncident(
            tenant_id=inspection.tenant_id,
            inspection_id=inspection.id,
            status="ACTION_PENDING",
            disposition=disposition,
            severity="MAJOR",
        )
        session.add(incident)
        session.flush()
        self._transition_inspection(
            session,
            inspection,
            InspectionStatus.ACTION_PENDING,
            actor=actor,
            reason="quality incident created; external actions pending",
            correlation_id=correlation_id,
        )
        record_audit(
            session,
            tenant_id=inspection.tenant_id,
            actor=actor,
            action="quality_incident.created",
            target_type="quality_incident",
            target_id=incident.id,
            correlation_id=correlation_id,
            payload={"disposition": disposition, "reason": reason},
        )
        deployment = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.id == inspection.deployment_pack_id,
                DeploymentPack.tenant_id == inspection.tenant_id,
            )
        )
        manifest = (
            self.deployment_manifest(session, deployment)
            if deployment is not None and deployment.tenant_id == inspection.tenant_id
            else None
        )
        canonical_connector_payload = {
            "inspection_id": inspection.id,
            "batch_no": inspection.batch_no,
            "product_code": inspection.product_code,
            "product_revision": inspection.product_revision,
            "station_code": inspection.station_code,
            "disposition": disposition,
            "reason": reason,
            "root_cause": "PENDING_INVESTIGATION",
        }
        mes_payload = (
            manifest.connector_payload("MES", canonical_connector_payload)
            if manifest
            else {"batch_no": inspection.batch_no, "reason": reason}
        )
        qms_payload = (
            manifest.connector_payload("QMS", canonical_connector_payload)
            if manifest
            else {
                "inspection_id": inspection.id,
                "batch_no": inspection.batch_no,
                "disposition": disposition,
                "reason": reason,
                "root_cause": "PENDING_INVESTIGATION",
            }
        )
        self._new_external_action(
            session,
            incident=incident,
            connector="MES",
            operation="HOLD_BATCH",
            idempotency_key=f"{incident.id}:mes:hold",
            payload=mes_payload,
            correlation_id=correlation_id,
        )
        self._new_external_action(
            session,
            incident=incident,
            connector="QMS",
            operation="CREATE_TICKET",
            idempotency_key=f"{incident.id}:qms:create",
            payload=qms_payload,
            correlation_id=correlation_id,
        )
        if manifest is not None and manifest.connectors.dxq_mock is not None:
            dxq_payload = self._dxq_quality_record_payload(
                session,
                inspection=inspection,
                incident=incident,
                disposition=disposition,
                reason=reason,
            )
            self._new_external_action(
                session,
                incident=incident,
                connector="DXQ_MOCK",
                operation="PUBLISH_QUALITY_EVENT",
                idempotency_key=f"{incident.id}:dxq_mock:publish",
                payload=manifest.connector_payload("DXQ_MOCK", dxq_payload),
                correlation_id=correlation_id,
            )
        if self.settings.process_inline:
            session.flush()
            self.process_pending_external_actions(
                session, incident_id=incident.id, tenant_id=incident.tenant_id
            )
        return incident

    def _dxq_quality_record_payload(
        self,
        session: Session,
        *,
        inspection: Inspection,
        incident: QualityIncident,
        disposition: str,
        reason: str,
    ) -> dict[str, Any]:
        """Build the generic simulated digital quality record boundary.

        The payload contains references and reviewed context, never the raw
        image bytes.  Defaults are explicit so an incomplete pilot context is
        visible to the simulated contract instead of being silently guessed.
        """

        metadata = inspection.context_metadata or {}
        inference = session.scalar(
            select(InferenceResult)
            .where(
                InferenceResult.inspection_id == inspection.id,
                InferenceResult.tenant_id == inspection.tenant_id,
            )
            .order_by(InferenceResult.attempt.desc())
        )

        def text_value(key: str, fallback: str) -> str:
            value = metadata.get(key)
            return str(value).strip() if value is not None and str(value).strip() else fallback

        return {
            "body_id": text_value("body_id", inspection.batch_no),
            "workpiece_id": text_value("workpiece_id", inspection.id),
            "paint_shop": text_value("paint_shop", "PAINT_SHOP_DEMO"),
            "booth_station": text_value("booth_station", inspection.station_code),
            "line": text_value("line", "LINE_UNSPECIFIED"),
            "model_variant": text_value("model_variant", "MODEL_UNSPECIFIED"),
            "color_code": text_value("color_code", "COLOR_UNSPECIFIED"),
            "paint_recipe": text_value("paint_recipe", "RECIPE_UNSPECIFIED"),
            "shift": text_value("shift", "SHIFT_UNSPECIFIED"),
            "timestamp": inspection.captured_at.isoformat(),
            "visual_defect_type": text_value("visual_defect_type", "UNCONFIRMED_ANOMALY"),
            "severity": incident.severity,
            "mask_or_heatmap": (
                {"heatmap_uri": inference.heatmap_uri}
                if inference is not None and inference.heatmap_uri
                else {"heatmap_uri": None, "quality_flags": inspection.quality_flags or []}
            ),
            "operator_decision": disposition,
            "equipment_alarm_refs": self._metadata_list(metadata, "equipment_alarm_refs"),
            "process_parameter_refs": self._metadata_list(metadata, "process_parameter_refs"),
            "root_cause_candidates": self._metadata_list(
                metadata, "root_cause_candidates", fallback=["PENDING_INVESTIGATION"]
            ),
            "disposition": disposition,
            "quality_case_id": incident.id,
            "review_reason": reason,
        }

    @staticmethod
    def _metadata_list(
        metadata: Mapping[str, Any], key: str, fallback: list[str] | None = None
    ) -> list[Any]:
        value = metadata.get(key)
        if isinstance(value, list):
            return value
        return list(fallback or [])

    def request_incident_action(
        self,
        session: Session,
        *,
        principal: Principal,
        incident_id: str,
        request: IncidentActionRequest,
        idempotency_key: str,
        correlation_id: str,
    ) -> ExternalAction:
        incident = session.scalar(
            select(QualityIncident).where(
                QualityIncident.id == incident_id,
                QualityIncident.tenant_id == principal.tenant_id,
            )
        )
        if incident is None:
            raise NotFound("quality incident not found")
        if not request.confirmed:
            raise InvalidInput("confirmed=true is required for external quality actions")
        existing = session.scalar(
            select(ExternalAction).where(
                ExternalAction.tenant_id == principal.tenant_id,
                ExternalAction.idempotency_key == idempotency_key,
            )
        )
        if existing:
            return existing
        payload = {**request.payload, "reason": request.reason}
        action = self._new_external_action(
            session,
            incident=incident,
            connector=request.connector,
            operation=request.operation,
            idempotency_key=idempotency_key,
            payload=payload,
            correlation_id=correlation_id,
        )
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="external_action.requested",
            target_type="external_action",
            target_id=action.id,
            correlation_id=correlation_id,
            payload={"connector": request.connector, "operation": request.operation},
        )
        if self.settings.process_inline:
            session.flush()
            self.process_pending_external_actions(
                session, incident_id=incident.id, tenant_id=incident.tenant_id
            )
        return action

    def _new_external_action(
        self,
        session: Session,
        *,
        incident: QualityIncident,
        connector: str,
        operation: str,
        idempotency_key: str,
        payload: dict[str, Any],
        correlation_id: str,
    ) -> ExternalAction:
        action = ExternalAction(
            tenant_id=incident.tenant_id,
            incident_id=incident.id,
            connector=connector,
            operation=operation,
            idempotency_key=idempotency_key,
            request_summary=redact(payload),
            status=ExternalActionStatus.PENDING,
        )
        session.add(action)
        session.flush()
        session.add(
            OutboxEvent(
                tenant_id=incident.tenant_id,
                topic="external_action.requested",
                aggregate_id=action.id,
                correlation_id=correlation_id,
                payload={"external_action_id": action.id},
            )
        )
        return action

    def process_pending_external_actions(
        self,
        session: Session,
        *,
        incident_id: str | None = None,
        tenant_id: str | None = None,
    ) -> int:
        query: Select[tuple[ExternalAction]] = select(ExternalAction).where(
            ExternalAction.status == ExternalActionStatus.PENDING
        )
        if incident_id:
            query = query.where(ExternalAction.incident_id == incident_id)
        if tenant_id:
            query = query.where(ExternalAction.tenant_id == tenant_id)
        actions = list(session.scalars(query.order_by(ExternalAction.created_at)))
        for action in actions:
            self._execute_external_action(session, action)
        return len(actions)

    def _execute_external_action(self, session: Session, action: ExternalAction) -> None:
        incident = session.scalar(
            select(QualityIncident).where(
                QualityIncident.id == action.incident_id,
                QualityIncident.tenant_id == action.tenant_id,
            )
        )
        if incident is None:
            raise DependencyUnavailable("external action incident boundary is invalid")
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == incident.inspection_id,
                Inspection.tenant_id == action.tenant_id,
            )
        )
        if inspection is None:
            raise DependencyUnavailable("external action inspection boundary is invalid")
        action.status = ExternalActionStatus.EXECUTING
        if inspection.status == InspectionStatus.ACTION_PENDING:
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.ACTION_EXECUTING,
                actor="system:connector-worker",
                reason="external action execution started",
            )
            incident.status = "ACTION_EXECUTING"
        connector = self.connectors.get(action.connector)
        if connector is None:
            action.status = ExternalActionStatus.MANUAL_REVIEW
            action.last_error = "connector is not configured"
            outcome = None
        else:
            outcome = self.connector_executor.execute(
                connector,
                action.operation,
                action.request_summary,
                action.idempotency_key,
            )
            action.attempts += outcome.attempts
            if outcome.result:
                action.status = ExternalActionStatus.SUCCEEDED
                action.external_reference = outcome.result.external_reference
                action.response_summary = redact(outcome.result.summary)
                action.last_error = None
            else:
                action.status = (
                    ExternalActionStatus.MANUAL_REVIEW
                    if outcome.error and outcome.error.requires_manual_review
                    else ExternalActionStatus.FAILED
                )
                action.last_error = str(outcome.error)[:1000]
        outbox = session.scalar(
            select(OutboxEvent).where(
                OutboxEvent.aggregate_id == action.id,
                OutboxEvent.topic == "external_action.requested",
                OutboxEvent.status == "PENDING",
            )
        )
        if outbox:
            outbox.status = "PROCESSED"
            outbox.processed_at = datetime.now(UTC)
        session.flush()
        statuses = set(
            session.scalars(
                select(ExternalAction.status).where(
                    ExternalAction.incident_id == incident.id,
                    ExternalAction.tenant_id == action.tenant_id,
                )
            )
        )
        if statuses <= {ExternalActionStatus.SUCCEEDED}:
            incident.status = "ACTION_COMPLETED"
            if inspection.status == InspectionStatus.ACTION_EXECUTING:
                self._transition_inspection(
                    session,
                    inspection,
                    InspectionStatus.ACTION_COMPLETED,
                    actor="system:connector-worker",
                    reason="all external actions completed idempotently",
                )
        elif statuses & {ExternalActionStatus.FAILED, ExternalActionStatus.MANUAL_REVIEW}:
            incident.status = "ACTION_FAILED"
            if inspection.status == InspectionStatus.ACTION_EXECUTING:
                self._transition_inspection(
                    session,
                    inspection,
                    InspectionStatus.ACTION_FAILED,
                    actor="system:connector-worker",
                    reason="external action failed; recovery or replay required",
                )
        record_audit(
            session,
            tenant_id=action.tenant_id,
            actor="system:connector-worker",
            action=(
                "external_action.completed"
                if action.status == ExternalActionStatus.SUCCEEDED
                else "external_action.failed"
            ),
            target_type="external_action",
            target_id=action.id,
            correlation_id=inspection.correlation_id,
            payload={
                "status": action.status,
                "attempts": action.attempts,
                "external_reference": action.external_reference,
                "error": action.last_error,
            },
        )

    def replay_external_action(
        self,
        session: Session,
        *,
        principal: Principal,
        action_id: str,
        reason: str,
        correlation_id: str,
    ) -> ExternalAction:
        action = session.scalar(
            select(ExternalAction).where(
                ExternalAction.id == action_id,
                ExternalAction.tenant_id == principal.tenant_id,
            )
        )
        if action is None:
            raise NotFound("external action not found")
        if action.status not in {
            ExternalActionStatus.FAILED,
            ExternalActionStatus.MANUAL_REVIEW,
        }:
            raise Conflict("only failed or manual-review actions can be replayed")
        incident = session.scalar(
            select(QualityIncident).where(
                QualityIncident.id == action.incident_id,
                QualityIncident.tenant_id == principal.tenant_id,
            )
        )
        if incident is None:
            raise NotFound("quality incident for external action not found")
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == incident.inspection_id,
                Inspection.tenant_id == principal.tenant_id,
            )
        )
        if inspection is None:
            raise NotFound("inspection for quality incident not found")
        action.status = ExternalActionStatus.PENDING
        action.last_error = None
        incident.status = "ACTION_PENDING"
        if inspection.status == InspectionStatus.ACTION_FAILED:
            self._transition_inspection(
                session,
                inspection,
                InspectionStatus.ACTION_PENDING,
                actor=principal.actor_id,
                reason=f"authorized replay requested: {reason}",
                correlation_id=correlation_id,
            )
        session.add(
            OutboxEvent(
                tenant_id=action.tenant_id,
                topic="external_action.requested",
                aggregate_id=action.id,
                correlation_id=correlation_id,
                payload={"external_action_id": action.id, "replay": True},
            )
        )
        record_audit(
            session,
            tenant_id=action.tenant_id,
            actor=principal.actor_id,
            action="external_action.replay_requested",
            target_type="external_action",
            target_id=action.id,
            correlation_id=correlation_id,
            payload={"reason": reason, "idempotency_key_reused": True},
        )
        if self.settings.process_inline:
            session.flush()
            self.process_pending_external_actions(
                session, incident_id=incident.id, tenant_id=incident.tenant_id
            )
        return action

    def close_incident(
        self,
        session: Session,
        *,
        principal: Principal,
        incident_id: str,
        request: CloseIncidentRequest,
        correlation_id: str,
    ) -> QualityIncident:
        incident = session.scalar(
            select(QualityIncident).where(
                QualityIncident.id == incident_id,
                QualityIncident.tenant_id == principal.tenant_id,
            )
        )
        if incident is None:
            raise NotFound("quality incident not found")
        statuses = set(
            session.scalars(
                select(ExternalAction.status).where(
                    ExternalAction.incident_id == incident.id,
                    ExternalAction.tenant_id == principal.tenant_id,
                )
            )
        )
        if not statuses or statuses != {ExternalActionStatus.SUCCEEDED}:
            raise Conflict("incident cannot close before all external actions succeed")
        incident.owner = request.owner
        incident.outcome = request.outcome
        incident.verification_record = request.verification_record
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == incident.inspection_id,
                Inspection.tenant_id == principal.tenant_id,
            )
        )
        if inspection is None:
            raise NotFound("inspection for quality incident not found")
        if inspection.status != InspectionStatus.ACTION_COMPLETED:
            raise Conflict("inspection is not ready for verification")
        self._transition_inspection(
            session,
            inspection,
            InspectionStatus.VERIFYING,
            actor=principal.actor_id,
            reason="required disposition fields and verification record supplied",
            correlation_id=correlation_id,
        )
        self._transition_inspection(
            session,
            inspection,
            InspectionStatus.CLOSED,
            actor=principal.actor_id,
            reason="quality incident verified and closed",
            correlation_id=correlation_id,
        )
        incident.status = "CLOSED"
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="quality_incident.closed",
            target_type="quality_incident",
            target_id=incident.id,
            correlation_id=correlation_id,
            payload={
                "owner": request.owner,
                "outcome": request.outcome,
                "verification_record": request.verification_record,
            },
        )
        return incident

    def get_external_action(
        self, session: Session, tenant_id: str, action_id: str
    ) -> ExternalAction:
        action = session.scalar(
            select(ExternalAction).where(
                ExternalAction.id == action_id, ExternalAction.tenant_id == tenant_id
            )
        )
        if action is None:
            raise NotFound("external action not found")
        return action

    def get_incident(
        self, session: Session, *, tenant_id: str, incident_id: str
    ) -> QualityIncidentResponse:
        incident = session.scalar(
            select(QualityIncident).where(
                QualityIncident.id == incident_id,
                QualityIncident.tenant_id == tenant_id,
            )
        )
        if incident is None:
            raise NotFound("quality incident not found")
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == incident.inspection_id,
                Inspection.tenant_id == tenant_id,
            )
        )
        if inspection is None:
            raise NotFound("inspection for quality incident not found")
        inference = session.scalar(
            select(InferenceResult)
            .where(
                InferenceResult.inspection_id == inspection.id,
                InferenceResult.tenant_id == tenant_id,
            )
            .order_by(InferenceResult.attempt.desc())
        )
        policy = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.inspection_id == inspection.id,
                PolicyDecision.tenant_id == tenant_id,
            )
        )
        review = session.scalar(
            select(ReviewTask).where(
                ReviewTask.inspection_id == inspection.id,
                ReviewTask.tenant_id == tenant_id,
            )
        )
        decision = (
            session.scalar(
                select(ReviewDecision).where(
                    ReviewDecision.review_task_id == review.id,
                    ReviewDecision.tenant_id == tenant_id,
                )
            )
            if review
            else None
        )
        actions = session.scalars(
            select(ExternalAction)
            .where(
                ExternalAction.incident_id == incident.id,
                ExternalAction.tenant_id == tenant_id,
            )
            .order_by(ExternalAction.created_at)
        )
        return QualityIncidentResponse(
            id=incident.id,
            inspection_id=inspection.id,
            status=incident.status,
            severity=incident.severity,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
            owner=incident.owner,
            disposition=incident.disposition,
            outcome=incident.outcome,
            verification_record=incident.verification_record,
            batch_no=inspection.batch_no,
            product_code=inspection.product_code,
            station_code=inspection.station_code,
            evidence=IncidentEvidence(
                score=inference.score if inference else 0.0,
                model_version=inference.model_version if inference else "unavailable",
                policy_version=policy.policy_version if policy else "unavailable",
                decision_actor=decision.actor_id if decision else "unavailable",
                decision_reason=(decision.reason or decision.notes or "not recorded")
                if decision
                else "not recorded",
            ),
            external_actions=[
                ExternalActionResponse(
                    id=action.id,
                    incident_id=action.incident_id,
                    connector=action.connector,
                    operation=action.operation,
                    status=action.status,
                    attempts=action.attempts,
                    external_reference=action.external_reference,
                    last_error=action.last_error,
                    idempotency_key=action.idempotency_key,
                    updated_at=action.updated_at,
                )
                for action in actions
            ],
            timeline=[
                TimelineEntry.model_validate(item)
                for item in self.timeline(session, tenant_id=tenant_id, incident_id=incident_id)
            ],
            correlation_id=inspection.correlation_id,
        )

    def inspection_timeline(
        self, session: Session, *, tenant_id: str, inspection_id: str
    ) -> list[dict[str, Any]]:
        inspection = session.scalar(
            select(Inspection).where(
                Inspection.id == inspection_id, Inspection.tenant_id == tenant_id
            )
        )
        if inspection is None:
            raise NotFound("inspection not found")
        audits = session.scalars(
            select(AuditEvent).where(
                AuditEvent.tenant_id == tenant_id,
                AuditEvent.target_id == inspection_id,
            )
        )
        transitions = session.scalars(
            select(StateTransition).where(
                StateTransition.tenant_id == tenant_id,
                StateTransition.entity_id == inspection_id,
            )
        )
        entries = [
            {
                "occurred_at": item.occurred_at,
                "source": "audit",
                "action": item.action,
                "actor": item.actor,
                "details": item.payload,
                "correlation_id": item.correlation_id,
            }
            for item in audits
        ]
        entries.extend(
            {
                "occurred_at": item.occurred_at,
                "source": "state_transition",
                "action": f"{item.from_state}->{item.to_state}",
                "actor": item.actor,
                "details": {"reason": item.reason, "entity_type": item.entity_type},
                "correlation_id": item.correlation_id,
            }
            for item in transitions
        )
        return sorted(entries, key=lambda item: item["occurred_at"])

    def timeline(
        self, session: Session, *, tenant_id: str, incident_id: str
    ) -> list[dict[str, Any]]:
        incident = session.scalar(
            select(QualityIncident).where(
                QualityIncident.id == incident_id, QualityIncident.tenant_id == tenant_id
            )
        )
        if incident is None:
            raise NotFound("quality incident not found")
        target_ids = [incident.id, incident.inspection_id]
        review_task_id = session.scalar(
            select(ReviewTask.id).where(
                ReviewTask.inspection_id == incident.inspection_id,
                ReviewTask.tenant_id == tenant_id,
            )
        )
        if review_task_id:
            target_ids.append(review_task_id)
        target_ids.extend(
            session.scalars(
                select(ExternalAction.id).where(
                    ExternalAction.incident_id == incident.id,
                    ExternalAction.tenant_id == tenant_id,
                )
            )
        )
        audits = list(
            session.scalars(
                select(AuditEvent).where(
                    AuditEvent.tenant_id == tenant_id, AuditEvent.target_id.in_(target_ids)
                )
            )
        )
        transitions = list(
            session.scalars(
                select(StateTransition).where(
                    StateTransition.tenant_id == tenant_id,
                    StateTransition.entity_id == incident.inspection_id,
                )
            )
        )
        entries = [
            {
                "occurred_at": item.occurred_at,
                "source": "audit",
                "action": item.action,
                "actor": item.actor,
                "details": item.payload,
                "correlation_id": item.correlation_id,
            }
            for item in audits
        ]
        entries.extend(
            {
                "occurred_at": item.occurred_at,
                "source": "state_transition",
                "action": f"{item.from_state}->{item.to_state}",
                "actor": item.actor,
                "details": {"reason": item.reason, "entity_type": item.entity_type},
                "correlation_id": item.correlation_id,
            }
            for item in transitions
        )
        return sorted(entries, key=lambda item: item["occurred_at"])

    def create_deployment(
        self,
        session: Session,
        *,
        principal: Principal,
        request: DeploymentCreateRequest,
        correlation_id: str,
    ) -> DeploymentPack:
        tenant = session.get(Tenant, principal.tenant_id)
        if tenant is None or tenant.status != "ACTIVE":
            raise Forbidden("tenant is not active")
        if request.manifest is not None:
            manifest = request.manifest
            if manifest.tenant.id != principal.tenant_id:
                raise Forbidden("deployment manifest tenant does not match authenticated tenant")
            if manifest.tenant.name != tenant.name:
                raise InvalidInput("deployment manifest tenant name does not match tenant registry")
        else:
            assert request.version is not None
            assert request.policy is not None
            manifest = legacy_manifest(
                tenant_id=principal.tenant_id,
                tenant_name=tenant.name,
                version=request.version,
                model=request.model,
                policy=request.policy,
                connectors=request.connectors,
            )
        deployment = DeploymentPack(
            tenant_id=principal.tenant_id,
            version=manifest.version,
            status="DRAFT",
            model_config_snapshot=redact(manifest.model.model_dump(mode="json")),
            policy_config=manifest.policy.model_dump(mode="json"),
            connector_config=redact(manifest.connectors.model_dump(mode="json")),
            manifest=redact(manifest.model_dump(mode="json")),
        )
        session.add(deployment)
        try:
            session.flush()
        except IntegrityError as exc:
            raise Conflict("deployment version already exists for tenant") from exc
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="deployment.created",
            target_type="deployment_pack",
            target_id=deployment.id,
            correlation_id=correlation_id,
            payload={"version": deployment.version, "pack_key": manifest.pack_key},
        )
        return deployment

    def list_deployments(self, session: Session, tenant_id: str) -> list[DeploymentPack]:
        return list(
            session.scalars(
                select(DeploymentPack)
                .where(DeploymentPack.tenant_id == tenant_id)
                .order_by(DeploymentPack.created_at.desc())
            )
        )

    def activate_deployment(
        self,
        session: Session,
        *,
        principal: Principal,
        deployment_id: str,
        reason: str,
        correlation_id: str,
    ) -> DeploymentPack:
        deployment = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.id == deployment_id,
                DeploymentPack.tenant_id == principal.tenant_id,
            )
        )
        if deployment is None:
            raise NotFound("deployment pack not found")
        manifest = self.deployment_manifest(session, deployment)
        if manifest.tenant.id != principal.tenant_id:
            raise Forbidden("deployment pack tenant boundary is invalid")
        try:
            for product in manifest.products:
                for station in manifest.stations:
                    manifest.policy.resolve(product.code, station.code)
        except (ValidationError, ValueError) as exc:
            raise InvalidInput("deployment policy schema or overrides are invalid") from exc
        if self.settings.environment == "production":
            for product in manifest.products:
                qualified = session.scalar(
                    select(ModelQualification).where(
                        ModelQualification.tenant_id == principal.tenant_id,
                        ModelQualification.product_code == product.code,
                        ModelQualification.model_id == manifest.model.id,
                        ModelQualification.model_version == manifest.model.version,
                        ModelQualification.package_sha256 == manifest.model.package_sha256,
                        ModelQualification.deployment_pack_key == manifest.pack_key,
                        ModelQualification.status == "ACTIVE",
                        ModelQualification.qualification_status == "GO",
                    )
                )
                if qualified is None:
                    raise InvalidInput(
                        "production Deployment Pack requires a matching ACTIVE model qualification",
                        details={"product_code": product.code, "pack_key": manifest.pack_key},
                    )
        checks = {
            "storage": self.storage.healthcheck(),
            "model": self.model_adapter.healthcheck(),
            **{
                f"connector:{name}": connector.healthcheck()
                for name, connector in self.connectors.items()
            },
        }
        if not all(checks.values()):
            raise DependencyUnavailable(
                "deployment preflight failed; active deployment was not changed", details=checks
            )
        active = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.tenant_id == principal.tenant_id,
                DeploymentPack.status == "ACTIVE",
            )
        )
        if active and active.id != deployment.id:
            active.status = "RETIRED"
            session.flush()
        deployment.status = "ACTIVE"
        deployment.approved_by = principal.actor_id
        deployment.activated_at = datetime.now(UTC)
        record_audit(
            session,
            tenant_id=principal.tenant_id,
            actor=principal.actor_id,
            action="deployment.activated",
            target_type="deployment_pack",
            target_id=deployment.id,
            correlation_id=correlation_id,
            payload={
                "version": deployment.version,
                "pack_key": manifest.pack_key,
                "reason": reason,
                "preflight": checks,
            },
        )
        return deployment

    def get_deployment(
        self, session: Session, tenant_id: str, deployment_id: str
    ) -> DeploymentPack:
        deployment = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.id == deployment_id, DeploymentPack.tenant_id == tenant_id
            )
        )
        if deployment is None:
            raise NotFound("deployment pack not found")
        return deployment

    def _transition_inspection(
        self,
        session: Session,
        inspection: Inspection,
        target: InspectionStatus,
        *,
        actor: str,
        reason: str,
        correlation_id: str | None = None,
    ) -> None:
        current = inspection.status
        try:
            assert_inspection_transition(current, target)
        except DomainConflict as exc:
            raise Conflict(str(exc)) from exc
        inspection.status = target
        correlation = correlation_id or inspection.correlation_id
        session.add(
            StateTransition(
                tenant_id=inspection.tenant_id,
                entity_type="inspection",
                entity_id=inspection.id,
                from_state=current,
                to_state=target,
                actor=actor,
                reason=reason,
                correlation_id=correlation,
            )
        )
        record_audit(
            session,
            tenant_id=inspection.tenant_id,
            actor=actor,
            action="inspection.state_changed",
            target_type="inspection",
            target_id=inspection.id,
            correlation_id=correlation,
            payload={"before": current, "after": target, "reason": reason},
        )

    def process_one_outbox(self, session: Session) -> bool:
        event = session.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.status == "PENDING", OutboxEvent.available_at <= datetime.now(UTC))
            .order_by(OutboxEvent.created_at)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            return False
        event.attempts += 1
        try:
            if event.topic == "inspection.inference_requested":
                self.process_inference(session, event.aggregate_id, tenant_id=event.tenant_id)
            elif event.topic == "external_action.requested":
                action = session.scalar(
                    select(ExternalAction).where(
                        ExternalAction.id == event.aggregate_id,
                        ExternalAction.tenant_id == event.tenant_id,
                    )
                )
                if action and action.status == ExternalActionStatus.PENDING:
                    self._execute_external_action(session, action)
            else:
                event.status = "FAILED"
                event.last_error = "unknown outbox topic"
            if event.status == "PENDING":
                event.status = "PROCESSED"
                event.processed_at = datetime.now(UTC)
        except Exception as exc:
            event.last_error = f"{type(exc).__name__}: {exc}"[:1000]
            if event.attempts >= 3:
                event.status = "FAILED"
            raise
        return True
