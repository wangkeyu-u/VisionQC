#!/usr/bin/env python3
"""Validate one or more VisionQC Deployment Pack manifests before onboarding."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "backend"))

from app.deployment import DeploymentManifest, load_manifest  # noqa: E402


def validate(paths: list[Path]) -> list[DeploymentManifest]:
    manifests = [load_manifest(path) for path in paths]
    tenant_ids = [manifest.tenant.id for manifest in manifests]
    pack_keys = [manifest.pack_key for manifest in manifests]
    if len(tenant_ids) != len(set(tenant_ids)):
        raise ValueError("input contains more than one manifest for the same tenant")
    if len(pack_keys) != len(set(pack_keys)):
        raise ValueError("input contains duplicate pack_key values")
    for manifest in manifests:
        for product in manifest.products:
            for station in manifest.stations:
                manifest.policy.resolve(product.code, station.code)
    return manifests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", nargs="+", type=Path, help="manifest JSON file(s)")
    args = parser.parse_args()
    paths = [path.resolve() for path in args.manifest]
    try:
        manifests = validate(paths)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Deployment Pack validation failed: {exc}", file=sys.stderr)
        return 1
    for manifest in manifests:
        print(
            json.dumps(
                {
                    "pack_key": manifest.pack_key,
                    "tenant_id": manifest.tenant.id,
                    "version": manifest.version,
                    "model_id": manifest.model.id,
                    "policy_version": manifest.policy.version,
                    "connectors": {
                        "mes": manifest.connectors.mes.contract_version,
                        "qms": manifest.connectors.qms.contract_version,
                    },
                    "status": "valid",
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
