from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from edge_gateway.config import GatewaySettings
from edge_gateway.deployment import GatewayDeploymentPack
from edge_gateway.runtime import GatewayRuntime

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def pack_a() -> GatewayDeploymentPack:
    return GatewayDeploymentPack.load(
        ROOT / "backend/deployment-packs/manifests/factory-a-transistor.json"
    )


@pytest.fixture
def pack_b() -> GatewayDeploymentPack:
    return GatewayDeploymentPack.load(
        ROOT / "backend/deployment-packs/manifests/factory-b-bottle.json"
    )


@pytest.fixture
def gateway_settings(tmp_path: Path, pack_a: GatewayDeploymentPack) -> GatewaySettings:
    return GatewaySettings(
        mode="demo",
        gateway_id=pack_a.gateway_id,
        pack_path=ROOT / "backend/deployment-packs/manifests/factory-a-transistor.json",
        data_dir=tmp_path / "state",
        watch_root=tmp_path / "incoming",
        database_path=tmp_path / "state" / "gateway.sqlite3",
        auth_secret=SecretStr("test-secret"),
        min_width=16,
        min_height=16,
        min_sharpness=2.0,
        stable_for_seconds=0,
        heartbeat_interval_seconds=0.1,
        upload_enabled=True,
        data_consent=True,
    )


@pytest.fixture
def runtime(gateway_settings: GatewaySettings, pack_a: GatewayDeploymentPack) -> GatewayRuntime:
    return GatewayRuntime(gateway_settings, pack_a)
