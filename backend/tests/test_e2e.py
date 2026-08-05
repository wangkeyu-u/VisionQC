from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.auth import Role
from app.domain import ExternalActionStatus
from app.models import ExternalAction, QualityIncident


@pytest.mark.e2e
def test_high_score_waits_for_human_then_closes_quality_loop(
    app, upload_inspection, client: TestClient, auth_headers
) -> None:
    upload = upload_inspection(0, idempotency_key="e2e-high")
    body = upload.json()
    assert body["status"] == "BATCH_HELD"
    assert body["incident_id"] is None
    with app.state.session_factory() as session:
        assert session.scalar(select(func.count(ExternalAction.id))) == 0

    inspector_attempt = client.post(
        f"/api/v1/reviews/{body['review_task_id']}/decisions",
        headers=auth_headers(),
        json={
            "expected_version": 1,
            "decision": "INVESTIGATE",
            "reason": "localized anomaly requires investigation",
            "confirmed": True,
        },
    )
    assert inspector_attempt.status_code == 403

    manager_headers = auth_headers(actor_id="manager-1", roles=[Role.QUALITY_MANAGER])
    decision = client.post(
        f"/api/v1/reviews/{body['review_task_id']}/decisions",
        headers=manager_headers,
        json={
            "expected_version": 1,
            "decision": "INVESTIGATE",
            "reason": "localized anomaly requires investigation",
            "confirmed": True,
        },
    )
    assert decision.status_code == 200
    incident_id = decision.json()["incident_id"]
    assert incident_id

    with app.state.session_factory() as session:
        incident = session.get(QualityIncident, incident_id)
        actions = session.scalars(
            select(ExternalAction).where(ExternalAction.incident_id == incident_id)
        ).all()
        assert incident is not None
        assert incident.status == "ACTION_COMPLETED"
        assert len(actions) == 2
        assert {action.status for action in actions} == {ExternalActionStatus.SUCCEEDED}
        assert len({action.idempotency_key for action in actions}) == 2

    close = client.post(
        f"/api/v1/incidents/{incident_id}/close",
        headers=manager_headers,
        json={
            "owner": "manager-1",
            "outcome": "investigation completed; controlled rework verified",
            "verification_record": "VR-2026-001",
        },
    )
    assert close.status_code == 200
    assert close.json()["status"] == "CLOSED"

    incident_detail = client.get(
        f"/api/v1/incidents/{incident_id}",
        headers=manager_headers,
    )
    assert incident_detail.status_code == 200
    assert incident_detail.json()["outcome"] == (
        "investigation completed; controlled rework verified"
    )
    assert incident_detail.json()["verification_record"] == "VR-2026-001"

    timeline = client.get(f"/api/v1/incidents/{incident_id}/timeline", headers=manager_headers)
    assert timeline.status_code == 200
    actions = {entry["action"] for entry in timeline.json()}
    assert "quality_incident.created" in actions
    assert "review.completed" in actions
    assert "quality_incident.closed" in actions
    assert any("BATCH_HELD->NONCONFORMANCE_CONFIRMED" == action for action in actions)


@pytest.mark.e2e
def test_qms_timeout_after_commit_does_not_duplicate_ticket(
    app, upload_inspection, client, auth_headers
) -> None:
    qms = app.state.service.connectors["QMS"]
    qms.fail_after_create_once = True
    upload = upload_inspection(0, idempotency_key="e2e-qms-timeout")
    manager_headers = auth_headers(actor_id="manager-1", roles=[Role.QUALITY_MANAGER])
    decision = client.post(
        f"/api/v1/reviews/{upload.json()['review_task_id']}/decisions",
        headers=manager_headers,
        json={
            "expected_version": 1,
            "decision": "REWORK",
            "reason": "confirmed anomaly; controlled rework",
            "confirmed": True,
        },
    )
    assert decision.status_code == 200
    assert len(qms.records) == 1
    assert len(qms.calls) == 2
    assert qms.calls[0] == qms.calls[1]


@pytest.mark.e2e
def test_model_failure_routes_to_review_and_never_releases(app, upload_inspection) -> None:
    app.state.service.model_adapter.available = False
    response = upload_inspection(255, idempotency_key="e2e-model-failure")
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "REVIEW_REQUIRED"
    assert body["review_task_id"]
    assert body["model"] is None
    assert "model unavailable" in body["failure_reason"]


@pytest.mark.e2e
def test_connector_final_failure_remains_recoverable(
    app, upload_inspection, client, auth_headers
) -> None:
    qms = app.state.service.connectors["QMS"]
    qms.always_fail = True
    upload = upload_inspection(0, idempotency_key="e2e-connector-failure")
    manager_headers = auth_headers(actor_id="manager-1", roles=[Role.QUALITY_MANAGER])
    decision = client.post(
        f"/api/v1/reviews/{upload.json()['review_task_id']}/decisions",
        headers=manager_headers,
        json={
            "expected_version": 1,
            "decision": "INVESTIGATE",
            "reason": "confirmed anomaly",
            "confirmed": True,
        },
    )
    assert decision.status_code == 200
    incident_id = decision.json()["incident_id"]
    with app.state.session_factory() as session:
        incident = session.get(QualityIncident, incident_id)
        failed = session.scalar(
            select(ExternalAction).where(
                ExternalAction.incident_id == incident_id,
                ExternalAction.connector == "QMS",
            )
        )
        assert incident is not None and incident.status == "ACTION_FAILED"
        assert failed is not None and failed.status == ExternalActionStatus.FAILED
        failed_id = failed.id
        old_key = failed.idempotency_key

    qms.always_fail = False
    replay = client.post(
        f"/api/v1/external-actions/{failed_id}/replay",
        headers=manager_headers,
        json={"reason": "QMS service restored and reconciliation approved"},
    )
    assert replay.status_code == 200
    assert replay.json()["status"] == ExternalActionStatus.SUCCEEDED
    with app.state.session_factory() as session:
        recovered = session.get(ExternalAction, failed_id)
        assert recovered is not None
        assert recovered.idempotency_key == old_key
        assert recovered.status == ExternalActionStatus.SUCCEEDED
