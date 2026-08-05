from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image

from edge_gateway.deployment import GatewayDeploymentPack
from edge_gateway.simulator import generate_samples

ROOT = Path(__file__).resolve().parents[2]


def test_factory_b_simulator_matches_pack_jpeg_extension(tmp_path: Path) -> None:
    pack = GatewayDeploymentPack.load(
        ROOT / "backend/deployment-packs/manifests/factory-b-bottle.json"
    )
    root = tmp_path / "incoming"

    generate_samples(pack, root, kinds=["normal"], count=1)

    sample = next(root.rglob("*.jpg"))
    with Image.open(BytesIO(sample.read_bytes())) as image:
        assert image.format == "JPEG"
