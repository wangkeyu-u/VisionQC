#!/usr/bin/env python3
"""Smoke-test two running Compose Edge Gateways and tenant isolation."""

from __future__ import annotations

import os
import time
from typing import Any

import httpx

BACKEND = os.getenv("VISIONQC_API_BASE_URL", "http://localhost:8000/api/v1").rstrip("/")
GATEWAYS = {
    "factory-a": os.getenv("VISIONQC_GATEWAY_A_URL", "http://localhost:8091").rstrip("/"),
    "factory-b": os.getenv("VISIONQC_GATEWAY_B_URL", "http://localhost:8092").rstrip("/"),
}


def wait_for(
    client: httpx.Client,
    url: str,
    predicate,
    *,
    headers: dict[str, str] | None = None,
    timeout: float = 90,
) -> Any:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = client.get(url, headers=headers)
        if response.status_code < 500:
            response.raise_for_status()
            last = response.json()
            if predicate(last):
                return last
        time.sleep(1)
    raise TimeoutError(f"timed out waiting for {url}: {last}")


def main() -> None:
    with httpx.Client(timeout=10) as client:
        demo = client.get(f"{BACKEND}/auth/demo-token")
        demo.raise_for_status()
        a_headers = {"Authorization": f"Bearer {demo.json()['access_token']}"}

        local_status: dict[str, dict[str, Any]] = {}
        for tenant, base in GATEWAYS.items():
            local_status[tenant] = wait_for(
                client,
                f"{base}/status",
                lambda body, tenant=tenant: body.get("gateway_id", "").startswith(tenant),
            )

        a_backend_status = wait_for(
            client,
            f"{BACKEND}/gateways/status",
            lambda rows: any(row["gateway_id"] == "factory-a-gw-st07" for row in rows),
            headers=a_headers,
        )
        assert {row["tenant_id"] for row in a_backend_status} == {"factory-a"}

        a_queue = wait_for(
            client,
            f"{GATEWAYS['factory-a']}/queue?limit=100",
            lambda rows: any(item.get("inspection_id") for item in rows),
        )
        a_item = next(item for item in a_queue if item.get("inspection_id"))
        switched = client.post(
            f"{BACKEND}/auth/switch-tenant",
            headers=a_headers,
            json={"tenant_id": "factory-b"},
        )
        switched.raise_for_status()
        b_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
        b_backend_status = wait_for(
            client,
            f"{BACKEND}/gateways/status",
            lambda rows: any(row["gateway_id"] == "factory-b-gw-cell12" for row in rows),
            headers=b_headers,
        )
        assert {row["tenant_id"] for row in b_backend_status} == {"factory-b"}
        cross_tenant = client.get(
            f"{BACKEND}/inspections/{a_item['inspection_id']}", headers=b_headers
        )
        assert cross_tenant.status_code == 404, cross_tenant.text

        print(
            {
                "gateways": {
                    tenant: {
                        "gateway_id": payload["gateway_id"],
                        "status": payload["status"],
                        "queue_depth": payload["queue_depth"],
                    }
                    for tenant, payload in local_status.items()
                },
                "backend_status": {
                    "factory-a": a_backend_status[0]["status"],
                    "factory-b": b_backend_status[0]["status"],
                },
                "cross_tenant_read": "blocked",
                "sample_inspection": a_item["inspection_id"],
            }
        )


if __name__ == "__main__":
    main()
