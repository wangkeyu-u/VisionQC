"""Generic, tenant-scoped VisionQC platform configuration.

This module is deliberately independent from any customer, industry, or
connector implementation.  A deployment may provide four layers of
configuration, in this order:

``platform_defaults -> industry_pack -> tenant_override -> runtime_site_override``

The merge is deterministic and produces both a canonical configuration hash
and field-level provenance.  Secrets are never accepted as configuration
values; integrations may only carry a reference to a secret managed by an
external secret store.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping
from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.policy import ThresholdRule

PLATFORM_CONFIGURATION_SCHEMA_VERSION = "visionqc.platform-config.v1"
PlatformSchemaVersion = Literal["visionqc.platform-config.v1"]
CONFIGURATION_LAYER_ORDER = (
    "platform_defaults",
    "industry_pack",
    "tenant_override",
    "runtime_site_override",
)

_NAMESPACE_PATTERN = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
_METADATA_KEY_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_LANGUAGE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z][a-z]{2})?(?:-[A-Z]{2})?$")
_SECRET_REFERENCE_PATTERN = re.compile(
    r"^(?:secret|vault|env|aws-secretsmanager|gcp-secret)://[^\s]+$"
)
_SECRET_MARKERS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "client_secret",
    "access_key",
    "credential",
)


class ConfigurationError(ValueError):
    """Raised when a configuration layer cannot be safely materialised."""

    def __init__(self, message: str, *, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or [message]


class PrivacyMode(StrEnum):
    TENANT_ISOLATED = "tenant_isolated"
    LOCAL_PROCESSING_ONLY = "local_processing_only"
    STANDARD = "standard"


class CaptureChannel(StrEnum):
    API_UPLOAD = "api_upload"
    FOLDER_WATCH = "folder_watch"
    USB_CAMERA = "usb_camera"
    RTSP_CAMERA = "rtsp_camera"
    EDGE_GATEWAY = "edge_gateway"


class SecretReference(BaseModel):
    """A pointer to a secret; the referenced value is never part of a config."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    secret_ref: str = Field(min_length=1, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def accept_uri_shorthand(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"secret_ref": value}
        if isinstance(value, Mapping) and "secret_ref" not in value and "secret_reference" in value:
            value = dict(value)
            value["secret_ref"] = value.pop("secret_reference")
        return value

    @model_validator(mode="after")
    def validate_reference(self) -> SecretReference:
        if not _SECRET_REFERENCE_PATTERN.match(self.secret_ref):
            raise ValueError(
                "secret_ref must use an external reference URI such as secret://vault/key"
            )
        return self


class WorkflowConfiguration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_release_enabled: bool = True
    manual_review_enabled: bool = True
    batch_hold_enabled: bool = True
    fail_safe_on_missing_dependency: bool = True


class WorkflowConfigurationOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    auto_release_enabled: bool | None = None
    manual_review_enabled: bool | None = None
    batch_hold_enabled: bool | None = None
    fail_safe_on_missing_dependency: bool | None = None


class SafetyGateConfiguration(BaseModel):
    """Safety invariants that tenant configuration is not allowed to relax."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # These are Literal values on purpose.  A config author cannot turn a
    # safety gate on or off by selecting a different tenant or industry pack.
    abnormal_auto_release: Literal[False] = False
    model_unavailable_auto_release: Literal[False] = False
    out_of_distribution_auto_release: Literal[False] = False
    image_quality_failure_auto_release: Literal[False] = False
    human_confirmation_for_external_action: Literal[True] = True


class SafetyGateConfigurationOverride(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    abnormal_auto_release: Literal[False] | None = None
    model_unavailable_auto_release: Literal[False] | None = None
    out_of_distribution_auto_release: Literal[False] | None = None
    image_quality_failure_auto_release: Literal[False] | None = None
    human_confirmation_for_external_action: Literal[True] | None = None


class ApprovalRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_requires_approval: bool = True
    hold_release_requires_approval: bool = True
    allowed_release_roles: list[str] = Field(
        default_factory=lambda: ["quality_manager", "admin"]
    )
    segregation_of_duties: bool = True

    @model_validator(mode="after")
    def validate_roles(self) -> ApprovalRules:
        if not self.allowed_release_roles:
            raise ValueError("allowed_release_roles must contain at least one role")
        if len(self.allowed_release_roles) != len(set(self.allowed_release_roles)):
            raise ValueError("allowed_release_roles must be unique")
        return self


class ApprovalRulesOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    release_requires_approval: bool | None = None
    hold_release_requires_approval: bool | None = None
    allowed_release_roles: list[str] | None = None
    segregation_of_duties: bool | None = None


class ModelReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    feature_bank_version: str | None = Field(default=None, max_length=128)
    qualification_ref: str | None = Field(default=None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def accept_version_alias(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"model_id": value, "model_version": "unversioned"}
        if isinstance(value, Mapping) and "model_version" not in value and "version" in value:
            value = dict(value)
            value["model_version"] = value.pop("version")
        if isinstance(value, Mapping) and "model_id" not in value:
            value = dict(value)
            for alias in ("id", "ref"):
                if alias in value:
                    value["model_id"] = value.pop(alias)
                    break
        return value


class ModelReferenceOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str | None = Field(default=None, max_length=128)
    model_version: str | None = Field(default=None, max_length=128)
    feature_bank_version: str | None = Field(default=None, max_length=128)
    qualification_ref: str | None = Field(default=None, max_length=500)

    @model_validator(mode="before")
    @classmethod
    def accept_version_alias(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"model_id": value}
        if isinstance(value, Mapping) and "model_version" not in value and "version" in value:
            value = dict(value)
            value["model_version"] = value.pop("version")
        if isinstance(value, Mapping) and "model_id" not in value:
            value = dict(value)
            for alias in ("id", "ref"):
                if alias in value:
                    value["model_id"] = value.pop(alias)
                    break
        return value


class ThresholdReference(BaseModel):
    """A calibrated threshold identity with optional inline calibration values.

    Production deployments can provide only ``ref`` and ``version`` and
    resolve the actual values from their model registry.  Inline values are
    supported for an auditable deployment manifest and for offline pilots.
    """

    model_config = ConfigDict(extra="forbid")

    ref: str = Field(default="thresholds://unconfigured", min_length=1, max_length=500)
    version: str = Field(default="unconfigured", min_length=1, max_length=128)
    review_threshold: float | None = Field(default=None, ge=0, le=1)
    hold_threshold: float | None = Field(default=None, ge=0, le=1)
    overrides: list[ThresholdRule] = Field(default_factory=list, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def accept_reference_aliases(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"ref": value}
        if isinstance(value, Mapping):
            value = dict(value)
            if "ref" not in value:
                for alias in ("threshold_ref", "policy_ref", "calibration_ref", "id"):
                    if alias in value:
                        value["ref"] = value.pop(alias)
                        break
            if "version" not in value and "policy_version" in value:
                value["version"] = value.pop("policy_version")
        return value

    @model_validator(mode="after")
    def validate_thresholds(self) -> ThresholdReference:
        if (self.review_threshold is None) != (self.hold_threshold is None):
            raise ValueError("review_threshold and hold_threshold must be provided together")
        if (
            self.review_threshold is not None
            and self.hold_threshold is not None
            and self.review_threshold >= self.hold_threshold
        ):
            raise ValueError("review_threshold must be less than hold_threshold")
        return self


class ThresholdReferenceOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ref: str | None = Field(default=None, max_length=500)
    version: str | None = Field(default=None, max_length=128)
    review_threshold: float | None = Field(default=None, ge=0, le=1)
    hold_threshold: float | None = Field(default=None, ge=0, le=1)
    overrides: list[ThresholdRule] | None = Field(default=None, max_length=100)

    @model_validator(mode="before")
    @classmethod
    def accept_reference_aliases(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"ref": value}
        if isinstance(value, Mapping):
            value = dict(value)
            if "ref" not in value:
                for alias in ("threshold_ref", "policy_ref", "calibration_ref", "id"):
                    if alias in value:
                        value["ref"] = value.pop(alias)
                        break
            if "version" not in value and "policy_version" in value:
                value["version"] = value.pop("policy_version")
        return value


class ConnectorReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: str = Field(min_length=1, max_length=128)
    contract_version: str = Field(default="unversioned", min_length=1, max_length=128)
    secret_ref: SecretReference | None = None

    @model_validator(mode="before")
    @classmethod
    def accept_reference_aliases(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"connector_id": value}
        if isinstance(value, Mapping):
            value = dict(value)
            if "connector_id" not in value:
                for alias in ("id", "ref", "driver"):
                    if alias in value:
                        value["connector_id"] = value.pop(alias)
                        break
            if "contract_version" not in value and "version" in value:
                value["contract_version"] = value.pop("version")
            if "secret_ref" not in value and "secret_reference" in value:
                value["secret_ref"] = value.pop("secret_reference")
        return value

    @model_validator(mode="after")
    def reject_embedded_credentials(self) -> ConnectorReference:
        # Connector references intentionally have no endpoint field.  Keep a
        # defensive check for future aliases so a credential-bearing URL is
        # never accidentally persisted as a reference.
        if "://" in self.connector_id:
            parsed = urlsplit(self.connector_id)
            if parsed.username or parsed.password:
                raise ValueError("connector references must not contain embedded credentials")
        return self


class ExtensionMetadata(BaseModel):
    """Bounded namespaced extension metadata.

    Values remain JSON data, but the namespace is explicit and the envelope is
    bounded.  The core never promotes extension keys to required columns.
    """

    model_config = ConfigDict(extra="forbid")

    values: dict[str, dict[str, Any]] = Field(default_factory=dict, max_length=50)

    @model_validator(mode="after")
    def validate_namespaces(self) -> ExtensionMetadata:
        for namespace, payload in self.values.items():
            if not _NAMESPACE_PATTERN.match(namespace):
                raise ValueError(
                    "extension namespaces must be lowercase names such as automotive-paint"
                )
            _assert_safe_json(payload, path=f"extensions.{namespace}")
        encoded = json.dumps(self.values, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 16_384:
            raise ValueError("extension metadata is too large")
        return self


class ExtensionMetadataOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")

    values: dict[str, dict[str, Any]] | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def validate_namespaces(self) -> ExtensionMetadataOverride:
        if self.values is not None:
            ExtensionMetadata(values=self.values)
        return self


class AutomotivePaintExtension(BaseModel):
    """Optional automotive-paint vocabulary; none of these fields is generic."""

    model_config = ConfigDict(extra="forbid")

    body_id: str | None = Field(default=None, max_length=128)
    workpiece_id: str | None = Field(default=None, max_length=128)
    paint_shop: str | None = Field(default=None, max_length=128)
    booth_station: str | None = Field(default=None, max_length=128)
    line: str | None = Field(default=None, max_length=128)
    model_variant: str | None = Field(default=None, max_length=128)
    color_code: str | None = Field(default=None, max_length=128)
    paint_recipe: str | None = Field(default=None, max_length=128)
    shift: str | None = Field(default=None, max_length=64)


class PlatformConfiguration(BaseModel):
    """Canonical effective configuration consumed by the generic platform."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visionqc.platform-config.v1"] = (
        "visionqc.platform-config.v1"
    )
    version: str = Field(default="1", min_length=1, max_length=128)
    tenant_id: str = Field(min_length=1, max_length=64)
    display_name: str = Field(default="VisionQC Platform", min_length=1, max_length=200)
    industry: str = Field(default="general-manufacturing", min_length=1, max_length=128)
    timezone: str = Field(default="UTC", min_length=1, max_length=128)
    language: str = Field(default="en", min_length=2, max_length=16)
    data_retention_days: int = Field(default=365, ge=1, le=36_500)
    privacy_mode: PrivacyMode = PrivacyMode.TENANT_ISOLATED
    capture_channels: list[str] = Field(default_factory=lambda: [CaptureChannel.API_UPLOAD.value])
    workflow: WorkflowConfiguration = Field(default_factory=WorkflowConfiguration)
    risk_gates: SafetyGateConfiguration = Field(default_factory=SafetyGateConfiguration)
    approval_rules: ApprovalRules = Field(default_factory=ApprovalRules)
    model_ref: ModelReference = Field(
        default_factory=lambda: ModelReference(
            model_id="unconfigured", model_version="unconfigured"
        )
    )
    threshold_ref: ThresholdReference = Field(default_factory=ThresholdReference)
    connector_refs: dict[str, ConnectorReference] = Field(default_factory=dict, max_length=50)
    extensions: ExtensionMetadata = Field(default_factory=ExtensionMetadata)

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        aliases = {
            "config_version": "version",
            "model_reference": "model_ref",
            "model": "model_ref",
            "threshold_reference": "threshold_ref",
            "connector_references": "connector_refs",
            "approval": "approval_rules",
            "capture": "capture_channels",
        }
        for source, target in aliases.items():
            if source in data and target not in data:
                data[target] = data.pop(source)
        localization = data.pop("localization", None)
        if isinstance(localization, Mapping):
            for key in ("timezone", "language"):
                if key not in data and key in localization:
                    data[key] = localization[key]
        retention = data.pop("retention", None)
        if isinstance(retention, Mapping) and "data_retention_days" not in data:
            data["data_retention_days"] = retention.get(
                "data_retention_days", retention.get("evidence_days")
            )
        privacy = data.pop("privacy", None)
        if "privacy_mode" not in data:
            if isinstance(privacy, Mapping):
                data["privacy_mode"] = privacy.get("privacy_mode", privacy.get("mode"))
            elif isinstance(privacy, str):
                data["privacy_mode"] = privacy
        for source, target in (("connectors", "connector_refs"), ("thresholds", "threshold_ref")):
            if source in data and target not in data:
                data[target] = data.pop(source)
        if isinstance(data.get("capture_channels"), Mapping):
            capture = data.pop("capture_channels")
            data["capture_channels"] = capture.get("channels", [])
        if isinstance(data.get("extensions"), Mapping) and "values" not in data["extensions"]:
            data["extensions"] = {"values": data["extensions"]}
        return data

    @model_validator(mode="after")
    def validate_platform_values(self) -> PlatformConfiguration:
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"timezone is not a known IANA timezone: {self.timezone}") from exc
        if not _LANGUAGE_PATTERN.match(self.language):
            raise ValueError("language must be a BCP-47-like language tag")
        if not self.capture_channels:
            raise ValueError("capture_channels must contain at least one channel")
        if len(self.capture_channels) != len(set(self.capture_channels)):
            raise ValueError("capture_channels must be unique")
        if any(not item.strip() or len(item) > 64 for item in self.capture_channels):
            raise ValueError("capture_channels contain an invalid channel name")
        for connector_name in self.connector_refs:
            if not _NAMESPACE_PATTERN.match(connector_name.lower().replace("_", "-")):
                raise ValueError(f"invalid connector reference name: {connector_name}")
        # Instantiating the safety model enforces all hard gates even when a
        # caller built this object from a dictionary assembled elsewhere.
        if self.risk_gates.abnormal_auto_release is not False:
            raise ValueError("abnormal_auto_release is a non-configurable hard safety gate")
        return self

    @property
    def config_version(self) -> str:
        return self.version

    @property
    def automotive_paint(self) -> AutomotivePaintExtension | None:
        payload = self.extensions.values.get("automotive-paint")
        return AutomotivePaintExtension.model_validate(payload) if payload is not None else None


class ConfigurationOverlay(BaseModel):
    """One partial layer.  Unknown top-level keys are rejected."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visionqc.platform-config.v1"] | None = "visionqc.platform-config.v1"
    version: str | None = Field(default=None, min_length=1, max_length=128)
    tenant_id: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, min_length=1, max_length=128)
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    data_retention_days: int | None = Field(default=None, ge=1, le=36_500)
    privacy_mode: PrivacyMode | None = None
    capture_channels: list[str] | None = Field(default=None, max_length=20)
    workflow: WorkflowConfigurationOverride | None = None
    risk_gates: SafetyGateConfigurationOverride | None = None
    approval_rules: ApprovalRulesOverride | None = None
    model_ref: ModelReferenceOverride | None = None
    threshold_ref: ThresholdReferenceOverride | None = None
    connector_refs: dict[str, ConnectorReference] | None = Field(default=None, max_length=50)
    extensions: ExtensionMetadataOverride | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_aliases(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        data = dict(value)
        aliases = {
            "config_version": "version",
            "model_reference": "model_ref",
            "model": "model_ref",
            "threshold_reference": "threshold_ref",
            "connector_references": "connector_refs",
            "approval": "approval_rules",
            "capture": "capture_channels",
        }
        for source, target in aliases.items():
            if source in data and target not in data:
                data[target] = data.pop(source)
        localization = data.pop("localization", None)
        if isinstance(localization, Mapping):
            for key in ("timezone", "language"):
                if key not in data and key in localization:
                    data[key] = localization[key]
        retention = data.pop("retention", None)
        if isinstance(retention, Mapping) and "data_retention_days" not in data:
            data["data_retention_days"] = retention.get(
                "data_retention_days", retention.get("evidence_days")
            )
        privacy = data.pop("privacy", None)
        if "privacy_mode" not in data:
            if isinstance(privacy, Mapping):
                data["privacy_mode"] = privacy.get("privacy_mode", privacy.get("mode"))
            elif isinstance(privacy, str):
                data["privacy_mode"] = privacy
        for source, target in (("connectors", "connector_refs"), ("thresholds", "threshold_ref")):
            if source in data and target not in data:
                data[target] = data.pop(source)
        capture = data.get("capture_channels")
        if isinstance(capture, Mapping):
            data["capture_channels"] = capture.get("channels", [])
        extensions = data.get("extensions")
        if isinstance(extensions, Mapping) and "values" not in extensions:
            data["extensions"] = {"values": extensions}
        if "risk_gates" in data and data["risk_gates"] is None:
            data.pop("risk_gates")
        return data

    @model_validator(mode="after")
    def validate_layer(self) -> ConfigurationOverlay:
        if self.schema_version not in (None, PLATFORM_CONFIGURATION_SCHEMA_VERSION):
            raise ValueError("configuration layer schema_version is not supported")
        if self.capture_channels is not None:
            if not self.capture_channels:
                raise ValueError("capture_channels cannot be empty in an override")
            if len(self.capture_channels) != len(set(self.capture_channels)):
                raise ValueError("capture_channels must be unique")
        if self.risk_gates is not None:
            # Pydantic Literal fields reject true values here.  This explicit
            # check keeps the error meaningful for alternate bool-like input.
            if self.risk_gates.abnormal_auto_release is not False and (
                self.risk_gates.abnormal_auto_release is not None
            ):
                raise ValueError("abnormal_auto_release cannot be enabled")
        if self.tenant_id is not None and not self.tenant_id.strip():
            raise ValueError("tenant_id cannot be blank")
        return self


class ConfigurationLayers(BaseModel):
    """The explicit four-layer input accepted by validation and deployment APIs."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["visionqc.platform-config.v1"] = "visionqc.platform-config.v1"
    platform_defaults: ConfigurationOverlay = Field(default_factory=ConfigurationOverlay)
    industry_pack: ConfigurationOverlay = Field(default_factory=ConfigurationOverlay)
    tenant_override: ConfigurationOverlay = Field(default_factory=ConfigurationOverlay)
    runtime_site_override: ConfigurationOverlay = Field(default_factory=ConfigurationOverlay)


class ConfigurationAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    created_by: str = Field(min_length=1, max_length=128)
    parent_version: str | None = Field(default=None, max_length=128)
    source: str = Field(default="configuration-api", min_length=1, max_length=128)


class EffectiveConfiguration(BaseModel):
    """Materialised configuration plus provenance and rollback metadata."""

    model_config = ConfigDict(extra="forbid")

    schema_version: PlatformSchemaVersion = "visionqc.platform-config.v1"
    tenant_id: str
    version: str
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    effective_config: PlatformConfiguration
    sources: dict[str, str]
    validation_status: Literal["VALID", "INVALID"] = "VALID"
    validation_errors: list[str] = Field(default_factory=list)
    audit: ConfigurationAudit
    rollback_versions: list[str] = Field(default_factory=list)

    @property
    def configuration(self) -> PlatformConfiguration:
        return self.effective_config

    @property
    def config_version(self) -> str:
        return self.version

    @property
    def source_layers(self) -> dict[str, str]:
        return self.sources


def _assert_safe_json(value: Any, *, path: str = "config") -> None:
    """Reject embedded secret values and non-JSON values before persistence."""

    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"secret_ref", "secret_reference"}:
                reference = item
                if isinstance(item, Mapping):
                    reference = item.get("secret_ref", item.get("secret_reference"))
                if reference is not None and (
                    not isinstance(reference, str) or not _SECRET_REFERENCE_PATTERN.match(reference)
                ):
                    raise ConfigurationError(
                        f"secret references must use an external URI at {path}.{key}"
                    )
                continue
            if any(marker in key_text for marker in _SECRET_MARKERS) and key_text not in {
                "secret_ref",
                "secret_reference",
            }:
                raise ConfigurationError(
                    f"embedded secret-like value is not allowed at {path}.{key}; use secret_ref"
                )
            _assert_safe_json(item, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _assert_safe_json(item, path=f"{path}[{index}]")
        return
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigurationError(f"configuration contains a non-finite number at {path}")
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    raise ConfigurationError(f"configuration contains a non-JSON value at {path}")


def assert_no_embedded_secrets(value: Any) -> None:
    """Validate a manifest/config payload before it is stored or returned."""

    _assert_safe_json(value)


def validate_controlled_metadata(value: Any) -> dict[str, Any]:
    """Validate an inspection extension envelope without promoting its keys.

    The legacy flat form remains accepted for old clients, while the
    namespaced ``extensions`` form is the preferred contract for industry
    packs.  Both forms are bounded JSON and reject secret-like values.
    """

    if not isinstance(value, Mapping):
        raise ConfigurationError("extension metadata must be a JSON object")
    _assert_safe_json(value, path="metadata")
    for key in value:
        if not _METADATA_KEY_PATTERN.match(str(key)):
            raise ConfigurationError(f"invalid metadata key: {key}")
    extensions = value.get("extensions")
    if extensions is not None:
        if not isinstance(extensions, Mapping):
            raise ConfigurationError("metadata.extensions must be an object")
        ExtensionMetadata(values=dict(extensions))
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > 16_384:
        raise ConfigurationError("extension metadata is too large")
    return dict(value)


def redact_configuration(value: Any) -> Any:
    """Return a safe response representation without resolving secret refs."""

    if isinstance(value, BaseModel):
        return redact_configuration(value.model_dump(mode="json"))
    if isinstance(value, Mapping):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"secret_ref", "secret_reference"}:
                # A reference is safe metadata, while its target value is not.
                if isinstance(item, Mapping):
                    redacted[str(key)] = {
                        nested_key: str(nested_value)
                        for nested_key, nested_value in item.items()
                        if str(nested_key).lower() in {"secret_ref", "secret_reference"}
                    }
                else:
                    redacted[str(key)] = None if item is None else str(item)
            elif any(marker in key_text for marker in _SECRET_MARKERS):
                redacted[str(key)] = "[REDACTED]"
            else:
                redacted[str(key)] = redact_configuration(item)
        return redacted
    if isinstance(value, list):
        return [redact_configuration(item) for item in value]
    return value


def _canonical_hash(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )
    return hashlib.sha256(encoded).hexdigest()


def _merge_dicts(
    current: dict[str, Any],
    incoming: Mapping[str, Any],
    *,
    source: str,
    sources: dict[str, str],
    prefix: str = "",
) -> None:
    for key, value in incoming.items():
        if key in {"schema_version"}:
            continue
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(value, Mapping) and isinstance(current.get(key), Mapping):
            _merge_dicts(
                current[key],
                value,
                source=source,
                sources=sources,
                prefix=path,
            )
        else:
            current[key] = deepcopy(value)
            sources[path] = source
        if isinstance(value, Mapping):
            for nested_key in _leaf_paths(value, prefix=path):
                sources[nested_key] = source


def _leaf_paths(value: Mapping[str, Any], *, prefix: str) -> list[str]:
    paths: list[str] = []
    for key, item in value.items():
        path = f"{prefix}.{key}" if prefix else str(key)
        if isinstance(item, Mapping):
            paths.extend(_leaf_paths(item, prefix=path))
        else:
            paths.append(path)
    return paths


def default_platform_configuration(*, tenant_id: str) -> PlatformConfiguration:
    """Return neutral platform defaults with no customer assumptions."""

    return PlatformConfiguration(tenant_id=tenant_id)


def _as_overlay(value: ConfigurationOverlay | Mapping[str, Any] | None) -> ConfigurationOverlay:
    if value is None:
        return ConfigurationOverlay()
    if isinstance(value, ConfigurationOverlay):
        return value
    try:
        _assert_safe_json(value)
        return ConfigurationOverlay.model_validate(value)
    except ConfigurationError:
        raise
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


def merge_configuration_layers(
    platform_defaults: ConfigurationOverlay | Mapping[str, Any] | None = None,
    industry_pack: ConfigurationOverlay | Mapping[str, Any] | None = None,
    tenant_override: ConfigurationOverlay | Mapping[str, Any] | None = None,
    runtime_site_override: ConfigurationOverlay | Mapping[str, Any] | None = None,
    *,
    tenant_id: str,
    version: str | None = None,
    created_by: str = "system:configuration",
    parent_version: str | None = None,
    source: str = "configuration-api",
    rollback_versions: list[str] | None = None,
) -> EffectiveConfiguration:
    """Merge four layers and return a validated, hash-addressed result."""

    if not tenant_id or not tenant_id.strip():
        raise ConfigurationError("tenant_id is required for configuration resolution")
    values = {
        "platform_defaults": _as_overlay(platform_defaults),
        "industry_pack": _as_overlay(industry_pack),
        "tenant_override": _as_overlay(tenant_override),
        "runtime_site_override": _as_overlay(runtime_site_override),
    }
    current = default_platform_configuration(tenant_id=tenant_id).model_dump(mode="json")
    sources = {path: "platform_defaults" for path in _leaf_paths(current, prefix="") if path}
    # The neutral defaults are conceptually the platform-default layer.  An
    # explicit platform_defaults object still wins at the first merge step.
    for layer_name in CONFIGURATION_LAYER_ORDER:
        overlay = values[layer_name]
        if overlay.tenant_id is not None and overlay.tenant_id != tenant_id:
            raise ConfigurationError(
                f"{layer_name}.tenant_id does not match the authenticated tenant"
            )
        incoming = overlay.model_dump(mode="json", exclude_none=True)
        _merge_dicts(current, incoming, source=layer_name, sources=sources)
    current["tenant_id"] = tenant_id
    if version is not None:
        current["version"] = version
        sources["version"] = "runtime_site_override"
    try:
        effective = PlatformConfiguration.model_validate(current)
    except ValueError as exc:
        raise ConfigurationError(
            "effective configuration failed strict validation", errors=[str(exc)]
        ) from exc
    payload = effective.model_dump(mode="json")
    config_hash = _canonical_hash(payload)
    audit = ConfigurationAudit(
        created_at=datetime.now(UTC),
        created_by=created_by,
        parent_version=parent_version,
        source=source,
    )
    return EffectiveConfiguration(
        tenant_id=tenant_id,
        version=effective.version,
        config_hash=config_hash,
        effective_config=effective,
        sources=sources,
        validation_status="VALID",
        audit=audit,
        rollback_versions=list(rollback_versions or []),
    )


def validate_configuration_layers(
    layers: ConfigurationLayers | Mapping[str, Any], *, tenant_id: str
) -> EffectiveConfiguration:
    """Validate explicit layers; useful for preflight APIs and integrations."""

    try:
        parsed = (
            layers
            if isinstance(layers, ConfigurationLayers)
            else ConfigurationLayers.model_validate(layers)
        )
        return merge_configuration_layers(
            parsed.platform_defaults,
            parsed.industry_pack,
            parsed.tenant_override,
            parsed.runtime_site_override,
            tenant_id=tenant_id,
        )
    except ConfigurationError:
        raise
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


def layers_from_effective_configuration(config: PlatformConfiguration) -> ConfigurationLayers:
    """Represent a legacy/effective config as an explicit tenant layer."""

    return ConfigurationLayers(
        tenant_override=ConfigurationOverlay.model_validate(
            config.model_dump(mode="json", exclude={"schema_version"})
        )
    )


def layers_from_legacy_manifest(manifest: Any) -> ConfigurationLayers:
    """Adapt a v1 deployment manifest without making it the platform model.

    This adapter is the compatibility path for checked-in packs and old API
    clients.  The resulting object is still a normal four-layer config and is
    safe to replace with explicit layers on the next deployment revision.
    """

    metadata = dict(getattr(manifest, "metadata", {}) or {})
    industry = str(
        metadata.get("industry")
        or metadata.get("customer_segment")
        or "general-manufacturing"
    )
    # Keep the industry vocabulary stable without carrying a customer name
    # into the generic core.  Existing pilot packs use the longer suffix.
    if industry == "automotive-paint-shop":
        industry = "automotive-paint"
    privacy_mode = metadata.get("privacy_mode") or metadata.get("privacy_default")
    if privacy_mode not in {item.value for item in PrivacyMode}:
        privacy_mode = PrivacyMode.TENANT_ISOLATED.value
    retention = metadata.get("data_retention_days") or metadata.get("evidence_retention_days")
    retention_value = int(retention) if retention is not None else 365
    connectors: dict[str, ConnectorReference] = {}
    connector_set = getattr(manifest, "connectors", None)
    if connector_set is not None:
        for name in ("mes", "qms", "dxq_mock"):
            definition = getattr(connector_set, name, None)
            if definition is None:
                continue
            connectors[name] = ConnectorReference(
                connector_id=str(definition.driver),
                contract_version=str(definition.contract_version),
            )
    model = getattr(manifest, "model", None)
    policy = getattr(manifest, "policy", None)
    if model is None or policy is None:
        raise ConfigurationError("legacy manifest must contain model and policy definitions")
    extensions = metadata.get("extensions", {})
    if not isinstance(extensions, Mapping):
        extensions = {}
    return ConfigurationLayers(
        industry_pack=ConfigurationOverlay.model_validate(
            {
                "industry": industry,
                "privacy_mode": privacy_mode,
                "data_retention_days": retention_value,
            }
        ),
        tenant_override=ConfigurationOverlay(
            tenant_id=str(manifest.tenant.id),
            display_name=str(manifest.tenant.name),
            model_ref=ModelReferenceOverride(
                model_id=str(model.id),
                model_version=str(model.version),
                feature_bank_version=str(model.feature_bank_version),
            ),
            threshold_ref=ThresholdReferenceOverride(
                ref=f"policy://{policy.version}",
                version=str(policy.version),
                review_threshold=float(policy.default.review_threshold),
                hold_threshold=float(policy.default.hold_threshold),
                overrides=list(policy.overrides),
            ),
            connector_refs=connectors,
            extensions=ExtensionMetadataOverride(values=dict(extensions)) if extensions else None,
        ),
        runtime_site_override=ConfigurationOverlay(
            capture_channels=[str(manifest.input_mode)],
            version=str(manifest.version),
        ),
    )


# Friendly aliases used by integrations while the platform contract evolves.
PlatformConfig = PlatformConfiguration
ConfigOverlay = ConfigurationOverlay
ConfigLayers = ConfigurationLayers
merge_config_layers = merge_configuration_layers
resolve_effective_configuration = merge_configuration_layers


__all__ = [
    "AutomotivePaintExtension",
    "assert_no_embedded_secrets",
    "CaptureChannel",
    "ConfigLayers",
    "ConfigOverlay",
    "CONFIGURATION_LAYER_ORDER",
    "ConfigurationAudit",
    "ConfigurationError",
    "ConfigurationLayers",
    "ConfigurationOverlay",
    "EffectiveConfiguration",
    "ExtensionMetadata",
    "ModelReference",
    "PlatformConfig",
    "PlatformConfiguration",
    "PLATFORM_CONFIGURATION_SCHEMA_VERSION",
    "PrivacyMode",
    "SafetyGateConfiguration",
    "SecretReference",
    "ThresholdReference",
    "default_platform_configuration",
    "layers_from_legacy_manifest",
    "layers_from_effective_configuration",
    "merge_config_layers",
    "merge_configuration_layers",
    "redact_configuration",
    "resolve_effective_configuration",
    "validate_configuration_layers",
    "validate_controlled_metadata",
]
