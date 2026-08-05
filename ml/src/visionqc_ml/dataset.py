"""MVTec AD acquisition, integrity checks, and fixed product manifests."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import tarfile
import tempfile
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from PIL import Image, UnidentifiedImageError
from pydantic import Field, model_validator

from .errors import DatasetIntegrityError, ManifestError
from .hashing import canonical_json_bytes, read_json, sha256_file, sha256_json, write_json
from .schemas import StrictModel


class ManifestEntry(StrictModel):
    """One immutable image assignment in the dataset manifest."""

    schema_version: Literal["visionqc.dataset-manifest.v1"] = "visionqc.dataset-manifest.v1"
    sample_id: str = Field(pattern=r"^sample_[0-9a-f]{16}$")
    category: str = Field(default="transistor", min_length=1)
    split: Literal["train", "validation", "test"]
    source_split: Literal["train", "test"]
    label: Literal[0, 1]
    anomaly_subtype: str = Field(min_length=1)
    image_path: str = Field(min_length=1)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mask_path: str | None = None
    mask_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @model_validator(mode="after")
    def validate_relationships(self) -> ManifestEntry:
        if self.source_split == "train" and (self.split != "train" or self.label != 0):
            raise ValueError("MVTec training samples must remain normal training samples")
        if self.label == 0 and (self.anomaly_subtype != "good" or self.mask_path is not None):
            raise ValueError("normal samples must use subtype good and have no mask")
        if self.label == 1 and (not self.mask_path or not self.mask_sha256):
            raise ValueError("anomalous samples require a ground-truth mask")
        return self


def load_manifest(path: Path, split: str | None = None) -> list[ManifestEntry]:
    """Load and validate a JSONL manifest, optionally selecting one split."""
    if not path.is_file():
        raise ManifestError(f"manifest does not exist: {path}")
    entries: list[ManifestEntry] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            continue
        try:
            entry = ManifestEntry.model_validate_json(raw_line)
        except Exception as exc:
            raise ManifestError(f"invalid manifest line {line_number}: {exc}") from exc
        if split is None or entry.split == split:
            entries.append(entry)
    if not entries:
        raise ManifestError(f"manifest contains no entries for split={split!r}")
    return entries


def _stream_download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    request = urllib.request.Request(url, headers={"User-Agent": "VisionQC-ML/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)
        partial.replace(destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def _selected_member_path(member_name: str, category: str) -> Path | None:
    pure = PurePosixPath(member_name)
    if pure.is_absolute() or ".." in pure.parts:
        raise DatasetIntegrityError(f"unsafe archive member: {member_name}")
    try:
        category_index = pure.parts.index(category)
    except ValueError:
        return None
    relative_parts = pure.parts[category_index + 1 :]
    if not relative_parts:
        return Path(category)
    return Path(category, *relative_parts)


def _extract_category(archive_path: Path, dataset_root: Path, category: str) -> Path:
    target = dataset_root / category
    if target.exists():
        return target
    dataset_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{category}-extract-", dir=dataset_root) as temporary:
        temporary_root = Path(temporary)
        selected_count = 0
        with tarfile.open(archive_path, mode="r:xz") as archive:
            for member in archive:
                relative = _selected_member_path(member.name, category)
                if relative is None:
                    continue
                destination = temporary_root / relative
                if member.issym() or member.islnk():
                    raise DatasetIntegrityError(f"links are not accepted in dataset archive: {member.name}")
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                if not member.isfile():
                    continue
                source = archive.extractfile(member)
                if source is None:
                    raise DatasetIntegrityError(f"cannot read archive member: {member.name}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                selected_count += 1
        staged = temporary_root / category
        if selected_count == 0 or not staged.is_dir():
            raise DatasetIntegrityError(f"archive contains no {category} dataset")
        staged.replace(target)
    return target


def validate_dataset_layout(
    dataset_root: Path,
    category: str,
    expected: dict[str, int] | None = None,
) -> dict[str, int]:
    """Validate the required MVTec directories and category counts."""
    category_root = dataset_root / category
    required = [category_root / "train" / "good", category_root / "test", category_root / "ground_truth"]
    missing = [str(path) for path in required if not path.is_dir()]
    if missing:
        raise DatasetIntegrityError(f"missing required dataset directories: {missing}")

    train_good = sorted((category_root / "train" / "good").glob("*.png"))
    test_good = sorted((category_root / "test" / "good").glob("*.png"))
    test_anomalous = sorted(path for path in (category_root / "test").glob("*/*.png") if path.parent.name != "good")
    masks = sorted((category_root / "ground_truth").glob("*/*.png"))
    counts = {
        "train_good_images": len(train_good),
        "test_good_images": len(test_good),
        "test_anomalous_images": len(test_anomalous),
        "ground_truth_masks": len(masks),
    }
    if expected:
        mismatches = {key: (expected[key], actual) for key, actual in counts.items() if expected.get(key) != actual}
        if mismatches:
            raise DatasetIntegrityError(f"dataset counts do not match source descriptor: {mismatches}")
    return counts


def validate_user_dataset(
    dataset_root: Path,
    *,
    category: str,
    source_config: Path | None = None,
    license_acknowledged: bool = False,
) -> dict[str, Any]:
    """Validate an operator-provided MVTec directory without downloading it.

    ``dataset_root`` may be the unpacked MVTec root (containing ``category``)
    or the category directory itself.  No network access is performed.  The
    resulting receipt is intentionally kept beside the local data and is
    suitable for provenance binding in a qualification package.
    """
    root = dataset_root
    if (root / "train").is_dir() and (root / "test").is_dir():
        root = dataset_root.parent
    category_root = root / category
    source: dict[str, Any] = read_json(source_config) if source_config else {}
    expected = source.get("expected")
    counts = validate_dataset_layout(root, category, expected)
    anomaly_images = {
        path.relative_to(root).as_posix(): path
        for path in sorted((category_root / "test").glob("*/*.png"))
        if path.parent.name != "good"
    }
    expected_masks = {
        (category_root / "ground_truth" / path.parent.name / f"{path.stem}_mask.png")
        .relative_to(root)
        .as_posix()
        for path in anomaly_images.values()
    }
    actual_masks = {
        path.relative_to(root).as_posix()
        for path in sorted((category_root / "ground_truth").glob("*/*.png"))
    }
    missing_masks = sorted(expected_masks - actual_masks)
    unexpected_masks = sorted(actual_masks - expected_masks)
    if missing_masks or unexpected_masks:
        raise DatasetIntegrityError(
            "image/mask correspondence mismatch: "
            f"missing masks={missing_masks[:20]}, unexpected masks={unexpected_masks[:20]}"
        )
    allowed_extensions = {".png"}
    allowed_metadata_files = {category_root / "license.txt", category_root / "readme.txt"}
    files = sorted(
        path
        for path in category_root.rglob("*")
        if path.is_file() and path.suffix.lower() not in allowed_extensions and path not in allowed_metadata_files
    )
    if files:
        raise DatasetIntegrityError(
            "MVTec AD image and mask files must be PNG; unsupported files: "
            + ", ".join(str(path.relative_to(root)) for path in files[:20])
        )
    decode_failures: list[str] = []
    file_hashes: list[dict[str, Any]] = []
    for path in sorted(path for path in category_root.rglob("*.png") if path.is_file()):
        try:
            with Image.open(path) as image:
                image.verify()
                width, height = image.size
        except (UnidentifiedImageError, OSError) as exc:
            decode_failures.append(f"{path.relative_to(root)}: {exc}")
            continue
        file_hashes.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
                "width": width,
                "height": height,
            }
        )
    if decode_failures:
        raise DatasetIntegrityError("dataset contains undecodable files: " + "; ".join(decode_failures[:20]))
    if not license_acknowledged:
        raise DatasetIntegrityError(
            "MVTec AD is non-commercial research data; pass --acknowledge-license after reviewing the source license"
        )
    receipt = {
        "schema_version": "visionqc.dataset-directory-receipt.v1",
        "source_type": "OFFICIAL_BENCHMARK",
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "acquisition_date": datetime.now(timezone.utc).date().isoformat(),
        "dataset": "MVTec AD",
        "category": category,
        "dataset_root": str(root.resolve()),
        "source_page": source.get("source_page"),
        "source_config": str(source_config.resolve()) if source_config else None,
        "source_archive_sha256": source.get("archive_sha256"),
        "counts": counts,
        "file_sha256": sha256_json(file_hashes),
        "dataset_summary_sha256": sha256_json({"category": category, "counts": counts, "files": file_hashes}),
        "hash_algorithm": "SHA-256",
        "license": source.get(
            "license",
            {
                "name": "CC BY-NC-SA 4.0",
                "commercial_use": False,
                "notice": "MVTec AD is non-commercial research data; it is not factory production evidence.",
            },
        ),
        "license_acknowledged": True,
        "network_access": False,
    }
    write_json(root / f"{category}.directory-receipt.json", receipt)
    return receipt


def validate_transistor_layout(dataset_root: Path, expected: dict[str, int] | None = None) -> dict[str, int]:
    """Backward-compatible transistor layout validator."""
    return validate_dataset_layout(dataset_root, "transistor", expected)


def download_dataset(
    source_config: Path,
    dataset_root: Path,
    archive_cache: Path,
    *,
    license_acknowledged: bool = False,
    archive_path: Path | None = None,
) -> dict[str, Any]:
    """Download a pinned MVTec archive, verify it, and extract one category only.

    The dataset is never copied into the repository.  The receipt always carries
    the non-commercial license warning and whether the caller explicitly
    acknowledged it, so CI and operators can enforce their own approval gate.
    """
    source = read_json(source_config)
    category = str(source.get("category", "transistor"))
    expected_sha = str(source["archive_sha256"])
    resolved_archive_path = archive_path or (archive_cache / str(source["archive_filename"]))
    if not resolved_archive_path.is_file():
        _stream_download(str(source["archive_url"]), resolved_archive_path)
    actual_sha = sha256_file(resolved_archive_path)
    if actual_sha != expected_sha:
        raise DatasetIntegrityError(f"archive SHA-256 mismatch: expected {expected_sha}, got {actual_sha}")
    _extract_category(resolved_archive_path, dataset_root, category)
    counts = validate_dataset_layout(dataset_root, category, source.get("expected"))
    license_info = dict(source.get("license", {}))
    commercial_use = bool(license_info.get("commercial_use", True))
    warning = (
        f"{license_info.get('name', 'Dataset license')}: commercial use is not permitted by this source descriptor."
        if not commercial_use
        else "Review the dataset license before redistribution or deployment."
    )
    receipt = {
        "schema_version": "visionqc.dataset-download-receipt.v1",
        "source_type": "OFFICIAL_BENCHMARK",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "source_config": str(source_config.resolve()),
        "source_page": source["source_page"],
        "archive_url": source["archive_url"],
        "archive_sha256": actual_sha,
        "archive_path": str(resolved_archive_path.resolve()),
        "extracted_category": category,
        "dataset_root": str(dataset_root.resolve()),
        "counts": counts,
        "license": license_info,
        "license_warning": warning,
        "license_acknowledged": license_acknowledged,
        "commercial_use_allowed": commercial_use,
    }
    write_json(dataset_root / f"{category}.download-receipt.json", receipt)
    return receipt


def download_transistor(source_config: Path, dataset_root: Path, archive_cache: Path) -> dict[str, Any]:
    """Backward-compatible wrapper for the original transistor workflow."""
    return download_dataset(source_config, dataset_root, archive_cache)


def _stable_partition(paths: list[Path], dataset_root: Path, seed: int, validation_ratio: float) -> set[str]:
    if not 0.0 < validation_ratio < 1.0:
        raise ValueError("validation_ratio must be between 0 and 1")
    ranked = sorted(
        paths,
        key=lambda path: hashlib.sha256(f"{seed}:{path.relative_to(dataset_root).as_posix()}".encode()).hexdigest(),
    )
    if len(ranked) == 1:
        validation_count = 0
    else:
        validation_count = min(len(ranked) - 1, max(1, math.floor(len(ranked) * validation_ratio + 0.5)))
    return {path.relative_to(dataset_root).as_posix() for path in ranked[:validation_count]}


def _mask_for_anomaly(image_path: Path, category_root: Path) -> Path:
    return category_root / "ground_truth" / image_path.parent.name / f"{image_path.stem}_mask.png"


def _entry_for_path(
    path: Path,
    dataset_root: Path,
    category: str,
    split: Literal["train", "validation", "test"],
) -> ManifestEntry:
    relative = path.relative_to(dataset_root).as_posix()
    relative_parts = PurePosixPath(relative).parts
    source_split: Literal["train", "test"] = (
        "train" if len(relative_parts) > 1 and relative_parts[1] == "train" else "test"
    )
    subtype = path.parent.name
    label: Literal[0, 1] = 0 if subtype == "good" else 1
    category_root = dataset_root / category
    mask_path = _mask_for_anomaly(path, category_root) if label == 1 else None
    if mask_path is not None and not mask_path.is_file():
        raise DatasetIntegrityError(f"missing ground-truth mask for {relative}: {mask_path}")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
    except (UnidentifiedImageError, OSError) as exc:
        raise DatasetIntegrityError(f"cannot decode image: {relative}") from exc
    return ManifestEntry(
        sample_id=f"sample_{hashlib.sha256(relative.encode()).hexdigest()[:16]}",
        category=category,
        split=split,
        source_split=source_split,
        label=label,
        anomaly_subtype=subtype,
        image_path=relative,
        image_sha256=sha256_file(path),
        mask_path=mask_path.relative_to(dataset_root).as_posix() if mask_path else None,
        mask_sha256=sha256_file(mask_path) if mask_path else None,
        width=width,
        height=height,
    )


def _manifest_line(entry: ManifestEntry) -> str:
    return canonical_json_bytes(entry.model_dump(mode="json")).decode("utf-8")


def generate_manifest(
    dataset_root: Path,
    output_dir: Path,
    seed: int = 20260804,
    validation_ratio: float = 0.5,
    category: str = "transistor",
) -> dict[str, Any]:
    """Hash all files and create an immutable, stratified validation/test split."""
    if not category.strip():
        raise ValueError("category must not be empty")
    validate_dataset_layout(dataset_root, category)
    category_root = dataset_root / category
    train_paths = sorted((category_root / "train" / "good").glob("*.png"))
    test_groups: dict[str, list[Path]] = defaultdict(list)
    for path in sorted((category_root / "test").glob("*/*.png")):
        test_groups[path.parent.name].append(path)

    validation_paths: set[str] = set()
    for paths in test_groups.values():
        validation_paths.update(_stable_partition(paths, dataset_root, seed, validation_ratio))

    entries: list[ManifestEntry] = []
    failures: list[dict[str, str]] = []
    for path, split in [(path, "train") for path in train_paths] + [
        (
            path,
            "validation" if path.relative_to(dataset_root).as_posix() in validation_paths else "test",
        )
        for paths in test_groups.values()
        for path in paths
    ]:
        try:
            entries.append(_entry_for_path(path, dataset_root, category, split))  # type: ignore[arg-type]
        except Exception as exc:
            failures.append({"path": str(path), "error": str(exc), "error_type": type(exc).__name__})

    output_dir.mkdir(parents=True, exist_ok=True)
    failures_path = output_dir / "failures.jsonl"
    failures_path.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in failures),
        encoding="utf-8",
    )
    if failures:
        raise DatasetIntegrityError(f"{len(failures)} dataset files failed validation; see {failures_path}")

    entries.sort(key=lambda item: (item.split, item.image_path))
    manifest_path = output_dir / "manifest.jsonl"
    manifest_path.write_text("".join(_manifest_line(entry) + "\n" for entry in entries), encoding="utf-8")

    content_identity = [
        {
            "image_path": entry.image_path,
            "image_sha256": entry.image_sha256,
            "mask_path": entry.mask_path,
            "mask_sha256": entry.mask_sha256,
        }
        for entry in sorted(entries, key=lambda item: item.image_path)
    ]
    split_hashes = {
        split: sha256_json([entry.model_dump(mode="json") for entry in entries if entry.split == split])
        for split in ("train", "validation", "test")
    }
    manifest_sha = sha256_file(manifest_path)
    meta = {
        "schema_version": "visionqc.dataset-manifest-meta.v1",
        "source_type": "OFFICIAL_BENCHMARK",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": "MVTec AD",
        "category": category,
        "dataset_root": str(dataset_root.resolve()),
        "dataset_fingerprint": sha256_json(content_identity),
        "manifest_sha256": manifest_sha,
        "split_sha256": split_hashes,
        "split_rule": {
            "version": "stratified-path-sha256-v1",
            "seed": seed,
            "validation_ratio": validation_ratio,
            "strata": "anomaly_subtype (good is its own stratum)",
            "test_usage": "holdout; never used for threshold selection",
        },
        "counts": dict(Counter(entry.split for entry in entries)),
        "license": {
            "name": "CC BY-NC-SA 4.0",
            "commercial_use": False,
            "notice": "MVTec AD is a non-commercial research benchmark; review the source license before use.",
        },
    }
    write_json(output_dir / "manifest-meta.json", meta)
    write_json(
        output_dir / "dataset-fingerprint.json",
        {
            "schema_version": "visionqc.dataset-fingerprint.v1",
            "dataset": "MVTec AD",
            "category": category,
            "fingerprint": meta["dataset_fingerprint"],
            "manifest_sha256": manifest_sha,
            "split_sha256": split_hashes,
            "hash_algorithm": "SHA-256",
            "identity_basis": "sorted image and mask relative paths plus content hashes",
            "source_archive_sha256": (
                read_json(dataset_root / f"{category}.download-receipt.json").get("archive_sha256")
                if (dataset_root / f"{category}.download-receipt.json").is_file()
                else None
            ),
        },
    )

    report = {
        "schema_version": "visionqc.dataset-report.v1",
        "manifest_sha256": manifest_sha,
        "counts_by_split_label": dict(sorted(Counter(f"{entry.split}:{entry.label}" for entry in entries).items())),
        "counts_by_split_subtype": dict(
            sorted(Counter(f"{entry.split}:{entry.anomaly_subtype}" for entry in entries).items())
        ),
        "resolutions": dict(sorted(Counter(f"{entry.width}x{entry.height}" for entry in entries).items())),
        "failed_samples": 0,
        "limitations": [
            "MVTec AD is a research benchmark and does not establish factory production performance.",
            "Ground-truth subtype names are used for evaluation stratification only, never as model predictions.",
        ],
    }
    write_json(output_dir / "data-report.json", report)
    return meta


def verify_manifest(manifest_path: Path, dataset_root: Path, meta_path: Path | None = None) -> dict[str, Any]:
    """Re-hash every declared image and mask and verify split fingerprints."""
    entries = load_manifest(manifest_path)
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    mismatches: list[str] = []
    for entry in entries:
        if entry.sample_id in seen_ids:
            mismatches.append(f"duplicate sample_id: {entry.sample_id}")
        seen_ids.add(entry.sample_id)
        if entry.image_path in seen_paths:
            mismatches.append(f"duplicate image_path: {entry.image_path}")
        seen_paths.add(entry.image_path)
        image_path = dataset_root / entry.image_path
        if not image_path.is_file():
            mismatches.append(f"missing image: {entry.image_path}")
        elif sha256_file(image_path) != entry.image_sha256:
            mismatches.append(f"image hash mismatch: {entry.image_path}")
        else:
            try:
                with Image.open(image_path) as image:
                    if image.size != (entry.width, entry.height):
                        mismatches.append(f"image dimensions changed: {entry.image_path}")
            except (UnidentifiedImageError, OSError) as exc:
                mismatches.append(f"image cannot be decoded: {entry.image_path}: {exc}")
        if entry.mask_path:
            mask_path = dataset_root / entry.mask_path
            if not mask_path.is_file():
                mismatches.append(f"missing mask: {entry.mask_path}")
            elif sha256_file(mask_path) != entry.mask_sha256:
                mismatches.append(f"mask hash mismatch: {entry.mask_path}")
    if mismatches:
        raise ManifestError("; ".join(mismatches[:20]))

    result: dict[str, Any] = {
        "valid": True,
        "entries": len(entries),
        "manifest_sha256": sha256_file(manifest_path),
        "counts": dict(Counter(entry.split for entry in entries)),
    }
    if meta_path:
        meta = read_json(meta_path)
        if result["manifest_sha256"] != meta["manifest_sha256"]:
            raise ManifestError("manifest digest does not match manifest-meta.json")
        if meta.get("category") and {entry.category for entry in entries} != {meta["category"]}:
            raise ManifestError("manifest categories do not match manifest-meta.json")
        content_identity = [
            {
                "image_path": entry.image_path,
                "image_sha256": entry.image_sha256,
                "mask_path": entry.mask_path,
                "mask_sha256": entry.mask_sha256,
            }
            for entry in sorted(entries, key=lambda item: item.image_path)
        ]
        if sha256_json(content_identity) != meta["dataset_fingerprint"]:
            raise ManifestError("dataset fingerprint does not match manifest content")
        actual_split_hashes = {
            split: sha256_json([entry.model_dump(mode="json") for entry in entries if entry.split == split])
            for split in ("train", "validation", "test")
        }
        if actual_split_hashes != meta["split_sha256"]:
            raise ManifestError("split hashes do not match manifest-meta.json")
        result["dataset_fingerprint"] = meta["dataset_fingerprint"]
    return result
