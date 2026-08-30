#!/usr/bin/env python3
"""Check the three opt-in industry Gateway services after Compose startup."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


HOST = os.getenv("VQC_COMPOSE_HOST", "localhost")
SERVICES = {
    "electronics": (8094, "example-electronics", "example-electronics/electronics"),
    "packaging": (8095, "example-packaging", "example-packaging/packaging"),
    "automotive-paint": (
        8096,
        "example-automotive-paint",
        "example-automotive-paint/automotive-paint",
    ),
}


def _get(url: str, timeout: float = 2.0) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _wait_for_service(kind: str, port: int, tenant_id: str, pack_key: str) -> dict[str, object]:
    deadline = time.monotonic() + float(os.getenv("VQC_COMPOSE_WAIT_SECONDS", "60"))
    url = f"http://{HOST}:{port}/healthz"
    last_error = "not reached"
    while time.monotonic() < deadline:
        try:
            payload = _get(url)
            if payload.get("tenant_id") != tenant_id or payload.get("pack_key") != pack_key:
                raise RuntimeError(
                    f"{kind} returned the wrong tenant/pack: "
                    f"{payload.get('tenant_id')} / {payload.get('pack_key')}"
                )
            return payload
        except (OSError, ValueError, RuntimeError) as exc:
            last_error = str(exc)
            time.sleep(1)
    raise RuntimeError(f"{kind} did not become ready at {url}: {last_error}")


def main() -> int:
    results = {
        kind: _wait_for_service(kind, port, tenant_id, pack_key)
        for kind, (port, tenant_id, pack_key) in SERVICES.items()
    }
    print(json.dumps({"status": "passed", "gateways": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError) as exc:
        print(f"Compose industry smoke failed: {exc}")
        raise SystemExit(1) from exc
