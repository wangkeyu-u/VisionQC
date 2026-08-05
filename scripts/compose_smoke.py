"""Exercise both seeded Deployment Packs through the frontend reverse proxy."""

from __future__ import annotations

import io
import os
import time
import uuid
from typing import Any

import httpx
from PIL import Image

BASE_URL = os.getenv("VISIONQC_BASE_URL", "http://localhost:3000/api/v1").rstrip("/")


def wait_for(client: httpx.Client, path: str, headers: dict[str, str], terminal: set[str]):
    for _ in range(50):
        response = client.get(f"{BASE_URL}{path}", headers=headers)
        if response.status_code == 404:
            time.sleep(0.2)
            continue
        response.raise_for_status()
        payload = response.json()
        if payload["status"] in terminal:
            return payload
        time.sleep(0.2)
    raise TimeoutError(f"timed out waiting for {path}")


def deployment_context(client: httpx.Client, headers: dict[str, str]) -> dict[str, Any]:
    response = client.get(f"{BASE_URL}/tenant-context", headers=headers)
    response.raise_for_status()
    body = response.json()
    assert body["current_deployment"] is not None, body
    return body


def upload_sample(
    client: httpx.Client,
    headers: dict[str, str],
    context: dict[str, Any],
    *,
    product: str,
    revision: str,
    batch: str,
    station: str,
    source: str,
    run_id: str,
) -> dict[str, Any]:
    manifest = context["current_deployment"]["manifest"]
    mapping = manifest["field_mapping"]
    image = io.BytesIO()
    Image.new("RGB", (64, 64), (0, 0, 0)).save(image, format="PNG")
    response = client.post(
        f"{BASE_URL}/inspections",
        headers={**headers, "Idempotency-Key": f"compose-smoke-{context['tenant']['id']}-{run_id}"},
        files={"image": ("smoke.png", image.getvalue(), "image/png")},
        data={
            mapping["product_code"]: product,
            mapping["product_revision"]: revision,
            mapping["batch_no"]: batch,
            mapping["station_code"]: station,
            mapping["captured_at"]: "2026-08-04T12:00:00Z",
            mapping["source"]: source,
        },
    )
    response.raise_for_status()
    return response.json()


def close_incident(
    client: httpx.Client,
    headers: dict[str, str],
    incident_id: str,
    run_id: str,
) -> dict[str, Any]:
    response = client.post(
        f"{BASE_URL}/incidents/{incident_id}/close",
        headers=headers,
        json={
            "owner": "demo-quality-manager",
            "outcome": "Deployment Pack cross-tenant smoke test completed.",
            "verification_record": f"SMOKE-VERIFY-{run_id}",
        },
    )
    response.raise_for_status()
    return response.json()


def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    with httpx.Client(timeout=10) as client:
        token = client.get(f"{BASE_URL}/auth/demo-token")
        token.raise_for_status()
        token_payload = token.json()
        a_headers = {"Authorization": f"Bearer {token_payload['access_token']}"}

        a_context = deployment_context(client, a_headers)
        a_manifest = a_context["current_deployment"]["manifest"]
        assert a_context["tenant"]["id"] == "factory-a", a_context
        assert a_manifest["pack_key"] == "factory_a/transistor", a_manifest
        assert a_manifest["model"]["id"] == "patchcore-transistor", a_manifest

        a_upload = upload_sample(
            client,
            a_headers,
            a_context,
            product=a_manifest["products"][0]["code"],
            revision=a_manifest["products"][0]["revision"],
            batch=f"BATCH-A-SMOKE-{run_id}",
            station=a_manifest["stations"][0]["code"],
            source="compose-smoke/factory-a",
            run_id=run_id,
        )
        a_inspection_id = a_upload["inspection_id"]
        a_inspection = wait_for(
            client,
            f"/inspections/{a_inspection_id}",
            a_headers,
            {"AUTO_RELEASED", "REVIEW_REQUIRED", "BATCH_HELD", "INFERENCE_FAILED"},
        )
        assert a_inspection["status"] == "BATCH_HELD", a_inspection
        original = next(item for item in a_inspection["images"] if item["kind"] == "ORIGINAL")
        asset = client.get(f"{BASE_URL}/assets/{original['id']}", headers=a_headers)
        asset.raise_for_status()
        assert asset.headers["content-type"] == "image/png"

        queue = client.get(f"{BASE_URL}/reviews", headers=a_headers)
        queue.raise_for_status()
        a_task = next(item for item in queue.json() if item["inspection_id"] == a_inspection_id)
        a_decision = client.post(
            f"{BASE_URL}/reviews/{a_task['id']}/decisions",
            headers=a_headers,
            json={
                "expected_version": a_task["version"],
                "decision": "INVESTIGATE",
                "reason": "Factory A smoke test confirmed an anomalous region.",
                "notes": "Deployment Pack A workflow evidence is complete.",
                "confirmed": True,
            },
        )
        a_decision.raise_for_status()
        a_incident_id = a_decision.json()["incident_id"]
        a_incident = wait_for(
            client,
            f"/incidents/{a_incident_id}",
            a_headers,
            {"ACTION_COMPLETED", "ACTION_FAILED"},
        )
        assert a_incident["status"] == "ACTION_COMPLETED", a_incident
        assert {item["connector"] for item in a_incident["external_actions"]} == {"MES", "QMS"}
        assert all(item["status"] == "SUCCEEDED" for item in a_incident["external_actions"])
        assert close_incident(client, a_headers, a_incident_id, run_id)["status"] == "CLOSED"

        switched = client.post(
            f"{BASE_URL}/auth/switch-tenant",
            headers=a_headers,
            json={"tenant_id": "factory-b"},
        )
        switched.raise_for_status()
        b_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
        b_context = deployment_context(client, b_headers)
        b_manifest = b_context["current_deployment"]["manifest"]
        assert b_context["tenant"]["id"] == "factory-b", b_context
        assert b_manifest["pack_key"] == "factory_b/bottle", b_manifest
        assert b_manifest["field_mapping"]["product_code"] == "sku", b_manifest
        assert b_manifest["model"]["id"] == "patchcore-bottle", b_manifest
        assert b_manifest["policy"]["default"]["hold_threshold"] != a_manifest["policy"]["default"]["hold_threshold"]
        assert b_manifest["connectors"]["qms"]["contract_version"] != a_manifest["connectors"]["qms"]["contract_version"]

        b_upload = upload_sample(
            client,
            b_headers,
            b_context,
            product=b_manifest["products"][0]["code"],
            revision=b_manifest["products"][0]["revision"],
            batch=f"LOT-B-SMOKE-{run_id}",
            station=b_manifest["stations"][0]["code"],
            source="compose-smoke/factory-b",
            run_id=run_id,
        )
        b_inspection_id = b_upload["inspection_id"]
        b_inspection = wait_for(
            client,
            f"/inspections/{b_inspection_id}",
            b_headers,
            {"AUTO_RELEASED", "REVIEW_REQUIRED", "BATCH_HELD", "INFERENCE_FAILED"},
        )
        assert b_inspection["status"] == "BATCH_HELD", b_inspection
        assert b_inspection["model"]["model_id"] == "patchcore-bottle", b_inspection
        b_queue = client.get(f"{BASE_URL}/reviews", headers=b_headers)
        b_queue.raise_for_status()
        b_task = next(item for item in b_queue.json() if item["inspection_id"] == b_inspection_id)
        b_decision = client.post(
            f"{BASE_URL}/reviews/{b_task['id']}/decisions",
            headers=b_headers,
            json={
                "expected_version": b_task["version"],
                "decision": "INVESTIGATE",
                "reason": "Factory B bottle surface anomaly requires containment.",
                "confirmed": True,
            },
        )
        b_decision.raise_for_status()
        b_incident_id = b_decision.json()["incident_id"]
        b_incident = wait_for(
            client,
            f"/incidents/{b_incident_id}",
            b_headers,
            {"ACTION_COMPLETED", "ACTION_FAILED"},
        )
        assert b_incident["status"] == "ACTION_COMPLETED", b_incident
        assert close_incident(client, b_headers, b_incident_id, run_id)["status"] == "CLOSED"

        # The old tenant token remains valid for A; the switched token cannot
        # read A's inspection or its object evidence.
        assert client.get(f"{BASE_URL}/inspections/{a_inspection_id}", headers=b_headers).status_code == 404
        assert client.get(f"{BASE_URL}/assets/{original['id']}", headers=b_headers).status_code == 404
        old_a_context = deployment_context(client, a_headers)
        assert old_a_context["tenant"]["id"] == "factory-a"

        print(
            {
                "factory_a": {"inspection_id": a_inspection_id, "incident_status": "CLOSED"},
                "factory_b": {"inspection_id": b_inspection_id, "incident_status": "CLOSED"},
                "isolation": "cross-tenant read blocked",
            }
        )


if __name__ == "__main__":
    main()
