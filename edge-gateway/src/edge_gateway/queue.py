from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


@dataclass(frozen=True)
class QueueItem:
    id: int
    gateway_id: str
    tenant_id: str
    pack_key: str
    pack_version: str
    source_path: str
    source_fingerprint: str
    spool_path: str | None
    original_filename: str
    content_sha256: str | None
    mime_type: str | None
    width: int | None
    height: int | None
    context: dict[str, str]
    idempotency_key: str | None
    status: str
    attempts: int
    next_attempt_at: str | None
    last_error: str | None
    error_code: str | None
    rejection_reason: str | None
    inspection_id: str | None
    dedup_of_id: int | None
    retryable: bool
    created_at: str
    updated_at: str
    uploaded_at: str | None


@dataclass(frozen=True)
class QueueSummary:
    depth: int
    counts: dict[str, int]
    recent_errors: list[dict[str, Any]]


class QueueStore:
    """Crash-safe local queue and audit ledger.

    SQLite WAL plus one row per source observation means a process restart can
    recover an in-flight upload without re-reading a half-written source file
    or creating another backend detection.
    """

    def __init__(self, path: Path):
        self.path = path
        if str(path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS queue_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    gateway_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    pack_key TEXT NOT NULL,
                    pack_version TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    source_fingerprint TEXT NOT NULL UNIQUE,
                    spool_path TEXT,
                    original_filename TEXT NOT NULL,
                    content_sha256 TEXT,
                    mime_type TEXT,
                    width INTEGER,
                    height INTEGER,
                    context_json TEXT NOT NULL,
                    idempotency_key TEXT,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TEXT,
                    next_attempt_at TEXT,
                    last_error TEXT,
                    error_code TEXT,
                    rejection_reason TEXT,
                    inspection_id TEXT,
                    dedup_of_id INTEGER,
                    retryable INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    uploaded_at TEXT,
                    FOREIGN KEY(dedup_of_id) REFERENCES queue_items(id)
                );
                CREATE INDEX IF NOT EXISTS ix_queue_due
                    ON queue_items(status, retryable, next_attempt_at, created_at);
                CREATE INDEX IF NOT EXISTS ix_queue_idempotency
                    ON queue_items(tenant_id, idempotency_key);
                CREATE INDEX IF NOT EXISTS ix_queue_errors
                    ON queue_items(status, updated_at);
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("PRAGMA table_info(queue_items)").fetchall()
            }
            if "last_attempt_at" not in columns:
                connection.execute("ALTER TABLE queue_items ADD COLUMN last_attempt_at TEXT")

    def _row(self, row: sqlite3.Row | None) -> QueueItem | None:
        if row is None:
            return None
        raw_context = json.loads(str(row["context_json"]))
        return QueueItem(
            id=int(row["id"]),
            gateway_id=str(row["gateway_id"]),
            tenant_id=str(row["tenant_id"]),
            pack_key=str(row["pack_key"]),
            pack_version=str(row["pack_version"]),
            source_path=str(row["source_path"]),
            source_fingerprint=str(row["source_fingerprint"]),
            spool_path=str(row["spool_path"]) if row["spool_path"] else None,
            original_filename=str(row["original_filename"]),
            content_sha256=str(row["content_sha256"]) if row["content_sha256"] else None,
            mime_type=str(row["mime_type"]) if row["mime_type"] else None,
            width=int(row["width"]) if row["width"] is not None else None,
            height=int(row["height"]) if row["height"] is not None else None,
            context={str(key): str(value) for key, value in raw_context.items()},
            idempotency_key=(str(row["idempotency_key"]) if row["idempotency_key"] else None),
            status=str(row["status"]),
            attempts=int(row["attempts"]),
            next_attempt_at=(str(row["next_attempt_at"]) if row["next_attempt_at"] else None),
            last_error=str(row["last_error"]) if row["last_error"] else None,
            error_code=str(row["error_code"]) if row["error_code"] else None,
            rejection_reason=(str(row["rejection_reason"]) if row["rejection_reason"] else None),
            inspection_id=str(row["inspection_id"]) if row["inspection_id"] else None,
            dedup_of_id=int(row["dedup_of_id"]) if row["dedup_of_id"] else None,
            retryable=bool(row["retryable"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            uploaded_at=str(row["uploaded_at"]) if row["uploaded_at"] else None,
        )

    def get(self, item_id: int) -> QueueItem | None:
        with self._connect() as connection:
            return self._row(
                connection.execute("SELECT * FROM queue_items WHERE id = ?", (item_id,)).fetchone()
            )

    def find_source(self, source_fingerprint: str) -> QueueItem | None:
        with self._connect() as connection:
            return self._row(
                connection.execute(
                    "SELECT * FROM queue_items WHERE source_fingerprint = ?",
                    (source_fingerprint,),
                ).fetchone()
            )

    def enqueue(
        self,
        *,
        gateway_id: str,
        tenant_id: str,
        pack_key: str,
        pack_version: str,
        source_path: str,
        source_fingerprint: str,
        spool_path: str,
        original_filename: str,
        content_sha256: str,
        mime_type: str,
        width: int,
        height: int,
        context: dict[str, str],
        idempotency_key: str,
    ) -> QueueItem:
        now = iso_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM queue_items WHERE source_fingerprint = ?",
                (source_fingerprint,),
            ).fetchone()
            if existing:
                connection.execute("COMMIT")
                return self._row(existing)  # type: ignore[return-value]

            primary = connection.execute(
                """
                SELECT * FROM queue_items
                WHERE tenant_id = ? AND idempotency_key = ? AND status != 'DUPLICATE'
                ORDER BY id LIMIT 1
                """,
                (tenant_id, idempotency_key),
            ).fetchone()
            if primary:
                cursor = connection.execute(
                    """
                    INSERT INTO queue_items (
                        gateway_id, tenant_id, pack_key, pack_version, source_path,
                        source_fingerprint, spool_path, original_filename, content_sha256,
                        mime_type, width, height, context_json, idempotency_key, status,
                        retryable, dedup_of_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, 'DUPLICATE', 0, ?, ?, ?)
                    """,
                    (
                        gateway_id,
                        tenant_id,
                        pack_key,
                        pack_version,
                        source_path,
                        source_fingerprint,
                        original_filename,
                        content_sha256,
                        mime_type,
                        width,
                        height,
                        json.dumps(context, sort_keys=True),
                        idempotency_key,
                        int(primary["id"]),
                        now,
                        now,
                    ),
                )
                duplicate = connection.execute(
                    "SELECT * FROM queue_items WHERE id = ?", (cursor.lastrowid,)
                ).fetchone()
                connection.execute("COMMIT")
                return self._row(duplicate)  # type: ignore[return-value]

            cursor = connection.execute(
                """
                INSERT INTO queue_items (
                    gateway_id, tenant_id, pack_key, pack_version, source_path,
                    source_fingerprint, spool_path, original_filename, content_sha256,
                    mime_type, width, height, context_json, idempotency_key, status,
                    next_attempt_at, retryable, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'QUEUED', ?, 1, ?, ?)
                """,
                (
                    gateway_id,
                    tenant_id,
                    pack_key,
                    pack_version,
                    source_path,
                    source_fingerprint,
                    spool_path,
                    original_filename,
                    content_sha256,
                    mime_type,
                    width,
                    height,
                    json.dumps(context, sort_keys=True),
                    idempotency_key,
                    now,
                    now,
                    now,
                ),
            )
            inserted = connection.execute(
                "SELECT * FROM queue_items WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            connection.execute("COMMIT")
            return self._row(inserted)  # type: ignore[return-value]

    def record_rejection(
        self,
        *,
        gateway_id: str,
        tenant_id: str,
        pack_key: str,
        pack_version: str,
        source_path: str,
        source_fingerprint: str,
        original_filename: str,
        error_code: str,
        rejection_reason: str,
        context: dict[str, str] | None = None,
        content_sha256: str | None = None,
    ) -> QueueItem:
        now = iso_now()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT * FROM queue_items WHERE source_fingerprint = ?",
                (source_fingerprint,),
            ).fetchone()
            if existing:
                connection.execute("COMMIT")
                return self._row(existing)  # type: ignore[return-value]
            cursor = connection.execute(
                """
                INSERT INTO queue_items (
                    gateway_id, tenant_id, pack_key, pack_version, source_path,
                    source_fingerprint, original_filename, content_sha256, context_json,
                    status, retryable, error_code, rejection_reason, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'REJECTED', 0, ?, ?, ?, ?)
                """,
                (
                    gateway_id,
                    tenant_id,
                    pack_key,
                    pack_version,
                    source_path,
                    source_fingerprint,
                    original_filename,
                    content_sha256,
                    json.dumps(context or {}, sort_keys=True),
                    error_code,
                    rejection_reason,
                    now,
                    now,
                ),
            )
            inserted = connection.execute(
                "SELECT * FROM queue_items WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            connection.execute("COMMIT")
            return self._row(inserted)  # type: ignore[return-value]

    def recover_inflight(self) -> int:
        now = iso_now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE queue_items
                SET status = 'FAILED', retryable = 1, next_attempt_at = ?,
                    error_code = 'PROCESS_RESTARTED',
                    last_error = '进程在上传中重启，已恢复为待重试状态。', updated_at = ?
                WHERE status = 'UPLOADING'
                """,
                (now, now),
            )
            return int(cursor.rowcount)

    def claim_due(self, now: datetime | None = None) -> QueueItem | None:
        current = (now or utc_now()).isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM queue_items
                WHERE retryable = 1 AND status IN ('QUEUED', 'FAILED')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY created_at, id LIMIT 1
                """,
                (current,),
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            updated = iso_now()
            connection.execute(
                """
                UPDATE queue_items
                SET status = 'UPLOADING', attempts = attempts + 1,
                    last_attempt_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (updated, updated, int(row["id"])),
            )
            claimed = connection.execute(
                "SELECT * FROM queue_items WHERE id = ?", (int(row["id"]),)
            ).fetchone()
            connection.execute("COMMIT")
            return self._row(claimed)

    def mark_uploaded(self, item_id: int, inspection_id: str) -> QueueItem:
        now = iso_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE queue_items
                SET status = 'UPLOADED', retryable = 0, next_attempt_at = NULL,
                    inspection_id = ?, uploaded_at = ?, updated_at = ?, last_error = NULL,
                    error_code = NULL
                WHERE id = ?
                """,
                (inspection_id, now, now, item_id),
            )
            return self._row(
                connection.execute("SELECT * FROM queue_items WHERE id = ?", (item_id,)).fetchone()
            )  # type: ignore[return-value]

    def clear_spool(self, item_id: int) -> QueueItem:
        """Remove the local spool reference after an explicit retention decision."""
        now = iso_now()
        with self._connect() as connection:
            connection.execute(
                "UPDATE queue_items SET spool_path = NULL, updated_at = ? WHERE id = ?",
                (now, item_id),
            )
            return self._row(
                connection.execute("SELECT * FROM queue_items WHERE id = ?", (item_id,)).fetchone()
            )  # type: ignore[return-value]

    def mark_local_only(self, item_id: int) -> QueueItem:
        """Close a local-only item without sending its original bytes anywhere."""
        now = iso_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE queue_items
                SET status = 'LOCAL_ONLY', retryable = 0, next_attempt_at = NULL,
                    updated_at = ?, last_error = NULL, error_code = NULL
                WHERE id = ?
                """,
                (now, item_id),
            )
            return self._row(
                connection.execute("SELECT * FROM queue_items WHERE id = ?", (item_id,)).fetchone()
            )  # type: ignore[return-value]

    def mark_failed(
        self,
        item_id: int,
        *,
        error_code: str,
        error: str,
        retryable: bool,
        retry_delay_seconds: float = 0,
    ) -> QueueItem:
        now_dt = utc_now()
        next_attempt = (
            (now_dt + timedelta(seconds=max(0, retry_delay_seconds))).isoformat()
            if retryable
            else None
        )
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE queue_items
                SET status = 'FAILED', retryable = ?, next_attempt_at = ?,
                    error_code = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(retryable),
                    next_attempt,
                    error_code,
                    error[:1000],
                    now_dt.isoformat(),
                    item_id,
                ),
            )
            return self._row(
                connection.execute("SELECT * FROM queue_items WHERE id = ?", (item_id,)).fetchone()
            )  # type: ignore[return-value]

    def retry(self, item_id: int) -> QueueItem:
        now = iso_now()
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE queue_items
                SET retryable = 1, status = 'FAILED', next_attempt_at = ?, updated_at = ?
                WHERE id = ? AND status = 'FAILED'
                """,
                (now, now, item_id),
            )
            row = connection.execute(
                "SELECT * FROM queue_items WHERE id = ?", (item_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"queue item {item_id} not found")
            return self._row(row)  # type: ignore[return-value]

    def purge_expired_spools(self, retention_days: int, *, include_uploaded: bool = False) -> int:
        """Delete expired local image spools while retaining audit metadata.

        ``LOCAL_ONLY`` items are eligible by default. Uploaded items are only
        included when the caller has explicitly enabled that retention policy.
        The queue row, hashes, status and decision history remain auditable.
        """
        cutoff = (utc_now() - timedelta(days=max(1, retention_days))).isoformat()
        statuses = ("LOCAL_ONLY", "UPLOADED") if include_uploaded else ("LOCAL_ONLY",)
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT id, spool_path FROM queue_items
                WHERE status IN ({placeholders}) AND updated_at < ? AND spool_path IS NOT NULL
                """,
                (*statuses, cutoff),
            ).fetchall()
            purged = 0
            for row in rows:
                spool_path = row["spool_path"]
                if spool_path:
                    try:
                        Path(str(spool_path)).unlink(missing_ok=True)
                    except OSError:
                        continue
                connection.execute(
                    "UPDATE queue_items SET spool_path = NULL, updated_at = ? WHERE id = ?",
                    (iso_now(), int(row["id"])),
                )
                purged += 1
            return purged

    def list_items(self, limit: int = 100) -> list[QueueItem]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM queue_items ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)
            ).fetchall()
            return [item for row in rows if (item := self._row(row)) is not None]

    def summary(self, recent_limit: int = 10) -> QueueSummary:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM queue_items GROUP BY status"
            ).fetchall()
            counts = {str(row["status"]): int(row["count"]) for row in rows}
            depth = sum(counts.get(status, 0) for status in ("QUEUED", "UPLOADING", "FAILED"))
            error_rows = connection.execute(
                """
                SELECT id, status, error_code, last_error, rejection_reason, updated_at
                FROM queue_items
                WHERE status IN ('REJECTED', 'FAILED')
                ORDER BY updated_at DESC, id DESC LIMIT ?
                """,
                (max(1, min(recent_limit, 50)),),
            ).fetchall()
            recent_errors = [
                {
                    "queue_id": int(row["id"]),
                    "status": str(row["status"]),
                    "code": row["error_code"],
                    "message": row["rejection_reason"] or row["last_error"],
                    "updated_at": row["updated_at"],
                }
                for row in error_rows
            ]
            return QueueSummary(depth=depth, counts=counts, recent_errors=recent_errors)
