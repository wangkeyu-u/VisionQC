"""Deterministic industrial camera/directory simulator.

The simulator writes files using the same path and filename contract as the
gateway.  It can continuously generate accepted, rejected and duplicate
samples without real camera hardware.
"""

from __future__ import annotations

import argparse
import io
import itertools
import time
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

from edge_gateway.config import GatewaySettings
from edge_gateway.deployment import GatewayDeploymentPack


def _image(
    kind: str, width: int = 640, height: int = 480, *, image_format: str = "PNG"
) -> bytes:
    output = io.BytesIO()
    if kind == "corrupt":
        return b"not-a-valid-image\x00\xff"
    if kind == "dark":
        image = Image.new("RGB", (width, height), (8, 10, 9))
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 80, width - 80, height - 80), outline=(24, 28, 24), width=4)
    elif kind == "overexposed":
        image = Image.new("RGB", (width, height), (252, 252, 252))
        draw = ImageDraw.Draw(image)
        draw.rectangle((80, 80, width - 80, height - 80), outline=(255, 255, 255), width=4)
    else:
        image = Image.new("RGB", (width, height), (35, 70, 62))
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            (64, 54, width - 64, height - 54),
            fill=(155, 185, 168),
            outline=(220, 245, 216),
            width=5,
        )
        draw.line((100, height // 2, width - 100, height // 2), fill=(25, 44, 38), width=7)
        draw.ellipse(
            (width // 2 - 25, height // 2 - 25, width // 2 + 25, height // 2 + 25),
            fill=(225, 100, 80),
        )
        if kind == "anomaly":
            draw.rectangle(
                (width - 180, 110, width - 95, 185),
                fill=(240, 35, 35),
                outline=(255, 235, 80),
                width=5,
            )
        if kind == "blurry":
            image = image.filter(ImageFilter.GaussianBlur(radius=7))
    image.save(output, format=image_format)
    return output.getvalue()


def generate_samples(
    pack: GatewayDeploymentPack,
    root: Path,
    *,
    kinds: list[str],
    count: int,
    interval_seconds: float = 0,
    continuous: bool = False,
) -> None:
    definition = pack.edge_gateway.simulator
    if definition is None:
        raise ValueError("Deployment Pack does not contain an edge_gateway.simulator definition")
    watch = pack.edge_gateway.watch
    root.mkdir(parents=True, exist_ok=True)
    sequence = itertools.count(1)
    last_normal: tuple[bytes, str, dict[str, str]] | None = None
    remaining = count
    while continuous or remaining > 0:
        number = next(sequence)
        kind = kinds[(number - 1) % len(kinds)]
        captured = datetime.now(UTC).astimezone().strftime(watch.timestamp_formats[0])
        batch = f"{definition.batch_prefix}-{number:04d}"
        values = {
            "product": definition.product,
            "station": definition.station,
            "product_revision": definition.product_revision,
            "batch": batch,
            "captured_at": captured,
            "date": datetime.now(UTC).astimezone().strftime("%Y/%m/%d"),
            "sequence": f"{number:06d}",
            "extension": definition.extension.removeprefix("."),
        }
        if kind == "duplicate":
            if last_normal is None:
                kind = "normal"
            else:
                data, filename, previous_values = last_normal
                values.update(previous_values)
                values["sequence"] = f"{number:06d}"
                relative_dir = definition.relative_dir_template.format(**values)
                path = (
                    root
                    / relative_dir
                    / filename.replace(previous_values["sequence"], values["sequence"])
                )
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                if interval_seconds:
                    time.sleep(interval_seconds)
                if not continuous:
                    remaining -= 1
                continue
        extension = definition.extension.lower()
        if kind == "jpeg":
            extension = ".jpg"
        values["extension"] = extension.removeprefix(".")
        relative_dir = definition.relative_dir_template.format(**values)
        filename = definition.filename_template.format(**values)
        path = root / relative_dir / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        data = _image(
            kind,
            image_format="JPEG" if extension.lower() in {".jpg", ".jpeg"} else "PNG",
        )
        path.write_bytes(data)
        if kind in {"normal", "anomaly", "jpeg"}:
            last_normal = (data, filename, dict(values))
        if interval_seconds:
            time.sleep(interval_seconds)
        if not continuous:
            remaining -= 1


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument(
        "--kind",
        nargs="+",
        default=["normal", "anomaly", "dark", "overexposed", "corrupt", "duplicate"],
    )
    parser.add_argument("--count", type=int, default=6)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--continuous", action="store_true")
    args = parser.parse_args()
    settings = GatewaySettings(pack_path=args.pack)
    pack = GatewayDeploymentPack.load(args.pack)
    root = args.root or settings.resolved_watch_root(pack.edge_gateway.watch.root)
    generate_samples(
        pack,
        root,
        kinds=args.kind,
        count=args.count,
        interval_seconds=args.interval,
        continuous=args.continuous,
    )


if __name__ == "__main__":
    main()
