from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import Role
from app.domain import ExternalActionStatus
from app.models import ExternalAction, QualityIncident


@pytest.mark.e2e
def test_duerr_paint_quality_closes_simulated_digital_quality_loop(
    app, client: TestClient, upload_inspection, auth_headers
) -> None:
    upload = upload_inspection(
        0,
        tenant_id="duerr-demo",
        idempotency_key="duerr-e2e-quality-loop",
        roles=[Role.INSPECTOR],
    )
    assert upload.status_code == 202, upload.text
    body = upload.json()
    assert body["status"] == "BATCH_HELD"
    assert body["context"]["metadata"]["paint_recipe"] == "R-01"

    manager_headers = auth_headers(
        tenant_id="duerr-demo", actor_id="duerr-manager", roles=[Role.QUALITY_MANAGER]
    )
    decision = client.post(
        f"/api/v1/reviews/{body['review_task_id']}/decisions",
        headers=manager_headers,
        json={
            "expected_version": 1,
            "decision": "INVESTIGATE",
            "reason": "漆面异常需要关联工艺参数并由人工确认。",
            "confirmed": True,
        },
    )
    assert decision.status_code == 200, decision.text
    incident_id = decision.json()["incident_id"]
    assert incident_id

    with app.state.session_factory() as session:
        incident = session.get(QualityIncident, incident_id)
        actions = session.scalars(
            select(ExternalAction).where(ExternalAction.incident_id == incident_id)
        ).all()
        assert incident is not None
        assert incident.status == "ACTION_COMPLETED"
        assert {action.connector for action in actions} == {"MES", "QMS", "DXQ_MOCK"}
        assert {action.status for action in actions} == {ExternalActionStatus.SUCCEEDED}
        dxq = next(action for action in actions if action.connector == "DXQ_MOCK")
        assert dxq.response_summary["simulated"] is True
        assert dxq.response_summary["contract_version"] == "simulated-dxq-quality-loop.v1"

    close = client.post(
        f"/api/v1/incidents/{incident_id}/close",
        headers=manager_headers,
        json={
            "owner": "duerr-manager",
            "outcome": "模拟涂装质量调查完成。",
            "verification_record": "DUERR-DEMO-VERIFY-001",
        },
    )
    assert close.status_code == 200
    assert close.json()["status"] == "CLOSED"
    assert client.get(
        f"/api/v1/inspections/{body['inspection_id']}",
        headers=auth_headers(tenant_id="factory-a", roles=[Role.AUDITOR]),
    ).status_code == 404
