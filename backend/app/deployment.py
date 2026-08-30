"""Versioned, tenant-scoped Deployment Pack contracts.

The manifest is the hand-off between an FDE and the VisionQC workflow.  It
contains the customer-facing product/station vocabulary, the input field
mapping, the model evidence metadata, the policy and the external contracts.
The workflow only consumes the canonical fields produced by this module; it
does not branch on a tenant or product name.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.policy import PolicyConfig

CANONICAL_FIELDS = (
    "product_code",
    "product_revision",
    "batch_no",
    "station_code",
    "captured_at",
    "source",
)

INDUSTRY_PACK_SCHEMA_VERSION: Literal["visionqc.industry-pack.v1"] = "visionqc.industry-pack.v1"
TENANT_OVERLAY_SCHEMA_VERSION: Literal["visionqc.tenant-overlay.v1"] = "visionqc.tenant-overlay.v1"
RESOLVED_PACK_SCHEMA_VERSION: Literal["visionqc.deployment-pack.v2"] = "visionqc.deployment-pack.v2"
HASH_CANONICALIZATION: Literal["json-sort-keys-utf8-no-whitespace-v1"] = (
    "json-sort-keys-utf8-no-whitespace-v1"
)


class DeploymentContract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TenantDefinition(DeploymentContract):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)


class ProductDefinition(DeploymentContract):
    code: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=64)
    aliases: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def aliases_are_unique(self) -> ProductDefinition:
        values = [self.code, *self.aliases]
        if len(values) != len(set(values)):
            raise ValueError("product code and aliases must be unique")
        return self

    def matches(self, value: str) -> bool:
        return self.code == "*" or value == self.code or value in self.aliases


class StationDefinition(DeploymentContract):
    code: str = Field(min_length=1, max_length=128)
    display_name: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    camera_profile: str = Field(min_length=1, max_length=128)


class GatewayWatchDefinition(DeploymentContract):
    """Configures a directory-based industrial camera contract."""

    root: str = Field(min_length=1, max_length=500)
    relative_path_regex: str = Field(min_length=1, max_length=500)
    filename_regex: str = Field(min_length=1, max_length=500)
    capture_map: dict[str, str] = Field(default_factory=dict)
    defaults: dict[str, str] = Field(default_factory=dict)
    source: str = Field(min_length=1, max_length=128)
    allowed_extensions: list[str] = Field(default_factory=lambda: [".png", ".jpg", ".jpeg"])
    timestamp_formats: list[str] = Field(default_factory=lambda: ["%Y%m%dT%H%M%S"])
    timezone_offset: str = Field(default="+00:00", pattern=r"^[+-]\d{2}:\d{2}$")
    stable_for_seconds: float = Field(default=1.0, ge=0, le=3600)
    archive_subdir: str = Field(default=".archive", min_length=1, max_length=128)
    quarantine_subdir: str = Field(default=".quarantine", min_length=1, max_length=128)


class EdgeGatewayDefinition(DeploymentContract):
    """Tenant binding and watch rules consumed by the standalone gateway."""

    gateway_id: str = Field(min_length=1, max_length=128)
    target_tenant_id: str = Field(min_length=1, max_length=64)
    watch: GatewayWatchDefinition
    simulator: dict[str, Any] | None = None


class FieldMapping(DeploymentContract):
    """Maps canonical workflow fields to the customer's submitted keys."""

    product_code: str = Field(min_length=1, max_length=64)
    product_revision: str = Field(min_length=1, max_length=64)
    batch_no: str = Field(min_length=1, max_length=64)
    station_code: str = Field(min_length=1, max_length=64)
    captured_at: str = Field(min_length=1, max_length=64)
    source: str = Field(default="source", min_length=1, max_length=64)

    @model_validator(mode="after")
    def keys_are_unique(self) -> FieldMapping:
        keys = [getattr(self, name) for name in CANONICAL_FIELDS]
        if len(keys) != len(set(keys)):
            raise ValueError("field mapping keys must be unique")
        return self

    def key_for(self, canonical_name: str) -> str:
        if canonical_name not in CANONICAL_FIELDS:
            raise KeyError(canonical_name)
        return str(getattr(self, canonical_name))


class ModelDefinition(DeploymentContract):
    id: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    feature_bank_version: str = Field(min_length=1, max_length=128)
    adapter: str = Field(min_length=1, max_length=128)
    runtime: str = Field(min_length=1, max_length=128)
    device: str = Field(min_length=1, max_length=64)
    package_uri: str = Field(min_length=1, max_length=500)
    package_sha256: str | None = Field(default=None, max_length=128)
    score_semantics: str = Field(min_length=1, max_length=500)
    limitations: list[str] = Field(default_factory=list, max_length=20)


class ConnectorDefinition(DeploymentContract):
    display_name: str = Field(min_length=1, max_length=200)
    driver: str = Field(min_length=1, max_length=64)
    contract_version: str = Field(min_length=1, max_length=64)
    endpoint: str = Field(min_length=1, max_length=500)
    payload_mapping: dict[str, str] = Field(default_factory=dict)
    fixed_fields: dict[str, Any] = Field(default_factory=dict)
    operations: list[str] = Field(min_length=1, max_length=20)
    capability: str = Field(default="workflow", min_length=1, max_length=64)
    health_path: str = Field(default="/health", min_length=1, max_length=200)
    timeout_seconds: float = Field(default=10.0, gt=0, le=300)
    retry_max_attempts: int = Field(default=3, ge=1, le=20)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=300)
    idempotency_header: str = Field(default="Idempotency-Key", min_length=1, max_length=128)
    secret_refs: list[str] = Field(default_factory=list, max_length=20)
    simulated: bool = False

    @model_validator(mode="after")
    def validate_contract(self) -> ConnectorDefinition:
        if len(self.operations) != len(set(self.operations)):
            raise ValueError("connector operations must be unique")
        invalid_refs = [
            ref for ref in self.secret_refs if re.fullmatch(r"[A-Z][A-Z0-9_]*", ref) is None
        ]
        if invalid_refs:
            raise ValueError(f"connector secret refs must be uppercase names: {invalid_refs}")
        return self


class ConnectorSet(DeploymentContract):
    mes: ConnectorDefinition
    qms: ConnectorDefinition
    # Optional, explicitly simulated digital-quality contract.  Existing
    # Factory A/B packs remain valid and continue to use only MES/QMS.
    dxq_mock: ConnectorDefinition | None = None
    ingest: ConnectorDefinition | None = None
    notification: ConnectorDefinition | None = None
    analytics: ConnectorDefinition | None = None
    generic_qms_mock: ConnectorDefinition | None = None


class PackReference(DeploymentContract):
    key: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class PackIntegrity(DeploymentContract):
    algorithm: Literal["sha256"] = "sha256"
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonicalization: Literal["json-sort-keys-utf8-no-whitespace-v1"] = HASH_CANONICALIZATION
    excludes: list[str] = Field(default_factory=lambda: ["integrity.manifest_sha256"])

    @model_validator(mode="after")
    def excludes_self_hash(self) -> PackIntegrity:
        if "integrity.manifest_sha256" not in self.excludes:
            raise ValueError("integrity.excludes must include integrity.manifest_sha256")
        return self


class PackValidation(DeploymentContract):
    status: str = Field(min_length=1, max_length=64)
    validator: str = Field(min_length=1, max_length=200)
    checks: list[str] = Field(min_length=1, max_length=50)
    warnings: list[str] = Field(default_factory=list, max_length=50)


class MigrationNotes(DeploymentContract):
    from_schema_versions: list[str] = Field(default_factory=list, max_length=20)
    strategy: Literal["none", "additive", "resolver", "manual"] = "additive"
    notes: str = Field(min_length=1, max_length=2000)


class CollectionDefinition(DeploymentContract):
    input_modes: list[Literal["api_upload", "folder_watch", "usb_camera"]] = Field(
        min_length=1, max_length=3
    )
    default_mode: Literal["api_upload", "folder_watch", "usb_camera"]
    watch: GatewayWatchDefinition | None = None
    camera: dict[str, Any] = Field(default_factory=dict)
    queue: dict[str, Any] = Field(default_factory=dict)
    privacy: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def default_mode_is_enabled(self) -> CollectionDefinition:
        if self.default_mode not in self.input_modes:
            raise ValueError("collection.default_mode must be included in input_modes")
        if "folder_watch" in self.input_modes and self.watch is None:
            raise ValueError("collection.watch is required when folder_watch is enabled")
        return self


class RiskStrategy(DeploymentContract):
    name: str = Field(min_length=1, max_length=128)
    policy: PolicyConfig
    model_output_semantics: str = Field(min_length=1, max_length=500)
    fail_safe_route: Literal["REVIEW_REQUIRED", "BATCH_HOLD_AND_REVIEW"] = "REVIEW_REQUIRED"
    automatic_release_allowed: bool = False
    approval_roles: list[str] = Field(min_length=1, max_length=20)


class WorkflowDefinition(DeploymentContract):
    states: list[str] = Field(min_length=1, max_length=50)
    transitions: list[dict[str, str]] = Field(default_factory=list, max_length=100)
    external_action_approval_required: bool = True
    human_review_required_for: list[str] = Field(default_factory=list, max_length=20)


class PermissionDefinition(DeploymentContract):
    roles: dict[str, list[str]] = Field(min_length=1)
    external_action_approval_roles: list[str] = Field(min_length=1, max_length=20)
    deployment_approval_roles: list[str] = Field(min_length=1, max_length=20)


class RetentionDefinition(DeploymentContract):
    raw_image_days: int = Field(ge=1, le=3650)
    metadata_days: int = Field(ge=1, le=3650)
    local_processing_default: bool = True
    delete_after_upload: bool = False
    legal_hold_supported: bool = True


class LocalizationDefinition(DeploymentContract):
    default_locale: str = Field(min_length=2, max_length=32)
    supported_locales: list[str] = Field(min_length=1, max_length=20)
    timezone: str = Field(pattern=r"^[+-]\d{2}:\d{2}$")
    terminology: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def default_locale_is_supported(self) -> LocalizationDefinition:
        if self.default_locale not in self.supported_locales:
            raise ValueError("localization.default_locale must be supported")
        return self


class IndustryPack(DeploymentContract):
    """Reusable industry defaults with no tenant identity or site secrets."""

    schema_version: Literal["visionqc.industry-pack.v1"] = INDUSTRY_PACK_SCHEMA_VERSION
    pack_key: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    industry: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1000)
    products: list[ProductDefinition] = Field(min_length=1, max_length=50)
    stations: list[StationDefinition] = Field(min_length=1, max_length=50)
    field_mapping: FieldMapping
    field_labels: dict[str, str] = Field(default_factory=dict)
    terminology: dict[str, str] = Field(default_factory=dict)
    collection: CollectionDefinition
    model: ModelDefinition
    policy: PolicyConfig
    risk_strategy: RiskStrategy
    workflow: WorkflowDefinition
    connectors: dict[str, ConnectorDefinition] = Field(min_length=1, max_length=20)
    permissions: PermissionDefinition
    retention: RetentionDefinition
    localization: LocalizationDefinition
    validation: PackValidation
    integrity: PackIntegrity
    migration: MigrationNotes
    defaults: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_catalog(self) -> IndustryPack:
        product_values = [value for item in self.products for value in (item.code, *item.aliases)]
        if len(product_values) != len(set(product_values)):
            raise ValueError("industry pack product codes and aliases must be unique")
        station_codes = [item.code for item in self.stations]
        if len(station_codes) != len(set(station_codes)):
            raise ValueError("industry pack stations must be unique")
        if self.risk_strategy.policy != self.policy:
            raise ValueError("risk_strategy.policy must match policy")
        for name, connector in self.connectors.items():
            if name.lower() != name:
                raise ValueError("industry pack connector keys must be lower-case")
            if not connector.capability:
                raise ValueError(f"connector {name} must declare a capability")
        return self


class TenantOverlay(DeploymentContract):
    """Customer/site-owned values layered on an IndustryPack."""

    schema_version: Literal["visionqc.tenant-overlay.v1"] = TENANT_OVERLAY_SCHEMA_VERSION
    overlay_key: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    industry_pack: PackReference
    tenant: TenantDefinition
    site: dict[str, str] = Field(min_length=1)
    input_mode: Literal["api_upload", "folder_watch", "usb_camera"] = "folder_watch"
    products: list[ProductDefinition] = Field(min_length=1, max_length=50)
    stations: list[StationDefinition] = Field(min_length=1, max_length=50)
    field_mapping: FieldMapping | None = None
    field_labels: dict[str, str] = Field(default_factory=dict)
    terminology: dict[str, str] = Field(default_factory=dict)
    collection: CollectionDefinition | None = None
    model: dict[str, Any] = Field(default_factory=dict)
    policy: PolicyConfig | None = None
    risk_strategy: dict[str, Any] = Field(default_factory=dict)
    workflow: dict[str, Any] = Field(default_factory=dict)
    connectors: dict[str, ConnectorDefinition] = Field(default_factory=dict, max_length=20)
    permissions: PermissionDefinition | None = None
    retention: RetentionDefinition | None = None
    localization: LocalizationDefinition | None = None
    edge_gateway: EdgeGatewayDefinition | None = None
    validation: PackValidation
    integrity: PackIntegrity
    migration: MigrationNotes
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_overlay(self) -> TenantOverlay:
        if not self.site.get("id") or not self.site.get("name"):
            raise ValueError("tenant overlay site must contain id and name")
        if self.edge_gateway and self.edge_gateway.target_tenant_id != self.tenant.id:
            raise ValueError("overlay edge gateway target_tenant_id must match tenant.id")
        return self


class DeploymentManifest(DeploymentContract):
    """The checked-in Deployment Pack contract.

    ``tenant.id`` is checked against the authenticated principal when a pack
    is created or activated.  A client cannot use the manifest to select a
    different tenant.
    """

    schema_version: Literal["visionqc.deployment-pack.v1", "visionqc.deployment-pack.v2"] = (
        "visionqc.deployment-pack.v1"
    )
    pack_key: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    tenant: TenantDefinition
    input_mode: Literal["api_upload", "folder_watch", "usb_camera"]
    products: list[ProductDefinition] = Field(min_length=1, max_length=50)
    stations: list[StationDefinition] = Field(min_length=1, max_length=50)
    field_mapping: FieldMapping
    field_labels: dict[str, str] = Field(default_factory=dict)
    model: ModelDefinition
    policy: PolicyConfig
    connectors: ConnectorSet
    metadata: dict[str, Any] = Field(default_factory=dict)
    edge_gateway: EdgeGatewayDefinition | None = None
    industry_pack: PackReference | None = None
    tenant_overlay: PackReference | None = None
    industry: str | None = Field(default=None, max_length=64)
    terminology: dict[str, str] = Field(default_factory=dict)
    collection: CollectionDefinition | None = None
    risk_strategy: RiskStrategy | None = None
    workflow: WorkflowDefinition | None = None
    permissions: PermissionDefinition | None = None
    retention: RetentionDefinition | None = None
    localization: LocalizationDefinition | None = None
    validation: PackValidation | None = None
    integrity: PackIntegrity | None = None
    migration: MigrationNotes | None = None

    @model_validator(mode="after")
    def validate_catalog(self) -> DeploymentManifest:
        product_codes = [item.code for item in self.products]
        station_codes = [item.code for item in self.stations]
        if len(product_codes) != len(set(product_codes)):
            raise ValueError("products must have unique canonical codes")
        product_values = [value for item in self.products for value in (item.code, *item.aliases)]
        if len(product_values) != len(set(product_values)):
            raise ValueError("product codes and aliases must be globally unique")
        if len(station_codes) != len(set(station_codes)):
            raise ValueError("stations must have unique codes")
        if self.edge_gateway and self.edge_gateway.target_tenant_id != self.tenant.id:
            raise ValueError("edge gateway target_tenant_id must match tenant.id")
        unknown_labels = set(self.field_labels) - set(CANONICAL_FIELDS)
        if unknown_labels:
            raise ValueError(f"field_labels contains unknown fields: {sorted(unknown_labels)}")
        if self.schema_version == RESOLVED_PACK_SCHEMA_VERSION:
            required = {
                "industry_pack": self.industry_pack,
                "tenant_overlay": self.tenant_overlay,
                "collection": self.collection,
                "risk_strategy": self.risk_strategy,
                "workflow": self.workflow,
                "permissions": self.permissions,
                "retention": self.retention,
                "localization": self.localization,
                "validation": self.validation,
                "integrity": self.integrity,
                "migration": self.migration,
            }
            missing = [name for name, value in required.items() if value is None]
            if missing:
                raise ValueError(
                    f"v2 deployment pack is missing required resolved fields: {', '.join(missing)}"
                )
            if self.risk_strategy and self.risk_strategy.policy != self.policy:
                raise ValueError("resolved risk_strategy.policy must match policy")
        return self

    @property
    def active_product(self) -> ProductDefinition:
        return self.products[0]

    def resolve_product(self, value: str) -> ProductDefinition | None:
        return next((product for product in self.products if product.matches(value)), None)

    def resolve_station(self, value: str) -> StationDefinition | None:
        return next(
            (station for station in self.stations if station.code == value or station.code == "*"),
            None,
        )

    def connector(self, name: str) -> ConnectorDefinition:
        value = getattr(self.connectors, name.lower(), None)
        if value is None:
            raise KeyError(f"connector {name!r} is not present in deployment pack")
        return cast(ConnectorDefinition, value)

    def connector_payload(self, name: str, canonical_payload: dict[str, Any]) -> dict[str, Any]:
        """Translate canonical workflow fields to a customer's external schema."""

        binding = self.connector(name)
        payload = {
            external_key: canonical_payload[canonical_key]
            for canonical_key, external_key in binding.payload_mapping.items()
            if canonical_key in canonical_payload
        }
        payload.update(binding.fixed_fields)
        return payload


def default_manifest_directory() -> Path:
    return Path(__file__).resolve().parents[1] / "deployment-packs" / "manifests"


def load_manifest(path: Path) -> DeploymentManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        manifest = DeploymentManifest.model_validate(payload)
        if manifest.schema_version == RESOLVED_PACK_SCHEMA_VERSION:
            _verify_integrity(payload, path)
        return manifest
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid Deployment Pack manifest {path}: {exc}") from exc


def load_manifests(directory: Path | None = None) -> list[DeploymentManifest]:
    root = directory or default_manifest_directory()
    # A customer can point the backend at a generated examples directory where
    # each tenant has its own folder.  The historical manifests directory is
    # flat, so recursive discovery is additive and remains backwards compatible.
    manifests: list[DeploymentManifest] = []
    for path in sorted(root.rglob("*.json")):
        try:
            schema_version = json.loads(path.read_text(encoding="utf-8")).get("schema_version")
        except (OSError, json.JSONDecodeError):
            # Let load_manifest produce the standard path-aware error.
            manifests.append(load_manifest(path))
            continue
        if schema_version in {INDUSTRY_PACK_SCHEMA_VERSION, TENANT_OVERLAY_SCHEMA_VERSION}:
            continue
        manifests.append(load_manifest(path))
    return manifests


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def payload_sha256(payload: dict[str, Any]) -> str:
    """Hash a pack while excluding only its self-reported integrity hash."""

    sanitized = deepcopy(payload)
    integrity = sanitized.get("integrity")
    if isinstance(integrity, dict):
        integrity.pop("manifest_sha256", None)
    return hashlib.sha256(canonical_json(sanitized)).hexdigest()


def _verify_integrity(payload: dict[str, Any], path: Path) -> None:
    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or not integrity.get("manifest_sha256"):
        raise ValueError("v2 deployment pack must declare integrity.manifest_sha256")
    expected = str(integrity["manifest_sha256"])
    actual = payload_sha256(payload)
    if expected != actual:
        raise ValueError(
            f"deployment pack hash mismatch for {path.name}: expected {expected}, computed {actual}"
        )


def verify_payload_integrity(payload: dict[str, Any], *, source: str = "pack") -> str:
    """Validate a new pack/overlay hash and return the computed digest."""

    integrity = payload.get("integrity")
    if not isinstance(integrity, dict) or not integrity.get("manifest_sha256"):
        raise ValueError(f"{source} must declare integrity.manifest_sha256")
    expected = str(integrity["manifest_sha256"])
    actual = payload_sha256(payload)
    if expected != actual:
        raise ValueError(f"{source} hash mismatch: expected {expected}, computed {actual}")
    return actual


def load_industry_pack(path: Path) -> IndustryPack:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pack = IndustryPack.model_validate(payload)
        verify_payload_integrity(payload, source=f"industry pack {path}")
        return pack
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid Industry Pack {path}: {exc}") from exc


def load_tenant_overlay(path: Path) -> TenantOverlay:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        overlay = TenantOverlay.model_validate(payload)
        verify_payload_integrity(payload, source=f"tenant overlay {path}")
        return overlay
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid tenant overlay {path}: {exc}") from exc


def _merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def resolve_pack(industry_pack: IndustryPack, overlay: TenantOverlay) -> DeploymentManifest:
    """Resolve immutable industry defaults and customer/site overlay to v2."""

    if overlay.industry_pack.key != industry_pack.pack_key:
        raise ValueError(
            f"overlay references industry pack {overlay.industry_pack.key!r}, "
            f"not {industry_pack.pack_key!r}"
        )
    if overlay.industry_pack.version != industry_pack.version:
        raise ValueError(
            f"overlay expects industry pack version {overlay.industry_pack.version!r}, "
            f"loaded {industry_pack.version!r}"
        )
    if (
        overlay.industry_pack.sha256 is not None
        and overlay.industry_pack.sha256 != industry_pack.integrity.manifest_sha256
    ):
        raise ValueError("overlay industry_pack.sha256 does not match the loaded Industry Pack")

    collection = overlay.collection or industry_pack.collection
    if overlay.input_mode not in collection.input_modes:
        raise ValueError(
            f"overlay input_mode {overlay.input_mode!r} is not enabled by the "
            "Industry Pack collection"
        )
    policy = overlay.policy or industry_pack.policy
    risk_data = _merge_dict(
        industry_pack.risk_strategy.model_dump(mode="json"), overlay.risk_strategy
    )
    risk_data["policy"] = policy.model_dump(mode="json")
    risk_strategy = RiskStrategy.model_validate(risk_data)
    workflow = WorkflowDefinition.model_validate(
        _merge_dict(industry_pack.workflow.model_dump(mode="json"), overlay.workflow)
    )
    permissions = overlay.permissions or industry_pack.permissions
    retention = overlay.retention or industry_pack.retention
    localization = overlay.localization or industry_pack.localization
    model_data = _merge_dict(industry_pack.model.model_dump(mode="json"), overlay.model)
    model = ModelDefinition.model_validate(model_data)

    connector_data = {
        key: value.model_dump(mode="json") for key, value in industry_pack.connectors.items()
    }
    for key, value in overlay.connectors.items():
        connector_data[key] = _merge_dict(
            connector_data.get(key, {}), value.model_dump(mode="json")
        )
    connector_data = {key.lower(): value for key, value in connector_data.items()}
    connector_set = ConnectorSet.model_validate(connector_data)

    field_mapping = overlay.field_mapping or industry_pack.field_mapping
    field_labels = {**industry_pack.field_labels, **overlay.field_labels}
    terminology = {**industry_pack.terminology, **overlay.terminology}
    metadata = {
        **industry_pack.metadata,
        **overlay.metadata,
        "industry_pack_key": industry_pack.pack_key,
        "industry_pack_version": industry_pack.version,
        "tenant_overlay_key": overlay.overlay_key,
        "tenant_overlay_version": overlay.version,
        "site_id": overlay.site["id"],
        "site_name": overlay.site["name"],
    }
    edge_gateway = overlay.edge_gateway
    if edge_gateway is None:
        raise ValueError("tenant overlay must declare edge_gateway for a runnable resolved pack")

    manifest = DeploymentManifest(
        schema_version=RESOLVED_PACK_SCHEMA_VERSION,
        pack_key=f"{overlay.tenant.id}/{industry_pack.pack_key}",
        version=overlay.version,
        display_name=f"{industry_pack.display_name} · {overlay.site['name']}",
        tenant=overlay.tenant,
        input_mode=overlay.input_mode,
        products=overlay.products or industry_pack.products,
        stations=overlay.stations or industry_pack.stations,
        field_mapping=field_mapping,
        field_labels=field_labels,
        model=model,
        policy=policy,
        connectors=connector_set,
        metadata=metadata,
        edge_gateway=edge_gateway,
        industry_pack=PackReference(
            key=industry_pack.pack_key,
            version=industry_pack.version,
            sha256=industry_pack.integrity.manifest_sha256,
        ),
        tenant_overlay=PackReference(
            key=overlay.overlay_key,
            version=overlay.version,
            sha256=overlay.integrity.manifest_sha256,
        ),
        industry=industry_pack.industry,
        terminology=terminology,
        collection=collection,
        risk_strategy=risk_strategy,
        workflow=workflow,
        permissions=permissions,
        retention=retention,
        localization=localization,
        validation=PackValidation(
            status="resolved",
            validator="app.deployment.resolve_pack",
            checks=[
                "industry_pack_integrity",
                "tenant_overlay_integrity",
                "tenant_gateway_binding",
                "field_mapping",
                "policy_thresholds",
                "connector_contracts",
            ],
        ),
        integrity=PackIntegrity(manifest_sha256="0" * 64),
        migration=MigrationNotes(
            from_schema_versions=[
                INDUSTRY_PACK_SCHEMA_VERSION,
                TENANT_OVERLAY_SCHEMA_VERSION,
                "visionqc.deployment-pack.v1",
            ],
            strategy="resolver",
            notes=(
                "Resolve the immutable industry pack and tenant/site overlay "
                "before runtime activation."
            ),
        ),
    )
    payload = manifest.model_dump(mode="json")
    manifest.integrity = PackIntegrity(manifest_sha256=payload_sha256(payload))
    return manifest


def load_and_resolve_pack(industry_path: Path, overlay_path: Path) -> DeploymentManifest:
    return resolve_pack(load_industry_pack(industry_path), load_tenant_overlay(overlay_path))


def legacy_manifest(
    *,
    tenant_id: str,
    tenant_name: str,
    version: str,
    model: dict[str, Any],
    policy: PolicyConfig,
    connectors: dict[str, Any],
) -> DeploymentManifest:
    """Wrap the pre-manifest API shape so old integrations remain readable."""

    model_data = {
        "id": model.get("model_id", "legacy-model"),
        "version": model.get("model_version", "legacy"),
        "feature_bank_version": model.get("feature_bank_version", "legacy-feature-bank"),
        "adapter": model.get("adapter", "stub"),
        "runtime": model.get("runtime", "visionqc"),
        "device": model.get("runtime_device", "cpu"),
        "package_uri": model.get("package_uri", "not-configured"),
        "package_sha256": model.get("package_sha256"),
        "score_semantics": (
            "normalized anomaly evidence; semantic defect requires human confirmation"
        ),
        "limitations": ["legacy deployment record; replace with a v1 manifest"],
    }
    connector_data = {
        key.lower(): {
            "display_name": str(value) if isinstance(value, str) else key,
            "driver": "legacy",
            "contract_version": "legacy",
            "endpoint": "not-configured",
            "payload_mapping": {},
            "fixed_fields": {},
            "operations": ["HOLD_BATCH", "CREATE_TICKET"],
        }
        for key, value in {
            "mes": connectors.get("mes", "MES"),
            "qms": connectors.get("qms", "QMS"),
        }.items()
    }
    return DeploymentManifest(
        pack_key=f"{tenant_id}/legacy",
        version=version,
        display_name=f"{tenant_name} legacy deployment",
        tenant={"id": tenant_id, "name": tenant_name},
        input_mode="api_upload",
        products=[
            {
                "code": "*",
                "display_name": "Configured product",
                "revision": "UNSPECIFIED",
                "aliases": [],
            }
        ],
        stations=[
            {
                "code": "*",
                "display_name": "Configured station",
                "description": "Legacy deployment station",
                "camera_profile": "legacy",
            }
        ],
        field_mapping={
            "product_code": "product_code",
            "product_revision": "product_revision",
            "batch_no": "batch_no",
            "station_code": "station_code",
            "captured_at": "captured_at",
            "source": "source",
        },
        field_labels={
            "product_code": "Product code",
            "product_revision": "Product revision",
            "batch_no": "Batch",
            "station_code": "Station",
            "captured_at": "Captured at",
            "source": "Source",
        },
        model=model_data,
        policy=policy,
        connectors=connector_data,
    )
