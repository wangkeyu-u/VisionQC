from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from edge_gateway.config import GatewaySettings
from edge_gateway.runtime import GatewayRuntime
from edge_gateway.uploader import UploadError, UploadResult


class FakeUploader:
    def __init__(self):
        self.uploads = []
        self.heartbeats = []

    def upload(self, item, data):
        self.uploads.append((item.idempotency_key, data))
        return UploadResult(f"insp-{item.id}", False, "RECEIVED")

    def heartbeat(self, payload):
        self.heartbeats.append(payload)
        return True

    def close(self):
        pass


class FlakyUploader(FakeUploader):
    def __init__(self):
        super().__init__()
        self.failures_remaining = 1

    def upload(self, item, data):
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise UploadError(
                "UPLOAD_TRANSPORT_ERROR", "simulated network outage", retryable=True
            )
        return super().upload(item, data)


class RecoveringHeartbeatUploader(FakeUploader):
    def __init__(self):
        super().__init__()
        self.heartbeat_results = iter((False, True))

    def heartbeat(self, payload):
        self.heartbeats.append(payload)
        return next(self.heartbeat_results)


def write_a_sample(root: Path, *, sequence: str = "000001") -> Path:
    from PIL import Image, ImageDraw

    path = root / "ST-07-final" / f"TR-AX14__B-A-0001__20260804T104218__{sequence}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (128, 96), (70, 110, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 116, 84), fill=(170, 190, 165), outline=(245, 245, 230), width=4)
    draw.line((20, 48, 108, 48), fill=(20, 40, 30), width=7)
    image.save(path, format="PNG")
    return path


def write_b_sample(root: Path, *, sequence: str = "000001") -> Path:
    from PIL import Image, ImageDraw

    path = (
        root
        / "cell"
        / "CELL-12"
        / "date"
        / "2026"
        / "08"
        / "04"
        / f"BT-BOTTLE-01__lot=LOT-B-0001__captured=20260804T104218__seq={sequence}.jpg"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (128, 96), (70, 110, 90))
    draw = ImageDraw.Draw(image)
    draw.ellipse((20, 12, 108, 84), fill=(170, 190, 165), outline=(245, 245, 230), width=4)
    draw.line((28, 48, 100, 48), fill=(20, 40, 30), width=7)
    image.save(path, format="JPEG")
    return path


def test_runtime_parses_pack_rules_and_uploads_once(
    runtime: GatewayRuntime, gateway_settings, pack_a
) -> None:
    fake = FakeUploader()
    runtime.close()
    runtime = GatewayRuntime(gateway_settings, pack_a, uploader=fake)  # type: ignore[arg-type]
    source = write_a_sample(runtime.watcher.root)

    assert runtime.scan_once() == []  # first observation is not yet stable
    accepted = runtime.scan_once()
    assert len(accepted) == 1
    item = accepted[0]
    assert item.context["product_code"] == "transistor"
    assert item.context["station_code"] == "ST-07 / 终检"
    assert item.context["batch_no"] == "B-A-0001"
    uploaded = runtime.upload_once()
    assert uploaded is not None and uploaded.status == "UPLOADED"
    assert len(fake.uploads) == 1
    assert runtime.upload_once() is None
    assert source.parent.name == "ST-07-final"  # archive keeps source-relative layout


def test_runtime_parses_factory_b_path_and_context(pack_b, tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    pack_path = root / "backend/deployment-packs/manifests/factory-b-bottle.json"
    settings = GatewaySettings(
        mode="demo",
        gateway_id=pack_b.gateway_id,
        pack_path=pack_path,
        data_dir=tmp_path / "state-b",
        watch_root=tmp_path / "incoming-b",
        database_path=tmp_path / "state-b" / "gateway.sqlite3",
        auth_secret=SecretStr("test-secret-with-sufficient-entropy"),
        min_width=16,
        min_height=16,
        min_sharpness=2.0,
        stable_for_seconds=0,
    )
    fake = FakeUploader()
    runtime = GatewayRuntime(settings, pack_b, uploader=fake)  # type: ignore[arg-type]
    write_b_sample(runtime.watcher.root)

    runtime.scan_once()
    accepted = runtime.scan_once()

    assert len(accepted) == 1
    assert accepted[0].context == {
        "product_code": "bottle",
        "product_revision": "B-2026.07",
        "batch_no": "LOT-B-0001",
        "station_code": "CELL-12",
        "captured_at": "2026-08-04T02:42:18+00:00",
        "source": "edge-camera/factory-b/cell12",
    }
    assert runtime.upload_once() is not None
    runtime.close()


def test_retryable_transport_failure_keeps_spool_and_can_resume(
    runtime: GatewayRuntime,
) -> None:
    flaky = FlakyUploader()
    runtime.close()
    runtime = GatewayRuntime(runtime.settings, runtime.pack, uploader=flaky)  # type: ignore[arg-type]
    write_a_sample(runtime.watcher.root, sequence="000010")
    runtime.scan_once()
    runtime.scan_once()

    failed = runtime.upload_once()

    assert failed is not None
    assert failed.status == "FAILED"
    assert failed.retryable is True
    assert failed.error_code == "UPLOAD_TRANSPORT_ERROR"
    assert failed.spool_path is not None and Path(failed.spool_path).exists()
    runtime.queue.retry(failed.id)
    resumed = runtime.upload_once()
    assert resumed is not None and resumed.status == "UPLOADED"
    runtime.close()


def test_successful_heartbeat_clears_transient_backend_failure(
    runtime: GatewayRuntime,
) -> None:
    uploader = RecoveringHeartbeatUploader()
    runtime.close()
    runtime = GatewayRuntime(runtime.settings, runtime.pack, uploader=uploader)  # type: ignore[arg-type]

    assert runtime.heartbeat_once(force=True) is False
    assert runtime.status_payload()["status"] == "DEGRADED"
    assert runtime.status_payload()["recent_error"]["code"] == "HEARTBEAT_FAILED"

    assert runtime.heartbeat_once(force=True) is True
    assert runtime.status_payload()["status"] == "ONLINE"
    assert runtime.status_payload()["recent_error"] is None
    runtime.close()


def test_restart_recovers_inflight_item_and_reuploads_from_spool(
    gateway_settings, pack_a
) -> None:
    first = GatewayRuntime(gateway_settings, pack_a, uploader=FakeUploader())  # type: ignore[arg-type]
    write_a_sample(first.watcher.root, sequence="000011")
    first.scan_once()
    first.scan_once()
    claimed = first.queue.claim_due()
    assert claimed is not None and claimed.status == "UPLOADING"
    first.close()

    second_uploader = FakeUploader()
    second = GatewayRuntime(gateway_settings, pack_a, uploader=second_uploader)  # type: ignore[arg-type]
    recovered = second.queue.get(claimed.id)
    assert recovered is not None
    assert recovered.status == "FAILED"
    assert recovered.error_code == "PROCESS_RESTARTED"
    uploaded = second.upload_once()
    assert uploaded is not None and uploaded.status == "UPLOADED"
    assert len(second_uploader.uploads) == 1
    second.close()


def test_runtime_persists_quality_rejection(runtime: GatewayRuntime) -> None:
    source = runtime.watcher.root / "ST-07-final" / "bad.png"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"broken")
    runtime.scan_once()
    runtime.scan_once()
    summary = runtime.queue.summary()
    assert summary.counts["REJECTED"] == 1
    assert summary.recent_errors[0]["code"] == "SECURITY_DECODE_FAILED"


def test_watcher_rearms_when_a_file_changes_after_stability(runtime: GatewayRuntime) -> None:
    source = write_a_sample(runtime.watcher.root, sequence="000009")
    assert runtime.watcher.stable_files() == []
    assert runtime.watcher.stable_files()
    source.write_bytes(source.read_bytes() + b"\n")
    assert runtime.watcher.stable_files() == []
    assert runtime.watcher.stable_files()
