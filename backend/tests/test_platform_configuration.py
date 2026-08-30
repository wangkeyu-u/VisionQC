from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.deployment import load_manifest
from app.platform_config import (
    ConfigurationError,
    ConfigurationLayers,
    PlatformConfiguration,
    layers_from_legacy_manifest,
    merge_configuration_layers,
    redact_configuration,
)
from app.policy import evaluate_policy
from app.schemas import InspectionContext


def test_four_configuration_layers_have_deterministic_precedence_and_provenance() -> None:
    result = merge_configuration_layers(
        platform_defaults={
            "display_name": "Platform default",
            "data_retention_days": 90,
            "capture_channels": ["api_upload"],
        },
        industry_pack={
            "display_name": "Industry pack",
            "data_retention_days": 180,
            "industry": "electronics",
        },
        tenant_override={
            "tenant_id": "tenant-a",
            "display_name": "Tenant A",
            "data_retention_days": 365,
        },
        runtime_site_override={
            "display_name": "Tenant A / Site 07",
            "timezone": "Asia/Shanghai",
        },
        tenant_id="tenant-a",
        version="cfg-2026-08-30",
    )

    effective = result.effective_config
    assert effective.display_name == "Tenant A / Site 07"
    assert effective.data_retention_days == 365
    assert effective.industry == "electronics"
    assert effective.timezone == "Asia/Shanghai"
    assert result.sources["display_name"] == "runtime_site_override"
    assert result.sources["data_retention_days"] == "tenant_override"
    assert result.sources["industry"] == "industry_pack"
    assert len(result.config_hash) == 64
    assert result.config_hash == merge_configuration_layers(
        {
            "display_name": "Platform default",
            "data_retention_days": 90,
            "capture_channels": ["api_upload"],
        },
        {"display_name": "Industry pack", "data_retention_days": 180, "industry": "electronics"},
        {"tenant_id": "tenant-a", "display_name": "Tenant A", "data_retention_days": 365},
        {"display_name": "Tenant A / Site 07", "timezone": "Asia/Shanghai"},
        tenant_id="tenant-a",
        version="cfg-2026-08-30",
    ).config_hash


def test_configuration_overrides_are_strict_and_tenant_bound() -> None:
    with pytest.raises(ValidationError):
        ConfigurationLayers.model_validate({"tenant_override": {"not_a_field": True}})

    with pytest.raises(ConfigurationError, match="does not match"):
        merge_configuration_layers(
            tenant_override={"tenant_id": "tenant-b"},
            tenant_id="tenant-a",
        )

    with pytest.raises(ValidationError):
        PlatformConfiguration(
            tenant_id="tenant-a",
            risk_gates={"abnormal_auto_release": True},
        )


def test_secret_values_are_rejected_but_secret_references_are_safe_to_expose() -> None:
    result = merge_configuration_layers(
        tenant_override={
            "connector_refs": {
                "qms": {
                    "connector_id": "quality-system",
                    "contract_version": "v1",
                    "secret_ref": {"secret_ref": "vault://tenant-a/qms"},
                }
            }
        },
        tenant_id="tenant-a",
    )
    safe = redact_configuration(result.effective_config)
    assert safe["connector_refs"]["qms"]["secret_ref"]["secret_ref"] == "vault://tenant-a/qms"
    assert "password" not in str(safe)

    with pytest.raises(ConfigurationError, match="embedded secret"):
        merge_configuration_layers(
            tenant_override={"connector_refs": {"qms": {"password": "leaked-secret"}}},
            tenant_id="tenant-a",
        )


def test_legacy_manifest_is_adapted_without_promoting_automotive_fields() -> None:
    path = (
        Path(__file__).parents[1]
        / "deployment-packs"
        / "manifests"
        / "duerr-demo-paint-quality.json"
    )
    manifest = load_manifest(path)
    layers = layers_from_legacy_manifest(manifest)
    result = merge_configuration_layers(
        layers.platform_defaults,
        layers.industry_pack,
        layers.tenant_override,
        layers.runtime_site_override,
        tenant_id="duerr-demo",
    )

    assert result.effective_config.industry == "automotive-paint"
    assert "body_id" not in result.effective_config.model_dump(mode="json")
    assert result.effective_config.automotive_paint is None


def test_generic_inspection_context_does_not_require_customer_identifiers() -> None:
    context = InspectionContext(
        product_code="generic-item",
        batch_no="lot-1",
        station_code="station-1",
        captured_at="2026-08-30T00:00:00Z",
    )
    assert context.workpiece_id is None
    assert "body_id" not in context.model_dump(mode="json")


def test_workflow_preferences_route_to_review_or_hold_without_relaxing_safety() -> None:
    from app.domain import PolicyRoute
    from app.policy import PolicyConfig

    policy = PolicyConfig(
        version="policy-1",
        default={"review_threshold": 0.4, "hold_threshold": 0.8},
    )
    review = evaluate_policy(
        0.6,
        policy,
        product_code="item",
        station_code="station",
        manual_review_enabled=False,
        batch_hold_enabled=True,
    )
    assert review.route == PolicyRoute.BATCH_HOLD_AND_REVIEW

    safe = evaluate_policy(
        0.1,
        policy,
        product_code="item",
        station_code="station",
        auto_release_enabled=False,
    )
    assert safe.route == PolicyRoute.MANUAL_REVIEW

    strict = evaluate_policy(
        0.6,
        policy,
        product_code="item",
        station_code="station",
        manual_review_enabled=False,
        batch_hold_enabled=False,
    )
    assert strict.route == PolicyRoute.BATCH_HOLD_AND_REVIEW


def test_effective_configuration_api_is_tenant_scoped_and_preflight_is_redacted(
    client: TestClient, auth_headers
) -> None:
    factory_a_headers = auth_headers(tenant_id="factory-a", roles=["admin"])
    factory_b_headers = auth_headers(tenant_id="factory-b", roles=["admin"])

    a_response = client.get("/api/v1/config/effective", headers=factory_a_headers)
    b_response = client.get("/api/v1/configuration/effective", headers=factory_b_headers)
    assert a_response.status_code == 200
    assert b_response.status_code == 200
    a_body = a_response.json()
    b_body = b_response.json()
    assert a_body["tenant_id"] == "factory-a"
    assert b_body["tenant_id"] == "factory-b"
    assert a_body["config_hash"] != b_body["config_hash"]
    assert a_body["effective_config"]["industry"] == "electronics"
    assert b_body["effective_config"]["industry"] == "glass-packaging"
    assert a_body["validation_status"] == "VALID"

    preview = client.post(
        "/api/v1/config/validate",
        headers=factory_a_headers,
        json={
            "platform_defaults": {"data_retention_days": 90},
            "industry_pack": {"data_retention_days": 180},
            "tenant_override": {
                "display_name": "Configured tenant",
                "connector_refs": {
                    "qms": {
                        "connector_id": "qms",
                        "contract_version": "v2",
                        "secret_ref": {"secret_ref": "vault://factory-a/qms"},
                    }
                },
            },
            "runtime_site_override": {"timezone": "Asia/Shanghai"},
        },
    )
    assert preview.status_code == 200, preview.text
    preview_body = preview.json()
    assert preview_body["effective_config"]["data_retention_days"] == 180
    assert preview_body["sources"]["data_retention_days"] == "industry_pack"
    assert preview_body["effective_config"]["connector_refs"]["qms"]["secret_ref"] == {
        "secret_ref": "vault://factory-a/qms"
    }
    assert "leaked-secret" not in preview.text

    gate = client.post(
        "/api/v1/config/validate",
        headers=factory_a_headers,
        json={"tenant_override": {"risk_gates": {"abnormal_auto_release": True}}},
    )
    assert gate.status_code == 422
    assert "Input should be False" in gate.text

    bad_schema = client.post(
        "/api/v1/config/validate",
        headers=factory_a_headers,
        json={"schema_version": "customer-specific-v9"},
    )
    assert bad_schema.status_code == 422
    assert "customer-specific-v9" not in bad_schema.text


def test_deployment_persists_secret_reference_without_breaking_legacy_manifest_reads(
    client: TestClient, auth_headers
) -> None:
    manifest = load_manifest(
        Path(__file__).parents[1] / "deployment-packs" / "manifests" / "factory-a-transistor.json"
    ).model_dump(mode="json")
    manifest["version"] = "platform-config-secret-ref"
    manifest["pack_key"] = "factory_a/platform-config-secret-ref"
    manifest["configuration_layers"] = {
        "tenant_override": {
            "connector_refs": {
                "qms": {
                    "connector_id": "quality-system",
                    "contract_version": "v1",
                    "secret_ref": "vault://factory-a/qms",
                }
            }
        }
    }
    response = client.post(
        "/api/v1/deployments",
        headers=auth_headers(tenant_id="factory-a", roles=["admin"]),
        json={"manifest": manifest},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["effective_config"]["connector_refs"]["qms"]["secret_ref"] == {
        "secret_ref": "vault://factory-a/qms"
    }
    reread = client.get(
        f"/api/v1/deployments/{body['id']}/manifest",
        headers=auth_headers(tenant_id="factory-a", roles=["admin"]),
    )
    assert reread.status_code == 200, reread.text
    assert "vault://factory-a/qms" in reread.text
    assert "[REDACTED]" not in reread.text
