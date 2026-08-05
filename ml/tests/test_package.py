from __future__ import annotations

from pathlib import Path

import pytest

from visionqc_ml.errors import ModelPackageError
from visionqc_ml.hashing import write_json
from visionqc_ml.package import build_model_package, verify_model_package


def _source_files(tmp_path: Path) -> dict[str, Path]:
    files = {
        "model": tmp_path / "model.pt",
        "training": tmp_path / "training.yaml",
        "preprocessing": tmp_path / "preprocessing.json",
        "thresholds": tmp_path / "thresholds.json",
        "evaluation_json": tmp_path / "evaluation.json",
        "evaluation_md": tmp_path / "evaluation.md",
        "meta": tmp_path / "manifest-meta.json",
        "notice": tmp_path / "NOTICE.md",
    }
    files["model"].write_bytes(b"fake model bytes")
    files["training"].write_text(
        "seed: 1\nmodel:\n  anomalib_version: 2.0.0\n  backbone: resnet18\n",
        encoding="utf-8",
    )
    write_json(
        files["preprocessing"],
        {"input_constraints": {"min_width": 1, "min_height": 1, "max_pixels": 10_000}},
    )
    write_json(files["thresholds"], {"policy_version": "p1", "review_threshold": 0.4, "hold_threshold": 0.8})
    write_json(files["evaluation_json"], {"metric": 1})
    files["evaluation_md"].write_text("evaluation\n", encoding="utf-8")
    write_json(files["meta"], {"dataset_fingerprint": "b" * 64, "manifest_sha256": "c" * 64})
    files["notice"].write_text("license notice\n", encoding="utf-8")
    return files


def build_fake_package(tmp_path: Path) -> Path:
    files = _source_files(tmp_path)
    return build_model_package(
        tmp_path / "packages",
        files["model"],
        files["training"],
        files["preprocessing"],
        files["thresholds"],
        files["evaluation_json"],
        files["evaluation_md"],
        files["meta"],
        files["notice"],
        "patchcore-transistor",
        "1.0.0-rc1",
        "deadbeef",
    )


def test_package_verifies_exact_inventory_and_hashes(tmp_path: Path) -> None:
    package = build_fake_package(tmp_path)
    manifest = verify_model_package(package)
    assert manifest.model_version == "1.0.0-rc1"
    assert manifest.feature_bank_version == "fb-" + "b" * 16
    (package / "config" / "thresholds.json").write_text("{}\n", encoding="utf-8")
    with pytest.raises(ModelPackageError, match="integrity mismatch"):
        verify_model_package(package)


def test_package_refuses_version_overwrite(tmp_path: Path) -> None:
    build_fake_package(tmp_path)
    with pytest.raises(ModelPackageError, match="will not be overwritten"):
        build_fake_package(tmp_path)
