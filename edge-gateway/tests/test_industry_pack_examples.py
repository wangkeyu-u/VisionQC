from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from pydantic import SecretStr

from edge_gateway.config import GatewaySettings
from edge_gateway.deployment import GatewayDeploymentPack
from edge_gateway.runtime import GatewayRuntime
from edge_gateway.uploader import UploadResult

ROOT = Path(__file__).resolve().parents[2]
EXAMPLES = {
    "electronics": ROOT
    / "backend/deployment-packs/examples/electronics-transistor/resolved-deployment-pack.json",
    "packaging": ROOT
    / "backend/deployment-packs/examples/packaging-bottle/resolved-deployment-pack.json",
    "automotive-paint": ROOT
    / "backend/deployment-packs/examples/automotive-paint/resolved-deployment-pack.json",
}


class LocalOnlyUploader:
    def __init__(self) -> None:
        self.uploads: list[str] = []

    def upload(self, item, data: bytes) -> UploadResult:
        self.uploads.append(item.idempotency_key)
        return UploadResult(f"inspection-{item.id}", False, "RECEIVED")

    def heartbeat(self, payload: dict[str, object]) -> bool:
        return True

    def close(self) -> None:
        return None


def _image(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (128, 96), (80, 110, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 116, 84), fill=(170, 190, 165), outline=(245, 245, 230), width=4)
    draw.line((20, 48, 108, 48), fill=(20, 40, 30), width=7)
    image.save(path, format="JPEG" if path.suffix == ".jpg" else "PNG")


def _sample(root: Path, kind: str, sequence: str = "000001") -> Path:
    pack = GatewayDeploymentPack.load(EXAMPLES[kind])
    simulator = pack.edge_gateway.simulator
    assert simulator is not None
    values = {
        "product": simulator.product,
        "station": simulator.station,
        "batch": f"{simulator.batch_prefix}-0001",
        "captured_at": "20260830T100000",
        "sequence": sequence,
        "extension": simulator.extension.removeprefix("."),
    }
    relative_dir = simulator.relative_dir_template.format(**values)
    filename = simulator.filename_template.format(**values)
    path = root / relative_dir / filename
    _image(path)
    return path


@pytest.mark.parametrize("kind", sorted(EXAMPLES))
def test_each_industry_example_resolves_and_ingests_without_code_branch(
    kind: str, tmp_path: Path
) -> None:
    pack = GatewayDeploymentPack.load(EXAMPLES[kind])
    settings = GatewaySettings(
        mode="demo",
        gateway_id=pack.gateway_id,
        pack_path=EXAMPLES[kind],
        data_dir=tmp_path / "state",
        watch_root=tmp_path / "incoming",
        auth_secret=SecretStr("test-secret-with-sufficient-entropy"),
        min_width=16,
        min_height=16,
        stable_for_seconds=0,
        upload_enabled=False,
        data_consent=False,
    )
    uploader = LocalOnlyUploader()
    runtime = GatewayRuntime(settings, pack, uploader=uploader)  # type: ignore[arg-type]
    _sample(runtime.watcher.root, kind)
    assert runtime.scan_once() == []
    accepted = runtime.scan_once()
    assert len(accepted) == 1
    assert accepted[0].tenant_id == pack.tenant_id
    assert accepted[0].context["product_code"] == pack.products[0].code
    assert runtime.upload_once() is not None
    assert uploader.uploads == []
    runtime.close()


def test_same_image_with_new_sequence_is_a_durable_duplicate(tmp_path: Path) -> None:
    pack = GatewayDeploymentPack.load(EXAMPLES["electronics"])
    settings = GatewaySettings(
        mode="demo",
        gateway_id=pack.gateway_id,
        pack_path=EXAMPLES["electronics"],
        data_dir=tmp_path / "state",
        watch_root=tmp_path / "incoming",
        auth_secret=SecretStr("test-secret-with-sufficient-entropy"),
        min_width=16,
        min_height=16,
        stable_for_seconds=0,
        upload_enabled=False,
        data_consent=False,
    )
    runtime = GatewayRuntime(settings, pack, uploader=LocalOnlyUploader())  # type: ignore[arg-type]
    first_path = _sample(runtime.watcher.root, "electronics", "000001")
    first_bytes = first_path.read_bytes()
    runtime.scan_once()
    accepted = runtime.scan_once()
    assert accepted[0].status == "QUEUED"
    runtime.upload_once()
    duplicate = _sample(runtime.watcher.root, "electronics", "000002")
    duplicate.write_bytes(first_bytes)
    runtime.scan_once()
    second = runtime.scan_once()
    assert second[0].status == "DUPLICATE"
    assert runtime.queue.summary().counts["DUPLICATE"] == 1
    runtime.close()


def test_bad_watch_path_has_a_human_readable_configuration_error(tmp_path: Path) -> None:
    pack = GatewayDeploymentPack.load(EXAMPLES["electronics"])
    bad_root = tmp_path / "not-a-folder"
    bad_root.write_text("not a directory", encoding="utf-8")
    settings = GatewaySettings(
        mode="demo",
        gateway_id=pack.gateway_id,
        pack_path=EXAMPLES["electronics"],
        data_dir=tmp_path / "state",
        watch_root=bad_root,
        auth_secret=SecretStr("test-secret-with-sufficient-entropy"),
    )
    with pytest.raises(ValueError, match="不是文件夹"):
        GatewayRuntime(settings, pack, uploader=LocalOnlyUploader())  # type: ignore[arg-type]
