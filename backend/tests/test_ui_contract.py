from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import Role


@pytest.mark.integration
def test_demo_auth_and_inspection_evidence_contract(
    client: TestClient, auth_headers, png_bytes
) -> None:
    token = client.get("/api/v1/auth/demo-token")
    assert token.status_code == 200
    assert token.json()["tenant_id"] == "factory-a"
    assert "quality_manager" in token.json()["roles"]

    headers = auth_headers(roles=[Role.INSPECTOR])
    headers["Idempotency-Key"] = "ui-contract-inspection"
    upload = client.post(
        "/api/v1/inspections",
        headers=headers,
        files={"image": ("sample.png", png_bytes(128), "image/png")},
        data={
            "product_code": "TR-AX14",
            "product_revision": "REV-C",
            "batch_no": "B-240804-18",
            "station_code": "ST-07",
            "captured_at": "2026-08-04T10:00:00Z",
        },
    )
    assert upload.status_code == 202
    body = upload.json()
    assert body["context"]["product_revision"] == "REV-C"
    assert body["created_at"] and body["updated_at"]
    original = next(image for image in body["images"] if image["kind"] == "ORIGINAL")

    listing = client.get("/api/v1/inspections", headers=headers)
    assert listing.status_code == 200
    assert listing.json()[0]["inspection_id"] == body["inspection_id"]

    asset = client.get(f"/api/v1/assets/{original['id']}", headers=headers)
    assert asset.status_code == 200
    assert asset.headers["content-type"] == "image/png"
    assert asset.content == png_bytes(128)

    timeline = client.get(
        f"/api/v1/inspections/{body['inspection_id']}/timeline", headers=headers
    )
    assert timeline.status_code == 200
    assert all(entry["correlation_id"] for entry in timeline.json())


@pytest.mark.e2e
def test_review_queue_and_incident_detail_contract(
    upload_inspection, client: TestClient, auth_headers
) -> None:
    upload = upload_inspection(0, idempotency_key="ui-contract-incident")
    task_id = upload.json()["review_task_id"]
    manager_headers = auth_headers(
        actor_id="manager-ui", roles=[Role.QUALITY_MANAGER]
    )

    queue = client.get("/api/v1/reviews", headers=manager_headers)
    task = next(item for item in queue.json() if item["id"] == task_id)
    assert task["route"] == "HIGH_SCORE_HOLD"
    assert task["priority"] == "CRITICAL"
    assert task["thumbnail_asset_id"]

    decision = client.post(
        f"/api/v1/reviews/{task_id}/decisions",
        headers=manager_headers,
        json={
            "expected_version": task["version"],
            "decision": "INVESTIGATE",
            "reason": "UNKNOWN_ANOMALY",
            "notes": "localized anomaly confirmed by named reviewer",
            "confirmed": True,
        },
    )
    assert decision.status_code == 200
    assert decision.json()["review_task_id"] == task_id
    assert decision.json()["actor"] == "manager-ui"

    incident = client.get(
        f"/api/v1/incidents/{decision.json()['incident_id']}", headers=manager_headers
    )
    assert incident.status_code == 200
    detail = incident.json()
    assert detail["evidence"]["decision_actor"] == "manager-ui"
    assert {action["connector"] for action in detail["external_actions"]} == {
        "MES",
        "QMS",
    }
    assert all(action["idempotency_key"] for action in detail["external_actions"])
    assert all(entry["correlation_id"] for entry in detail["timeline"])


@pytest.mark.integration
def test_operations_incidents_and_modelops_contract_is_tenant_scoped(
    upload_inspection, client: TestClient, auth_headers
) -> None:
    upload = upload_inspection(0, idempotency_key="ui-contract-operations")
    assert upload.status_code == 202

    factory_a_headers = auth_headers(
        actor_id="operator-a", tenant_id="factory-a", roles=[Role.QUALITY_MANAGER]
    )
    summary = client.get("/api/v1/operations/summary", headers=factory_a_headers)
    assert summary.status_code == 200
    summary_body = summary.json()
    assert summary_body["tenant_id"] == "factory-a"
    assert summary_body["inspections_24h"] >= 1
    assert summary_body["review_backlog"] >= 1
    assert isinstance(summary_body["route_counts"], dict)

    incidents = client.get("/api/v1/incidents", headers=factory_a_headers)
    assert incidents.status_code == 200
    assert incidents.json() == []

    modelops = client.get("/api/v1/modelops/status", headers=factory_a_headers)
    assert modelops.status_code == 200
    modelops_body = modelops.json()
    assert modelops_body["tenant_id"] == "factory-a"
    assert modelops_body["model_release_status"] == "DRAFT"
    assert modelops_body["synthetic_smoke"] is True
    assert modelops_body["mvtec_metrics_available"] is False
    assert modelops_body["calibration_constraints_satisfied"] is False
    contract = modelops_body["gate_results"]["pilot_gate_contract"]
    assert contract["version"] == "visionqc-pilot-gates.v3"
    assert contract["threshold_selection"]["allowed_source_split"] == "validation"
    assert contract["threshold_selection"]["holdout_used_for_tuning"] is False
    assert contract["checks"]["abnormal_auto_release_rate"]["threshold"] == 0.0
    assert contract["checks"]["abnormal_auto_release_rate"]["gate_class"] == "HARD_GATE"

    factory_b_headers = auth_headers(
        actor_id="operator-b", tenant_id="factory-b", roles=[Role.QUALITY_MANAGER]
    )
    b_summary = client.get("/api/v1/operations/summary", headers=factory_b_headers)
    assert b_summary.status_code == 200
    assert b_summary.json()["tenant_id"] == "factory-b"
    assert b_summary.json()["inspections_24h"] == 0
    b_incidents = client.get("/api/v1/incidents", headers=factory_b_headers)
    assert b_incidents.status_code == 200
    assert b_incidents.json() == []
