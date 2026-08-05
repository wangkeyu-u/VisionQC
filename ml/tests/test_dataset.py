from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from visionqc_ml.dataset import (
    download_transistor,
    generate_manifest,
    load_manifest,
    validate_user_dataset,
    verify_manifest,
)
from visionqc_ml.errors import DatasetIntegrityError, ManifestError
from visionqc_ml.hashing import sha256_file, write_json


def test_download_verifies_archive_and_extracts_only_transistor(synthetic_dataset: Path, tmp_path: Path) -> None:
    archive = tmp_path / "source.tar.xz"
    with tarfile.open(archive, "w:xz") as bundle:
        bundle.add(
            synthetic_dataset / "transistor",
            arcname="mvtec_anomaly_detection/transistor",
        )
    source = tmp_path / "source.json"
    write_json(
        source,
        {
            "archive_url": archive.resolve().as_uri(),
            "archive_filename": "dataset.tar.xz",
            "archive_sha256": sha256_file(archive),
            "source_page": "https://example.invalid/mvtec",
            "expected": {
                "train_good_images": 4,
                "test_good_images": 4,
                "test_anomalous_images": 8,
                "ground_truth_masks": 8,
            },
            "license": {"name": "test"},
        },
    )
    receipt = download_transistor(source, tmp_path / "downloaded", tmp_path / "cache")
    assert receipt["archive_sha256"] == sha256_file(archive)
    assert (tmp_path / "downloaded" / "transistor" / "train" / "good" / "000.png").is_file()
    assert not (tmp_path / "downloaded" / "mvtec_anomaly_detection").exists()


def test_manifest_is_deterministic_and_stratified(synthetic_dataset: Path, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first_meta = generate_manifest(synthetic_dataset, first, seed=77, validation_ratio=0.5)
    second_meta = generate_manifest(synthetic_dataset, second, seed=77, validation_ratio=0.5)

    assert (first / "manifest.jsonl").read_bytes() == (second / "manifest.jsonl").read_bytes()
    assert first_meta["dataset_fingerprint"] == second_meta["dataset_fingerprint"]
    assert first_meta["split_sha256"] == second_meta["split_sha256"]
    entries = load_manifest(first / "manifest.jsonl")
    assert {entry.split for entry in entries} == {"train", "validation", "test"}
    assert all(entry.label == 0 for entry in entries if entry.split == "train")
    for split in ("validation", "test"):
        subtypes = {entry.anomaly_subtype for entry in entries if entry.split == split}
        assert subtypes == {"good", "bent_lead", "damaged_case"}
    assert (first / "failures.jsonl").read_text() == ""


def test_verify_manifest_detects_content_tampering(synthetic_dataset: Path, tmp_path: Path) -> None:
    output = tmp_path / "manifest"
    generate_manifest(synthetic_dataset, output)
    verification = verify_manifest(
        output / "manifest.jsonl",
        synthetic_dataset,
        output / "manifest-meta.json",
    )
    assert verification["valid"] is True

    target = synthetic_dataset / "transistor" / "train" / "good" / "000.png"
    target.write_bytes(target.read_bytes() + b"tamper")
    with pytest.raises(ManifestError, match="hash mismatch"):
        verify_manifest(output / "manifest.jsonl", synthetic_dataset, output / "manifest-meta.json")


def test_different_seed_changes_split_not_dataset_fingerprint(synthetic_dataset: Path, tmp_path: Path) -> None:
    first = generate_manifest(synthetic_dataset, tmp_path / "first", seed=1)
    second = generate_manifest(synthetic_dataset, tmp_path / "second", seed=2)
    assert first["dataset_fingerprint"] == second["dataset_fingerprint"]
    assert first["manifest_sha256"] != second["manifest_sha256"]


def test_validate_user_dataset_rejects_image_mask_mismatch(synthetic_dataset: Path) -> None:
    mask = synthetic_dataset / "transistor" / "ground_truth" / "bent_lead" / "000_mask.png"
    mask.unlink()
    with pytest.raises(DatasetIntegrityError, match="correspondence mismatch"):
        validate_user_dataset(synthetic_dataset, category="transistor", license_acknowledged=True)


def test_validate_user_dataset_allows_official_category_metadata(synthetic_dataset: Path) -> None:
    category = synthetic_dataset / "transistor"
    (category / "license.txt").write_text("official license metadata\n", encoding="utf-8")
    (category / "readme.txt").write_text("official category metadata\n", encoding="utf-8")

    receipt = validate_user_dataset(synthetic_dataset, category="transistor", license_acknowledged=True)

    assert receipt["counts"]["train_good_images"] == 4


def test_validate_user_dataset_rejects_unrecognized_non_image_file(synthetic_dataset: Path) -> None:
    (synthetic_dataset / "transistor" / "notes.txt").write_text("not official metadata\n", encoding="utf-8")

    with pytest.raises(DatasetIntegrityError, match="unsupported files"):
        validate_user_dataset(synthetic_dataset, category="transistor", license_acknowledged=True)
