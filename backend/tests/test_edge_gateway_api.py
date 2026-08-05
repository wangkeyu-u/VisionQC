from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth import Role


def gateway_headers(auth_headers, *, tenant_id: str, gateway_id: str) -> dict[str, str]:
    return {
        **auth_headers(actor_id=gateway_id, tenant_id=tenant_id, roles=[Role.EDGE_GATEWAY]),
        "X-Gateway-ID": gateway_id,
    }


def test_gateway_heartbeat_is_tenant_and_gateway_scoped(
    client: TestClient, auth_headers, png_bytes
) -> None:
    headers = gateway_headers(
        auth_headers,
        tenant_id="factory-a",
        gateway_id="factory-a-gw-st07",
    )
    heartbeat = client.post(
        "/api/v1/gateways/heartbeat",
        headers=headers,
        json={
            "gateway_id": "factory-a-gw-st07",
            "gateway_version": "0.1.0",
            "station_code": "ST-07 / 终检",
            "reported_status": "DEGRADED",
            "queue_depth": 2,
            "upload_failure_count": 1,
            "deployment_pack_key": "factory_a/transistor",
            "deployment_pack_version": "1.0.0",
            "metrics": {"queue_counts": {"FAILED": 1}},
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["tenant_id"] == "factory-a"
    assert heartbeat.json()["status"] == "DEGRADED"

    statuses = client.get("/api/v1/gateways/status", headers=auth_headers(tenant_id="factory-a"))
    assert statuses.status_code == 200
    assert statuses.json()[0]["gateway_id"] == "factory-a-gw-st07"
    assert statuses.json()[0]["queue_depth"] == 2

    wrong_actor = client.post(
        "/api/v1/gateways/heartbeat",
        headers=gateway_headers(
            auth_headers,
            tenant_id="factory-a",
            gateway_id="factory-a-gw-st07",
        ),
        json={
            "gateway_id": "factory-b-gw-cell12",
            "gateway_version": "0.1.0",
            "station_code": "ST-07 / 终检",
            "queue_depth": 0,
        },
    )
    assert wrong_actor.status_code == 403

    wrong_gateway_token = gateway_headers(
        auth_headers,
        tenant_id="factory-a",
        gateway_id="factory-b-gw-cell12",
    )
    wrong_gateway_token["Idempotency-Key"] = "edge-gateway-unregistered"
    rejected_upload = client.post(
        "/api/v1/inspections",
        headers=wrong_gateway_token,
        files={"image": ("capture.png", png_bytes(120), "image/png")},
        data={
            "product_code": "TR-AX14",
            "product_revision": "REV-C",
            "batch_no": "B-EDGE-002",
            "station_code": "ST-07 / 终检",
            "captured_at": "2026-08-04T10:00:00Z",
            "source": "edge-camera/factory-a/st07",
        },
    )
    assert rejected_upload.status_code == 403


def test_gateway_upload_reuses_manual_inspection_path_without_tenant_spoof(
    client: TestClient, auth_headers, png_bytes
) -> None:
    headers = gateway_headers(
        auth_headers,
        tenant_id="factory-a",
        gateway_id="factory-a-gw-st07",
    )
    headers["Idempotency-Key"] = "edge-gateway-upload-a"
    response = client.post(
        "/api/v1/inspections",
        headers=headers,
        files={"image": ("capture.png", png_bytes(120), "image/png")},
        data={
            "product_code": "TR-AX14",
            "product_revision": "REV-C",
            "batch_no": "B-EDGE-001",
            "station_code": "ST-07 / 终检",
            "captured_at": "2026-08-04T10:00:00Z",
            "source": "edge-camera/factory-a/st07",
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["tenant_id"] == "factory-a"
    assert response.json()["context"]["source"] == "edge-camera/factory-a/st07"

    # A signed Factory A gateway token cannot select Factory B by submitting
    # B's customer field vocabulary; the active A pack remains the boundary.
    headers["Idempotency-Key"] = "edge-gateway-cross-tenant"
    spoof = client.post(
        "/api/v1/inspections",
        headers=headers,
        files={"image": ("capture.png", png_bytes(120), "image/png")},
        data={
            "sku": "bottle",
            "revision": "B-2026.07",
            "lot_id": "LOT-B-001",
            "cell": "CELL-12",
            "captured_at": "2026-08-04T10:00:00Z",
            "source_system": "spoof",
        },
    )
    assert spoof.status_code == 422
