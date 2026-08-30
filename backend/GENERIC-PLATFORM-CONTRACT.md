# VisionQC Platform generic contract

This document defines the backend contract for a tenant-neutral VisionQC
Platform.  A customer or industry is selected by configuration; it is not a
domain requirement of the inspection workflow.

## Configuration

The current schema identifier is `visionqc.platform-config.v1`.  Configuration
is resolved in this fixed order, with later layers taking precedence for the
same field:

`platform_defaults -> industry_pack -> tenant_override -> runtime_site_override`

Each layer is a strict object.  Unknown fields, invalid IANA time zones,
invalid language tags, duplicate capture channels, invalid thresholds, and
cross-tenant `tenant_id` values are rejected.  Materialisation returns:

- the canonical `effective_config`;
- a SHA-256 `config_hash` of the canonical JSON form;
- field-level `sources` identifying the winning layer;
- `version`, validation status, audit metadata, and prior versions suitable for
  rollback selection.

The canonical configuration covers display name, industry, locale, retention,
privacy mode, capture channels, workflow, approval rules, model reference,
calibration/threshold reference, connector references, and namespaced
extensions.  Hard safety fields are immutable: abnormal, unavailable-model,
out-of-distribution, and image-quality failures cannot auto-release, and
external actions require human confirmation.  Workflow preferences can route
safe results to review or Hold, but cannot relax these invariants.

Secret material is never accepted in configuration.  Connectors may carry a
`secret_ref` such as `vault://tenant/qms` or `secret://store/key`; the target
secret must be resolved by the connector/runtime outside this API.  Manifests,
effective configuration responses, version responses, audit payloads, and
validation errors redact secret-like values and do not resolve references.

## Generic domain

`InspectionContext` requires only product, batch/lot, station, capture time,
and source.  `workpiece_id` is optional.  `Workpiece` and `QualityCase` are
generic tenant-scoped concepts; the historical `quality_incidents` table and
incident endpoints remain compatible.  Site or industry values belong in the
bounded `metadata` extension envelope, preferably under
`metadata.extensions.<namespace>`.

The `automotive-paint` namespace is an optional adapter used by the simulated
DXQ compatibility path.  Values such as `body_id`, `color_code`, and
`paint_recipe` are never required by the generic core and are not promoted to
generic database columns.

## API

- `GET /api/v1/config/effective` returns the authenticated tenant's validated,
  redacted effective configuration, sources, version, hash, audit, and rollback
  candidates.
- `POST /api/v1/config/validate` validates explicit four-layer input without
  persisting it.  `/api/v1/config/preview` and
  `/api/v1/configuration/validate` are compatibility aliases.
- `GET /api/v1/config/versions` returns only configuration versions belonging
  to the authenticated tenant.

The authenticated JWT tenant is authoritative.  A tenant ID in a body or
layer can only equal that tenant; it cannot select or read another tenant.

## Compatibility and migration

`visionqc.deployment-pack.v1` manifests and the legacy deployment create
shape remain accepted.  The backend adapts them into the four layers at read
or bootstrap time, preserving the old manifest, model, policy, and connector
fields.  New deployment rows persist the effective snapshot, layer payload,
provenance, validation state, and an immutable tenant configuration version.

Migration `0009_platform_configuration` adds the configuration-version and
generic workpiece tables, plus additive deployment/inspection/quality-case
columns.  Existing rows remain readable through the legacy adapter and can be
backfilled during bootstrap without overwriting customer-approved packs.
