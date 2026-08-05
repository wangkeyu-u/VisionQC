from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from visionqc_ml.policy import ThresholdPolicy
from visionqc_ml.schemas import InferenceResult, PolicyDecision


def _payload(score: float, decision: str) -> dict[str, object]:
    digest = "a" * 64
    image = {"uri": "/tmp/heatmap.png", "sha256": digest, "mime_type": "image/png", "width": 32, "height": 32}
    return {
        "schema_version": "visionqc.inference.v1",
        "inspection_id": "insp_1",
        "status": "SCORED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {
            "id": "patchcore-transistor",
            "version": "1.0.0-rc1",
            "feature_bank_version": "fb-1",
            "package_sha256": digest,
            "adapter": "anomalib.patchcore.v2",
            "runtime": "anomalib==2.0.0",
            "device": "cpu",
        },
        "input": {"uri": "/tmp/input.png", "sha256": digest, "mime_type": "image/png", "width": 32, "height": 32},
        "anomaly": {
            "score": score,
            "heatmap": image,
            "overlay": image,
            "claim_scope": "anomaly_and_region_only",
            "semantic_defect_confirmed": False,
            "root_cause_confirmed": False,
            "statement": "Anomaly evidence only; defect semantics and root cause require human confirmation.",
        },
        "policy": {
            "version": "policy-1",
            "review_threshold": 0.4,
            "hold_threshold": 0.8,
            "decision": decision,
            "reason": "test",
        },
        "latency": {"preprocess_ms": 1, "inference_ms": 2, "postprocess_ms": 1, "total_ms": 4, "warm": True},
        "warnings": [],
    }


def test_policy_boundaries_are_explicit() -> None:
    policy = ThresholdPolicy("v1", 0.4, 0.8)
    assert policy.route(0.399)[0] == PolicyDecision.AUTO_RELEASE
    assert policy.route(0.4)[0] == PolicyDecision.REVIEW_REQUIRED
    assert policy.route(0.799)[0] == PolicyDecision.REVIEW_REQUIRED
    assert policy.route(0.8)[0] == PolicyDecision.BATCH_HOLD_AND_REVIEW


def test_schema_prevents_semantic_or_root_cause_confirmation() -> None:
    payload = _payload(0.9, "BATCH_HOLD_AND_REVIEW")
    payload["anomaly"]["semantic_defect_confirmed"] = True  # type: ignore[index]
    with pytest.raises(ValidationError):
        InferenceResult.model_validate(payload)


def test_schema_rejects_policy_score_mismatch() -> None:
    with pytest.raises(ValidationError, match="does not match score routing"):
        InferenceResult.model_validate(_payload(0.2, "REVIEW_REQUIRED"))

