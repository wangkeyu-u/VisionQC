from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.auth import Role
from app.models import AuditEvent, DeploymentPack, ModelQualification
from app.qualification import REQUIRED_EVIDENCE_FILES, verify_evidence_package


def _write_evidence(path: Path, fingerprint: str, provenance: dict, *, passing: bool) -> str:
    """Synthetic API contract evidence, without a trained model or customer result."""
    path.mkdir(exist_ok=True)
    decision = "CUSTOMER_PILOT_PASS" if passing else "CUSTOMER_PILOT_NO_GO"
    metrics = {
        "image_auroc": 0.99,
        "defect_error_auto_release_rate": 0.01 if passing else 0.30,
        "review_hold_recall": 0.99 if passing else 0.70,
        "hold_recall": 0.90,
        "normal_review_hold_rate": 0.10,
        "warm_p95_ms": 100.0,
    }
    gates = {
        "decision": "GO" if passing else "NO-GO",
        "report_status": decision,
        "checks": {
            name: {"status": "PASS" if passing else "FAIL", "value": value}
            for name, value in {
                **metrics,
                "no_split_leakage": True,
                "model_package_integrity": True,
                "customer_data_provenance": True,
            }.items()
        },
    }
    payloads = {
        "qualification-summary.json": {
            "qualification_status": decision,
            "source_type": "CUSTOMER_PILOT",
        },
        "metrics.json": {"metrics": metrics, "gates": gates},
        "provenance.json": {
            "source_type": "CUSTOMER_PILOT",
            "dataset_fingerprint": fingerprint,
            "customer_provenance": provenance,
            "model_package_sha256": "a" * 64,
        },
    }
    for name in REQUIRED_EVIDENCE_FILES - {"evidence-manifest.json", "release-decision.json"}:
        content = json.dumps(payloads.get(name, {})) if name.endswith(".json") else "Test fixture"
        (path / name).write_text(content, encoding="utf-8")

    def inventory() -> dict:
        return {
            item.name: {
                "sha256": hashlib.sha256(item.read_bytes()).hexdigest(),
                "size_bytes": item.stat().st_size,
            }
            for item in path.iterdir()
            if item.name not in {"evidence-manifest.json", "release-decision.json"}
        }

    files = inventory()
    digest = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    release = {
        "decision": decision,
        "gate_decision": gates["decision"],
        "approval_status": "PENDING_APPROVAL" if passing else "BLOCKED",
        "source_type": "CUSTOMER_PILOT",
        "dataset_fingerprint": fingerprint,
        "model_package_sha256": "a" * 64,
        "evidence_package_sha256": digest,
    }
    release_path = path / "release-decision.json"
    release_path.write_text(json.dumps(release), encoding="utf-8")
    files[release_path.name] = {
        "sha256": hashlib.sha256(release_path.read_bytes()).hexdigest(),
        "size_bytes": release_path.stat().st_size,
    }
    (path / "evidence-manifest.json").write_text(
        json.dumps({"schema_version": "visionqc.evidence-manifest.v1", "files": files}),
        encoding="utf-8",
    )
    assert verify_evidence_package(path, expected_model_package_sha256="a" * 64)["valid"]
    return digest


@pytest.fixture
def qualification_fixture(app, client, auth_headers, png_bytes, tmp_path):
    provenance = {
        "tenant": "factory-a",
        "site": "test-site",
        "line": "test-line",
        "camera": "test-camera",
        "product": "transistor",
        "capture_window_start": "2026-10-01T10:00:00Z",
        "capture_window_end": "2026-10-01T11:00:00Z",
        "label_source": "synthetic test labels",
        "approver": "test-approver",
        "consent": True,
        "retention_policy": "temporary test data",
    }
    root = tmp_path / "synthetic-captures"
    root.mkdir()
    (root / "sample.png").write_bytes(png_bytes(80))
    importer_headers = auth_headers(actor_id="ml-1", roles=[Role.ML_ENGINEER])
    registration = client.post(
        "/api/v1/datasets/registrations",
        headers=importer_headers,
        json={
            "source_type": "CUSTOMER_PILOT",
            "name": "synthetic lifecycle fixture",
            "category": "transistor",
            "source_path": str(root),
            "customer_provenance": provenance,
        },
    )
    assert registration.status_code == 201, registration.text
    dataset = registration.json()
    assert dataset["source"]["status"] == "VALIDATED"
    fingerprint = dataset["source"]["dataset_fingerprint"]
    evidence_path = tmp_path / "evidence"
    digest = _write_evidence(evidence_path, fingerprint, provenance, passing=True)
    # Bind the bootstrap demo pack to the fixture package identity for API activation.
    with app.state.session_factory() as session:
        pack = session.scalar(
            select(DeploymentPack).where(
                DeploymentPack.tenant_id == "factory-a", DeploymentPack.status == "ACTIVE"
            )
        )
        assert pack is not None
        manifest = {
            **pack.manifest,
            "model": {**pack.manifest["model"], "package_sha256": "a" * 64},
        }
        pack.manifest = manifest
        session.commit()
    model = manifest["model"]
    create = client.post(
        "/api/v1/modelops/qualifications",
        headers=importer_headers,
        json={
            "product_code": "transistor",
            "model_id": model["id"],
            "model_version": model["version"],
            "feature_bank_version": model["feature_bank_version"],
            "package_sha256": "a" * 64,
            "evidence_path": str(evidence_path),
            "evidence_sha256": digest,
            "deployment_pack_key": manifest["pack_key"],
            "dataset_registration_id": dataset["id"],
        },
    )
    assert create.status_code == 200, create.text
    qualification_id = create.json()["id"]

    def action(name):
        actor, role = {
            "evaluate": ("ml-1", Role.ML_ENGINEER),
            "approve": ("quality-1", Role.QUALITY_MANAGER),
            "activate": ("release-1", Role.FDE),
            "retire": ("quality-1", Role.QUALITY_MANAGER),
            "rollback": ("release-1", Role.FDE),
        }[name]
        return client.post(
            f"/api/v1/modelops/qualifications/{qualification_id}/{name}",
            headers=auth_headers(actor_id=actor, roles=[role]),
            json={"reason": "exercise synthetic lifecycle contract"},
        )

    return {
        "id": qualification_id,
        "action": action,
        "evidence_path": evidence_path,
        "fingerprint": fingerprint,
        "provenance": provenance,
        "dataset_id": dataset["id"],
    }


def _advance(fixture, target):
    for action, status in (
        ("evaluate", "EVALUATED"),
        ("approve", "APPROVED"),
        ("activate", "ACTIVE"),
        ("retire", "RETIRED"),
    ):
        response = fixture["action"](action)
        assert response.status_code == 200, response.text
        assert response.json()["status"] == status
        if status == target:
            return
    raise AssertionError(f"unknown lifecycle target: {target}")


def test_valid_evidence_can_complete_lifecycle_and_rollback(qualification_fixture):
    _advance(qualification_fixture, "RETIRED")
    rollback = qualification_fixture["action"]("rollback")
    assert rollback.status_code == 200, rollback.text
    assert rollback.json()["status"] == "ACTIVE"


@pytest.mark.parametrize(
    ("action", "before"),
    [("approve", "EVALUATED"), ("activate", "APPROVED"), ("rollback", "RETIRED")],
)
def test_rehashed_replacement_evidence_cannot_advance_lifecycle(
    app, qualification_fixture, action, before
):
    fixture = qualification_fixture
    _advance(fixture, before)
    replacement_digest = _write_evidence(
        fixture["evidence_path"], fixture["fingerprint"], fixture["provenance"], passing=False
    )
    response = fixture["action"](action)
    assert response.status_code == 422, response.text
    assert "digest does not match registered digest" in response.text
    with app.state.session_factory() as session:
        item = session.get(ModelQualification, fixture["id"])
        assert item is not None
        assert item.status == before
        assert item.evidence_sha256 != replacement_digest
        assert item.gates["decision"] == "GO"
        audits = session.scalars(
            select(AuditEvent).where(AuditEvent.target_id == fixture["id"])
        ).all()
        event = {"approve": "approved", "activate": "activated", "rollback": "rollback"}[action]
        assert not any(entry.action == f"model_qualification.{event}" for entry in audits)


def test_revoked_customer_dataset_cannot_be_reactivated_by_rollback(
    app, client, auth_headers, qualification_fixture
):
    fixture = qualification_fixture
    _advance(fixture, "RETIRED")
    revoked = client.post(
        f"/api/v1/datasets/registrations/{fixture['dataset_id']}/revoke",
        headers=auth_headers(actor_id="ml-2", roles=[Role.ML_ENGINEER]),
        json={"reason": "withdraw the dataset authorization"},
    )
    assert revoked.status_code == 200, revoked.text
    response = fixture["action"]("rollback")
    assert response.status_code == 403, response.text
    with app.state.session_factory() as session:
        assert session.get(ModelQualification, fixture["id"]).status == "RETIRED"
        assert session.scalar(
            select(AuditEvent.id).where(
                AuditEvent.target_id == fixture["id"],
                AuditEvent.action == "model_qualification.rollback",
            )
        ) is None


@pytest.mark.parametrize(
    ("action", "before"),
    [("approve", "EVALUATED"), ("activate", "APPROVED"), ("rollback", "RETIRED")],
)
def test_corrupt_evidence_returns_controlled_error_without_state_change(
    app, qualification_fixture, action, before
):
    fixture = qualification_fixture
    _advance(fixture, before)
    (fixture["evidence_path"] / "metrics.json").write_text("corrupt", encoding="utf-8")
    response = fixture["action"](action)
    assert response.status_code == 422, response.text
    assert "qualification evidence verification failed" in response.text
    with app.state.session_factory() as session:
        assert session.get(ModelQualification, fixture["id"]).status == before


@pytest.mark.parametrize(
    ("action", "before"),
    [("approve", "EVALUATED"), ("activate", "APPROVED"), ("rollback", "RETIRED")],
)
@pytest.mark.parametrize(
    "field,value", [("gate_decision", "NO-GO"), ("approval_status", "BLOCKED")]
)
def test_blocked_release_metadata_cannot_reuse_cached_go_gates(
    app, qualification_fixture, action, before, field, value
):
    fixture = qualification_fixture
    _advance(fixture, before)
    path = fixture["evidence_path"]
    release_path = path / "release-decision.json"
    release = json.loads(release_path.read_text(encoding="utf-8"))
    original_digest = release["evidence_package_sha256"]
    release[field] = value
    release_path.write_text(json.dumps(release), encoding="utf-8")
    inventory_path = path / "evidence-manifest.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    inventory["files"][release_path.name] = {
        "sha256": hashlib.sha256(release_path.read_bytes()).hexdigest(),
        "size_bytes": release_path.stat().st_size,
    }
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    # The core digest intentionally excludes the release file; pinning alone is insufficient.
    assert verify_evidence_package(path, expected_model_package_sha256="a" * 64)[
        "evidence_package_sha256"
    ] == original_digest
    response = fixture["action"](action)
    assert response.status_code == 422, response.text
    assert "not eligible for customer approval" in response.text
    with app.state.session_factory() as session:
        assert session.get(ModelQualification, fixture["id"]).status == before


def test_qualification_lifecycle_requires_evidence_and_role_separation(
    client, auth_headers
) -> None:
    create = client.post(
        "/api/v1/modelops/qualifications",
        headers=auth_headers(actor_id="ml-1", roles=[Role.ML_ENGINEER]),
        json={
            "product_code": "transistor",
            "model_id": "candidate",
            "model_version": "1.0.0",
            "feature_bank_version": "fb-1",
            "package_sha256": "a" * 64,
            "evidence_path": str(Path("/tmp/qualification-not-present")),
            "evidence_sha256": "b" * 64,
            "deployment_pack_key": "factory_a/transistor",
        },
    )
    assert create.status_code == 200, create.text
    qualification_id = create.json()["id"]

    forbidden = client.post(
        f"/api/v1/modelops/qualifications/{qualification_id}/evaluate",
        headers=auth_headers(actor_id="quality-1", roles=[Role.QUALITY_MANAGER]),
        json={"reason": "attempted evaluation with wrong role"},
    )
    assert forbidden.status_code == 403

    missing_evidence = client.post(
        f"/api/v1/modelops/qualifications/{qualification_id}/evaluate",
        headers=auth_headers(actor_id="ml-1", roles=[Role.ML_ENGINEER]),
        json={"reason": "evaluate candidate evidence package"},
    )
    assert missing_evidence.status_code == 422

    illegal_activation = client.post(
        f"/api/v1/modelops/qualifications/{qualification_id}/activate",
        headers=auth_headers(actor_id="release-1", roles=[Role.FDE]),
        json={"reason": "attempt activation before evaluation"},
    )
    assert illegal_activation.status_code == 409
