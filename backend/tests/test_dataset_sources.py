from __future__ import annotations

import io
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.auth import Role


def _official_category(root: Path, png_bytes) -> Path:
    paths = (
        "train/good/000.png",
        "test/good/000.png",
        "test/scratch/000.png",
        "ground_truth/scratch/000_mask.png",
    )
    for relative in paths:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(png_bytes(80 if "good" in relative else 180))
    return root


def test_modelops_starts_without_optional_data_and_is_demo_only(
    client: TestClient, auth_headers
) -> None:
    response = client.get(
        "/api/v1/modelops/status",
        headers=auth_headers(actor_id="modelops-reader", roles=[Role.QUALITY_MANAGER]),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["dataset_source_type"] == "DEMO_SYNTHETIC"
    assert body["report_status"] == "DEMO_ONLY"
    assert body["dataset_registration_id"] is None
    assert body["customer_data_gate"] == "BLOCKED_NO_CUSTOMER_DATA"
    assert "NO_EFFECT_CLAIM" in body["risk_labels"]
    assert body["mvtec_metrics_available"] is False


def test_official_benchmark_registration_is_validated_and_tenant_scoped(
    client: TestClient, auth_headers, png_bytes, tmp_path: Path
) -> None:
    category_root = _official_category(tmp_path / "transistor", png_bytes)
    headers = auth_headers(actor_id="benchmark-importer", roles=[Role.ML_ENGINEER])
    response = client.post(
        "/api/v1/datasets/registrations",
        headers=headers,
        json={
            "source_type": "OFFICIAL_BENCHMARK",
            "name": "MVTec transistor lab source",
            "category": "transistor",
            "source_path": str(category_root),
            "license_acknowledged": True,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"]["source_type"] == "OFFICIAL_BENCHMARK"
    assert body["source"]["status"] == "VALIDATED"
    assert len(body["source"]["dataset_fingerprint"]) == 64
    assert {"NON_COMMERCIAL_BENCHMARK", "NOT_FACTORY_DATA"}.issubset(body["source"]["risk_labels"])
    assert "source_path" not in body["metadata"]
    assert body["metadata"]["source_name"] == "transistor"

    listed = client.get("/api/v1/datasets/registrations", headers=headers)
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == body["id"]

    other_tenant = client.get(
        "/api/v1/datasets/registrations",
        headers=auth_headers(tenant_id="factory-b", roles=[Role.ML_ENGINEER]),
    )
    assert other_tenant.status_code == 200
    assert other_tenant.json() == []
    cross_tenant_revoke = client.post(
        f"/api/v1/datasets/registrations/{body['id']}/revoke",
        headers=auth_headers(tenant_id="factory-b", roles=[Role.ML_ENGINEER]),
        json={"reason": "cross tenant revoke must fail"},
    )
    assert cross_tenant_revoke.status_code == 404

    revoked = client.post(
        f"/api/v1/datasets/registrations/{body['id']}/revoke",
        headers=auth_headers(actor_id="auditor-1", roles=[Role.ML_ENGINEER]),
        json={"reason": "withdraw benchmark registration"},
    )
    assert revoked.status_code == 200
    assert revoked.json()["source"]["status"] == "REVOKED"
    assert revoked.json()["source"]["dataset_fingerprint"] == body["source"]["dataset_fingerprint"]


def test_customer_provenance_missing_keeps_registration_draft_and_blocks_pilot(
    client: TestClient, auth_headers, png_bytes, tmp_path: Path
) -> None:
    customer_root = tmp_path / "customer"
    customer_root.mkdir()
    (customer_root / "capture-000.png").write_bytes(png_bytes(120))
    headers = auth_headers(actor_id="customer-importer", roles=[Role.ML_ENGINEER])
    response = client.post(
        "/api/v1/datasets/registrations",
        headers=headers,
        json={
            "source_type": "CUSTOMER_PILOT",
            "name": "customer capture without provenance",
            "category": "transistor",
            "source_path": str(customer_root),
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"]["status"] == "DRAFT"
    assert "CUSTOMER_PROVENANCE_INCOMPLETE" in body["source"]["risk_labels"]
    status = client.get(
        "/api/v1/modelops/status",
        headers=auth_headers(actor_id="customer-reader", roles=[Role.QUALITY_MANAGER]),
    )
    assert status.status_code == 200
    assert status.json()["dataset_source_type"] == "CUSTOMER_PILOT"
    assert status.json()["dataset_source_status"] == "DRAFT"
    assert status.json()["report_status"] == "CUSTOMER_PILOT_INSUFFICIENT_EVIDENCE"
    assert status.json()["customer_data_gate"] == "BLOCKED_CUSTOMER_PROVENANCE_INCOMPLETE"
    assert status.json()["activation_allowed"] is False


def test_dataset_contract_rejects_missing_license_traversal_and_fingerprint_mismatch(
    client: TestClient, auth_headers, png_bytes, tmp_path: Path
) -> None:
    valid_root = _official_category(tmp_path / "valid", png_bytes)
    headers = auth_headers(actor_id="contract-tester", roles=[Role.ML_ENGINEER])
    missing_license = client.post(
        "/api/v1/datasets/registrations",
        headers=headers,
        json={
            "source_type": "OFFICIAL_BENCHMARK",
            "name": "unacknowledged",
            "category": "transistor",
            "source_path": str(valid_root),
        },
    )
    assert missing_license.status_code == 422

    traversal_archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(traversal_archive, "w") as archive:
        archive.writestr("../outside.png", png_bytes(20))
    unsafe = client.post(
        "/api/v1/datasets/registrations",
        headers=headers,
        json={
            "source_type": "OFFICIAL_BENCHMARK",
            "name": "unsafe archive",
            "category": "transistor",
            "source_path": str(traversal_archive),
            "license_acknowledged": True,
        },
    )
    assert unsafe.status_code == 422

    mismatch = client.post(
        "/api/v1/datasets/registrations",
        headers=headers,
        json={
            "source_type": "OFFICIAL_BENCHMARK",
            "name": "wrong digest",
            "category": "transistor",
            "source_path": str(valid_root),
            "expected_sha256": "0" * 64,
            "license_acknowledged": True,
        },
    )
    assert mismatch.status_code == 422


def test_official_archive_upload_accepts_category_license_metadata(
    client: TestClient, auth_headers, png_bytes
) -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("mvtec/transistor/train/good/000.png", png_bytes(80))
        archive.writestr("mvtec/transistor/test/good/000.png", png_bytes(80))
        archive.writestr("mvtec/transistor/test/scratch/000.png", png_bytes(180))
        archive.writestr(
            "mvtec/transistor/ground_truth/scratch/000_mask.png", png_bytes(255)
        )
        archive.writestr("mvtec/transistor/license.txt", "CC BY-NC-SA 4.0")
        archive.writestr("mvtec/transistor/readme.txt", "official category metadata")
    payload.seek(0)

    response = client.post(
        "/api/v1/datasets/registrations/upload",
        headers=auth_headers(actor_id="archive-importer", roles=[Role.ML_ENGINEER]),
        data={
            "source_type": "OFFICIAL_BENCHMARK",
            "name": "MVTec transistor archive",
            "category": "transistor",
            "license_acknowledged": "true",
        },
        files={"file": ("mvtec.zip", payload.getvalue(), "application/zip")},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["source"]["status"] == "VALIDATED"
    assert body["metadata"]["import_mode"] == "upload"
    assert body["metadata"]["file_count"] == 6


def test_mounted_import_respects_configured_roots(
    client: TestClient, auth_headers, png_bytes, tmp_path: Path, settings
) -> None:
    allowed_root = tmp_path / "allowed-imports"
    allowed_root.mkdir()
    settings.dataset_import_roots = str(allowed_root)
    outside = _official_category(tmp_path / "outside" / "transistor", png_bytes)

    response = client.post(
        "/api/v1/datasets/registrations",
        headers=auth_headers(actor_id="root-guard", roles=[Role.ML_ENGINEER]),
        json={
            "source_type": "OFFICIAL_BENCHMARK",
            "name": "outside configured root",
            "category": "transistor",
            "source_path": str(outside),
            "license_acknowledged": True,
        },
    )

    assert response.status_code == 422
    assert "outside the configured import roots" in response.text


def test_qualification_binds_dataset_fingerprint_and_rejects_cross_tenant_reference(
    client: TestClient, auth_headers, png_bytes, tmp_path: Path
) -> None:
    category_root = _official_category(tmp_path / "transistor", png_bytes)
    import_response = client.post(
        "/api/v1/datasets/registrations",
        headers=auth_headers(actor_id="binder", roles=[Role.ML_ENGINEER]),
        json={
            "source_type": "OFFICIAL_BENCHMARK",
            "name": "bindable benchmark",
            "category": "transistor",
            "source_path": str(category_root),
            "license_acknowledged": True,
        },
    )
    assert import_response.status_code == 201
    registration = import_response.json()
    base = {
        "product_code": "transistor",
        "model_id": "candidate",
        "model_version": "1.0.0",
        "feature_bank_version": "fb-1",
        "package_sha256": "a" * 64,
        "evidence_path": "/tmp/evidence-package",
        "evidence_sha256": "b" * 64,
        "deployment_pack_key": "factory_a/transistor",
        "dataset_registration_id": registration["id"],
    }
    wrong_fingerprint = client.post(
        "/api/v1/modelops/qualifications",
        headers=auth_headers(actor_id="binder", roles=[Role.ML_ENGINEER]),
        json={**base, "dataset_fingerprint": "f" * 64},
    )
    assert wrong_fingerprint.status_code == 422

    cross_tenant = client.post(
        "/api/v1/modelops/qualifications",
        headers=auth_headers(tenant_id="factory-b", actor_id="other", roles=[Role.ML_ENGINEER]),
        json=base,
    )
    assert cross_tenant.status_code == 404
