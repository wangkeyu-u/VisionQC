from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.audit import record_audit
from app.model_adapter import ModelOutput
from app.models import AuditEvent


@pytest.mark.integration
def test_upload_is_tenant_idempotent_and_model_runs_once(
    app, upload_inspection, auth_headers, client: TestClient
) -> None:
    first = upload_inspection(255, idempotency_key="upload-1")
    assert first.status_code == 202
    assert first.json()["status"] == "AUTO_RELEASED"
    assert first.json()["model"]["semantic_defect_confirmed"] is False

    replay = upload_inspection(255, idempotency_key="upload-1")
    assert replay.status_code == 202
    assert replay.json()["inspection_id"] == first.json()["inspection_id"]
    assert replay.json()["idempotent_replay"] is True
    assert app.state.service.model_adapter.calls == 1

    cross_tenant = client.get(
        f"/api/v1/inspections/{first.json()['inspection_id']}",
        headers=auth_headers(tenant_id="factory-b"),
    )
    assert cross_tenant.status_code == 404


@pytest.mark.integration
def test_same_idempotency_key_with_different_content_conflicts(upload_inspection) -> None:
    assert upload_inspection(255, idempotency_key="upload-conflict").status_code == 202
    conflict = upload_inspection(0, idempotency_key="upload-conflict")
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "conflict"


@pytest.mark.integration
def test_invalid_file_is_rejected_before_model_call(app, client, auth_headers) -> None:
    headers = auth_headers()
    headers["Idempotency-Key"] = "invalid-file"
    response = client.post(
        "/api/v1/inspections",
        headers=headers,
        files={"image": ("fake.png", b"not-an-image", "image/png")},
        data={
            "product_code": "transistor",
            "batch_no": "BATCH-001",
            "station_code": "ST-01",
            "captured_at": "2026-08-04T10:00:00Z",
        },
    )
    assert response.status_code == 422
    assert app.state.service.model_adapter.calls == 0
    with app.state.session_factory() as session:
        rejection = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "security.upload_rejected")
        )
        assert rejection is not None
        assert rejection.correlation_id == response.json()["correlation_id"]


@pytest.mark.integration
def test_image_quality_failure_is_safe_review_and_never_auto_releases(
    app, upload_inspection
) -> None:
    app.state.settings.image_quality_enabled = True
    response = upload_inspection(0, idempotency_key="quality-gate-dark")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "REVIEW_REQUIRED"
    assert body["review_task_id"]
    assert body["model"] is None
    assert "TOO_DARK" in body["quality_flags"]
    assert "safe-degrade" in body["failure_reason"]
    assert app.state.service.model_adapter.calls == 0


@pytest.mark.integration
def test_model_ood_signal_is_safe_review(monkeypatch, app, upload_inspection) -> None:
    def ood_output(_image: bytes) -> ModelOutput:
        return ModelOutput(
            score=0.1,
            heatmap_png=b"not-used-because-ood",
            model_id="ood-test",
            model_version="test",
            feature_bank_version="test",
            runtime_device="cpu",
            latency_ms=1,
            ood=True,
        )

    monkeypatch.setattr(app.state.service.model_adapter, "infer", ood_output)
    response = upload_inspection(255, idempotency_key="quality-gate-ood")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "REVIEW_REQUIRED"
    assert body["model"] is None
    assert "out-of-distribution" in body["failure_reason"]


@pytest.mark.integration
def test_review_claim_and_decision_use_optimistic_lock(
    upload_inspection, client, auth_headers
) -> None:
    upload = upload_inspection(128, idempotency_key="review-lock")
    assert upload.json()["status"] == "REVIEW_REQUIRED"
    task_id = upload.json()["review_task_id"]

    inspector_headers = auth_headers()
    claim = client.post(
        f"/api/v1/reviews/{task_id}/claim",
        headers=inspector_headers,
        json={"expected_version": 1},
    )
    assert claim.status_code == 200
    assert claim.json()["version"] == 2

    decision = client.post(
        f"/api/v1/reviews/{task_id}/decisions",
        headers=inspector_headers,
        json={"expected_version": 2, "decision": "GOOD", "notes": "visual check passed"},
    )
    assert decision.status_code == 200
    assert decision.json()["inspection_status"] == "RELEASE_APPROVED"

    stale = client.post(
        f"/api/v1/reviews/{task_id}/decisions",
        headers=inspector_headers,
        json={"expected_version": 2, "decision": "GOOD"},
    )
    assert stale.status_code == 409


@pytest.mark.integration
def test_append_only_audit_rejects_orm_mutation(db_session) -> None:
    event = record_audit(
        db_session,
        tenant_id="factory-b",
        actor="auditor-test",
        action="test.created",
        target_type="test",
        target_id="target-1",
        correlation_id="corr-test",
        payload={"safe": True},
    )
    db_session.flush()
    event.action = "tampered"
    with pytest.raises(ValueError, match="append-only"):
        db_session.flush()


@pytest.mark.integration
def test_authentication_and_required_idempotency_header(client, auth_headers, png_bytes) -> None:
    no_auth = client.get("/api/v1/reviews")
    assert no_auth.status_code == 401

    missing_key = client.post(
        "/api/v1/inspections",
        headers=auth_headers(),
        files={"image": ("sample.png", png_bytes(255), "image/png")},
        data={
            "product_code": "transistor",
            "batch_no": "BATCH-001",
            "station_code": "ST-01",
            "captured_at": "2026-08-04T10:00:00Z",
        },
    )
    assert missing_key.status_code == 422
