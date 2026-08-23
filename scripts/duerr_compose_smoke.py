"""Exercise the Dürr demo tenant through the Compose API boundary.

The script intentionally validates the simulated DXQ contract. It never calls
an official/private Dürr endpoint and is only a local portfolio smoke test.
"""

from __future__ import annotations

import io
import json
import os
import time
import uuid
from typing import Any

import httpx
from PIL import Image, ImageDraw

BASE_URL = os.getenv("VISIONQC_BASE_URL", "http://localhost:3000/api/v1").rstrip("/")


def wait_for(
    client: httpx.Client, path: str, headers: dict[str, str], terminal: set[str]
) -> dict[str, Any]:
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


def paint_panel_png() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (128, 96), (65, 82, 108))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 116, 84), radius=8, fill=(112, 140, 170), outline=(230, 238, 245), width=4)
    draw.line((24, 48, 104, 48), fill=(24, 33, 48), width=8)
    draw.ellipse((76, 28, 91, 43), fill=(35, 20, 18), outline=(250, 200, 160), width=2)
    image.save(output, format="PNG")
    return output.getvalue()


def main() -> None:
    run_id = uuid.uuid4().hex[:12]
    with httpx.Client(timeout=10) as client:
        token_response = client.get(f"{BASE_URL}/auth/demo-token")
        token_response.raise_for_status()
        initial = token_response.json()
        switch = client.post(
            f"{BASE_URL}/auth/switch-tenant",
            headers={"Authorization": f"Bearer {initial['access_token']}"},
            json={"tenant_id": "duerr-demo"},
        )
        switch.raise_for_status()
        headers = {"Authorization": f"Bearer {switch.json()['access_token']}"}

        context_response = client.get(f"{BASE_URL}/tenant-context", headers=headers)
        context_response.raise_for_status()
        context = context_response.json()
        manifest = context["current_deployment"]["manifest"]
        assert context["tenant"]["id"] == "duerr-demo", context
        assert manifest["pack_key"] == "duerr_demo/paint_quality", manifest
        assert manifest["connectors"]["dxq_mock"]["driver"] == "dxq_mock", manifest

        metadata = {
            "body_id": f"BODY-DUERR-SMOKE-{run_id}",
            "workpiece_id": f"WORKPIECE-{run_id}",
            "paint_shop": "PAINT_SHOP-DEMO",
            "booth_station": "PAINT-QC-01",
            "line": "LINE-01",
            "model_variant": "SUV-DEMO",
            "color_code": "C101",
            "paint_recipe": "R-01",
            "shift": "A",
            "equipment_alarm_refs": ["ALARM-SIM-001"],
            "process_parameter_refs": ["PARAM-SIM-001"],
        }
        image = paint_panel_png()
        upload = client.post(
            f"{BASE_URL}/inspections",
            headers={**headers, "Idempotency-Key": f"duerr-compose-smoke-{run_id}"},
            files={"image": ("paint-panel.png", image, "image/png")},
            data={
                "product_code": "painted_body_panel",
                "product_revision": "PILOT-0.1",
                "batch_no": metadata["body_id"],
                "station_code": "PAINT-QC-01",
                "captured_at": "2026-08-23T10:00:00Z",
                "source": "compose-smoke/duerr-demo",
                "context_metadata_json": json.dumps(metadata, ensure_ascii=False),
            },
        )
        upload.raise_for_status()
        inspection_id = upload.json()["inspection_id"]
        inspection = wait_for(
            client,
            f"/inspections/{inspection_id}",
            headers,
            {"BATCH_HELD", "REVIEW_REQUIRED", "INFERENCE_FAILED"},
        )
        assert inspection["status"] in {"BATCH_HELD", "REVIEW_REQUIRED", "INFERENCE_FAILED"}, inspection
        review_queue = client.get(f"{BASE_URL}/reviews", headers=headers)
        review_queue.raise_for_status()
        task = next(item for item in review_queue.json() if item["inspection_id"] == inspection_id)
        decision = client.post(
            f"{BASE_URL}/reviews/{task['id']}/decisions",
            headers=headers,
            json={
                "expected_version": task["version"],
                "decision": "INVESTIGATE",
                "reason": "Dürr paint-quality portfolio smoke requires human confirmation.",
                "confirmed": True,
            },
        )
        decision.raise_for_status()
        incident_id = decision.json()["incident_id"]
        incident = wait_for(
            client,
            f"/incidents/{incident_id}",
            headers,
            {"ACTION_COMPLETED", "ACTION_FAILED"},
        )
        assert incident["status"] == "ACTION_COMPLETED", incident
        assert {action["connector"] for action in incident["external_actions"]} == {
            "MES",
            "QMS",
            "DXQ_MOCK",
        }
        dxq = next(action for action in incident["external_actions"] if action["connector"] == "DXQ_MOCK")
        assert dxq["response_summary"]["simulated"] is True
        assert dxq["response_summary"]["contract_version"] == "simulated-dxq-quality-loop.v1"

        close = client.post(
            f"{BASE_URL}/incidents/{incident_id}/close",
            headers=headers,
            json={
                "owner": "duerr-compose-smoke",
                "outcome": "Simulated paint-quality loop closed.",
                "verification_record": f"DUERR-COMPOSE-{run_id}",
            },
        )
        close.raise_for_status()
        assert close.json()["status"] == "CLOSED"

        factory_a_headers = {"Authorization": f"Bearer {initial['access_token']}"}
        assert client.get(
            f"{BASE_URL}/inspections/{inspection_id}", headers=factory_a_headers
        ).status_code == 404
        print({"tenant": "duerr-demo", "incident_status": "CLOSED", "dxq": "simulated contract passed"})


if __name__ == "__main__":
    main()
