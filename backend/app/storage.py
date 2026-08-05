from __future__ import annotations

import hashlib
import io
import tempfile
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath
from typing import BinaryIO

import boto3  # type: ignore[import-untyped]
from botocore.exceptions import ClientError  # type: ignore[import-untyped]

from app.config import Settings


class ObjectAlreadyExists(RuntimeError):
    pass


class ObjectStorage(ABC):
    @abstractmethod
    def put_immutable(self, key: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    @abstractmethod
    def put_stream(
        self, key: str, source: BinaryIO, content_type: str, *, max_bytes: int | None = None
    ) -> tuple[str, str, int]:
        """Stream an immutable object and return ``(uri, sha256, size_bytes)``."""
        raise NotImplementedError

    @abstractmethod
    def get(self, uri: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def healthcheck(self) -> bool:
        raise NotImplementedError


def safe_key(key: str) -> str:
    path = PurePosixPath(key)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise ValueError("unsafe object key")
    return str(path)


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


class LocalObjectStorage(ObjectStorage):
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def put_immutable(self, key: str, data: bytes, content_type: str) -> str:
        del content_type
        uri, _digest, _size = self.put_stream(key, io.BytesIO(data), "application/octet-stream")
        return uri

    def put_stream(
        self, key: str, source: BinaryIO, content_type: str, *, max_bytes: int | None = None
    ) -> tuple[str, str, int]:
        del content_type
        normalized = safe_key(key)
        path = (self.root / normalized).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("object key escapes storage root")
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(path.suffix + ".partial")
        digest = hashlib.sha256()
        size = 0
        try:
            with partial.open("wb") as handle:
                while block := source.read(1024 * 1024):
                    size += len(block)
                    if max_bytes is not None and size > max_bytes:
                        raise ValueError("object exceeds the configured size limit")
                    digest.update(block)
                    handle.write(block)
            computed = digest.hexdigest()
            if path.exists():
                if _sha256_path(path) != computed:
                    raise ObjectAlreadyExists(normalized)
                partial.unlink(missing_ok=True)
            else:
                partial.replace(path)
        except Exception:
            partial.unlink(missing_ok=True)
            raise
        return f"local://{normalized}", computed, size

    def get(self, uri: str) -> bytes:
        if not uri.startswith("local://"):
            raise ValueError("unsupported local storage URI")
        normalized = safe_key(uri.removeprefix("local://"))
        path = (self.root / normalized).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("object URI escapes storage root")
        return path.read_bytes()

    def healthcheck(self) -> bool:
        return self.root.exists() and self.root.is_dir()


class S3ObjectStorage(ObjectStorage):
    def __init__(self, settings: Settings):
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=(
                settings.s3_access_key.get_secret_value() if settings.s3_access_key else None
            ),
            aws_secret_access_key=(
                settings.s3_secret_key.get_secret_value() if settings.s3_secret_key else None
            ),
            region_name=settings.s3_region,
        )

    def put_immutable(self, key: str, data: bytes, content_type: str) -> str:
        normalized = safe_key(key)
        uri, _digest, _size = self.put_stream(normalized, io.BytesIO(data), content_type)
        return uri

    def put_stream(
        self, key: str, source: BinaryIO, content_type: str, *, max_bytes: int | None = None
    ) -> tuple[str, str, int]:
        normalized = safe_key(key)
        digest = hashlib.sha256()
        size = 0
        with tempfile.NamedTemporaryFile(prefix="visionqc-object-", suffix=".partial") as temporary:
            while block := source.read(1024 * 1024):
                size += len(block)
                if max_bytes is not None and size > max_bytes:
                    raise ValueError("object exceeds the configured size limit")
                digest.update(block)
                temporary.write(block)
            temporary.flush()
            temporary.seek(0)
            computed = digest.hexdigest()
            try:
                existing = self.client.head_object(Bucket=self.bucket, Key=normalized)
            except ClientError as exc:
                if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") != 404:
                    raise
                existing = None
            if existing is not None:
                if existing.get("Metadata", {}).get("sha256") != computed:
                    raise ObjectAlreadyExists(normalized)
            else:
                self.client.upload_fileobj(
                    temporary,
                    self.bucket,
                    normalized,
                    ExtraArgs={"ContentType": content_type, "Metadata": {"sha256": computed}},
                )
        return f"s3://{self.bucket}/{normalized}", computed, size

    def get(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("object URI is outside configured bucket")
        key = safe_key(uri.removeprefix(prefix))
        return bytes(self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read())

    def healthcheck(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError:
            return False


def build_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "s3":
        return S3ObjectStorage(settings)
    return LocalObjectStorage(settings.local_storage_path)
