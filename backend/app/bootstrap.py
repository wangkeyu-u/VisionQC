from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deployment import DeploymentManifest, load_manifests
from app.models import DeploymentPack, Tenant


def _pack_id(manifest: DeploymentManifest) -> str:
    safe_version = "".join(
        character if character.isalnum() else "_" for character in manifest.version
    )
    return f"dep_{manifest.tenant.id.replace('-', '_')}_{safe_version}"


def _persist_manifest(session: Session, manifest: DeploymentManifest) -> DeploymentPack:
    return DeploymentPack(
        id=_pack_id(manifest),
        tenant_id=manifest.tenant.id,
        version=manifest.version,
        status="ACTIVE",
        model_config_snapshot=manifest.model.model_dump(mode="json"),
        policy_config=manifest.policy.model_dump(mode="json"),
        connector_config=manifest.connectors.model_dump(mode="json"),
        manifest=manifest.model_dump(mode="json"),
        approved_by="system:bootstrap",
    )


def bootstrap_defaults(session: Session, settings: Settings) -> None:
    if not settings.bootstrap_enabled:
        return

    manifest_dir: Path | None = settings.deployment_manifest_dir
    manifests = load_manifests(manifest_dir)
    allowed_tenants = set(settings.parsed_bootstrap_tenant_ids)
    selected = [item for item in manifests if item.tenant.id in allowed_tenants]

    # A deployment manifest is the source of truth for the demo tenants.  The
    # explicit allow-list prevents an arbitrary JSON file copied into the
    # container from silently becoming a reachable customer.
    for manifest in selected:
        tenant = session.get(Tenant, manifest.tenant.id)
        if tenant is None:
            tenant = Tenant(id=manifest.tenant.id, name=manifest.tenant.name, status="ACTIVE")
            session.add(tenant)
            session.flush()

        active = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.tenant_id == tenant.id,
                DeploymentPack.status == "ACTIVE",
            )
        )
        current_payload = manifest.model_dump(mode="json")
        if active is None:
            session.add(_persist_manifest(session, manifest))
        elif not active.manifest:
            # Backfill records created by the pre-v1 API without changing their
            # version or historical inspection snapshots.
            active.manifest = current_payload
        elif active.approved_by == "system:bootstrap" and active.manifest != current_payload:
            # A long-lived demo volume may have been bootstrapped by an older
            # branch before Edge Gateway fields were part of the unified pack.
            # Converge only system-owned bootstrap records; never overwrite a
            # customer/FDE-approved deployment in place.
            if active.id == _pack_id(manifest):
                active.version = manifest.version
                active.model_config_snapshot = manifest.model.model_dump(mode="json")
                active.policy_config = manifest.policy.model_dump(mode="json")
                active.connector_config = manifest.connectors.model_dump(mode="json")
                active.manifest = current_payload
            else:
                active.status = "RETIRED"
                session.flush()
                session.add(_persist_manifest(session, manifest))

    # Preserve the old single-tenant setting for local installations that use
    # a custom manifest directory containing only one customer.
    if not selected and session.get(Tenant, settings.bootstrap_tenant_id) is None:
        session.add(
            Tenant(
                id=settings.bootstrap_tenant_id,
                name=settings.bootstrap_tenant_name,
                status="ACTIVE",
            )
        )
