"""Offline shadow scoring and candidate comparison helpers."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .calibration import load_score_records
from .hashing import sha256_file, write_json


def _route(score: float, review_threshold: float, hold_threshold: float) -> str:
    if score < review_threshold:
        return "AUTO_RELEASE"
    if score < hold_threshold:
        return "REVIEW_REQUIRED"
    return "BATCH_HOLD_AND_REVIEW"


def run_shadow_evaluation(
    active_predictions_path: Path,
    candidate_predictions_path: Path,
    active_thresholds_path: Path,
    candidate_thresholds_path: Path,
    output_path: Path,
    *,
    product_category: str,
) -> dict[str, Any]:
    """Compare active and candidate outputs without calling an online service."""
    active = load_score_records(active_predictions_path)
    candidate = load_score_records(candidate_predictions_path)
    active_by_id = {record.sample_id: record for record in active}
    candidate_by_id = {record.sample_id: record for record in candidate}
    if set(active_by_id) != set(candidate_by_id):
        raise ValueError("shadow evaluation requires identical sample ids")
    for records, label in ((active, "active"), (candidate, "candidate")):
        categories = {record.product_category for record in records if record.product_category is not None}
        if categories and categories != {product_category}:
            raise ValueError(f"{label} predictions do not match product category {product_category}: {categories}")

    active_thresholds = _thresholds(active_thresholds_path)
    candidate_thresholds = _thresholds(candidate_thresholds_path)
    changes: Counter[str] = Counter()
    score_deltas: list[float] = []
    changed_samples: list[dict[str, Any]] = []
    for sample_id in sorted(active_by_id):
        active_record = active_by_id[sample_id]
        candidate_record = candidate_by_id[sample_id]
        active_route = _route(active_record.score, *active_thresholds)
        candidate_route = _route(candidate_record.score, *candidate_thresholds)
        score_delta = candidate_record.score - active_record.score
        score_deltas.append(score_delta)
        if active_route != candidate_route:
            changes[f"{active_route}->{candidate_route}"] += 1
            changed_samples.append(
                {
                    "sample_id": sample_id,
                    "label": active_record.label,
                    "active_score": active_record.score,
                    "candidate_score": candidate_record.score,
                    "score_delta": score_delta,
                    "active_route": active_route,
                    "candidate_route": candidate_route,
                }
            )
    result = {
        "schema_version": "visionqc.shadow-evaluation.v1",
        "product_category": product_category,
        "sample_count": len(active),
        "active_predictions_sha256": sha256_file(active_predictions_path),
        "candidate_predictions_sha256": sha256_file(candidate_predictions_path),
        "active_thresholds": active_thresholds,
        "candidate_thresholds": candidate_thresholds,
        "score_delta": {
            "mean": sum(score_deltas) / len(score_deltas) if score_deltas else None,
            "min": min(score_deltas) if score_deltas else None,
            "max": max(score_deltas) if score_deltas else None,
        },
        "route_changes": dict(sorted(changes.items())),
        "changed_sample_count": len(changed_samples),
        "changed_samples": changed_samples,
        "safety_note": "Shadow evaluation is offline evidence. It does not activate a model or write to MES/QMS.",
        "rollback_conditions_to_review": [
            "candidate increases auto-release of benchmark anomalies beyond the approved policy bound",
            "candidate worsens hold recall or latency guardrails on the accepted evaluation cohort",
            "human review identifies a material camera/process-specific regression",
        ],
    }
    write_json(output_path, result)
    return result


def _thresholds(path: Path) -> tuple[float, float]:
    payload = _read_json(path)
    review = float(payload["review_threshold"])
    hold = float(payload["hold_threshold"])
    if not 0.0 <= review < hold <= 1.0:
        raise ValueError(f"invalid thresholds in {path}")
    return review, hold


def _read_json(path: Path) -> dict[str, Any]:
    import json

    return json.loads(path.read_text(encoding="utf-8"))
