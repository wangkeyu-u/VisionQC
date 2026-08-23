"""Versioned, tenant-scoped Deployment Pack contracts.

The manifest is the hand-off between an FDE and the VisionQC workflow.  It
contains the customer-facing product/station vocabulary, the input field
mapping, the model evidence metadata, the policy and the external contracts.
The workflow only consumes the canonical fields produced by this module; it
does not branch on a tenant or product name.
"""

from __future__ import annotations

import json
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


class ConnectorSet(DeploymentContract):
    mes: ConnectorDefinition
    qms: ConnectorDefinition
    # Optional, explicitly simulated digital-quality contract.  Existing
    # Factory A/B packs remain valid and continue to use only MES/QMS.
    dxq_mock: ConnectorDefinition | None = None


class DeploymentManifest(DeploymentContract):
    """The checked-in Deployment Pack contract.

    ``tenant.id`` is checked against the authenticated principal when a pack
    is created or activated.  A client cannot use the manifest to select a
    different tenant.
    """

    schema_version: Literal["visionqc.deployment-pack.v1"] = "visionqc.deployment-pack.v1"
    pack_key: str = Field(min_length=1, max_length=128)
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=200)
    tenant: TenantDefinition
    input_mode: Literal["api_upload", "folder_watch"]
    products: list[ProductDefinition] = Field(min_length=1, max_length=50)
    stations: list[StationDefinition] = Field(min_length=1, max_length=50)
    field_mapping: FieldMapping
    field_labels: dict[str, str] = Field(default_factory=dict)
    model: ModelDefinition
    policy: PolicyConfig
    connectors: ConnectorSet
    metadata: dict[str, Any] = Field(default_factory=dict)
    edge_gateway: EdgeGatewayDefinition | None = None

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
        return DeploymentManifest.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid Deployment Pack manifest {path}: {exc}") from exc


def load_manifests(directory: Path | None = None) -> list[DeploymentManifest]:
    root = directory or default_manifest_directory()
    return [load_manifest(path) for path in sorted(root.glob("*.json"))]


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
