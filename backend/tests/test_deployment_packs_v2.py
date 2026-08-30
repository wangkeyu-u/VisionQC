from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.deployment import (
    RESOLVED_PACK_SCHEMA_VERSION,
    IndustryPack,
    load_industry_pack,
    load_manifest,
    load_manifests,
    load_tenant_overlay,
    payload_sha256,
    resolve_pack,
)

ROOT = Path(__file__).resolve().parents[1]
PACK_ROOT = ROOT / "deployment-packs"


def _example_paths() -> list[tuple[Path, Path]]:
    return [
        (
            PACK_ROOT / "industry-packs/electronics.json",
            PACK_ROOT / "overlays/examples/electronics-transistor.json",
        ),
        (
            PACK_ROOT / "industry-packs/packaging.json",
            PACK_ROOT / "overlays/examples/packaging-bottle.json",
        ),
        (
            PACK_ROOT / "industry-packs/automotive-paint.json",
            PACK_ROOT / "overlays/examples/automotive-paint.json",
        ),
    ]


def test_three_industry_overlays_resolve_to_complete_v2_contract() -> None:
    industries = {load_industry_pack(path).industry for path, _ in _example_paths()}
    assert industries == {"electronics", "packaging", "automotive-paint"}

    for industry_path, overlay_path in _example_paths():
        industry = load_industry_pack(industry_path)
        overlay = load_tenant_overlay(overlay_path)
        resolved = resolve_pack(industry, overlay)
        assert resolved.schema_version == RESOLVED_PACK_SCHEMA_VERSION
        assert resolved.tenant.id == overlay.tenant.id
        assert resolved.industry_pack is not None
        assert resolved.tenant_overlay is not None
        assert resolved.collection is not None
        assert resolved.risk_strategy is not None
        assert resolved.workflow is not None
        assert resolved.permissions is not None
        assert resolved.retention is not None
        assert resolved.localization is not None
        assert resolved.validation is not None
        assert resolved.integrity is not None
        assert resolved.migration is not None
        assert resolved.connectors.qms.capability == "qms"
        assert resolved.connectors.ingest is not None
        assert resolved.connectors.notification is not None
        assert resolved.connectors.analytics is not None
        assert (
            payload_sha256(resolved.model_dump(mode="json")) == resolved.integrity.manifest_sha256
        )


def test_checked_in_resolved_examples_are_hash_verified() -> None:
    for path in sorted((PACK_ROOT / "examples").glob("*/resolved-deployment-pack.json")):
        manifest = load_manifest(path)
        assert manifest.schema_version == RESOLVED_PACK_SCHEMA_VERSION
        assert manifest.integrity is not None
        assert payload_sha256(json.loads(path.read_text(encoding="utf-8"))) == (
            manifest.integrity.manifest_sha256
        )


def test_manifest_discovery_skips_source_overlay_files() -> None:
    manifests = load_manifests(PACK_ROOT / "examples")
    assert {manifest.tenant.id for manifest in manifests} == {
        "example-electronics",
        "example-packaging",
        "example-automotive-paint",
    }


def test_pack_hash_tampering_is_rejected(tmp_path: Path) -> None:
    source = PACK_ROOT / "industry-packs/electronics.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["description"] = "tampered"
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="hash mismatch"):
        load_industry_pack(target)


def test_overlay_must_pin_the_exact_industry_pack_hash() -> None:
    industry = load_industry_pack(PACK_ROOT / "industry-packs/electronics.json")
    overlay = load_tenant_overlay(PACK_ROOT / "overlays/examples/electronics-transistor.json")
    mismatched = overlay.model_copy(
        update={"industry_pack": overlay.industry_pack.model_copy(update={"sha256": "0" * 64})}
    )
    with pytest.raises(ValueError, match="industry_pack.sha256"):
        resolve_pack(industry, mismatched)


def test_connector_contract_rejects_duplicate_operations_and_secret_values() -> None:
    industry_path = PACK_ROOT / "industry-packs/electronics.json"
    payload = json.loads(industry_path.read_text(encoding="utf-8"))
    payload["connectors"]["mes"]["operations"] = ["HOLD_BATCH", "HOLD_BATCH"]
    with pytest.raises(ValueError, match="operations must be unique"):
        IndustryPack.model_validate(payload)
    payload["connectors"]["mes"]["operations"] = ["HOLD_BATCH", "RELEASE_BATCH"]
    payload["connectors"]["mes"]["secret_refs"] = ["not-a-secret"]
    with pytest.raises(ValueError, match="secret refs"):
        IndustryPack.model_validate(payload)


def test_legacy_v1_manifest_remains_readable() -> None:
    manifest = load_manifest(PACK_ROOT / "manifests/factory-a-transistor.json")
    assert manifest.schema_version == "visionqc.deployment-pack.v1"
    assert manifest.integrity is None
