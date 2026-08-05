"""Run both product PatchCore smoke baselines on deterministic synthetic data.

This script exercises the real Anomalib/PyTorch training, memory-bank export,
evaluation, package verification, and single-image inference paths without
downloading or committing MVTec data.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import yaml
from PIL import Image

from visionqc_ml.dataset import generate_manifest
from visionqc_ml.hashing import write_json
from visionqc_ml.inference import VisionQCInferenceService
from visionqc_ml.training import run_patchcore_baseline

ML_ROOT = Path(__file__).resolve().parents[1]


def _write_rgb(path: Path, value: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.full((40, 48, 3), value, dtype=np.uint8)
    array[8:16, 10:22, 0] = min(255, value + 30)
    Image.fromarray(array, mode="RGB").save(path)


def _write_mask(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((40, 48), dtype=np.uint8)
    array[8:16, 10:22] = 255
    Image.fromarray(array, mode="L").save(path)


def _make_dataset(root: Path, category: str) -> None:
    subtype = "bent_lead" if category == "transistor" else "contamination"
    for index in range(4):
        _write_rgb(root / category / "train" / "good" / f"{index:03d}.png", 30 + index)
        _write_rgb(root / category / "test" / "good" / f"{index:03d}.png", 40 + index)
        _write_rgb(root / category / "test" / subtype / f"{index:03d}.png", 140 + index)
        _write_mask(root / category / "ground_truth" / subtype / f"{index:03d}_mask.png")


def run(output_root: Path) -> dict[str, object]:
    dataset_root = output_root / "dataset"
    manifest_root = output_root / "manifests"
    package_root = output_root / "packages"
    notice = ML_ROOT / "licenses" / "MVTEC-AD-NOTICE.md"
    summaries: dict[str, object] = {}
    for category in ("transistor", "bottle"):
        _make_dataset(dataset_root, category)
        manifest_dir = manifest_root / category
        generate_manifest(dataset_root, manifest_dir, seed=20260804, validation_ratio=0.5, category=category)
        config_path = ML_ROOT / "configs" / f"patchcore-smoke-{category}.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        model_id = str(config["model"]["id"])
        run_dir = output_root / "runs" / category
        summary = run_patchcore_baseline(
            config_path,
            manifest_dir / "manifest.jsonl",
            manifest_dir / "manifest-meta.json",
            dataset_root,
            run_dir,
            package_root,
            ML_ROOT.parent,
            notice,
        )
        package_dir = Path(str(summary["package_dir"]))
        service = VisionQCInferenceService.from_package(package_dir, device="cpu", expected_category=category)
        representative = dataset_root / category / "test" / "good" / "000.png"
        service.warmup(representative, runs=1)
        result = service.infer(representative, f"{category}-smoke", output_root / "inference")
        summaries[category] = {
            **summary,
            "model_id": model_id,
            "single_image_score": result.anomaly.score,
            "single_image_decision": result.policy.decision.value,
            "package_verified": service.health()["ready"],
            "evaluation_path": str((run_dir / "evaluation" / "evaluation.json").resolve()),
            "gallery_path": str((run_dir / "gallery" / "index.html").resolve()),
        }
    result = {
        "schema_version": "visionqc.modelops-smoke.v1",
        "synthetic": True,
        "claim_boundary": "Smoke evidence validates the implementation contract, not MVTec or factory accuracy.",
        "output_root": str(output_root.resolve()),
        "products": summaries,
    }
    write_json(output_root / "smoke-summary.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ML_ROOT / ".artifacts" / "smoke")
    args = parser.parse_args()
    import json

    print(json.dumps(run(args.output_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
