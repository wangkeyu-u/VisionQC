from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth import Role
from app.bootstrap import bootstrap_defaults
from app.deployment import load_manifests
from app.models import DeploymentPack, ExternalAction


@pytest.mark.integration
def test_checked_in_deployment_manifests_are_distinct_and_valid() -> None:
    manifests = load_manifests(Path(__file__).parents[1] / "deployment-packs" / "manifests")
    by_key = {manifest.pack_key: manifest for manifest in manifests}

    assert set(by_key) == {
        "factory_a/transistor",
        "factory_b/bottle",
        "duerr_demo/paint_quality",
    }
    factory_a = by_key["factory_a/transistor"]
    factory_b = by_key["factory_b/bottle"]
    assert factory_a.field_mapping.product_code == "product_code"
    assert factory_b.field_mapping.product_code == "sku"
    assert factory_a.model.id != factory_b.model.id
    assert factory_a.policy.default.hold_threshold != factory_b.policy.default.hold_threshold
    assert factory_a.connectors.qms.contract_version != factory_b.connectors.qms.contract_version
    duerr = by_key["duerr_demo/paint_quality"]
    assert duerr.tenant.id == "duerr-demo"
    assert duerr.connectors.dxq_mock is not None
    assert duerr.metadata["privacy_default"] == "local_processing_only"
    assert "not commissioned or endorsed by Dürr" in duerr.metadata["portfolio_disclaimer"]


@pytest.mark.integration
def test_tenant_context_uses_jwt_claim_and_switch_issues_scoped_token(
    client: TestClient, auth_headers
) -> None:
    fde_headers = auth_headers(actor_id="fde-1", roles=[Role.FDE])
    factory_a = client.get("/api/v1/tenant-context", headers=fde_headers)
    assert factory_a.status_code == 200
    a_context = factory_a.json()
    assert a_context["tenant"]["id"] == "factory-a"
    assert a_context["current_deployment"]["manifest"]["pack_key"] == "factory_a/transistor"
    assert {tenant["id"] for tenant in a_context["available_tenants"]} == {
        "factory-a",
        "factory-b",
        "duerr-demo",
    }

    # This header is deliberately not a tenant selector.  The signed JWT
    # claim remains the only tenant boundary used by the API.
    spoofed = client.get(
        "/api/v1/tenant-context",
        headers={**fde_headers, "X-Tenant-ID": "factory-b"},
    )
    assert spoofed.status_code == 200
    assert spoofed.json()["tenant"]["id"] == "factory-a"

    switched = client.post(
        "/api/v1/auth/switch-tenant",
        headers=fde_headers,
        json={"tenant_id": "factory-b"},
    )
    assert switched.status_code == 200
    b_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
    factory_b = client.get("/api/v1/tenant-context", headers=b_headers)
    assert factory_b.status_code == 200
    assert factory_b.json()["tenant"]["id"] == "factory-b"
    assert factory_b.json()["current_deployment"]["manifest"]["pack_key"] == "factory_b/bottle"

    # The original token is not mutated by a switch.
    assert (
        client.get("/api/v1/tenant-context", headers=fde_headers).json()["tenant"]["id"]
        == "factory-a"
    )


@pytest.mark.integration
def test_bootstrap_converges_stale_system_pack_to_unified_gateway_contract(
    app, client: TestClient
) -> None:
    with app.state.session_factory() as session:
        active = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.tenant_id == "factory-a",
                DeploymentPack.status == "ACTIVE",
            )
        )
        assert active is not None
        stale_manifest = dict(active.manifest or {})
        stale_manifest["edge_gateway"] = None
        active.manifest = stale_manifest
        session.commit()

        bootstrap_defaults(session, app.state.settings)
        session.commit()

    with app.state.session_factory() as session:
        active = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.tenant_id == "factory-a",
                DeploymentPack.status == "ACTIVE",
            )
        )
        assert active is not None
        assert active.approved_by == "system:bootstrap"
        assert active.manifest["edge_gateway"]["gateway_id"] == "factory-a-gw-st07"


@pytest.mark.integration
def test_factory_b_uses_mapped_fields_model_policy_and_connector_contract(
    app, client: TestClient, upload_inspection, auth_headers
) -> None:
    upload = upload_inspection(
        0,
        idempotency_key="factory-b-pack-contract",
        tenant_id="factory-b",
        roles=[Role.INSPECTOR],
    )
    assert upload.status_code == 202, upload.text
    body = upload.json()
    assert body["tenant_id"] == "factory-b"
    assert body["context"]["product_code"] == "bottle"
    assert body["context"]["batch_no"] == "LOT-B-001"
    assert body["context"]["station_code"] == "CELL-12"
    assert body["model"]["model_id"] == "patchcore-bottle"
    assert body["model"]["model_version"] == "2.3.0"
    assert body["policy"]["version"] == "factory-b-bottle-policy-2.1.0"
    assert body["policy"]["snapshot"]["resolved_rule"] == {
        "review_threshold": 0.25,
        "hold_threshold": 0.62,
    }

    manager_headers = auth_headers(
        actor_id="manager-b",
        tenant_id="factory-b",
        roles=[Role.QUALITY_MANAGER],
    )
    decision = client.post(
        f"/api/v1/reviews/{body['review_task_id']}/decisions",
        headers=manager_headers,
        json={
            "expected_version": 1,
            "decision": "INVESTIGATE",
            "reason": "bottle surface anomaly requires containment",
            "confirmed": True,
        },
    )
    assert decision.status_code == 200
    with app.state.session_factory() as session:
        actions = (
            session.query(ExternalAction)
            .filter(ExternalAction.tenant_id == "factory-b")
            .all()
        )
        mes = next(action for action in actions if action.connector == "MES")
        qms = next(action for action in actions if action.connector == "QMS")
        assert mes.request_summary["lot_id"] == "LOT-B-001"
        assert mes.request_summary["cell_id"] == "CELL-12"
        assert qms.request_summary["sku"] == "bottle"
        assert qms.request_summary["supplier_code"] == "SUPPLIER-B-DEMO"


@pytest.mark.integration
def test_cross_tenant_pack_and_asset_reads_are_not_discoverable(
    client: TestClient, upload_inspection, auth_headers
) -> None:
    upload = upload_inspection(0, idempotency_key="isolation-source")
    assert upload.status_code == 202
    inspection = client.get(
        f"/api/v1/inspections/{upload.json()['inspection_id']}",
        headers=auth_headers(tenant_id="factory-a"),
    )
    original_id = next(
        item["id"] for item in inspection.json()["images"] if item["kind"] == "ORIGINAL"
    )
    decision = client.post(
        f"/api/v1/reviews/{inspection.json()['review_task_id']}/decisions",
        headers=auth_headers(tenant_id="factory-a", roles=[Role.QUALITY_MANAGER]),
        json={
            "expected_version": 1,
            "decision": "INVESTIGATE",
            "reason": "isolation test incident",
            "confirmed": True,
        },
    )
    assert decision.status_code == 200
    incident_id = decision.json()["incident_id"]
    incident = client.get(
        f"/api/v1/incidents/{incident_id}",
        headers=auth_headers(tenant_id="factory-a", roles=[Role.QUALITY_MANAGER]),
    )
    assert incident.status_code == 200
    action_id = incident.json()["external_actions"][0]["id"]
    b_headers = auth_headers(tenant_id="factory-b", roles=[Role.AUDITOR])
    assert client.get(
        f"/api/v1/inspections/{upload.json()['inspection_id']}", headers=b_headers
    ).status_code == 404
    assert client.get(f"/api/v1/assets/{original_id}", headers=b_headers).status_code == 404
    assert client.get(f"/api/v1/incidents/{incident_id}", headers=b_headers).status_code == 404
    assert client.get(f"/api/v1/external-actions/{action_id}", headers=b_headers).status_code == 404
    assert (
        client.get("/api/v1/deployments", headers=b_headers).json()[0]["tenant_id"]
        == "factory-b"
    )


@pytest.mark.integration
def test_invalid_deployment_manifest_is_rejected_before_persistence(
    client: TestClient, auth_headers
) -> None:
    invalid = {
        "manifest": {
            "schema_version": "visionqc.deployment-pack.v1",
            "pack_key": "factory_a/invalid",
            "version": "9.9.9",
            "display_name": "Invalid",
            "tenant": {"id": "factory-a", "name": "Factory A"},
            "input_mode": "api_upload",
            "products": [
                {"code": "transistor", "display_name": "T", "revision": "R", "aliases": []}
            ],
            "stations": [
                {
                    "code": "ST-01",
                    "display_name": "S",
                    "description": "S",
                    "camera_profile": "c",
                }
            ],
            "field_mapping": {
                "product_code": "product_code",
                "product_revision": "product_revision",
                "batch_no": "batch_no",
                "station_code": "station_code",
                "captured_at": "captured_at",
                "source": "source",
            },
            "field_labels": {},
            "model": {
                "id": "m",
                "version": "1",
                "feature_bank_version": "fb",
                "adapter": "stub",
                "runtime": "stub",
                "device": "cpu",
                "package_uri": "demo",
                "score_semantics": "anomaly evidence",
            },
            "policy": {
                "version": "bad",
                "default": {"review_threshold": 0.8, "hold_threshold": 0.2},
            },
            "connectors": {
                "mes": {
                    "display_name": "M",
                    "driver": "mock",
                    "contract_version": "1",
                    "endpoint": "m",
                    "operations": ["HOLD_BATCH"],
                },
                "qms": {
                    "display_name": "Q",
                    "driver": "mock",
                    "contract_version": "1",
                    "endpoint": "q",
                    "operations": ["CREATE_TICKET"],
                },
            },
        }
    }
    response = client.post(
        "/api/v1/deployments",
        headers=auth_headers(actor_id="fde-1", roles=[Role.FDE]),
        json=invalid,
    )
    assert response.status_code == 422
