from __future__ import annotations

from datetime import UTC, datetime, timedelta

from edge_gateway.queue import QueueStore


def enqueue(store: QueueStore, *, source: str, key: str):
    return store.enqueue(
        gateway_id="gw-a",
        tenant_id="factory-a",
        pack_key="factory_a/transistor",
        pack_version="1.0.0",
        source_path=source,
        source_fingerprint=f"fingerprint-{source}",
        spool_path=f"/spool/{source}.png",
        original_filename=f"{source}.png",
        content_sha256="a" * 64,
        mime_type="image/png",
        width=128,
        height=96,
        context={
            "product_code": "transistor",
            "batch_no": "B-1",
            "station_code": "ST-07 / 终检",
            "captured_at": "2026-08-04T00:00:00+00:00",
            "source": "test",
        },
        idempotency_key=key,
    )


def test_queue_deduplicates_idempotency_without_second_upload(tmp_path) -> None:
    store = QueueStore(tmp_path / "gateway.sqlite3")
    first = enqueue(store, source="one", key="same-key")
    duplicate = enqueue(store, source="two", key="same-key")
    assert first.status == "QUEUED"
    assert duplicate.status == "DUPLICATE"
    assert duplicate.dedup_of_id == first.id
    assert store.summary().counts["DUPLICATE"] == 1


def test_queue_recovers_upload_claim_after_process_restart(tmp_path) -> None:
    path = tmp_path / "gateway.sqlite3"
    first_store = QueueStore(path)
    first = enqueue(first_store, source="one", key="key-1")
    claimed = first_store.claim_due()
    assert claimed is not None and claimed.status == "UPLOADING"

    restarted = QueueStore(path)
    assert restarted.recover_inflight() == 1
    recovered = restarted.get(first.id)
    assert recovered is not None
    assert recovered.status == "FAILED"
    assert recovered.retryable is True
    assert recovered.error_code == "PROCESS_RESTARTED"
    due = restarted.claim_due(datetime.now(UTC) + timedelta(seconds=1))
    assert due is not None and due.status == "UPLOADING"
