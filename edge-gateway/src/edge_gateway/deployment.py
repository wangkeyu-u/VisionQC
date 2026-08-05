"""Small, independent reader for the VisionQC Deployment Pack contract."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GatewayProduct(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)

    def matches(self, value: str) -> bool:
        return self.code == "*" or value == self.code or value in self.aliases


class GatewayStation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    description: str = Field(default="")
    camera_profile: str = Field(default="")


class GatewayFieldMapping(BaseModel):
    model_config = ConfigDict(extra="ignore")

    product_code: str = Field(min_length=1)
    product_revision: str = Field(min_length=1)
    batch_no: str = Field(min_length=1)
    station_code: str = Field(min_length=1)
    captured_at: str = Field(min_length=1)
    source: str = Field(default="source", min_length=1)

    @model_validator(mode="after")
    def unique_keys(self) -> GatewayFieldMapping:
        values = [
            self.product_code,
            self.product_revision,
            self.batch_no,
            self.station_code,
            self.captured_at,
            self.source,
        ]
        if len(values) != len(set(values)):
            raise ValueError("Deployment Pack field mapping keys must be unique")
        return self

    def key_for(self, canonical_name: str) -> str:
        return str(getattr(self, canonical_name))


class WatchDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    root: str = "/var/lib/visionqc-gateway/incoming"
    relative_path_regex: str = Field(min_length=1)
    filename_regex: str = Field(min_length=1)
    capture_map: dict[str, str] = Field(default_factory=dict)
    defaults: dict[str, str] = Field(default_factory=dict)
    source: str = Field(min_length=1)
    allowed_extensions: list[str] = Field(default_factory=lambda: [".png", ".jpg", ".jpeg"])
    timestamp_formats: list[str] = Field(default_factory=lambda: ["%Y%m%dT%H%M%S"])
    timezone_offset: str = "+00:00"
    stable_for_seconds: float = Field(default=1.0, ge=0, le=3600)
    archive_subdir: str = ".archive"
    quarantine_subdir: str = ".quarantine"

    @model_validator(mode="after")
    def validate_patterns(self) -> WatchDefinition:
        try:
            re.compile(self.relative_path_regex)
            re.compile(self.filename_regex)
        except re.error as exc:
            raise ValueError(f"invalid gateway filename/path regex: {exc}") from exc
        extensions = {
            item.lower() if item.startswith(".") else f".{item.lower()}"
            for item in self.allowed_extensions
        }
        if not extensions.intersection({".png", ".jpg", ".jpeg"}):
            raise ValueError("gateway must allow at least one PNG/JPEG extension")
        return self

    @property
    def normalized_extensions(self) -> set[str]:
        return {
            item.lower() if item.startswith(".") else f".{item.lower()}"
            for item in self.allowed_extensions
        }


class SimulatorDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    relative_dir_template: str
    filename_template: str
    product: str
    station: str
    product_revision: str
    batch_prefix: str
    extension: str = ".png"


class EdgeGatewayDefinition(BaseModel):
    model_config = ConfigDict(extra="ignore")

    gateway_id: str = Field(min_length=1, max_length=128)
    target_tenant_id: str = Field(min_length=1, max_length=64)
    watch: WatchDefinition
    simulator: SimulatorDefinition | None = None


class GatewayDeploymentPack(BaseModel):
    """Only the fields needed at the edge are parsed; other pack fields are ignored."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = "visionqc.deployment-pack.v1"
    pack_key: str = Field(min_length=1)
    version: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    tenant: dict[str, str]
    products: list[GatewayProduct] = Field(min_length=1)
    stations: list[GatewayStation] = Field(min_length=1)
    field_mapping: GatewayFieldMapping
    edge_gateway: EdgeGatewayDefinition

    @model_validator(mode="after")
    def validate_tenant_binding(self) -> GatewayDeploymentPack:
        tenant_id = self.tenant.get("id")
        if not tenant_id or tenant_id != self.edge_gateway.target_tenant_id:
            raise ValueError("edge gateway target_tenant_id must match Deployment Pack tenant.id")
        if len({item.code for item in self.products}) != len(self.products):
            raise ValueError("Deployment Pack product codes must be unique")
        if len({item.code for item in self.stations}) != len(self.stations):
            raise ValueError("Deployment Pack station codes must be unique")
        return self

    @property
    def tenant_id(self) -> str:
        return self.tenant["id"]

    @property
    def gateway_id(self) -> str:
        return self.edge_gateway.gateway_id

    def resolve_product(self, value: str) -> GatewayProduct | None:
        return next((item for item in self.products if item.matches(value)), None)

    def resolve_station(self, value: str) -> GatewayStation | None:
        return next(
            (item for item in self.stations if item.code == value or item.code == "*"), None
        )

    @classmethod
    def load(cls, path: Path) -> GatewayDeploymentPack:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls.model_validate(payload)


def parse_timezone_offset(value: str) -> timezone:
    match = re.fullmatch(r"([+-])(\d{2}):(\d{2})", value)
    if not match:
        raise ValueError(f"invalid timezone offset {value!r}")
    seconds = (int(match.group(2)) * 60 + int(match.group(3))) * 60
    if match.group(1) == "-":
        seconds *= -1
    return timezone(timedelta(seconds=seconds))


def normalize_captured_at(raw: str, watch: WatchDefinition) -> str:
    value = raw.strip()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        parsed = None
        for fmt in watch.timestamp_formats:
            try:
                parsed = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            raise ValueError(
                f"captured_at value {raw!r} does not match Deployment Pack formats"
            ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=parse_timezone_offset(watch.timezone_offset))
    return parsed.astimezone(UTC).isoformat()
