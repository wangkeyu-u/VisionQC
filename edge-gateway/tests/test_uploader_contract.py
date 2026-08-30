from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from edge_gateway.config import GatewaySettings
from edge_gateway.deployment import GatewayDeploymentPack
from edge_gateway.queue import QueueStore
from edge_gateway.uploader import BackendUploader


class FakeResponse:
    status_code = 202

    def json(self):
        return {
            "inspection_id": "insp-contract-b",
            "status": "RECEIVED",
            "idempotent_replay": False,
        }


class RecordingClient:
    def __init__(self):
        self.calls = []

    def post(self, path: str, **kwargs):
        self.calls.append((path, kwargs))
        return FakeResponse()


def test_factory_b_upload_contract_uses_pack_mapping_without_tenant_override(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[2]
    pack_path = root / "backend/deployment-packs/manifests/factory-b-bottle.json"
    pack = GatewayDeploymentPack.load(pack_path)
    settings = GatewaySettings(
        mode="demo",
        gateway_id=pack.gateway_id,
        pack_path=pack_path,
        data_dir=tmp_path,
        auth_secret=SecretStr("test-secret-for-gateway-contract-32b"),
    )
    queue = QueueStore(tmp_path / "gateway.sqlite3")
    item = queue.enqueue(
        gateway_id=pack.gateway_id,
        tenant_id=pack.tenant_id,
        pack_key=pack.pack_key,
        pack_version=pack.version,
        source_path="cell/CELL-12/date/2026/08/04/sample.jpg",
        source_fingerprint="fingerprint-b",
        spool_path=str(tmp_path / "sample.jpg"),
        original_filename="BT-BOTTLE-01__lot=LOT-B-0001__captured=20260804T104218__seq=000001.jpg",
        content_sha256="sha-b",
        mime_type="image/jpeg",
        width=128,
        height=96,
        context={
            "product_code": "bottle",
            "product_revision": "REV-B",
            "batch_no": "LOT-B-0001",
            "station_code": "CELL-12",
            "captured_at": "2026-08-04T02:42:18+00:00",
            "source": "industrial-camera-b",
        },
        idempotency_key="edge_contract_b",
    )
    client = RecordingClient()
    uploader = BackendUploader(settings, pack, client=client)  # type: ignore[arg-type]

    result = uploader.upload(item, b"jpeg-bytes")

    assert result.inspection_id == "insp-contract-b"
    path, request = client.calls[0]
    assert path == "/inspections"
    assert request["data"] == {
        "sku": "bottle",
        "revision": "REV-B",
        "lot_id": "LOT-B-0001",
        "cell": "CELL-12",
        "captured_at": "2026-08-04T02:42:18+00:00",
        "source_system": "industrial-camera-b",
    }
    assert "tenant_id" not in request["data"]
    assert request["headers"]["X-Gateway-ID"] == "factory-b-gw-cell12"
    assert request["headers"]["X-Tenant-ID"] == "factory-b"
    assert request["headers"]["X-Deployment-Pack"] == "factory_b/bottle"
    assert request["headers"]["X-Deployment-Pack-Version"] == "2.1.0"
    assert request["headers"]["Idempotency-Key"] == "edge_contract_b"
