from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.deployment import DeploymentManifest, load_manifests
from app.models import DeploymentPack, Tenant, TenantConfigurationVersion
from app.platform_config import (
    ConfigurationError,
    ConfigurationLayers,
    EffectiveConfiguration,
    layers_from_effective_configuration,
    layers_from_legacy_manifest,
    merge_configuration_layers,
    redact_configuration,
)


def _pack_id(manifest: DeploymentManifest) -> str:
    safe_version = "".join(
        character if character.isalnum() else "_" for character in manifest.version
    )
    return f"dep_{manifest.tenant.id.replace('-', '_')}_{safe_version}"


def _materialize_configuration(
    manifest: DeploymentManifest,
) -> tuple[DeploymentManifest, ConfigurationLayers, EffectiveConfiguration]:
    layers = (
        manifest.configuration_layers
        if manifest.configuration_layers is not None
        else (
            layers_from_effective_configuration(manifest.configuration)
            if manifest.configuration is not None
            else layers_from_legacy_manifest(manifest)
        )
    )
    try:
        config = merge_configuration_layers(
            layers.platform_defaults,
            layers.industry_pack,
            layers.tenant_override,
            layers.runtime_site_override,
            tenant_id=manifest.tenant.id,
            version=manifest.version,
            created_by="system:bootstrap",
            source="legacy-manifest-bootstrap",
        )
    except (ConfigurationError, ValueError) as exc:
        raise ValueError(f"invalid bootstrap configuration for {manifest.tenant.id}") from exc
    payload = manifest.model_dump(mode="json")
    payload["configuration"] = config.effective_config.model_dump(mode="json")
    payload["configuration_layers"] = layers.model_dump(mode="json", exclude_none=True)
    return DeploymentManifest.model_validate(payload), layers, config


def _persist_materialized(
    session: Session,
    materialized: DeploymentManifest,
    layers: ConfigurationLayers,
    config: EffectiveConfiguration,
) -> DeploymentPack:
    now = datetime.now(UTC)
    config_snapshot = redact_configuration(config.effective_config.model_dump(mode="json"))
    config_layers = redact_configuration(layers.model_dump(mode="json", exclude_none=True))
    config_audit = redact_configuration(config.audit.model_dump(mode="json"))
    # A pre-v1 database may already contain a version row for the same
    # deployment.  Reusing an identical hash keeps bootstrap idempotent and
    # avoids creating a second version in the stale-system convergence path.
    session.flush()
    existing_configuration = session.scalar(
        select(TenantConfigurationVersion).where(
            TenantConfigurationVersion.tenant_id == materialized.tenant.id,
            TenantConfigurationVersion.version == config.version,
        )
    )
    if existing_configuration is None:
        session.add(
            TenantConfigurationVersion(
                tenant_id=materialized.tenant.id,
                schema_version=config.schema_version,
                version=config.version,
                config_hash=config.config_hash,
                effective_config=config_snapshot,
                source_layers=config_layers,
                validation_status="VALID",
                audit_metadata=config_audit,
                status="ACTIVE",
                created_by="system:bootstrap",
                parent_version=config.audit.parent_version,
                activated_at=now,
            )
        )
    elif existing_configuration.config_hash != config.config_hash:
        raise ValueError(
            f"configuration version {config.version} already exists with a different hash"
        )
    return DeploymentPack(
        id=_pack_id(materialized),
        tenant_id=materialized.tenant.id,
        version=materialized.version,
        status="ACTIVE",
        model_config_snapshot=redact_configuration(materialized.model.model_dump(mode="json")),
        policy_config=redact_configuration(materialized.policy.model_dump(mode="json")),
        connector_config=redact_configuration(materialized.connectors.model_dump(mode="json")),
        manifest=redact_configuration(materialized.model_dump(mode="json")),
        configuration_version=config.version,
        configuration_schema_version=config.schema_version,
        configuration_hash=config.config_hash,
        configuration_snapshot=config_snapshot,
        configuration_layers=config_layers,
        configuration_sources=dict(config.sources),
        configuration_validation_status=config.validation_status,
        configuration_audit=config_audit,
        approved_by="system:bootstrap",
        activated_at=now,
    )


def _persist_manifest(session: Session, manifest: DeploymentManifest) -> DeploymentPack:
    materialized, layers, config = _materialize_configuration(manifest)
    return _persist_materialized(session, materialized, layers, config)


def _apply_configuration_snapshot(
    deployment: DeploymentPack,
    *,
    manifest: DeploymentManifest,
    layers: ConfigurationLayers,
    config: EffectiveConfiguration,
) -> None:
    deployment.version = manifest.version
    deployment.model_config_snapshot = manifest.model.model_dump(mode="json")
    deployment.policy_config = manifest.policy.model_dump(mode="json")
    deployment.connector_config = manifest.connectors.model_dump(mode="json")
    deployment.manifest = redact_configuration(manifest.model_dump(mode="json"))
    deployment.configuration_version = config.version
    deployment.configuration_schema_version = config.schema_version
    deployment.configuration_hash = config.config_hash
    deployment.configuration_snapshot = redact_configuration(
        config.effective_config.model_dump(mode="json")
    )
    deployment.configuration_layers = redact_configuration(
        layers.model_dump(mode="json", exclude_none=True)
    )
    deployment.configuration_sources = dict(config.sources)
    deployment.configuration_validation_status = config.validation_status
    deployment.configuration_audit = redact_configuration(config.audit.model_dump(mode="json"))


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
        materialized, layers, config = _materialize_configuration(manifest)
        current_payload = materialized.model_dump(mode="json")
        if active is None:
            session.add(_persist_materialized(session, materialized, layers, config))
        elif not active.manifest:
            # Backfill records created by the pre-v1 API without changing their
            # version or historical inspection snapshots.
            _apply_configuration_snapshot(
                active,
                manifest=materialized,
                layers=layers,
                config=config,
            )
        elif active.approved_by == "system:bootstrap" and active.manifest != current_payload:
            # A long-lived demo volume may have been bootstrapped by an older
            # branch before Edge Gateway fields were part of the unified pack.
            # Converge only system-owned bootstrap records; never overwrite a
            # customer/FDE-approved deployment in place.
            if active.id == _pack_id(manifest):
                _apply_configuration_snapshot(
                    active,
                    manifest=materialized,
                    layers=layers,
                    config=config,
                )
            else:
                active.status = "RETIRED"
                session.flush()
                session.add(_persist_materialized(session, materialized, layers, config))

        if active is not None:
            # The stale-system branch above may have queued a replacement pack
            # and its config version while autoflush is disabled on the
            # application session.  Make that row visible before checking for
            # a compatibility backfill, avoiding a duplicate unique key.
            session.flush()
            configuration_version = session.scalar(
                select(TenantConfigurationVersion).where(
                    TenantConfigurationVersion.tenant_id == tenant.id,
                    TenantConfigurationVersion.version == config.version,
                )
            )
            if configuration_version is None:
                session.add(
                    TenantConfigurationVersion(
                        tenant_id=tenant.id,
                        schema_version=config.schema_version,
                        version=config.version,
                        config_hash=config.config_hash,
                        effective_config=redact_configuration(
                            config.effective_config.model_dump(mode="json")
                        ),
                        source_layers=redact_configuration(
                            layers.model_dump(mode="json", exclude_none=True)
                        ),
                        validation_status=config.validation_status,
                        audit_metadata=redact_configuration(config.audit.model_dump(mode="json")),
                        status="ACTIVE",
                        created_by="system:bootstrap",
                        parent_version=config.audit.parent_version,
                        activated_at=active.activated_at or datetime.now(UTC),
                    )
                )

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
