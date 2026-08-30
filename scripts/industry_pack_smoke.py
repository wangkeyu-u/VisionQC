#!/usr/bin/env python3
"""Run the config -> edge preflight -> neutral connector smoke for all examples."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
EDGE_SOURCE_ROOT = REPOSITORY_ROOT / "edge-gateway" / "src"
sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(EDGE_SOURCE_ROOT))

from app.connectors import InMemoryConnector, RetryingConnectorExecutor  # noqa: E402
from app.deployment import load_manifest  # noqa: E402
from app.generic_qms_mock import GenericQmsMockConnector  # noqa: E402
from edge_gateway.config import GatewaySettings  # noqa: E402
from edge_gateway.deployment import GatewayDeploymentPack  # noqa: E402
from edge_gateway.runtime import GatewayRuntime  # noqa: E402
from edge_gateway.simulator import generate_samples  # noqa: E402


EXAMPLE_ROOT = BACKEND_ROOT / "deployment-packs" / "examples"
EXAMPLES = {
    "electronics": EXAMPLE_ROOT / "electronics-transistor" / "resolved-deployment-pack.json",
    "packaging": EXAMPLE_ROOT / "packaging-bottle" / "resolved-deployment-pack.json",
    "automotive-paint": EXAMPLE_ROOT / "automotive-paint" / "resolved-deployment-pack.json",
}


def _run_preflight(pack_path: Path, watch_root: Path, data_dir: Path) -> str:
    command = [
        sys.executable,
        str(REPOSITORY_ROOT / "scripts" / "visionqc.py"),
        "preflight",
        "--pack",
        str(pack_path),
        "--watch-root",
        str(watch_root),
        "--data-dir",
        str(data_dir),
        "--skip-network",
    ]
    result = subprocess.run(
        command,
        cwd=BACKEND_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = (result.stdout + result.stderr).strip()
        raise RuntimeError(f"preflight failed for {pack_path}: {detail}")
    return next(
        (line for line in reversed(result.stdout.splitlines()) if line.startswith("Result:")),
        "Result: READY",
    )


def _connector_smoke(tenant_id: str, station_code: str) -> dict[str, object]:
    executor = RetryingConnectorExecutor(max_attempts=2, backoff_seconds=0)
    mes = InMemoryConnector("MES_SMOKE")
    mes_result = executor.execute(
        mes,
        "HOLD_BATCH",
        {"batch_no": f"{tenant_id}-batch", "reason": "neutral smoke"},
        f"{tenant_id}:mes:001",
    )
    qms = GenericQmsMockConnector()
    qms_result = executor.execute(
        qms,
        "CREATE_TICKET",
        {
            "case_reference": f"{tenant_id}-case-001",
            "batch_reference": f"{tenant_id}-batch",
            "station_reference": station_code,
            "disposition": "REVIEW",
            "reason": "neutral connector contract smoke",
            "evidence_refs": ["sha256:synthetic-smoke"],
        },
        f"{tenant_id}:qms:001",
    )
    replay = executor.execute(
        qms,
        "CREATE_TICKET",
        {
            "case_reference": f"{tenant_id}-case-001",
            "batch_reference": f"{tenant_id}-batch",
            "station_reference": station_code,
            "disposition": "REVIEW",
            "reason": "neutral connector contract smoke",
        },
        f"{tenant_id}:qms:001",
    )
    if mes_result.error or qms_result.error or replay.error:
        raise RuntimeError("neutral connector smoke returned an error")
    if not qms_result.result or not replay.result:
        raise RuntimeError("generic QMS smoke did not return a result")
    if not replay.result.summary.get("deduplicated"):
        raise RuntimeError("generic QMS smoke did not prove idempotent replay")
    return {
        "mes": mes_result.result.status if mes_result.result else "ERROR",
        "qms": qms_result.result.status,
        "qms_replay": "deduplicated",
    }


def _run_example(kind: str, pack_path: Path) -> dict[str, object]:
    manifest = load_manifest(pack_path)
    pack = GatewayDeploymentPack.load(pack_path)
    station_code = pack.stations[0].code
    with TemporaryDirectory(prefix=f"visionqc-{kind}-") as temporary:
        root = Path(temporary)
        incoming = root / "incoming"
        state = root / "state"
        preflight_result = _run_preflight(pack_path, incoming, state)
        settings = GatewaySettings(
            mode="demo",
            gateway_id=pack.gateway_id,
            pack_path=pack_path,
            data_dir=state,
            watch_root=incoming,
            stable_for_seconds=0,
            upload_enabled=False,
            data_consent=False,
            min_width=32,
            min_height=32,
        )
        runtime = GatewayRuntime(settings, pack)
        try:
            generate_samples(pack, runtime.watcher.root, kinds=["normal"], count=1)
            runtime.scan_once()
            accepted = runtime.scan_once()
            if len(accepted) != 1 or accepted[0].status != "QUEUED":
                raise RuntimeError(f"edge ingest did not queue one sample for {kind}")
            local_result = runtime.upload_once()
            if local_result is None or local_result.status != "LOCAL_ONLY":
                raise RuntimeError(f"privacy boundary did not keep {kind} sample local")
        finally:
            runtime.close()
        connector_result = _connector_smoke(manifest.tenant.id, station_code)
    return {
        "industry": manifest.industry,
        "tenant_id": manifest.tenant.id,
        "pack_key": manifest.pack_key,
        "preflight": preflight_result,
        "edge": "queued_then_local_only",
        "connectors": connector_result,
    }


def main() -> int:
    results = [_run_example(kind, path) for kind, path in EXAMPLES.items()]
    print(json.dumps({"status": "passed", "examples": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
