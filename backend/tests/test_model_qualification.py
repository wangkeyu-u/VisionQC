from __future__ import annotations

from pathlib import Path

from app.auth import Role


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
