"""Controlled dataset import and source fingerprinting.

Raw datasets live in configured object storage, never in Git or frontend
static assets.  This module validates archive members before storing them and
uses streaming copies with explicit compressed/uncompressed limits.
"""

from __future__ import annotations

import hashlib
import json
import tarfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from app.storage import ObjectStorage

ALLOWED_ARCHIVE_SUFFIXES = {".zip", ".tar", ".gz", ".tgz", ".xz", ".txz"}
OFFICIAL_IMAGE_SUFFIXES = {".png"}
CUSTOMER_FILE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".json", ".csv"}


class DatasetImportError(ValueError):
    """Raised when an import cannot satisfy the dataset source contract."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _digest_stream(source: Any, *, max_bytes: int) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    while block := source.read(1024 * 1024):
        size += len(block)
        if size > max_bytes:
            raise DatasetImportError("dataset source exceeds the configured compressed size limit")
        digest.update(block)
    return digest.hexdigest(), size


def _safe_member_path(name: str) -> PurePosixPath:
    # Archive names are POSIX paths even when an archive was produced on a
    # Windows host.  Normalising the separator before checking prevents a
    # ``..\\outside`` member from bypassing the traversal guard.
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise DatasetImportError(f"archive member path is unsafe: {name}")
    return path


def _category_relative(path: PurePosixPath, category: str) -> PurePosixPath | None:
    try:
        index = path.parts.index(category)
    except ValueError:
        return None
    relative = PurePosixPath(*path.parts[index:])
    return relative


def _validate_official_members(
    members: list[dict[str, Any]],
    *,
    source_type: str,
    category: str,
    max_files: int,
    max_uncompressed_bytes: int,
) -> dict[str, Any]:
    if len(members) > max_files:
        raise DatasetImportError("archive contains too many members")
    selected = [item for item in members if item.get("relative_path")]
    if not selected:
        raise DatasetImportError(f"archive contains no {category} members")
    total = sum(int(item.get("size_bytes", 0)) for item in selected)
    if total > max_uncompressed_bytes:
        raise DatasetImportError("archive uncompressed size exceeds the configured limit")
    paths = {str(item["relative_path"]) for item in selected}
    if len(paths) != len(selected):
        raise DatasetImportError("archive contains duplicate canonical member paths")
    if source_type == "OFFICIAL_BENCHMARK":
        required_prefixes = {
            f"{category}/train/good/",
            f"{category}/test/good/",
            f"{category}/ground_truth/",
        }
        if not all(any(path.startswith(prefix) for path in paths) for prefix in required_prefixes):
            raise DatasetImportError(
                "official benchmark archive does not contain the required MVTec layout"
            )
        invalid = [
            path
            for path in paths
            if Path(path).suffix.lower() not in OFFICIAL_IMAGE_SUFFIXES
            and not (
                len(PurePosixPath(path).parts) == 2
                and PurePosixPath(path).name in {"license.txt", "readme.txt"}
            )
        ]
        if invalid:
            raise DatasetImportError(
                "official benchmark archive may contain PNG images and "
                "category license metadata only"
            )
        allowed_suffixes: set[str] | None = None
    else:
        allowed_suffixes = CUSTOMER_FILE_SUFFIXES
    if allowed_suffixes is not None and any(
        Path(path).suffix.lower() not in allowed_suffixes for path in paths
    ):
        raise DatasetImportError("dataset archive contains a file extension outside the allow-list")
    manifest = sorted(
        (
            {
                "path": str(item["relative_path"]),
                "sha256": str(item["sha256"]),
                "size_bytes": int(item["size_bytes"]),
            }
            for item in selected
        ),
        key=lambda item: str(item["path"]),
    )
    manifest_sha256 = hashlib.sha256(_canonical_json(manifest)).hexdigest()
    return {
        "manifest_sha256": manifest_sha256,
        "dataset_fingerprint": hashlib.sha256(
            _canonical_json(
                {"source_type": source_type, "category": category, "manifest": manifest}
            )
        ).hexdigest(),
        "file_count": len(manifest),
        "total_bytes": total,
        "manifest": manifest,
    }


def _inspect_archive(
    path: Path,
    *,
    source_type: str,
    category: str,
    max_files: int,
    max_uncompressed_bytes: int,
    max_compression_ratio: float,
) -> dict[str, Any]:
    suffix = path.name.lower()
    if not any(suffix.endswith(extension) for extension in ALLOWED_ARCHIVE_SUFFIXES):
        raise DatasetImportError("dataset archive extension is not allowed")
    members: list[dict[str, Any]] = []
    try:
        if suffix.endswith(".zip"):
            with zipfile.ZipFile(path) as archive:
                zip_infos = archive.infolist()
                if len(zip_infos) > max_files:
                    raise DatasetImportError("archive contains too many members")
                total = 0
                for zip_info in zip_infos:
                    zip_member_path = _safe_member_path(zip_info.filename)
                    if zip_info.is_dir():
                        continue
                    mode = (zip_info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise DatasetImportError(
                            f"archive links are not allowed: {zip_info.filename}"
                        )
                    total += zip_info.file_size
                    if total > max_uncompressed_bytes:
                        raise DatasetImportError(
                            "archive uncompressed size exceeds the configured limit"
                        )
                    relative = (
                        _category_relative(zip_member_path, category)
                        if source_type == "OFFICIAL_BENCHMARK"
                        else zip_member_path
                    )
                    if relative is None:
                        continue
                    with archive.open(zip_info) as source:
                        digest, size = _digest_stream(source, max_bytes=max_uncompressed_bytes)
                    members.append(
                        {"relative_path": relative, "sha256": digest, "size_bytes": size}
                    )
        else:
            with tarfile.open(path, mode="r:*") as archive:
                tar_infos = archive.getmembers()
                if len(tar_infos) > max_files:
                    raise DatasetImportError("archive contains too many members")
                total = 0
                for tar_info in tar_infos:
                    tar_member_path = _safe_member_path(tar_info.name)
                    if tar_info.isdir():
                        continue
                    if tar_info.issym() or tar_info.islnk() or not tar_info.isfile():
                        raise DatasetImportError(
                            f"archive links or special files are not allowed: {tar_info.name}"
                        )
                    total += tar_info.size
                    if total > max_uncompressed_bytes:
                        raise DatasetImportError(
                            "archive uncompressed size exceeds the configured limit"
                        )
                    relative = (
                        _category_relative(tar_member_path, category)
                        if source_type == "OFFICIAL_BENCHMARK"
                        else tar_member_path
                    )
                    if relative is None:
                        continue
                    tar_source = archive.extractfile(tar_info)
                    if tar_source is None:
                        raise DatasetImportError(f"cannot read archive member: {tar_info.name}")
                    with tar_source:
                        digest, size = _digest_stream(tar_source, max_bytes=max_uncompressed_bytes)
                    members.append(
                        {"relative_path": relative, "sha256": digest, "size_bytes": size}
                    )
    except (tarfile.TarError, zipfile.BadZipFile, OSError) as exc:
        raise DatasetImportError(f"dataset archive cannot be inspected: {exc}") from exc
    result = _validate_official_members(
        members,
        source_type=source_type,
        category=category,
        max_files=max_files,
        max_uncompressed_bytes=max_uncompressed_bytes,
    )
    compressed_size = max(1, path.stat().st_size)
    if result["total_bytes"] > compressed_size * max_compression_ratio:
        raise DatasetImportError("archive compression ratio exceeds the configured safety limit")
    return result


def _inspect_directory(
    path: Path, *, source_type: str, category: str, max_files: int, max_bytes: int
) -> dict[str, Any]:
    if not path.is_dir():
        raise DatasetImportError("dataset directory does not exist")
    category_directory = path / category
    root = category_directory if category_directory.is_dir() else path
    is_category_root = root == path and source_type == "OFFICIAL_BENCHMARK"
    files: list[dict[str, Any]] = []
    total = 0
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise DatasetImportError(f"dataset symlinks are not allowed: {item}")
        if not item.is_file():
            continue
        relative = (
            f"{category}/{item.relative_to(root).as_posix()}"
            if is_category_root or root != path
            else item.relative_to(path).as_posix()
        )
        if (
            source_type == "OFFICIAL_BENCHMARK"
            and Path(relative).suffix.lower() not in OFFICIAL_IMAGE_SUFFIXES
        ):
            if Path(relative).name not in {"license.txt", "readme.txt"}:
                raise DatasetImportError(
                    "official benchmark directory may contain PNG images and license metadata only"
                )
        elif (
            source_type == "CUSTOMER_PILOT"
            and Path(relative).suffix.lower() not in CUSTOMER_FILE_SUFFIXES
        ):
            raise DatasetImportError(f"customer dataset file extension is not allowed: {relative}")
        total += item.stat().st_size
        if len(files) >= max_files or total > max_bytes:
            raise DatasetImportError("dataset directory exceeds the configured file or size limit")
        with item.open("rb") as source:
            digest, size = _digest_stream(source, max_bytes=max_bytes)
        files.append({"path": relative, "sha256": digest, "size_bytes": size})
    if not files:
        raise DatasetImportError("dataset directory contains no allowed files")
    if source_type == "OFFICIAL_BENCHMARK":
        required = [f"{category}/train/good", f"{category}/test/good", f"{category}/ground_truth"]
        paths = {item["path"] for item in files}
        if not all(any(path.startswith(prefix + "/") for path in paths) for prefix in required):
            raise DatasetImportError(
                "official benchmark directory does not contain the required MVTec layout"
            )
    manifest_sha256 = hashlib.sha256(_canonical_json(files)).hexdigest()
    return {
        "manifest_sha256": manifest_sha256,
        "dataset_fingerprint": hashlib.sha256(
            _canonical_json({"source_type": source_type, "category": category, "manifest": files})
        ).hexdigest(),
        "file_count": len(files),
        "total_bytes": total,
        "manifest": files,
    }


def inspect_dataset_source(
    path: Path,
    *,
    source_type: str,
    category: str,
    max_files: int,
    max_bytes: int,
    max_uncompressed_bytes: int,
    max_compression_ratio: float,
) -> dict[str, Any]:
    """Inspect a mounted path before any raw bytes enter object storage."""
    requested = path.expanduser()
    if requested.is_symlink():
        raise DatasetImportError("dataset source root symlinks are not allowed")
    resolved = requested.resolve()
    if not resolved.exists():
        raise DatasetImportError(f"dataset source does not exist: {resolved}")
    if resolved.is_file():
        with resolved.open("rb") as source:
            source_sha256, source_size = _digest_stream(source, max_bytes=max_bytes)
        manifest = _inspect_archive(
            resolved,
            source_type=source_type,
            category=category,
            max_files=max_files,
            max_uncompressed_bytes=max_uncompressed_bytes,
            max_compression_ratio=max_compression_ratio,
        )
        return {
            "source_path": str(resolved),
            "source_sha256": source_sha256,
            "source_size_bytes": source_size,
            **manifest,
        }
    manifest = _inspect_directory(
        resolved,
        source_type=source_type,
        category=category,
        max_files=max_files,
        max_bytes=max_bytes,
    )
    return {
        "source_path": str(resolved),
        "source_sha256": None,
        "source_size_bytes": manifest["total_bytes"],
        **manifest,
    }


def store_dataset_source(
    path: Path,
    *,
    tenant_id: str,
    registration_id: str,
    source_type: str,
    category: str,
    storage: ObjectStorage,
    inspection: dict[str, Any],
    max_bytes: int,
) -> tuple[str, str]:
    """Store the validated source and its immutable manifest using streaming copies."""
    base_key = f"datasets/{tenant_id}/{registration_id}"
    source_path = Path(str(inspection["source_path"]))
    if source_path.is_file():
        with source_path.open("rb") as source:
            uri, digest, _size = storage.put_stream(
                f"{base_key}/source/{source_path.name}",
                source,
                "application/octet-stream",
                max_bytes=max_bytes,
            )
        if digest != inspection["source_sha256"]:
            raise DatasetImportError("dataset source changed during import")
        manifest_uri = storage.put_immutable(
            f"{base_key}/manifest.json",
            _canonical_json({"source_type": source_type, "category": category, **inspection}),
            "application/json",
        )
        return uri, manifest_uri

    for item in inspection["manifest"]:
        relative_path = PurePosixPath(str(item["path"]))
        file_path = source_path.joinpath(*relative_path.parts)
        # A caller may mount the category directory itself rather than the
        # MVTec dataset root.  The manifest keeps the canonical category
        # prefix, so resolve that prefix only when the direct path is absent.
        if not file_path.is_file() and relative_path.parts[:1] == (category,):
            file_path = source_path.joinpath(*relative_path.parts[1:])
        if not file_path.is_file() or not file_path.resolve().is_relative_to(source_path.resolve()):
            raise DatasetImportError(
                f"dataset source member is outside the mounted source: {item['path']}"
            )
        with file_path.open("rb") as source:
            _uri, digest, _size = storage.put_stream(
                f"{base_key}/source/{item['path']}",
                source,
                "application/octet-stream",
                max_bytes=max_bytes,
            )
        if digest != item["sha256"]:
            raise DatasetImportError(f"dataset source changed during import: {item['path']}")
    manifest_uri = storage.put_immutable(
        f"{base_key}/manifest.json",
        _canonical_json({"source_type": source_type, "category": category, **inspection}),
        "application/json",
    )
    return manifest_uri, manifest_uri
