"""Validate the contract and hashes emitted by the paint-quality generator."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image

REQUIRED_DEFECT_CLASSES = {"dust_nib", "scratch", "paint_run_sag", "orange_peel"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def validate_manifest(root: Path) -> dict[str, Any]:
    manifest_path = root / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "visionqc.synthetic.paint-quality-manifest.v1":
        raise ValueError("unexpected paint-quality manifest schema")
    if manifest.get("source_type") != "DEMO_SYNTHETIC":
        raise ValueError("synthetic dataset must declare DEMO_SYNTHETIC")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or len(samples) != manifest.get("count"):
        raise ValueError("manifest sample count is inconsistent")
    if not REQUIRED_DEFECT_CLASSES.issubset(set(manifest.get("defect_classes", []))):
        raise ValueError("manifest does not declare all required paint defect classes")
    if manifest.get("content_fingerprint") != canonical_hash(samples):
        raise ValueError("manifest content fingerprint is invalid")
    seen: set[str] = set()
    class_counts: dict[str, int] = {}
    for sample in samples:
        sample_id = str(sample.get("sample_id"))
        if sample_id in seen:
            raise ValueError(f"duplicate sample_id: {sample_id}")
        seen.add(sample_id)
        files = sample.get("files", {})
        rgb = root / str(files["rgb"])
        mask = root / str(files["mask"])
        annotation_path = root / str(files["annotation"])
        for path in (rgb, mask, annotation_path):
            if not path.is_file() or path.resolve().parent != path.parent.resolve():
                raise ValueError(f"manifest file is missing or escapes root: {path}")
        if sha256(rgb) != files.get("rgb_sha256") or sha256(mask) != files.get("mask_sha256"):
            raise ValueError(f"file hash mismatch for {sample_id}")
        annotation = json.loads(annotation_path.read_text(encoding="utf-8"))
        if annotation.get("sample_id") != sample_id or annotation.get("source_type") != "DEMO_SYNTHETIC":
            raise ValueError(f"annotation identity mismatch for {sample_id}")
        with Image.open(rgb) as rgb_image, Image.open(mask) as mask_image:
            if rgb_image.size != mask_image.size:
                raise ValueError(f"RGB/mask dimensions differ for {sample_id}")
            grayscale = mask_image.convert("L")
            mask_bytes = grayscale.tobytes()
            values = set(mask_bytes)
            if not values.issubset({0, 255}):
                raise ValueError(f"mask is not binary for {sample_id}: {sorted(values)[:5]}")
            foreground = sum(value > 0 for value in mask_bytes)
        defect_type = str(sample.get("defect_type"))
        class_counts[defect_type] = class_counts.get(defect_type, 0) + 1
        if defect_type == "normal" and foreground != 0:
            raise ValueError(f"normal sample has a non-empty mask: {sample_id}")
        if defect_type != "normal" and foreground == 0:
            raise ValueError(f"defect sample has an empty mask: {sample_id}")
    return {
        "valid": True,
        "count": len(samples),
        "class_counts": class_counts,
        "content_fingerprint": manifest["content_fingerprint"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_manifest(args.root.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
