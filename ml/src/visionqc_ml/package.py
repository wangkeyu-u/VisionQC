"""Versioned model package construction and integrity verification."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .errors import ModelPackageError
from .hashing import read_json, sha256_file, sha256_json, write_json
from .schemas import ModelPackageManifest, PackageFile, inference_json_schema

PACKAGE_LIMITATIONS = [
    "The model detects anomalous appearance and localizes anomalous regions only.",
    "It does not confirm a semantic defect type or root cause.",
    "MVTec AD benchmark results do not establish real-factory production performance.",
    "MVTec AD is licensed CC BY-NC-SA 4.0 and is not licensed for commercial use.",
]


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise ModelPackageError(f"required package source file does not exist: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _file_index(package_dir: Path) -> dict[str, PackageFile]:
    files: dict[str, PackageFile] = {}
    for path in sorted(item for item in package_dir.rglob("*") if item.is_file() and item.name != "model-package.json"):
        relative = path.relative_to(package_dir).as_posix()
        files[relative] = PackageFile(sha256=sha256_file(path), size_bytes=path.stat().st_size)
    return files


def build_model_package(
    target_root: Path,
    model_path: Path,
    training_config_path: Path,
    preprocessing_path: Path,
    thresholds_path: Path,
    evaluation_json_path: Path,
    evaluation_markdown_path: Path,
    manifest_meta_path: Path,
    dataset_notice_path: Path,
    model_id: str,
    model_version: str,
    code_commit: str,
    lifecycle_status: str = "EVALUATED",
    dependency_lock_path: Path | None = None,
    runtime_notice_path: Path | None = None,
    feature_bank_path: Path | None = None,
    feature_bank_metadata_path: Path | None = None,
    feature_bank_version: str | None = None,
) -> Path:
    """Assemble an immutable package directory and write its complete hash index."""
    meta = read_json(manifest_meta_path)
    training_config = yaml.safe_load(training_config_path.read_text(encoding="utf-8"))
    category = str(training_config.get("data", {}).get("category", "unknown"))
    resolved_feature_bank_version = (
        feature_bank_version
        or training_config.get("model", {}).get("feature_bank_version")
        or f"fb-{str(meta['dataset_fingerprint'])[:16]}"
    )
    final_dir = target_root / model_id / model_version
    if final_dir.exists():
        raise ModelPackageError(f"versioned package already exists and will not be overwritten: {final_dir}")
    final_dir.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f".{model_version}-", dir=final_dir.parent) as temporary:
        staged = Path(temporary) / model_version
        staged.mkdir()
        _copy(model_path, staged / "weights" / "model.pt")
        _copy(training_config_path, staged / "config" / "training.yaml")
        _copy(preprocessing_path, staged / "config" / "preprocessing.json")
        _copy(thresholds_path, staged / "config" / "thresholds.json")
        _copy(evaluation_json_path, staged / "metrics" / "evaluation.json")
        _copy(evaluation_markdown_path, staged / "metrics" / "evaluation.md")
        _copy(manifest_meta_path, staged / "provenance" / "manifest-meta.json")
        _copy(dataset_notice_path, staged / "licenses" / "MVTEC-AD-NOTICE.md")
        if dependency_lock_path is not None:
            _copy(dependency_lock_path, staged / "provenance" / "uv.lock")
        if runtime_notice_path is not None:
            _copy(runtime_notice_path, staged / "licenses" / "MODEL-RUNTIME-NOTICE.md")
        feature_bank_file: str | None = None
        feature_bank_sha256: str | None = None
        if feature_bank_path is not None:
            _copy(feature_bank_path, staged / "weights" / "feature-bank.pt")
            feature_bank_file = "weights/feature-bank.pt"
            feature_bank_sha256 = sha256_file(staged / feature_bank_file)
            if feature_bank_metadata_path is not None:
                _copy(feature_bank_metadata_path, staged / "provenance" / "feature-bank.json")
            else:
                write_json(
                    staged / "provenance" / "feature-bank.json",
                    {
                        "schema_version": "visionqc.feature-bank.v1",
                        "file": feature_bank_file,
                        "sha256": feature_bank_sha256,
                        "source": "Anomalib PatchCore fitted memory bank",
                    },
                )
        write_json(staged / "schemas" / "inference-result.schema.json", inference_json_schema())
        write_json(
            staged / "metadata.json",
            {
                "schema_version": "visionqc.model-metadata.v1",
                "model_id": model_id,
                "model_version": model_version,
                "category": category,
                "feature_bank_version": resolved_feature_bank_version,
                "feature_bank_file": feature_bank_file,
                "feature_bank_sha256": feature_bank_sha256,
                "algorithm": "PatchCore",
                "implementation": f"Anomalib {training_config['model']['anomalib_version']}",
                "backbone": training_config["model"]["backbone"],
                "score_range": [0.0, 1.0],
                "score_semantics": "normalized anomaly evidence; higher means more anomalous appearance",
                "score_normalization": (
                    "Anomalib 2.0 PostProcessor validation normalization embedded in exported Torch model"
                ),
                "threshold_ownership": "versioned deployment policy; calibrated from validation only",
                "code_commit": code_commit,
                "limitations": PACKAGE_LIMITATIONS,
            },
        )
        files = _file_index(staged)
        package_sha = sha256_json({path: item.model_dump(mode="json") for path, item in files.items()})
        manifest = ModelPackageManifest(
            model_id=model_id,
            model_version=model_version,
            feature_bank_version=resolved_feature_bank_version,
            category=category,
            created_at=datetime.now(timezone.utc),
            lifecycle_status=lifecycle_status,  # type: ignore[arg-type]
            dataset_fingerprint=meta["dataset_fingerprint"],
            training_manifest_sha256=meta["manifest_sha256"],
            code_commit=code_commit,
            package_sha256=package_sha,
            feature_bank_file=feature_bank_file,
            feature_bank_sha256=feature_bank_sha256,
            files=files,
            limitations=PACKAGE_LIMITATIONS,
        )
        write_json(staged / "model-package.json", manifest.model_dump(mode="json"))
        staged.replace(final_dir)
    return final_dir


def verify_model_package(package_dir: Path, expected_category: str | None = None) -> ModelPackageManifest:
    """Validate schema, exact file inventory, hashes, and package provenance."""
    manifest_path = package_dir / "model-package.json"
    if not manifest_path.is_file():
        raise ModelPackageError(f"missing model-package.json: {package_dir}")
    try:
        manifest = ModelPackageManifest.model_validate(read_json(manifest_path))
    except Exception as exc:
        raise ModelPackageError(f"invalid model package manifest: {exc}") from exc
    if expected_category is not None and manifest.category != expected_category:
        raise ModelPackageError(
            f"model package category mismatch: expected {expected_category}, got {manifest.category}"
        )

    discovered = _file_index(package_dir)
    declared_paths = set(manifest.files)
    discovered_paths = set(discovered)
    if declared_paths != discovered_paths:
        missing = sorted(declared_paths - discovered_paths)
        unexpected = sorted(discovered_paths - declared_paths)
        raise ModelPackageError(f"package inventory mismatch; missing={missing}, unexpected={unexpected}")
    mismatches = [
        path
        for path in sorted(declared_paths)
        if discovered[path].sha256 != manifest.files[path].sha256
        or discovered[path].size_bytes != manifest.files[path].size_bytes
    ]
    if mismatches:
        raise ModelPackageError(f"package file integrity mismatch: {mismatches}")
    if manifest.feature_bank_file:
        feature_bank_path = package_dir / manifest.feature_bank_file
        if not feature_bank_path.is_file():
            raise ModelPackageError(f"declared feature bank is missing: {manifest.feature_bank_file}")
        if manifest.feature_bank_sha256 != sha256_file(feature_bank_path):
            raise ModelPackageError(f"feature bank digest mismatch: {manifest.feature_bank_file}")
    for required in (
        "metadata.json",
        "config/training.yaml",
        "config/preprocessing.json",
        "config/thresholds.json",
        "metrics/evaluation.json",
        "provenance/manifest-meta.json",
        "schemas/inference-result.schema.json",
        "weights/model.pt",
    ):
        if not (package_dir / required).is_file():
            raise ModelPackageError(f"required model package file is missing: {required}")
    try:
        metadata: dict[str, Any] = read_json(package_dir / "metadata.json")
        thresholds: dict[str, Any] = read_json(package_dir / "config" / "thresholds.json")
        if metadata.get("model_id") != manifest.model_id or metadata.get("model_version") != manifest.model_version:
            raise ModelPackageError("metadata model identity does not match package manifest")
        if float(thresholds["review_threshold"]) >= float(thresholds["hold_threshold"]):
            raise ModelPackageError("package thresholds are not strictly ordered")
    except ModelPackageError:
        raise
    except Exception as exc:
        raise ModelPackageError(f"model package metadata is not loadable: {exc}") from exc
    actual_package_sha = sha256_json({path: item.model_dump(mode="json") for path, item in discovered.items()})
    if actual_package_sha != manifest.package_sha256:
        raise ModelPackageError(
            f"package digest mismatch: expected {manifest.package_sha256}, got {actual_package_sha}"
        )
    return manifest
