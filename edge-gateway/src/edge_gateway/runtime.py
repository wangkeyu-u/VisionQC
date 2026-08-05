from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edge_gateway.config import GatewaySettings
from edge_gateway.deployment import GatewayDeploymentPack, normalize_captured_at
from edge_gateway.quality import QualityReject, assess_image
from edge_gateway.queue import QueueItem, QueueStore, QueueSummary
from edge_gateway.uploader import BackendUploader, UploadError, deterministic_idempotency_key

logger = logging.getLogger("visionqc.edge_gateway")


@dataclass
class _Observation:
    size: int
    mtime_ns: int
    first_seen_monotonic: float
    emitted_fingerprint: str | None = None


@dataclass(frozen=True)
class ParsedFile:
    context: dict[str, str]
    source_path: Path


class DirectoryWatcher:
    def __init__(
        self,
        root: Path,
        *,
        stable_for_seconds: float,
        allowed_extensions: set[str],
        excluded_dirs: set[str],
    ):
        self.root = root
        self.stable_for_seconds = stable_for_seconds
        self.allowed_extensions = allowed_extensions
        self.excluded_dirs = excluded_dirs
        self._observations: dict[str, _Observation] = {}
        self.root.mkdir(parents=True, exist_ok=True)

    def _iter_files(self) -> list[Path]:
        files: list[Path] = []
        for path in self.root.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in self.allowed_extensions:
                continue
            try:
                relative_parts = path.relative_to(self.root).parts
            except ValueError:
                continue
            if any(part in self.excluded_dirs for part in relative_parts):
                continue
            files.append(path)
        return sorted(files)

    def stable_files(self, now_monotonic: float | None = None) -> list[Path]:
        now = now_monotonic if now_monotonic is not None else time.monotonic()
        current_paths: set[str] = set()
        stable: list[Path] = []
        for path in self._iter_files():
            key = str(path.resolve())
            current_paths.add(key)
            try:
                stat = path.stat()
            except OSError:
                continue
            observation = self._observations.get(key)
            if (
                observation is None
                or observation.size != stat.st_size
                or observation.mtime_ns != stat.st_mtime_ns
            ):
                self._observations[key] = _Observation(
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    first_seen_monotonic=now,
                )
                continue
            if now - observation.first_seen_monotonic < self.stable_for_seconds:
                continue
            fingerprint = f"{stat.st_size}:{stat.st_mtime_ns}"
            if observation.emitted_fingerprint == fingerprint:
                continue
            observation.emitted_fingerprint = fingerprint
            stable.append(path)

        for key in set(self._observations) - current_paths:
            del self._observations[key]
        return stable

    def reset(self, path: Path) -> None:
        observation = self._observations.get(str(path.resolve()))
        if observation is not None:
            observation.emitted_fingerprint = None


class GatewayRuntime:
    def __init__(
        self,
        settings: GatewaySettings,
        pack: GatewayDeploymentPack,
        *,
        queue: QueueStore | None = None,
        uploader: BackendUploader | None = None,
    ):
        self.settings = settings
        self.pack = pack
        self.gateway_id = (
            pack.gateway_id if settings.gateway_id == "gateway-local" else settings.gateway_id
        )
        watch = pack.edge_gateway.watch
        root = settings.resolved_watch_root(watch.root)
        stable_for = (
            settings.stable_for_seconds
            if settings.stable_for_seconds is not None
            else watch.stable_for_seconds
        )
        self.watcher = DirectoryWatcher(
            root,
            stable_for_seconds=stable_for,
            allowed_extensions=watch.normalized_extensions,
            excluded_dirs={watch.archive_subdir, watch.quarantine_subdir},
        )
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.spool_dir = settings.data_dir / "spool"
        self.spool_dir.mkdir(parents=True, exist_ok=True)
        self.queue = queue or QueueStore(settings.resolved_database_path)
        self.uploader = uploader or BackendUploader(settings, pack)
        self._last_heartbeat_monotonic = 0.0
        self._last_heartbeat_at: str | None = None
        self._backend_reachable = False
        self._last_success_at: str | None = None
        self._last_failure_at: str | None = None
        self._last_error: dict[str, Any] | None = None
        self.queue.recover_inflight()

    def close(self) -> None:
        self.uploader.close()

    def _source_fingerprint(self, path: Path) -> str:
        stat = path.stat()
        return hashlib.sha256(
            f"{path.resolve()}|{stat.st_size}|{stat.st_mtime_ns}".encode()
        ).hexdigest()

    def _parse_file(self, path: Path) -> ParsedFile:
        watch = self.pack.edge_gateway.watch
        relative_parent = path.parent.relative_to(self.watcher.root).as_posix()
        if relative_parent == ".":
            relative_parent = ""
        path_match = re.fullmatch(watch.relative_path_regex, relative_parent)
        name_match = re.fullmatch(watch.filename_regex, path.name)
        if path_match is None or name_match is None:
            raise QualityReject(
                "FILENAME_OR_PATH_UNRECOGNIZED",
                "文件路径或命名不符合当前 Deployment Pack 的工位规则。",
                {"relative_parent": relative_parent, "filename": path.name},
            )
        groups = {**path_match.groupdict(), **name_match.groupdict()}
        values = dict(watch.defaults)
        for canonical, group_name in watch.capture_map.items():
            captured = groups.get(group_name)
            if captured:
                values[canonical] = captured
        required = ("product_code", "batch_no", "station_code", "captured_at")
        missing = [name for name in required if not values.get(name)]
        if missing:
            raise QualityReject(
                "CONTEXT_INCOMPLETE",
                "无法从目录/文件名补全必填业务上下文，未上传。",
                {"missing_fields": missing},
            )
        product = self.pack.resolve_product(values["product_code"])
        station = self.pack.resolve_station(values["station_code"])
        if product is None:
            raise QualityReject(
                "PRODUCT_NOT_IN_PACK",
                "文件中的产品不是当前 Deployment Pack 允许的产品。",
                {"product_code": values["product_code"]},
            )
        if station is None:
            raise QualityReject(
                "STATION_NOT_IN_PACK",
                "文件路径中的工位不是当前 Deployment Pack 允许的工位。",
                {"station_code": values["station_code"]},
            )
        values["product_code"] = product.code
        values["station_code"] = station.code
        values["captured_at"] = normalize_captured_at(values["captured_at"], watch)
        values.setdefault("product_revision", product.revision)
        values["source"] = values.get("source") or watch.source
        return ParsedFile(
            context={key: str(value) for key, value in values.items()}, source_path=path
        )

    def _atomic_spool(self, assessment_sha256: str, extension: str, data: bytes) -> Path:
        destination = self.spool_dir / f"{assessment_sha256}.{extension}"
        if destination.exists():
            if destination.read_bytes() != data:
                raise RuntimeError("spool hash collision detected")
            return destination
        temporary = self.spool_dir / f".{assessment_sha256}.{extension}.{os.getpid()}.tmp"
        with temporary.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            temporary.replace(destination)
        except FileExistsError:
            temporary.unlink(missing_ok=True)
        return destination

    def _archive_source(self, path: Path, subdir: str) -> None:
        try:
            relative = path.relative_to(self.watcher.root)
            destination = self.watcher.root / subdir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            path.replace(destination)
        except (OSError, ValueError) as exc:
            logger.warning("could not move processed source %s: %s", path, exc)

    def _set_error(self, code: str, message: str, *, status: str) -> None:
        self._last_error = {
            "code": code,
            "message": message,
            "status": status,
            "at": datetime.now(UTC).isoformat(),
        }
        self._last_failure_at = self._last_error["at"]

    def scan_once(self) -> list[QueueItem]:
        """Detect stable files and persist either a queued item or a rejection."""

        accepted: list[QueueItem] = []
        for path in self.watcher.stable_files():
            try:
                before = path.stat()
                data = path.read_bytes()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise QualityReject(
                        "FILE_STILL_WRITING", "文件在读取期间仍发生变化，等待下一次稳定检查。"
                    )
                source_fingerprint = self._source_fingerprint(path)
                if self.queue.find_source(source_fingerprint) is not None:
                    continue
                assessment = assess_image(data, path.name, self.settings)
                parsed = self._parse_file(path)
                idempotency = deterministic_idempotency_key(
                    tenant_id=self.pack.tenant_id,
                    pack_key=self.pack.pack_key,
                    pack_version=self.pack.version,
                    content_sha256=assessment.sha256,
                    context=parsed.context,
                )
                spool = self._atomic_spool(assessment.sha256, assessment.extension, data)
                item = self.queue.enqueue(
                    gateway_id=self.gateway_id,
                    tenant_id=self.pack.tenant_id,
                    pack_key=self.pack.pack_key,
                    pack_version=self.pack.version,
                    source_path=str(path),
                    source_fingerprint=source_fingerprint,
                    spool_path=str(spool),
                    original_filename=path.name,
                    content_sha256=assessment.sha256,
                    mime_type=assessment.mime_type,
                    width=assessment.width,
                    height=assessment.height,
                    context=parsed.context,
                    idempotency_key=idempotency,
                )
                accepted.append(item)
                self._archive_source(path, self.pack.edge_gateway.watch.archive_subdir)
            except QualityReject as exc:
                if exc.code == "FILE_STILL_WRITING":
                    # This is a transient stability race, not an auditable
                    # input rejection. Re-arm the observation for the next
                    # unchanged-size window.
                    self.watcher.reset(path)
                    self._set_error(exc.code, exc.reason, status="RETRYING")
                    continue
                try:
                    source_fingerprint = self._source_fingerprint(path)
                except OSError:
                    source_fingerprint = hashlib.sha256(str(path).encode()).hexdigest()
                item = self.queue.record_rejection(
                    gateway_id=self.gateway_id,
                    tenant_id=self.pack.tenant_id,
                    pack_key=self.pack.pack_key,
                    pack_version=self.pack.version,
                    source_path=str(path),
                    source_fingerprint=source_fingerprint,
                    original_filename=path.name,
                    error_code=exc.code,
                    rejection_reason=exc.reason,
                    content_sha256=None,
                )
                self._last_error = {
                    "code": exc.code,
                    "message": exc.reason,
                    "status": "REJECTED",
                    "queue_id": item.id,
                    "metrics": exc.metrics,
                    "at": datetime.now(UTC).isoformat(),
                }
                self._last_failure_at = self._last_error["at"]
                if path.exists():
                    self._archive_source(path, self.pack.edge_gateway.watch.quarantine_subdir)
            except (OSError, RuntimeError) as exc:
                # A local spool or filesystem failure must not leave the
                # observation marked as emitted; keep the source in place so
                # the next cycle can retry it instead of silently losing it.
                self.watcher.reset(path)
                self._set_error("LOCAL_INGEST_ERROR", str(exc), status="FAILED")
                logger.exception("local ingest failed for %s", path)
        return accepted

    def upload_once(self) -> QueueItem | None:
        item = self.queue.claim_due()
        if item is None:
            return None
        if not item.spool_path:
            self.queue.mark_failed(
                item.id,
                error_code="SPOOL_MISSING",
                error="队列项没有本地 spool 文件，保留为失败项等待人工处理。",
                retryable=False,
            )
            self._set_error("SPOOL_MISSING", "队列项没有本地 spool 文件。", status="FAILED")
            return self.queue.get(item.id)
        try:
            data = Path(item.spool_path).read_bytes()
            result = self.uploader.upload(item, data)
        except UploadError as exc:
            delay = min(3600.0, 2.0 ** min(item.attempts, 10))
            updated = self.queue.mark_failed(
                item.id,
                error_code=exc.code,
                error=exc.message,
                retryable=exc.retryable,
                retry_delay_seconds=delay,
            )
            self._set_error(exc.code, exc.message, status="FAILED")
            return updated
        except OSError as exc:
            updated = self.queue.mark_failed(
                item.id,
                error_code="SPOOL_READ_ERROR",
                error=str(exc),
                retryable=False,
            )
            self._set_error("SPOOL_READ_ERROR", str(exc), status="FAILED")
            return updated
        updated = self.queue.mark_uploaded(item.id, result.inspection_id)
        self._last_success_at = datetime.now(UTC).isoformat()
        self._last_error = None
        return updated

    def _reported_status(self, summary: QueueSummary) -> str:
        if self._last_error and self._last_error.get("status") == "FAILED":
            return "DEGRADED"
        if summary.counts.get("FAILED", 0) > 0 or summary.depth > 0:
            return "DEGRADED"
        return "ONLINE"

    def heartbeat_once(self, *, force: bool = False) -> bool:
        now = time.monotonic()
        if (
            not force
            and now - self._last_heartbeat_monotonic < self.settings.heartbeat_interval_seconds
        ):
            return self._backend_reachable
        summary = self.queue.summary()
        payload = {
            "gateway_id": self.gateway_id,
            "gateway_version": self.settings.version,
            "station_code": self.pack.edge_gateway.watch.defaults.get("station_code", "*"),
            "reported_status": self._reported_status(summary),
            "queue_depth": summary.depth,
            "last_error": (self._last_error or {}).get("message"),
            "upload_success_count": summary.counts.get("UPLOADED", 0),
            "upload_failure_count": summary.counts.get("FAILED", 0),
            "deployment_pack_key": self.pack.pack_key,
            "deployment_pack_version": self.pack.version,
            "metrics": {"queue_counts": summary.counts},
        }
        self._backend_reachable = self.uploader.heartbeat(payload)
        self._last_heartbeat_monotonic = now
        self._last_heartbeat_at = datetime.now(UTC).isoformat()
        if self._backend_reachable:
            if (self._last_error or {}).get("code") == "HEARTBEAT_FAILED":
                self._last_error = None
        else:
            self._set_error(
                "HEARTBEAT_FAILED", "后端心跳失败，网关继续保留本地队列。", status="FAILED"
            )
        return self._backend_reachable

    def run_cycle(self) -> dict[str, Any]:
        accepted = self.scan_once()
        uploaded = self.upload_once()
        self.heartbeat_once()
        return {
            "accepted": len(accepted),
            "uploaded": bool(uploaded and uploaded.status == "UPLOADED"),
            "queue": self.status_payload(),
        }

    def status_payload(self) -> dict[str, Any]:
        summary = self.queue.summary()
        return {
            "gateway_id": self.gateway_id,
            "tenant_id": self.pack.tenant_id,
            "pack_key": self.pack.pack_key,
            "pack_version": self.pack.version,
            "gateway_version": self.settings.version,
            "station_code": self.pack.edge_gateway.watch.defaults.get("station_code", "*"),
            "status": self._reported_status(summary),
            "backend_reachable": self._backend_reachable,
            "queue_depth": summary.depth,
            "queue_counts": summary.counts,
            "last_heartbeat_at": self._last_heartbeat_at,
            "last_upload_succeeded_at": self._last_success_at,
            "last_upload_failed_at": self._last_failure_at,
            "recent_error": self._last_error,
            "recent_errors": summary.recent_errors,
        }
