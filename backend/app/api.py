from __future__ import annotations

import json
from collections.abc import Generator
from typing import Annotated, Any, cast

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.auth import Principal, Role, create_access_token, require_roles
from app.models import AuditEvent, ExternalAction, Tenant
from app.schemas import (
    ActivateDeploymentRequest,
    ClaimReviewRequest,
    CloseIncidentRequest,
    DatasetRegistrationRequest,
    DatasetRegistrationResponse,
    DemoTokenResponse,
    DeploymentCreateRequest,
    DeploymentResponse,
    ExternalActionResponse,
    GatewayHeartbeatRequest,
    GatewayStatusResponse,
    HealthResponse,
    IncidentActionRequest,
    IncidentSummaryResponse,
    InspectionResponse,
    ModelOpsStatusResponse,
    ModelQualificationResponse,
    OperationsSummaryResponse,
    QualificationCreateRequest,
    QualificationDecisionRequest,
    QualityIncidentResponse,
    ReplayRequest,
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewTaskResponse,
    SwitchTenantRequest,
    SwitchTenantResponse,
    TenantContextResponse,
    TenantSummary,
    TimelineEntry,
)
from app.services import InvalidInput, VisionQCService

router = APIRouter(prefix="/api/v1")


def get_session(request: Request) -> Generator[Session, None, None]:
    session = request.app.state.session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


SessionDep = Annotated[Session, Depends(get_session)]


def get_service(request: Request) -> VisionQCService:
    return cast(VisionQCService, request.app.state.service)


ServiceDep = Annotated[VisionQCService, Depends(get_service)]


def correlation_id(request: Request) -> str:
    return cast(str, request.state.correlation_id)


def external_response(action: ExternalAction) -> ExternalActionResponse:
    return ExternalActionResponse(
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


def deployment_response(deployment: Any, manifest: Any) -> DeploymentResponse:
    return DeploymentResponse(
        id=deployment.id,
        tenant_id=deployment.tenant_id,
        version=deployment.version,
        status=deployment.status,
        model=deployment.model_config_snapshot,
        policy=deployment.policy_config,
        connectors=deployment.connector_config,
        approved_by=deployment.approved_by,
        activated_at=deployment.activated_at,
        manifest=manifest,
    )


@router.get("/health", response_model=HealthResponse, tags=["operations"])
def health(request: Request) -> HealthResponse:
    service: VisionQCService = request.app.state.service
    checks = {
        "storage": service.storage.healthcheck(),
        "model": service.model_adapter.healthcheck(),
    }
    return HealthResponse(status="ok" if all(checks.values()) else "degraded", checks=checks)


@router.get("/auth/demo-token", response_model=DemoTokenResponse, tags=["authentication"])
def demo_token(request: Request) -> DemoTokenResponse:
    settings = request.app.state.settings
    if settings.environment == "production":
        raise HTTPException(status_code=404, detail="not found")
    roles: list[Role | str] = [
        Role.INSPECTOR,
        Role.QUALITY_MANAGER,
        Role.AUDITOR,
        Role.FDE,
    ]
    actor_id = "demo-quality-manager"
    return DemoTokenResponse(
        access_token=create_access_token(
            settings,
            actor_id=actor_id,
            tenant_id=settings.bootstrap_tenant_id,
            roles=roles,
        ),
        tenant_id=settings.bootstrap_tenant_id,
        actor_id=actor_id,
        roles=[str(role) for role in roles],
    )


@router.post(
    "/auth/switch-tenant",
    response_model=SwitchTenantResponse,
    tags=["authentication"],
)
def switch_tenant(
    body: SwitchTenantRequest,
    request: Request,
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_roles(Role.FDE, Role.ADMIN))],
) -> SwitchTenantResponse:
    settings = request.app.state.settings
    if settings.environment not in {"demo", "test"}:
        # Production tenant switching must come from the identity provider's
        # membership/step-up flow, never from a client-controlled header.
        raise HTTPException(
            status_code=403,
            detail="tenant switching is disabled in this environment",
        )
    if body.tenant_id not in settings.parsed_demo_switchable_tenant_ids:
        raise HTTPException(status_code=403, detail="tenant is not enabled for demo switching")
    target = session.get(Tenant, body.tenant_id)
    if target is None or target.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="target tenant not found")
    record_audit(
        session,
        tenant_id=principal.tenant_id,
        actor=principal.actor_id,
        action="tenant.switch_requested",
        target_type="tenant",
        target_id=target.id,
        correlation_id=correlation_id(request),
        payload={"from_tenant": principal.tenant_id, "to_tenant": target.id},
    )
    roles = sorted(str(role) for role in principal.roles)
    return SwitchTenantResponse(
        access_token=create_access_token(
            settings,
            actor_id=principal.actor_id,
            tenant_id=target.id,
            roles=roles,
        ),
        tenant_id=target.id,
        actor_id=principal.actor_id,
        roles=roles,
        switched_from=principal.tenant_id,
    )


@router.get("/tenant-context", response_model=TenantContextResponse, tags=["deployments"])
def tenant_context(
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ML_ENGINEER,
                Role.ADMIN,
                Role.AUDITOR,
                Role.FDE,
            )
        ),
    ],
) -> TenantContextResponse:
    settings = request.app.state.settings
    tenant = session.get(Tenant, principal.tenant_id)
    if tenant is None or tenant.status != "ACTIVE":
        raise HTTPException(status_code=404, detail="tenant not found")
    deployments = service.list_deployments(session, principal.tenant_id)
    active = next((item for item in deployments if item.status == "ACTIVE"), None)
    current = (
        deployment_response(active, service.deployment_manifest(session, active))
        if active
        else None
    )
    allowed_ids = {principal.tenant_id}
    if Role.FDE in principal.roles or Role.ADMIN in principal.roles:
        allowed_ids.update(settings.parsed_demo_switchable_tenant_ids)
    summaries = [
        TenantSummary(id=item.id, name=item.name, status=item.status)
        for item in session.scalars(select(Tenant).where(Tenant.id.in_(allowed_ids))).all()
        if item.status == "ACTIVE"
    ]
    return TenantContextResponse(
        tenant=TenantSummary(id=tenant.id, name=tenant.name, status=tenant.status),
        current_deployment=current,
        available_tenants=sorted(summaries, key=lambda item: item.id),
    )


@router.post(
    "/gateways/heartbeat",
    response_model=GatewayStatusResponse,
    tags=["edge-gateways"],
)
def gateway_heartbeat(
    body: GatewayHeartbeatRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.EDGE_GATEWAY))],
    tenant_header: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    pack_header: Annotated[str | None, Header(alias="X-Deployment-Pack")] = None,
    pack_version_header: Annotated[str | None, Header(alias="X-Deployment-Pack-Version")] = None,
) -> GatewayStatusResponse:
    if tenant_header is not None and tenant_header != principal.tenant_id:
        raise HTTPException(status_code=403, detail="tenant header does not match token")
    if pack_header is not None and body.deployment_pack_key not in {None, pack_header}:
        raise HTTPException(status_code=403, detail="deployment pack header does not match body")
    if pack_version_header is not None and body.deployment_pack_version not in {
        None,
        pack_version_header,
    }:
        raise HTTPException(
            status_code=403, detail="deployment pack version header does not match body"
        )
    return service.record_gateway_heartbeat(
        session,
        principal=principal,
        request=body,
        correlation_id=correlation_id(request),
    )


@router.get(
    "/gateways/status",
    response_model=list[GatewayStatusResponse],
    tags=["edge-gateways"],
)
def gateway_status(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ADMIN,
                Role.AUDITOR,
                Role.FDE,
            )
        ),
    ],
) -> list[GatewayStatusResponse]:
    return service.list_gateway_statuses(session, principal.tenant_id)


@router.get("/operations/summary", response_model=OperationsSummaryResponse, tags=["operations"])
def operations_summary(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ADMIN,
                Role.AUDITOR,
                Role.FDE,
            )
        ),
    ],
) -> OperationsSummaryResponse:
    return service.operations_summary(session, principal.tenant_id)


@router.get(
    "/stations/status",
    response_model=list[GatewayStatusResponse],
    include_in_schema=False,
)
def station_status(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ADMIN,
                Role.AUDITOR,
                Role.FDE,
            )
        ),
    ],
) -> list[GatewayStatusResponse]:
    return service.list_gateway_statuses(session, principal.tenant_id)


@router.post(
    "/inspections",
    response_model=InspectionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["inspections"],
)
async def create_inspection(
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER, Role.ADMIN, Role.EDGE_GATEWAY)),
    ],
    image: Annotated[UploadFile, File()],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
    gateway_id: Annotated[str | None, Header(alias="X-Gateway-ID")] = None,
    tenant_header: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    pack_header: Annotated[str | None, Header(alias="X-Deployment-Pack")] = None,
    pack_version_header: Annotated[str | None, Header(alias="X-Deployment-Pack-Version")] = None,
) -> InspectionResponse:
    if Role.EDGE_GATEWAY in principal.roles and gateway_id != principal.actor_id:
        raise HTTPException(status_code=403, detail="gateway identity header does not match token")
    if Role.EDGE_GATEWAY in principal.roles:
        if tenant_header is not None and tenant_header != principal.tenant_id:
            raise HTTPException(status_code=403, detail="tenant header does not match token")
        deployment = service.active_deployment(session, principal.tenant_id)
        manifest = service.deployment_manifest(session, deployment)
        if pack_header is not None and pack_header != manifest.pack_key:
            raise HTTPException(
                status_code=403, detail="deployment pack header does not match active pack"
            )
        if pack_version_header is not None and pack_version_header != manifest.version:
            raise HTTPException(
                status_code=403,
                detail="deployment pack version header does not match active pack",
            )
    form = await request.form()
    context = service.context_from_fields(session, principal=principal, fields=form)
    data = await image.read(service.settings.max_upload_bytes + 1)
    return service.create_inspection(
        session,
        principal=principal,
        context=context,
        image_bytes=data,
        content_type=image.content_type,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id(request),
    )


@router.get("/inspections", response_model=list[InspectionResponse], tags=["inspections"])
def list_inspections(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ML_ENGINEER,
                Role.ADMIN,
                Role.AUDITOR,
            )
        ),
    ],
) -> list[InspectionResponse]:
    return service.list_inspections(session, tenant_id=principal.tenant_id)


@router.get("/inspections/{inspection_id}", response_model=InspectionResponse, tags=["inspections"])
def get_inspection(
    inspection_id: str,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ML_ENGINEER,
                Role.ADMIN,
                Role.AUDITOR,
            )
        ),
    ],
) -> InspectionResponse:
    return service.get_inspection(
        session, tenant_id=principal.tenant_id, inspection_id=inspection_id
    )


@router.get(
    "/inspections/{inspection_id}/timeline",
    response_model=list[TimelineEntry],
    tags=["inspections"],
)
def inspection_timeline(
    inspection_id: str,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER, Role.ADMIN, Role.AUDITOR)),
    ],
) -> list[TimelineEntry]:
    return [
        TimelineEntry.model_validate(item)
        for item in service.inspection_timeline(
            session, tenant_id=principal.tenant_id, inspection_id=inspection_id
        )
    ]


@router.get("/assets/{asset_id}", tags=["evidence"])
def get_asset(
    asset_id: str,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ML_ENGINEER,
                Role.ADMIN,
                Role.AUDITOR,
            )
        ),
    ],
) -> Response:
    asset = service.get_image_asset(session, tenant_id=principal.tenant_id, asset_id=asset_id)
    return Response(
        content=service.storage.get(asset.uri),
        media_type=asset.mime_type,
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/reviews", response_model=list[ReviewTaskResponse], tags=["reviews"])
def list_reviews(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER, Role.AUDITOR)),
    ],
) -> list[ReviewTaskResponse]:
    return [
        service.review_task_response(session, task)
        for task in service.list_reviews(session, principal.tenant_id)
    ]


@router.post("/reviews/{task_id}/claim", response_model=ReviewTaskResponse, tags=["reviews"])
def claim_review(
    task_id: str,
    body: ClaimReviewRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER))],
) -> ReviewTaskResponse:
    task = service.claim_review(
        session,
        principal=principal,
        task_id=task_id,
        expected_version=body.expected_version,
        correlation_id=correlation_id(request),
    )
    return service.review_task_response(session, task)


@router.post(
    "/reviews/{task_id}/decisions",
    response_model=ReviewDecisionResponse,
    tags=["reviews"],
)
def decide_review(
    task_id: str,
    body: ReviewDecisionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER))],
) -> ReviewDecisionResponse:
    decision, inspection, incident, task_version = service.decide_review(
        session,
        principal=principal,
        task_id=task_id,
        request=body,
        correlation_id=correlation_id(request),
    )
    return ReviewDecisionResponse(
        review_task_id=task_id,
        decision_id=decision.id,
        inspection_id=inspection.id,
        inspection_status=inspection.status,
        incident_id=incident.id if incident else None,
        task_version=task_version,
        submitted_at=decision.created_at,
        actor=decision.actor_id,
        correlation_id=correlation_id(request),
    )


@router.get(
    "/incidents/{incident_id}",
    response_model=QualityIncidentResponse,
    tags=["quality-incidents"],
)
def get_incident(
    incident_id: str,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER, Role.ADMIN, Role.AUDITOR)),
    ],
) -> QualityIncidentResponse:
    return service.get_incident(session, tenant_id=principal.tenant_id, incident_id=incident_id)


@router.get("/incidents", response_model=list[IncidentSummaryResponse], tags=["quality-incidents"])
def list_incidents(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER, Role.ADMIN, Role.AUDITOR)),
    ],
) -> list[IncidentSummaryResponse]:
    return [
        IncidentSummaryResponse(
            id=incident.id,
            inspection_id=incident.inspection_id,
            status=incident.status,
            severity=incident.severity,
            created_at=incident.created_at,
            updated_at=incident.updated_at,
            owner=incident.owner,
            disposition=incident.disposition,
            batch_no=(incident.inspection.batch_no if incident.inspection is not None else "—"),
            product_code=(
                incident.inspection.product_code if incident.inspection is not None else "—"
            ),
            station_code=(
                incident.inspection.station_code if incident.inspection is not None else "—"
            ),
        )
        for incident in service.list_incidents(session, principal.tenant_id)
    ]


@router.get("/modelops/status", response_model=ModelOpsStatusResponse, tags=["modelops"])
def modelops_status(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.INSPECTOR,
                Role.QUALITY_MANAGER,
                Role.ML_ENGINEER,
                Role.ADMIN,
                Role.AUDITOR,
                Role.FDE,
            )
        ),
    ],
) -> ModelOpsStatusResponse:
    return service.modelops_status(session, principal.tenant_id)


def dataset_registration_response(item: Any) -> DatasetRegistrationResponse:
    return VisionQCService.dataset_response(item)


@router.get(
    "/datasets/registrations",
    response_model=list[DatasetRegistrationResponse],
    tags=["datasets"],
)
def list_dataset_registrations(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.ML_ENGINEER, Role.QUALITY_MANAGER, Role.ADMIN, Role.AUDITOR, Role.FDE
            )
        ),
    ],
) -> list[DatasetRegistrationResponse]:
    return [
        dataset_registration_response(item)
        for item in service.list_dataset_registrations(session, principal.tenant_id)
    ]


@router.post(
    "/datasets/registrations",
    response_model=DatasetRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["datasets"],
)
def create_dataset_registration(
    body: DatasetRegistrationRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal, Depends(require_roles(Role.ML_ENGINEER, Role.FDE, Role.QUALITY_MANAGER))
    ],
) -> DatasetRegistrationResponse:
    return dataset_registration_response(
        service.register_dataset(
            session,
            principal=principal,
            request=body,
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/datasets/registrations/upload",
    response_model=DatasetRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["datasets"],
)
def upload_dataset_registration(
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal, Depends(require_roles(Role.ML_ENGINEER, Role.FDE, Role.QUALITY_MANAGER))
    ],
    file: Annotated[UploadFile, File(...)],
    source_type: str = Form(...),
    name: str = Form(...),
    category: str = Form(...),
    expected_sha256: str | None = Form(default=None),
    license_acknowledged: bool = Form(default=False),
    customer_provenance_json: str | None = Form(default=None),
    metadata_json: str | None = Form(default=None),
) -> DatasetRegistrationResponse:
    try:
        payload: dict[str, Any] = {
            "source_type": source_type,
            "name": name,
            "category": category,
            "expected_sha256": expected_sha256,
            "license_acknowledged": license_acknowledged,
            "customer_provenance": (
                json.loads(customer_provenance_json) if customer_provenance_json else None
            ),
            "metadata": json.loads(metadata_json) if metadata_json else {},
        }
        body = DatasetRegistrationRequest.model_validate(payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise InvalidInput(
            "dataset upload registration fields are invalid", details={"reason": str(exc)}
        ) from exc
    return dataset_registration_response(
        service.register_dataset_upload(
            session,
            principal=principal,
            request=body,
            source=file.file,
            filename=file.filename or "dataset.bin",
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/datasets/registrations/{registration_id}/revoke",
    response_model=DatasetRegistrationResponse,
    tags=["datasets"],
)
def revoke_dataset_registration(
    registration_id: str,
    body: QualificationDecisionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal, Depends(require_roles(Role.ML_ENGINEER, Role.FDE, Role.QUALITY_MANAGER))
    ],
) -> DatasetRegistrationResponse:
    return dataset_registration_response(
        service.revoke_dataset_registration(
            session,
            principal=principal,
            registration_id=registration_id,
            reason=body.reason,
            correlation_id=correlation_id(request),
        )
    )


def qualification_response(item: Any) -> ModelQualificationResponse:
    return ModelQualificationResponse.model_validate(item)


@router.get(
    "/modelops/qualifications", response_model=list[ModelQualificationResponse], tags=["modelops"]
)
def list_model_qualifications(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.ML_ENGINEER, Role.QUALITY_MANAGER, Role.ADMIN, Role.AUDITOR, Role.FDE
            )
        ),
    ],
) -> list[ModelQualificationResponse]:
    return [
        qualification_response(item)
        for item in service.list_qualifications(session, principal.tenant_id)
    ]


@router.post(
    "/modelops/qualifications", response_model=ModelQualificationResponse, tags=["modelops"]
)
def create_model_qualification(
    body: QualificationCreateRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.ML_ENGINEER, Role.FDE))],
) -> ModelQualificationResponse:
    return qualification_response(
        service.create_qualification(
            session, principal=principal, request=body, correlation_id=correlation_id(request)
        )
    )


@router.post(
    "/modelops/qualifications/{qualification_id}/evaluate",
    response_model=ModelQualificationResponse,
    tags=["modelops"],
)
def evaluate_model_qualification(
    qualification_id: str,
    body: QualificationDecisionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.ML_ENGINEER))],
) -> ModelQualificationResponse:
    return qualification_response(
        service.evaluate_qualification(
            session,
            principal=principal,
            qualification_id=qualification_id,
            reason=body.reason,
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/modelops/qualifications/{qualification_id}/approve",
    response_model=ModelQualificationResponse,
    tags=["modelops"],
)
def approve_model_qualification(
    qualification_id: str,
    body: QualificationDecisionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY_MANAGER))],
) -> ModelQualificationResponse:
    return qualification_response(
        service.approve_qualification(
            session,
            principal=principal,
            qualification_id=qualification_id,
            reason=body.reason,
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/modelops/qualifications/{qualification_id}/activate",
    response_model=ModelQualificationResponse,
    tags=["modelops"],
)
def activate_model_qualification(
    qualification_id: str,
    body: QualificationDecisionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.FDE))],
) -> ModelQualificationResponse:
    return qualification_response(
        service.activate_qualification(
            session,
            principal=principal,
            qualification_id=qualification_id,
            reason=body.reason,
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/modelops/qualifications/{qualification_id}/retire",
    response_model=ModelQualificationResponse,
    tags=["modelops"],
)
def retire_model_qualification(
    qualification_id: str,
    body: QualificationDecisionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.QUALITY_MANAGER))],
) -> ModelQualificationResponse:
    return qualification_response(
        service.retire_qualification(
            session,
            principal=principal,
            qualification_id=qualification_id,
            reason=body.reason,
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/modelops/qualifications/{qualification_id}/rollback",
    response_model=ModelQualificationResponse,
    tags=["modelops"],
)
def rollback_model_qualification(
    qualification_id: str,
    body: QualificationDecisionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.FDE))],
) -> ModelQualificationResponse:
    return qualification_response(
        service.rollback_qualification(
            session,
            principal=principal,
            qualification_id=qualification_id,
            reason=body.reason,
            correlation_id=correlation_id(request),
        )
    )


@router.post(
    "/incidents/{incident_id}/actions",
    response_model=ExternalActionResponse,
    tags=["quality-incidents"],
)
def create_incident_action(
    incident_id: str,
    body: IncidentActionRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY_MANAGER))],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=200)],
) -> ExternalActionResponse:
    return external_response(
        service.request_incident_action(
            session,
            principal=principal,
            incident_id=incident_id,
            request=body,
            idempotency_key=idempotency_key,
            correlation_id=correlation_id(request),
        )
    )


@router.get(
    "/external-actions/{action_id}",
    response_model=ExternalActionResponse,
    tags=["quality-incidents"],
)
def get_external_action(
    action_id: str,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal, Depends(require_roles(Role.QUALITY_MANAGER, Role.ADMIN, Role.AUDITOR))
    ],
) -> ExternalActionResponse:
    return external_response(service.get_external_action(session, principal.tenant_id, action_id))


@router.post(
    "/external-actions/{action_id}/replay",
    response_model=ExternalActionResponse,
    tags=["quality-incidents"],
)
def replay_external_action(
    action_id: str,
    body: ReplayRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY_MANAGER, Role.ADMIN))],
) -> ExternalActionResponse:
    return external_response(
        service.replay_external_action(
            session,
            principal=principal,
            action_id=action_id,
            reason=body.reason,
            correlation_id=correlation_id(request),
        )
    )


@router.post("/incidents/{incident_id}/close", tags=["quality-incidents"])
def close_incident(
    incident_id: str,
    body: CloseIncidentRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.QUALITY_MANAGER))],
) -> dict[str, str]:
    incident = service.close_incident(
        session,
        principal=principal,
        incident_id=incident_id,
        request=body,
        correlation_id=correlation_id(request),
    )
    return {"incident_id": incident.id, "status": incident.status}


@router.get(
    "/incidents/{incident_id}/timeline",
    response_model=list[TimelineEntry],
    tags=["quality-incidents"],
)
def incident_timeline(
    incident_id: str,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.INSPECTOR, Role.QUALITY_MANAGER, Role.ADMIN, Role.AUDITOR)),
    ],
) -> list[TimelineEntry]:
    return [
        TimelineEntry.model_validate(entry)
        for entry in service.timeline(
            session, tenant_id=principal.tenant_id, incident_id=incident_id
        )
    ]


@router.get("/audit-events", tags=["audit"])
def list_audit_events(
    session: SessionDep,
    principal: Annotated[Principal, Depends(require_roles(Role.AUDITOR, Role.ADMIN))],
    target_id: str | None = None,
) -> list[dict[str, Any]]:
    query = select(AuditEvent).where(AuditEvent.tenant_id == principal.tenant_id)
    if target_id:
        query = query.where(AuditEvent.target_id == target_id)
    events = session.scalars(query.order_by(AuditEvent.occurred_at)).all()
    return [
        {
            "id": event.id,
            "actor": event.actor,
            "action": event.action,
            "target_type": event.target_type,
            "target_id": event.target_id,
            "correlation_id": event.correlation_id,
            "payload": event.payload,
            "payload_digest": event.payload_digest,
            "occurred_at": event.occurred_at,
        }
        for event in events
    ]


@router.post("/deployments", response_model=DeploymentResponse, tags=["deployments"])
def create_deployment(
    body: DeploymentCreateRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[Principal, Depends(require_roles(Role.ADMIN, Role.FDE))],
) -> DeploymentResponse:
    deployment = service.create_deployment(
        session,
        principal=principal,
        request=body,
        correlation_id=correlation_id(request),
    )
    return deployment_response(deployment, service.deployment_manifest(session, deployment))


@router.get("/deployments", response_model=list[DeploymentResponse], tags=["deployments"])
def list_deployments(
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(require_roles(Role.ADMIN, Role.FDE, Role.QUALITY_MANAGER, Role.AUDITOR)),
    ],
) -> list[DeploymentResponse]:
    return [
        deployment_response(item, service.deployment_manifest(session, item))
        for item in service.list_deployments(session, principal.tenant_id)
    ]


@router.post(
    "/deployments/{deployment_id}/activate",
    response_model=DeploymentResponse,
    tags=["deployments"],
)
def activate_deployment(
    deployment_id: str,
    body: ActivateDeploymentRequest,
    request: Request,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal, Depends(require_roles(Role.QUALITY_MANAGER, Role.ADMIN, Role.FDE))
    ],
) -> DeploymentResponse:
    deployment = service.activate_deployment(
        session,
        principal=principal,
        deployment_id=deployment_id,
        reason=body.reason,
        correlation_id=correlation_id(request),
    )
    return deployment_response(deployment, service.deployment_manifest(session, deployment))


@router.get(
    "/deployments/{deployment_id}/manifest",
    response_model=DeploymentResponse,
    tags=["deployments"],
)
def export_deployment_manifest(
    deployment_id: str,
    session: SessionDep,
    service: ServiceDep,
    principal: Annotated[
        Principal,
        Depends(
            require_roles(
                Role.ADMIN,
                Role.QUALITY_MANAGER,
                Role.ML_ENGINEER,
                Role.AUDITOR,
                Role.FDE,
            )
        ),
    ],
) -> DeploymentResponse:
    deployment = service.get_deployment(session, principal.tenant_id, deployment_id)
    return deployment_response(deployment, service.deployment_manifest(session, deployment))
