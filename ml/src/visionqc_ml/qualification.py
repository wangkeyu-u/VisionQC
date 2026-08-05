"""VisionQC Pilot qualification protocols, gates, and evidence packages.

This module deliberately accepts precomputed score JSONL.  Training and
inference remain separate concerns; a qualification run never invents model
scores when the official data or a verified model package is unavailable.
"""

from __future__ import annotations

import platform
import subprocess
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score

from .calibration import CalibrationResult, ScoreRecord, load_score_records
from .dataset import ManifestEntry, load_manifest, validate_user_dataset, verify_manifest
from .dataset_source import CustomerDataProvenance, DatasetSourceType, demo_dataset_source
from .hashing import read_json, sha256_file, sha256_json, write_json
from .package import verify_model_package

PILOT_GATE_VERSION = "visionqc-pilot-gates.v2"
PILOT_GATES: dict[str, dict[str, Any]] = {
    "image_auroc": {"operator": ">=", "threshold": 0.90},
    "defect_error_auto_release_rate": {"operator": "<=", "threshold": 0.05},
    "review_hold_recall": {"operator": ">=", "threshold": 0.95},
    "hold_recall": {"operator": ">=", "threshold": 0.80},
    "normal_review_hold_rate": {"operator": "<=", "threshold": 0.25},
    "warm_p95_ms": {"operator": "<=", "threshold": 500.0},
    "no_split_leakage": {"operator": "==", "threshold": True},
    "model_package_integrity": {"operator": "==", "threshold": True},
    "customer_data_provenance": {
        "operator": "==",
        "threshold": True,
        "scope": "customer_pilot_approval",
    },
}

REQUIRED_EVIDENCE_FILES = {
    "qualification-summary.json",
    "model-card.md",
    "evaluation-report.md",
    "metrics.json",
    "confidence-intervals.json",
    "split-manifest.json",
    "provenance.json",
    "release-decision.json",
    "error-cases.json",
    "source-evidence.json",
    "evidence-manifest.json",
}


def _blocked_metrics(reason: str) -> dict[str, Any]:
    """Return the complete metric surface without inventing unavailable values."""
    return {
        "metric_status": "UNAVAILABLE",
        "unavailable_reason": reason,
        "sample_count": 0,
        "normal_sample_count": 0,
        "anomalous_sample_count": 0,
        "image_auroc": None,
        "pixel_auroc": None,
        "aupro": None,
        "precision": None,
        "recall": None,
        "f1": None,
        "normal_false_positive_rate": None,
        "defect_error_auto_release_rate": None,
        "review_hold_recall": None,
        "hold_recall": None,
        "manual_review_burden_rate": None,
        "cold_start_ms": None,
        "warm_inference_p50_ms": None,
        "warm_inference_p95_ms": None,
        "warm_p95_ms": None,
    }


def _top_level_inventory(path: Path) -> dict[str, dict[str, Any]]:
    return {
        item.name: {"sha256": sha256_file(item), "size_bytes": item.stat().st_size}
        for item in sorted(path.iterdir())
        if item.is_file() and item.name != "evidence-manifest.json"
    }


def _git_commit(repository_root: Path | None) -> str:
    if repository_root is None:
        return "unknown"
    try:
        return subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _jsonl_records(path: Path, allowed: set[str] | None = None) -> list[ScoreRecord]:
    records = [ScoreRecord.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not records:
        raise ValueError(f"no score records in {path}")
    if allowed and any(record.split not in allowed for record in records):
        raise ValueError(f"score records contain an unexpected split; expected one of {sorted(allowed)}")
    return records


def split_manifest_for_protocol_b(entries: Iterable[ManifestEntry], *, seed: int = 20260804) -> dict[str, Any]:
    """Make a deterministic stratified calibration/holdout manifest.

    Training samples are never placed in either branch.  Each image and mask
    content hash is included so overlap can be detected even if paths change.
    """
    candidates = [entry for entry in entries if entry.source_split == "test"]
    groups: dict[str, list[ManifestEntry]] = {}
    for entry in candidates:
        groups.setdefault(entry.anomaly_subtype, []).append(entry)
    calibration: list[ManifestEntry] = []
    holdout: list[ManifestEntry] = []
    for _subtype, items in sorted(groups.items()):
        ranked = sorted(items, key=lambda item: sha256_json({"seed": seed, "sample_id": item.sample_id}))
        cut = max(1, len(ranked) // 2) if len(ranked) > 1 else 1
        calibration.extend(ranked[:cut])
        holdout.extend(ranked[cut:] or ranked[:1])

    def row(entry: ManifestEntry, split: str) -> dict[str, Any]:
        return {
            "sample_id": entry.sample_id,
            "split": split,
            "image_path": entry.image_path,
            "image_sha256": entry.image_sha256,
            "mask_path": entry.mask_path,
            "mask_sha256": entry.mask_sha256,
            "label": entry.label,
            "anomaly_subtype": entry.anomaly_subtype,
        }

    result = {
        "schema_version": "visionqc.protocol-b-split.v1",
        "protocol": "B",
        "seed": seed,
        "rule": "source test only; deterministic SHA-256 stratification by anomaly_subtype",
        "train": [row(entry, "train") for entry in entries if entry.source_split == "train"],
        "calibration": [row(entry, "calibration") for entry in sorted(calibration, key=lambda item: item.sample_id)],
        "holdout": [row(entry, "holdout") for entry in sorted(holdout, key=lambda item: item.sample_id)],
    }
    validate_split_manifest(result)
    result["split_sha256"] = {
        key: sha256_json(value) for key, value in result.items() if key in {"train", "calibration", "holdout"}
    }
    result["manifest_sha256"] = sha256_json(result)
    return result


def validate_split_manifest(split_manifest: dict[str, Any]) -> dict[str, Any]:
    """Reject path, sample, image, or mask overlap across every declared split."""
    split_names = ("train", "validation", "calibration", "holdout")
    buckets = {key: split_manifest.get(key, []) for key in split_names if key in split_manifest}
    seen: dict[str, tuple[str, str]] = {}
    overlaps: list[dict[str, str]] = []
    for split, rows in buckets.items():
        for row in rows:
            for field in ("sample_id", "image_path", "image_sha256", "mask_path", "mask_sha256"):
                value = row.get(field)
                if not value:
                    continue
                previous = seen.get(f"{field}:{value}")
                if previous:
                    overlaps.append({"field": field, "value": str(value), "left": previous[0], "right": split})
                else:
                    seen[f"{field}:{value}"] = (split, str(row.get("sample_id", "")))
    if overlaps:
        raise ValueError(f"split overlap detected: {overlaps[:10]}")
    return {"valid": True, "overlap_count": 0, "sample_counts": {key: len(value) for key, value in buckets.items()}}


def _classification(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    predicted = (scores >= threshold).astype(np.int8)
    precision, recall, f1, _ = precision_recall_fscore_support(labels, predicted, average="binary", zero_division=0)
    return {
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "threshold": threshold,
        "confusion_matrix": {
            "tn": int(np.sum((labels == 0) & (predicted == 0))),
            "fp": int(np.sum((labels == 0) & (predicted == 1))),
            "fn": int(np.sum((labels == 1) & (predicted == 0))),
            "tp": int(np.sum((labels == 1) & (predicted == 1))),
        },
    }


def _metric_values(records: list[ScoreRecord], review: float, hold: float) -> dict[str, float | None]:
    labels = np.asarray([item.label for item in records], dtype=np.int8)
    scores = np.asarray([item.score for item in records], dtype=np.float64)
    normal = labels == 0
    anomalous = labels == 1
    if not np.any(normal) or not np.any(anomalous):
        return {
            name: None
            for name in (
                "image_auroc",
                "defect_error_auto_release_rate",
                "review_hold_recall",
                "hold_recall",
                "normal_review_hold_rate",
                "cold_p95_ms",
                "warm_p95_ms",
            )
        }
    warm = np.asarray([item.latency_ms for item in records if item.warm], dtype=np.float64)
    cold = np.asarray([item.latency_ms for item in records if not item.warm], dtype=np.float64)
    return {
        "image_auroc": float(roc_auc_score(labels, scores)),
        "defect_error_auto_release_rate": float(np.mean(scores[anomalous] < review)),
        "review_hold_recall": float(np.mean(scores[anomalous] >= review)),
        "hold_recall": float(np.mean(scores[anomalous] >= hold)),
        "normal_review_hold_rate": float(np.mean(scores[normal] >= review)),
        "cold_p95_ms": float(np.percentile(cold, 95)) if cold.size else None,
        "warm_p95_ms": float(np.percentile(warm, 95)) if warm.size else None,
    }


def evaluate_protocol_a(records: list[ScoreRecord]) -> dict[str, Any]:
    """Return threshold-free image metrics for an independent test set."""
    labels = np.asarray([item.label for item in records], dtype=np.int8)
    scores = np.asarray([item.score for item in records], dtype=np.float64)
    image_auroc = float(roc_auc_score(labels, scores)) if len(np.unique(labels)) == 2 else None
    return {
        "protocol": "A",
        "threshold_free": True,
        "image_auroc": image_auroc,
        "pixel_auroc": None,
        "aupro": None,
        "sample_count": len(records),
        "label_counts": {"normal": int(np.sum(labels == 0)), "anomalous": int(np.sum(labels == 1))},
        "pixel_note": "pixel AUROC/AUPRO require verified heatmap and ground-truth mask arrays; no value is invented when absent",
    }


def calibrate_protocol_b(
    records: list[ScoreRecord], *, max_false_accept_rate: float = 0.05, target_hold_recall: float = 0.80
) -> dict[str, Any]:
    """Select review/hold thresholds from calibration records only."""
    if not records or {item.label for item in records} != {0, 1}:
        raise ValueError("Protocol B calibration requires normal and anomalous records")
    if any(item.split not in {"validation", "calibration"} for item in records):
        raise ValueError("Protocol B calibration accepts validation/calibration records only; holdout is forbidden")
    scores = np.asarray([item.score for item in records], dtype=np.float64)
    labels = np.asarray([item.label for item in records], dtype=np.int8)
    candidates = np.unique(np.concatenate(([0.0], scores, [1.0])))
    review_candidates = [
        float(item) for item in candidates if item < 1 and np.mean(scores[labels == 1] < item) <= max_false_accept_rate
    ]
    review = max(review_candidates, default=0.0)
    hold_candidates = [
        float(item)
        for item in candidates
        if item > review and np.mean(scores[labels == 1] >= item) >= target_hold_recall
    ]
    hold = max(hold_candidates, default=min(1.0, float(np.nextafter(review, 1.0))))
    if hold <= review:
        raise ValueError("Protocol B calibration cannot produce ordered review/hold thresholds")
    return {
        "protocol": "B",
        "source_split": "calibration",
        "review_threshold": review,
        "hold_threshold": hold,
        "constraints": {"max_false_accept_rate": max_false_accept_rate, "target_hold_recall": target_hold_recall},
        "achieved_on_calibration": _metric_values(records, review, hold),
        "sample_count": len(records),
    }


def evaluate_protocol_b(
    calibration: list[ScoreRecord], holdout: list[ScoreRecord], *, seed: int = 20260804
) -> dict[str, Any]:
    """Calibrate on one split and report business metrics only on holdout."""
    thresholds = calibrate_protocol_b(calibration)
    metrics = _metric_values(holdout, thresholds["review_threshold"], thresholds["hold_threshold"])
    return {
        "protocol": "B",
        "threshold_source": "calibration only",
        "thresholds": thresholds,
        "holdout_metrics": metrics,
        "confidence_intervals": bootstrap_confidence_intervals(
            holdout, thresholds["review_threshold"], thresholds["hold_threshold"], seed=seed
        ),
        "calibration_sample_count": len(calibration),
        "holdout_sample_count": len(holdout),
    }


def bootstrap_confidence_intervals(
    records: list[ScoreRecord], review: float, hold: float, *, seed: int, resamples: int = 1000
) -> dict[str, Any]:
    labels = np.asarray([item.label for item in records], dtype=np.int8)
    normal = np.flatnonzero(labels == 0)
    anomalous = np.flatnonzero(labels == 1)
    if len(normal) < 2 or len(anomalous) < 2:
        return {
            "method": "stratified percentile bootstrap",
            "available": False,
            "resamples": 0,
            "intervals": {},
            "reason": "at least two normal and two anomalous samples are required",
        }
    rng = np.random.default_rng(seed)
    observations: dict[str, list[float]] = {}
    for _ in range(resamples):
        indices = np.concatenate(
            (rng.choice(normal, len(normal), replace=True), rng.choice(anomalous, len(anomalous), replace=True))
        )
        sampled = [records[int(index)] for index in indices]
        for name, value in _metric_values(sampled, review, hold).items():
            if value is not None:
                observations.setdefault(name, []).append(value)
    estimates = _metric_values(records, review, hold)
    return {
        "method": "stratified percentile bootstrap",
        "available": True,
        "resamples": resamples,
        "seed": seed,
        "class_counts": {"normal": len(normal), "anomalous": len(anomalous)},
        "intervals": {
            name: {
                "estimate": estimates[name],
                "lower": float(np.percentile(values, 2.5)),
                "upper": float(np.percentile(values, 97.5)),
                "confidence": 0.95,
            }
            for name, values in observations.items()
        },
    }


def evaluate_pilot_gates(
    metrics: dict[str, Any],
    *,
    package_verified: bool,
    no_split_leakage: bool,
    evidence_complete: bool,
    source_type: DatasetSourceType = DatasetSourceType.OFFICIAL_BENCHMARK,
    customer_provenance_valid: bool | None = None,
) -> dict[str, Any]:
    source_type = DatasetSourceType(source_type)
    checks: dict[str, dict[str, Any]] = {}
    for name, rule in PILOT_GATES.items():
        value: Any = metrics.get(name)
        if name == "model_package_integrity":
            value = package_verified
        elif name == "no_split_leakage":
            value = no_split_leakage
        elif name == "customer_data_provenance":
            if source_type != DatasetSourceType.CUSTOMER_PILOT:
                checks[name] = {"status": "NOT_APPLICABLE", "value": None, **rule}
                continue
            value = customer_provenance_valid
        present = value is not None
        if not present:
            status = "INSUFFICIENT_EVIDENCE"
        elif rule["operator"] == ">=":
            status = "PASS" if value >= rule["threshold"] else "FAIL"
        elif rule["operator"] == "<=":
            status = "PASS" if value <= rule["threshold"] else "FAIL"
        else:
            status = "PASS" if value == rule["threshold"] else "FAIL"
        checks[name] = {"status": status, "value": value, **rule}
    missing = [name for name, check in checks.items() if check["status"] == "INSUFFICIENT_EVIDENCE"]
    failed = [name for name, check in checks.items() if check["status"] == "FAIL"]
    if not evidence_complete or missing:
        decision = "INSUFFICIENT_EVIDENCE"
    elif failed:
        decision = "NO-GO"
    else:
        decision = "GO"
    return {
        "gate_version": PILOT_GATE_VERSION,
        "source_type": source_type.value,
        "decision": decision,
        "checks": checks,
        "missing": missing,
        "failed": failed,
        "approval_eligible": (
            source_type == DatasetSourceType.CUSTOMER_PILOT
            and decision == "GO"
            and customer_provenance_valid is True
        ),
    }


def qualification_report_status(source_type: DatasetSourceType, decision: str) -> str:
    """Map an internal gate decision to a source-scoped public report status."""
    source_type = DatasetSourceType(source_type)
    if source_type == DatasetSourceType.DEMO_SYNTHETIC:
        return "DEMO_ONLY"
    prefix = "BENCHMARK" if source_type == DatasetSourceType.OFFICIAL_BENCHMARK else "CUSTOMER_PILOT"
    suffix = {
        "GO": "PASS",
        "NO-GO": "NO_GO",
        "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE",
    }.get(decision, "INSUFFICIENT_EVIDENCE")
    return f"{prefix}_{suffix}"


def _manifest_row(entry: ManifestEntry, split: str) -> dict[str, Any]:
    return {
        "sample_id": entry.sample_id,
        "split": split,
        "source_split": entry.source_split,
        "category": entry.category,
        "image_path": entry.image_path,
        "image_sha256": entry.image_sha256,
        "mask_path": entry.mask_path,
        "mask_sha256": entry.mask_sha256,
        "label": entry.label,
        "anomaly_subtype": entry.anomaly_subtype,
    }


def _pilot_split_manifest(entries: Iterable[ManifestEntry], manifest_meta: dict[str, Any]) -> dict[str, Any]:
    """Bind the run's fixed validation/test assignment to Pilot terminology."""
    materialized = list(entries)
    result: dict[str, Any] = {
        "schema_version": "visionqc.pilot-split-manifest.v2",
        "protocol": "A+B",
        "rule": "train remains adaptation data; validation calibrates thresholds; original test is frozen holdout",
        "source_manifest_sha256": manifest_meta["manifest_sha256"],
        "train": [_manifest_row(entry, "train") for entry in materialized if entry.split == "train"],
        "validation": [_manifest_row(entry, "validation") for entry in materialized if entry.split == "validation"],
        "holdout": [_manifest_row(entry, "holdout") for entry in materialized if entry.split == "test"],
    }
    validate_split_manifest(result)
    result["split_sha256"] = {key: sha256_json(result[key]) for key in ("train", "validation", "holdout")}
    result["manifest_sha256"] = sha256_json(result)
    return result


def _within(path: Path, root: Path) -> bool:
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
    except (OSError, ValueError):
        return False
    return resolved_path.is_relative_to(resolved_root)


def _required_file(path: Path, description: str) -> Path:
    if not path.is_file():
        raise ValueError(f"{description} is missing: {path}")
    return path


def _assert_close(actual: Any, expected: float, description: str, *, tolerance: float = 1e-8) -> None:
    if actual is None or abs(float(actual) - expected) > tolerance:
        raise ValueError(f"{description} does not match derived evidence: expected {expected}, got {actual}")


def _validate_prediction_alignment(
    records: list[ScoreRecord],
    entries: dict[str, ManifestEntry],
    *,
    split: str,
    category: str,
    run_dir: Path,
    predictions_path: Path,
) -> None:
    expected_ids = set(entries)
    actual_ids = {record.sample_id for record in records}
    if actual_ids != expected_ids:
        raise ValueError(
            f"{split} predictions do not exactly cover the manifest: "
            f"missing={sorted(expected_ids - actual_ids)[:10]}, unexpected={sorted(actual_ids - expected_ids)[:10]}"
        )
    for record in records:
        entry = entries[record.sample_id]
        if record.product_category != category:
            raise ValueError(
                f"{split} prediction category mismatch for {record.sample_id}: "
                f"expected {category}, got {record.product_category}"
            )
        if record.image_path != entry.image_path:
            raise ValueError(f"{split} prediction image path mismatch for {record.sample_id}")
        if record.label != entry.label or record.anomaly_subtype != entry.anomaly_subtype:
            raise ValueError(f"{split} prediction label/subtype mismatch for {record.sample_id}")
        heatmap_path = Path(record.heatmap_path)
        if not heatmap_path.is_absolute():
            heatmap_path = predictions_path.parent / heatmap_path
        if not _within(heatmap_path, run_dir) or not heatmap_path.is_file():
            raise ValueError(f"{split} prediction heatmap path is missing or outside the run: {heatmap_path}")


def _derived_holdout_metrics(
    records: list[ScoreRecord], thresholds: CalibrationResult, evaluation: dict[str, Any], performance: dict[str, Any]
) -> dict[str, Any]:
    labels = np.asarray([record.label for record in records], dtype=np.int8)
    scores = np.asarray([record.score for record in records], dtype=np.float64)
    normal = labels == 0
    anomalous = labels == 1
    if not np.any(normal) or not np.any(anomalous):
        raise ValueError("holdout predictions must contain both normal and anomalous samples")
    image_level = evaluation.get("metrics", {}).get("image_level", {})
    pixel_level = evaluation.get("metrics", {}).get("pixel_level", {})
    business = evaluation.get("metrics", {}).get("business", {})
    performance_metrics = evaluation.get("metrics", {}).get("performance", {})
    review = _classification(labels, scores, thresholds.review_threshold)
    hold = _classification(labels, scores, thresholds.hold_threshold)
    image_auroc = float(roc_auc_score(labels, scores))
    _assert_close(image_level.get("auroc"), image_auroc, "evaluation image AUROC")
    _assert_close(
        business.get("false_accept_rate"),
        float(np.mean(scores[anomalous] < thresholds.review_threshold)),
        "evaluation false accept rate",
    )
    _assert_close(
        business.get("false_reject_rate"),
        float(np.mean(scores[normal] >= thresholds.hold_threshold)),
        "evaluation false reject rate",
    )
    _assert_close(
        business.get("manual_review_rate"),
        float(np.mean(scores >= thresholds.review_threshold)),
        "evaluation manual review rate",
    )
    _assert_close(
        business.get("hold_rate"), float(np.mean(scores >= thresholds.hold_threshold)), "evaluation hold rate"
    )
    _assert_close(
        business.get("auto_release_rate"),
        float(np.mean(scores < thresholds.review_threshold)),
        "evaluation auto release rate",
    )
    _assert_close(
        image_level.get("at_review_threshold", {}).get("threshold"),
        thresholds.review_threshold,
        "evaluation review threshold",
    )
    _assert_close(
        image_level.get("at_hold_threshold", {}).get("threshold"),
        thresholds.hold_threshold,
        "evaluation hold threshold",
    )
    _assert_close(
        image_level.get("at_review_threshold", {}).get("recall"), review["recall"], "evaluation review recall"
    )
    _assert_close(image_level.get("at_hold_threshold", {}).get("recall"), hold["recall"], "evaluation hold recall")
    _assert_close(performance_metrics.get("warm_p50_ms"), float(performance["warm_p50_ms"]), "evaluation warm P50")
    _assert_close(performance_metrics.get("warm_p95_ms"), float(performance["warm_p95_ms"]), "evaluation warm P95")
    if pixel_level.get("auroc") is None or pixel_level.get("aupro_at_0_30_fpr") is None:
        raise ValueError("evaluation pixel AUROC and AUPRO are required for complete real-data evidence")
    return {
        "metric_status": "AVAILABLE",
        "unavailable_reason": None,
        "sample_count": len(records),
        "normal_sample_count": int(np.sum(normal)),
        "anomalous_sample_count": int(np.sum(anomalous)),
        "image_auroc": image_auroc,
        "pixel_auroc": float(pixel_level["auroc"]),
        "aupro": float(pixel_level["aupro_at_0_30_fpr"]),
        "precision": float(review["precision"]),
        "recall": float(review["recall"]),
        "f1": float(review["f1"]),
        "normal_false_positive_rate": float(np.mean(scores[normal] >= thresholds.review_threshold)),
        "normal_review_hold_rate": float(np.mean(scores[normal] >= thresholds.review_threshold)),
        "defect_error_auto_release_rate": float(np.mean(scores[anomalous] < thresholds.review_threshold)),
        "review_hold_recall": float(np.mean(scores[anomalous] >= thresholds.review_threshold)),
        "hold_recall": float(np.mean(scores[anomalous] >= thresholds.hold_threshold)),
        "manual_review_burden_rate": float(business["manual_review_rate"]),
        "cold_start_ms": float(performance["cold_ms"]),
        "warm_inference_p50_ms": float(performance["warm_p50_ms"]),
        "warm_inference_p95_ms": float(performance["warm_p95_ms"]),
        "warm_p95_ms": float(performance["warm_p95_ms"]),
    }


def _validate_gallery(
    gallery: dict[str, Any],
    gallery_dir: Path,
    records: list[ScoreRecord],
    thresholds: CalibrationResult,
    category: str,
) -> None:
    if gallery.get("schema_version") != "visionqc.error-gallery.v1":
        raise ValueError("gallery schema is invalid")
    cases = gallery.get("cases")
    if not isinstance(cases, list) or gallery.get("case_count", len(cases)) != len(cases):
        raise ValueError("gallery case count does not match gallery cases")
    expected_ids = {record.sample_id for record in records}
    case_ids: set[str] = set()
    for case in cases:
        sample_id = case.get("sample_id")
        if sample_id in case_ids or sample_id not in expected_ids:
            raise ValueError(f"gallery sample coverage is invalid: {sample_id}")
        case_ids.add(sample_id)
        if case.get("product_category") != category:
            raise ValueError(f"gallery category mismatch for {sample_id}")
        _assert_close(case.get("review_threshold"), thresholds.review_threshold, "gallery review threshold")
        _assert_close(case.get("hold_threshold"), thresholds.hold_threshold, "gallery hold threshold")
        for field in ("original", "heatmap", "overlay"):
            raw = case.get(field)
            if not isinstance(raw, str):
                raise ValueError(f"gallery {field} path is missing for {sample_id}")
            asset = gallery_dir / raw
            if Path(raw).is_absolute() or not _within(asset, gallery_dir) or not asset.is_file():
                raise ValueError(f"gallery {field} path is invalid for {sample_id}: {raw}")
    if case_ids != expected_ids:
        raise ValueError("gallery does not cover every held-out prediction")
    if gallery.get("thresholds", {}).get("review") is not None:
        _assert_close(
            gallery["thresholds"].get("review"), thresholds.review_threshold, "gallery summary review threshold"
        )
    if gallery.get("thresholds", {}).get("hold") is not None:
        _assert_close(gallery["thresholds"].get("hold"), thresholds.hold_threshold, "gallery summary hold threshold")


def _source_file(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "sha256": sha256_file(path), "size_bytes": path.stat().st_size}


def _source_inventory(
    run_dir: Path,
    package_path: Path,
    manifest_path: Path,
    manifest_meta_path: Path,
    receipt_path: Path,
    validation_path: Path,
    test_path: Path,
    thresholds_path: Path,
    evaluation_path: Path,
    performance_path: Path,
    gallery_dir: Path,
) -> dict[str, Any]:
    files: dict[str, dict[str, Any]] = {}

    def add(key: str, path: Path) -> None:
        files[key] = _source_file(path)

    add("run.json", run_dir / "run.json")
    add("summary.json", run_dir / "summary.json")
    add("manifest.jsonl", manifest_path)
    add("manifest-meta.json", manifest_meta_path)
    add("dataset-directory-receipt.json", receipt_path)
    add("predictions/validation.jsonl", validation_path)
    add("predictions/test.jsonl", test_path)
    add("calibration/thresholds.json", thresholds_path)
    add("evaluation/evaluation.json", evaluation_path)
    add("performance-probe.json", performance_path)
    add("package/model-package.json", package_path / "model-package.json")
    for path in sorted(item for item in gallery_dir.rglob("*") if item.is_file()):
        add(f"gallery/{path.relative_to(gallery_dir).as_posix()}", path)
    return {
        "schema_version": "visionqc.pilot-source-evidence.v1",
        "run_dir": str(run_dir.resolve()),
        "model_package_dir": str(package_path.resolve()),
        "files": files,
    }


def load_pilot_evidence(
    run_dir: Path,
    *,
    category: str,
    model_package: Path,
    dataset_root: Path | None = None,
    source_config: Path | None = None,
) -> dict[str, Any]:
    """Load and cross-check the immutable baseline artifacts consumed by Pilot."""
    run_dir = run_dir.expanduser().resolve()
    package_path = model_package.expanduser().resolve()
    run_path = _required_file(run_dir / "run.json", "baseline run manifest")
    summary_path = _required_file(run_dir / "summary.json", "baseline run summary")
    run_metadata = read_json(run_path)
    summary = read_json(summary_path)
    declared_manifest = Path(str(run_metadata.get("manifest_path", ""))).expanduser()
    if not declared_manifest.is_absolute():
        declared_manifest = (run_dir / declared_manifest).resolve()
    manifest_path = _required_file(declared_manifest, "dataset manifest")
    manifest_meta_path = _required_file(manifest_path.parent / "manifest-meta.json", "dataset manifest metadata")
    manifest_meta = read_json(manifest_meta_path)
    if (
        manifest_meta.get("source_type", DatasetSourceType.OFFICIAL_BENCHMARK.value)
        != DatasetSourceType.OFFICIAL_BENCHMARK.value
    ):
        raise ValueError("benchmark qualification requires an OFFICIAL_BENCHMARK manifest")
    if manifest_meta.get("category") != category:
        raise ValueError(f"manifest category mismatch: expected {category}, got {manifest_meta.get('category')}")
    declared_dataset_root = Path(str(manifest_meta.get("dataset_root", ""))).expanduser()
    resolved_dataset_root = (dataset_root or declared_dataset_root).resolve()
    if not declared_dataset_root or resolved_dataset_root != declared_dataset_root.resolve():
        raise ValueError(
            f"dataset root mismatch: run declares {declared_dataset_root}, supplied {resolved_dataset_root}"
        )
    receipt_path = _required_file(
        resolved_dataset_root / f"{category}.directory-receipt.json", "dataset directory receipt"
    )
    receipt = read_json(receipt_path)
    if (
        receipt.get("category") != category
        or Path(str(receipt.get("dataset_root", ""))).resolve() != resolved_dataset_root
        or receipt.get("source_type", DatasetSourceType.OFFICIAL_BENCHMARK.value)
        != DatasetSourceType.OFFICIAL_BENCHMARK.value
    ):
        raise ValueError("dataset receipt category or path does not match the manifest")
    if receipt.get("license_acknowledged") is not True:
        raise ValueError("dataset license acknowledgement is missing from the receipt")
    if source_config is not None:
        source = read_json(source_config)
        if source.get("category") != category:
            raise ValueError("source configuration category does not match the Pilot category")
        expected_archive = source.get("archive_sha256")
        if expected_archive and receipt.get("source_archive_sha256") != expected_archive:
            raise ValueError("dataset archive SHA-256 does not match the source configuration")
    verify_manifest(manifest_path, resolved_dataset_root, manifest_meta_path)
    entries = load_manifest(manifest_path)
    if {entry.category for entry in entries} != {category}:
        raise ValueError("manifest contains more than the requested category")
    actual_counts = {
        split: sum(1 for entry in entries if entry.split == split) for split in ("train", "validation", "test")
    }
    if manifest_meta.get("counts") != actual_counts:
        raise ValueError("manifest split counts do not match manifest metadata")
    split_manifest = _pilot_split_manifest(entries, manifest_meta)

    declared_package = summary.get("package_dir")
    if declared_package and Path(str(declared_package)).expanduser().resolve() != package_path:
        raise ValueError("model package path does not match the baseline summary")
    if summary.get("run_dir") and Path(str(summary["run_dir"])).expanduser().resolve() != run_dir:
        raise ValueError("baseline run path does not match run.json/CLI input")
    if summary.get("category") != category:
        raise ValueError("baseline summary category does not match the Pilot category")
    if summary.get("dataset_fingerprint") != manifest_meta.get("dataset_fingerprint"):
        raise ValueError("baseline summary dataset fingerprint does not match the manifest")

    package_manifest = verify_model_package(package_path, expected_category=category)
    if summary.get("package_sha256") != package_manifest.package_sha256:
        raise ValueError("model package SHA-256 does not match the baseline summary")
    if package_manifest.dataset_fingerprint != manifest_meta.get("dataset_fingerprint"):
        raise ValueError("model package dataset fingerprint does not match the manifest")
    if package_manifest.training_manifest_sha256 != manifest_meta.get("manifest_sha256"):
        raise ValueError("model package manifest SHA-256 does not match the dataset manifest")

    validation_path = _required_file(run_dir / "predictions" / "validation.jsonl", "validation predictions")
    test_path = _required_file(run_dir / "predictions" / "test.jsonl", "test predictions")
    thresholds_path = _required_file(run_dir / "calibration" / "thresholds.json", "calibration thresholds")
    evaluation_path = _required_file(run_dir / "evaluation" / "evaluation.json", "evaluation report")
    performance_path = _required_file(run_dir / "performance-probe.json", "performance probe")
    gallery_dir = run_dir / "gallery"
    gallery_json_path = _required_file(gallery_dir / "gallery.json", "error gallery JSON")
    gallery_index_path = _required_file(gallery_dir / "index.html", "error gallery HTML")

    validation_records = load_score_records(validation_path, required_split="validation")
    test_records = load_score_records(test_path, required_split="test")
    validation_entries = {entry.sample_id: entry for entry in entries if entry.split == "validation"}
    test_entries = {entry.sample_id: entry for entry in entries if entry.split == "test"}
    _validate_prediction_alignment(
        validation_records,
        validation_entries,
        split="validation",
        category=category,
        run_dir=run_dir,
        predictions_path=validation_path,
    )
    _validate_prediction_alignment(
        test_records,
        test_entries,
        split="test",
        category=category,
        run_dir=run_dir,
        predictions_path=test_path,
    )
    thresholds = CalibrationResult.model_validate(read_json(thresholds_path))
    if thresholds.source_split != "validation":
        raise ValueError("thresholds must declare validation as their source split")
    if thresholds.source_predictions_sha256 != sha256_file(validation_path):
        raise ValueError("threshold source prediction SHA-256 does not match validation predictions")
    validation_labels = [record.label for record in validation_records]
    expected_counts = {
        "total": len(validation_records),
        "normal": validation_labels.count(0),
        "anomalous": validation_labels.count(1),
    }
    if thresholds.sample_counts != expected_counts:
        raise ValueError("threshold sample counts do not match validation predictions")
    if sha256_file(package_path / "config" / "thresholds.json") != sha256_file(thresholds_path):
        raise ValueError("model package thresholds do not match the baseline calibration thresholds")
    if sha256_file(package_path / "provenance" / "manifest-meta.json") != sha256_file(manifest_meta_path):
        raise ValueError("model package manifest metadata does not match the baseline manifest metadata")

    evaluation = read_json(evaluation_path)
    if evaluation.get("schema_version") != "visionqc.evaluation.v1" or evaluation.get("evaluation_split") != "test":
        raise ValueError("evaluation must be a visionqc test evaluation")
    artifacts = evaluation.get("artifacts", {})
    if artifacts.get("predictions_sha256") != sha256_file(test_path):
        raise ValueError("evaluation prediction SHA-256 does not match test predictions")
    if artifacts.get("thresholds_sha256") != sha256_file(thresholds_path):
        raise ValueError("evaluation threshold SHA-256 does not match calibration thresholds")
    evaluation_dataset = evaluation.get("dataset", {})
    if evaluation_dataset.get("category") != category:
        raise ValueError("evaluation category does not match the Pilot category")
    for name in ("dataset_fingerprint", "manifest_sha256"):
        if evaluation_dataset.get(name) != manifest_meta.get(name):
            raise ValueError(f"evaluation {name} does not match manifest metadata")
    if evaluation_dataset.get("test_split_sha256") != manifest_meta.get("split_sha256", {}).get("test"):
        raise ValueError("evaluation test split SHA-256 does not match manifest metadata")
    evaluation_model = evaluation.get("model", {})
    if (
        evaluation_model.get("id") != package_manifest.model_id
        or evaluation_model.get("version") != package_manifest.model_version
    ):
        raise ValueError("evaluation model identity does not match the model package")
    if evaluation_model.get("adapter") != package_manifest.adapter:
        raise ValueError("evaluation model adapter does not match the model package")
    evaluation_thresholds = CalibrationResult.model_validate(evaluation.get("thresholds", {}))
    if evaluation_thresholds.model_dump(mode="json") != thresholds.model_dump(mode="json"):
        raise ValueError("evaluation thresholds do not match the frozen calibration artifact")
    package_evaluation_path = package_path / "metrics" / "evaluation.json"
    if sha256_file(package_evaluation_path) != sha256_file(evaluation_path):
        raise ValueError("model package evaluation report does not match the baseline evaluation")

    performance = read_json(performance_path)
    if performance.get("schema_version") != "visionqc.performance-probe.v1" or performance.get("category") != category:
        raise ValueError("performance probe schema or category is invalid")
    if (
        performance.get("warm_p50_ms") is None
        or performance.get("warm_p95_ms") is None
        or performance.get("cold_ms") is None
    ):
        raise ValueError("performance probe is missing required latency values")
    gallery = read_json(gallery_json_path)
    _validate_gallery(gallery, gallery_dir, test_records, thresholds, category)
    gallery["case_count"] = len(gallery["cases"])
    gallery["case_types"] = {
        case_type: sum(1 for case in gallery["cases"] if case.get("case_type") == case_type)
        for case_type in sorted({str(case.get("case_type")) for case in gallery["cases"]})
    }
    evaluation_gallery = evaluation.get("gallery", {})
    if Path(str(evaluation_gallery.get("json", ""))).expanduser().resolve() != gallery_json_path.resolve():
        raise ValueError("evaluation gallery JSON path does not match the baseline gallery")
    if Path(str(evaluation_gallery.get("path", ""))).expanduser().resolve() != gallery_index_path.resolve():
        raise ValueError("evaluation gallery HTML path does not match the baseline gallery")
    if evaluation_gallery.get("case_count") != gallery.get("case_count"):
        raise ValueError("evaluation gallery case count does not match the baseline gallery")

    metrics = _derived_holdout_metrics(test_records, thresholds, evaluation, performance)
    source_evidence = _source_inventory(
        run_dir,
        package_path,
        manifest_path,
        manifest_meta_path,
        receipt_path,
        validation_path,
        test_path,
        thresholds_path,
        evaluation_path,
        performance_path,
        gallery_dir,
    )
    return {
        "run_dir": run_dir,
        "package_path": package_path,
        "package_manifest": package_manifest,
        "manifest_path": manifest_path,
        "manifest_meta_path": manifest_meta_path,
        "manifest_meta": manifest_meta,
        "dataset_root": resolved_dataset_root,
        "dataset_receipt": receipt,
        "split_manifest": split_manifest,
        "validation_path": validation_path,
        "test_path": test_path,
        "thresholds_path": thresholds_path,
        "thresholds": thresholds,
        "evaluation_path": evaluation_path,
        "evaluation": evaluation,
        "performance_path": performance_path,
        "performance": performance,
        "gallery_dir": gallery_dir,
        "gallery": gallery,
        "metrics": metrics,
        "confidence_intervals": evaluation.get("metrics", {}).get("image_level", {}).get("bootstrap_ci", {}),
        "error_cases": gallery,
        "source_evidence": source_evidence,
        "summary": summary,
        "run_metadata": run_metadata,
        "model_reference": {
            "id": package_manifest.model_id,
            "version": package_manifest.model_version,
            "adapter": package_manifest.adapter,
            "package_sha256": package_manifest.package_sha256,
        },
    }


def _core_digest(output_dir: Path) -> str:
    entries = {
        path.relative_to(output_dir).as_posix(): {"sha256": sha256_file(path), "size_bytes": path.stat().st_size}
        for path in sorted(output_dir.iterdir())
        if path.is_file() and path.name not in {"release-decision.json", "evidence-manifest.json"}
    }
    return sha256_json(entries)


def verify_evidence_package(path: Path, *, expected_model_package_sha256: str | None = None) -> dict[str, Any]:
    """Verify evidence inventory and provenance before it can be approved/activated."""
    if not path.is_dir() or not REQUIRED_EVIDENCE_FILES.issubset(
        {item.name for item in path.iterdir() if item.is_file()}
    ):
        raise ValueError(f"qualification evidence package is incomplete: {path}")
    inventory = read_json(path / "evidence-manifest.json")
    if inventory.get("schema_version") != "visionqc.evidence-manifest.v1":
        raise ValueError("qualification evidence manifest schema is invalid")
    expected_inventory = _top_level_inventory(path)
    declared_inventory = inventory.get("files")
    if not isinstance(declared_inventory, dict) or set(declared_inventory) != set(expected_inventory):
        raise ValueError("qualification evidence inventory does not cover the complete package")
    for relative, details in inventory.get("files", {}).items():
        relative_path = Path(relative)
        if relative_path.is_absolute() or relative_path.name != relative or relative_path.parent != Path("."):
            raise ValueError(f"qualification evidence inventory contains an unsafe path: {relative}")
        file_path = path / relative
        if (
            not file_path.is_file()
            or sha256_file(file_path) != details["sha256"]
            or file_path.stat().st_size != details["size_bytes"]
        ):
            raise ValueError(f"qualification evidence file integrity mismatch: {relative}")
    source_evidence = read_json(path / "source-evidence.json")
    if source_evidence.get("schema_version") != "visionqc.pilot-source-evidence.v1":
        raise ValueError("qualification source evidence schema is invalid")
    source_files = source_evidence.get("files", {})
    if not isinstance(source_files, dict):
        raise ValueError("qualification source evidence files are invalid")
    for key, details in source_files.items():
        source_path = Path(str(details.get("path", ""))).expanduser()
        if not source_path.is_file():
            raise ValueError(f"qualification source evidence is missing: {key}: {source_path}")
        if sha256_file(source_path) != details.get("sha256") or source_path.stat().st_size != details.get("size_bytes"):
            raise ValueError(f"qualification source evidence integrity mismatch: {key}")
    release = read_json(path / "release-decision.json")
    expected_digest = _core_digest(path)
    if release.get("evidence_package_sha256") != expected_digest:
        raise ValueError("qualification evidence summary digest mismatch")
    provenance = read_json(path / "provenance.json")
    if expected_model_package_sha256 and provenance.get("model_package_sha256") != expected_model_package_sha256:
        raise ValueError("model package digest does not match qualification evidence")
    summary = read_json(path / "qualification-summary.json")
    metrics = read_json(path / "metrics.json")
    if release.get("decision") != summary.get("qualification_status"):
        raise ValueError("qualification summary decision does not match release decision")
    if release.get("decision") != metrics.get("gates", {}).get("report_status"):
        raise ValueError("qualification metrics gate decision does not match release decision")
    if release.get("model_package_sha256") != provenance.get("model_package_sha256"):
        raise ValueError("qualification release and provenance package digests do not match")
    source_type = str(provenance.get("source_type", provenance.get("data_status", "")))
    if source_type not in {item.value for item in DatasetSourceType}:
        raise ValueError("qualification evidence source type is invalid")
    if summary.get("source_type", source_type) != source_type:
        raise ValueError("qualification summary and provenance source types do not match")
    if release.get("source_type", source_type) != source_type:
        raise ValueError("qualification release and provenance source types do not match")
    if release.get("dataset_fingerprint") != provenance.get("dataset_fingerprint"):
        raise ValueError("qualification release and provenance dataset fingerprints do not match")
    return {
        "valid": True,
        "evidence_package_sha256": expected_digest,
        "decision": release.get("decision"),
        "gate_decision": release.get("gate_decision", metrics.get("gates", {}).get("decision")),
        "source_type": summary.get("source_type", provenance.get("source_type")),
        "dataset_fingerprint": provenance.get("dataset_fingerprint"),
        "approval_status": release.get("approval_status"),
        "model_package_sha256": provenance.get("model_package_sha256"),
    }


def _markdown_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _pilot_evaluation_markdown(
    *,
    factory: str,
    category: str,
    gate_result: dict[str, Any],
    metrics: dict[str, Any],
    confidence_intervals: dict[str, Any],
    split_manifest: dict[str, Any] | None,
    thresholds: dict[str, Any] | None,
    evaluation_report: dict[str, Any] | None,
    error_cases: dict[str, Any] | None,
    source_evidence: dict[str, Any],
) -> str:
    source_type = DatasetSourceType(gate_result.get("source_type", DatasetSourceType.OFFICIAL_BENCHMARK))
    report_status = str(gate_result.get("report_status") or gate_result["decision"])
    if source_type == DatasetSourceType.DEMO_SYNTHETIC:
        title = f"# VisionQC Demo-only workflow — {category}"
        scope_statement = "演示数据仅用于验证页面、接口和闭环流程, 不得用于效果声明、benchmark 声明或生产决策。"
        metric_heading = "Demo fixture metrics"
    elif source_type == DatasetSourceType.OFFICIAL_BENCHMARK:
        title = f"# VisionQC Benchmark Qualification / Pre-Pilot Lab Validation — {category}"
        scope_statement = (
            "本报告仅证明官方 benchmark 上的系统与评测流程可运行, 不代表任何客户数据、工厂现场效果或生产准备度。"
        )
        metric_heading = "Frozen benchmark holdout metrics"
    else:
        title = f"# VisionQC Customer Pilot qualification — {category}"
        scope_statement = "本报告仅适用于已登记且 provenance 完整的客户数据, 仍不等同于无条件生产批准。"
        metric_heading = "Frozen customer-pilot holdout metrics"
    available = metrics.get("metric_status") == "AVAILABLE"
    if not available:
        return (
            f"{title}\n\n"
            f"Report status: **{report_status}**\n\n"
            f"{scope_statement}\n\n"
            "Protocols: validation-only threshold calibration followed by an untouched holdout.\n\n"
            "No formal metric is reported when the selected optional dataset source has no verified evaluation evidence.\n\n"
            "| Metric | Value |\n| --- | ---: |\n"
            "| Image AUROC | null |\n| Pixel AUROC | null |\n| AUPRO | null |\n"
            "| Precision / Recall / F1 | null / null / null |\n"
            "| Normal false-positive rate | null |\n"
            "| Defect error auto-release rate | null |\n"
            "| Review + Hold recall | null |\n| Hold recall | null |\n"
            "| Manual review burden rate | null |\n| Cold start | null |\n"
            "| Warm inference P50 / P95 | null / null |\n\n"
            "Unavailable values are explicit nulls because the baseline evidence contract was not satisfied.\n"
        )

    lines = [
        title,
        "",
        f"Report status: **{report_status}**",
        "",
        scope_statement,
        "",
        f"## {metric_heading}",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Image AUROC | {_markdown_value(metrics['image_auroc'])} |",
        f"| Pixel AUROC | {_markdown_value(metrics['pixel_auroc'])} |",
        f"| AUPRO @ FPR 0.30 | {_markdown_value(metrics['aupro'])} |",
        f"| Precision / Recall / F1 @ review | {_markdown_value(metrics['precision'])} / {_markdown_value(metrics['recall'])} / {_markdown_value(metrics['f1'])} |",
        f"| Normal review/hold rate | {_markdown_value(metrics['normal_review_hold_rate'])} |",
        f"| Defect error auto-release rate | {_markdown_value(metrics['defect_error_auto_release_rate'])} |",
        f"| Review + Hold recall | {_markdown_value(metrics['review_hold_recall'])} |",
        f"| Hold recall | {_markdown_value(metrics['hold_recall'])} |",
        f"| Manual review burden rate | {_markdown_value(metrics['manual_review_burden_rate'])} |",
        f"| Cold start (ms) | {_markdown_value(metrics['cold_start_ms'])} |",
        f"| Warm P50 / P95 (ms) | {_markdown_value(metrics['warm_inference_p50_ms'])} / {_markdown_value(metrics['warm_inference_p95_ms'])} |",
        "",
        "## Pilot Gate checks",
        "",
        "| Gate | Value | Threshold | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    for name, check in gate_result["checks"].items():
        lines.append(
            f"| `{name}` | {_markdown_value(check['value'])} | {_markdown_value(check['threshold'])} | **{check['status']}** |"
        )
    lines.extend(
        [
            "",
            "## Threshold provenance",
            "",
            f"- Source split: `{(thresholds or {}).get('source_split', 'validation')}`.",
            f"- Strategy: `{(thresholds or {}).get('strategy', 'legacy')}`; safety margin: `{_markdown_value((thresholds or {}).get('safety_margin', 0.0))}`.",
            f"- Review threshold: `{_markdown_value((thresholds or {}).get('review_threshold'))}`; hold threshold: `{_markdown_value((thresholds or {}).get('hold_threshold'))}`.",
            "- Test labels were not used to select or adjust either threshold.",
            "",
            "## Confidence intervals",
            "",
        ]
    )
    intervals = confidence_intervals.get("intervals", {}) if isinstance(confidence_intervals, dict) else {}
    if intervals:
        lines.extend(["| Metric | Estimate | Lower | Upper |", "| --- | ---: | ---: | ---: |"])
        for name, interval in sorted(intervals.items()):
            lines.append(
                f"| `{name}` | {_markdown_value(interval.get('estimate'))} | {_markdown_value(interval.get('lower'))} | {_markdown_value(interval.get('upper'))} |"
            )
    else:
        lines.append("Confidence intervals are unavailable for the recorded sample size.")
    case_types = (error_cases or {}).get("case_types", {})
    lines.extend(
        [
            "",
            "## Error cases and claim boundary",
            "",
            f"- Gallery cases: `{(error_cases or {}).get('case_count', 0)}`; case types: `{case_types}`.",
            "- Allowed claim: anomaly likelihood and anomalous-region localization.",
            "- Not claimed: confirmed semantic defect type, root cause, or factory production readiness.",
            "",
            "## Split and evidence contract",
            "",
            f"- Validation samples: `{len((split_manifest or {}).get('validation', []))}`; frozen holdout samples: `{len((split_manifest or {}).get('holdout', []))}`.",
            f"- Source artifacts bound by SHA-256: `{len(source_evidence.get('files', {}))}`.",
            "- MVTec AD is an official non-commercial research benchmark; these results cannot be presented as factory, customer Pilot, or production evidence.",
            f"- Source type: `{source_type.value}`; report status: `{report_status}`.",
        ]
    )
    if evaluation_report:
        lines.extend(["", f"- Baseline evaluation timestamp: `{evaluation_report.get('evaluated_at', 'unknown')}`."])
    return "\n".join(lines) + "\n"


def write_qualification_package(
    output_dir: Path,
    *,
    factory: str,
    category: str,
    source_type: DatasetSourceType = DatasetSourceType.DEMO_SYNTHETIC,
    metrics: dict[str, Any] | None = None,
    confidence_intervals: dict[str, Any] | None = None,
    split_manifest: dict[str, Any] | None = None,
    model_package: Path | None = None,
    dataset_receipt: dict[str, Any] | None = None,
    repository_root: Path | None = None,
    limitations: list[str] | None = None,
    source_evidence: dict[str, Any] | None = None,
    evaluation_report: dict[str, Any] | None = None,
    error_cases: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    model_reference: dict[str, Any] | None = None,
    dataset_fingerprint: str | None = None,
    customer_provenance: CustomerDataProvenance | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write the complete, tamper-evident qualification evidence directory."""
    source_type = DatasetSourceType(source_type)
    if isinstance(customer_provenance, dict):
        customer_provenance = CustomerDataProvenance.model_validate(customer_provenance)
    output_dir.mkdir(parents=True, exist_ok=True)
    package_manifest = verify_model_package(model_package, expected_category=category) if model_package else None
    package_sha = package_manifest.package_sha256 if package_manifest else None
    blockers: list[str] = []
    if source_type != DatasetSourceType.DEMO_SYNTHETIC and package_manifest is None:
        blockers.append("A verified Anomalib PatchCore model package is not available.")
    if source_type != DatasetSourceType.DEMO_SYNTHETIC and not split_manifest:
        blockers.append("Protocol A/B split evidence is not available.")
    if source_type != DatasetSourceType.DEMO_SYNTHETIC and metrics is None:
        blockers.append("Prediction scores, heatmaps, and thresholded holdout metrics are not available.")
    if source_type != DatasetSourceType.DEMO_SYNTHETIC and not dataset_fingerprint:
        blockers.append(f"{source_type.value} requires an immutable dataset fingerprint.")
    if source_type != DatasetSourceType.DEMO_SYNTHETIC and dataset_receipt is None:
        blockers.append(f"{source_type.value} requires a verified dataset receipt.")
    if source_type == DatasetSourceType.CUSTOMER_PILOT and customer_provenance is None:
        blockers.append(
            "CUSTOMER_PILOT requires tenant, site, line, camera, product, capture window, label source, "
            "approver, consent, and retention provenance."
        )
    actual_metrics = (
        metrics
        if metrics is not None
        else _blocked_metrics(
            "; ".join(blockers)
            or (
                "DEMO_SYNTHETIC is for workflow demonstration only; performance metrics are intentionally not asserted."
                if source_type == DatasetSourceType.DEMO_SYNTHETIC
                else "Required qualification metric evidence is unavailable."
            )
        )
    )
    source_evidence_available = source_evidence is not None and bool(source_evidence.get("files"))
    source_evidence = source_evidence or {
        "schema_version": "visionqc.pilot-source-evidence.v1",
        "status": "NOT_AVAILABLE",
        "files": {},
    }
    if source_type != DatasetSourceType.DEMO_SYNTHETIC and not source_evidence_available:
        blockers.append("The baseline source-evidence hash inventory is not available.")
    if source_type == DatasetSourceType.DEMO_SYNTHETIC and dataset_fingerprint is None:
        dataset_fingerprint = demo_dataset_source(category).dataset_fingerprint
    customer_provenance_valid: bool | None = (
        True
        if source_type != DatasetSourceType.CUSTOMER_PILOT
        else None
        if customer_provenance is None
        else customer_provenance.consent
    )
    if (
        source_type == DatasetSourceType.CUSTOMER_PILOT
        and customer_provenance is not None
        and not customer_provenance.consent
    ):
        blockers.append("CUSTOMER_PILOT requires explicit consent before Pilot approval.")
    gate_result = evaluate_pilot_gates(
        actual_metrics,
        package_verified=package_manifest is not None,
        no_split_leakage=bool(split_manifest and validate_split_manifest(split_manifest)["valid"]),
        evidence_complete=(
            source_type != DatasetSourceType.DEMO_SYNTHETIC
            and package_manifest is not None
            and bool(split_manifest)
            and metrics is not None
            and source_evidence_available
            and (
                source_type != DatasetSourceType.CUSTOMER_PILOT
                or customer_provenance_valid is True
            )
        ),
        source_type=source_type,
        customer_provenance_valid=customer_provenance_valid,
    )
    report_status = qualification_report_status(source_type, gate_result["decision"])
    gate_result["report_status"] = report_status
    now = datetime.now(timezone.utc).isoformat()
    limitations = limitations or []
    if source_type == DatasetSourceType.DEMO_SYNTHETIC:
        limitations = [
            "DEMO_SYNTHETIC is a small built-in fixture for workflow demonstration only.",
            "Demo data must not be used for effect claims, benchmark claims, customer Pilot approval, or production decisions.",
            *limitations,
        ]
    elif source_type == DatasetSourceType.OFFICIAL_BENCHMARK:
        limitations = [
            "MVTec AD is an official non-commercial research benchmark, not factory or customer Pilot data.",
            "Passing benchmark gates only means READY_FOR_CUSTOMER_DATA; it never authorizes APPROVED or ACTIVE.",
            *limitations,
        ]
    qualification_run_status = (
        "DEMO_ONLY" if source_type == DatasetSourceType.DEMO_SYNTHETIC else "BLOCKED" if blockers else "COMPLETED"
    )
    provenance = {
        "schema_version": "visionqc.pilot-provenance.v1",
        "context_name": factory,
        "category": category,
        "source_type": source_type.value,
        "data_status": source_type.value,
        "dataset_fingerprint": dataset_fingerprint,
        "dataset_receipt": dataset_receipt,
        "dataset_summary_sha256": (dataset_receipt or {}).get("dataset_summary_sha256"),
        "customer_provenance": customer_provenance.model_dump(mode="json") if customer_provenance else None,
        "model_package_sha256": package_sha,
        "code_commit": _git_commit(repository_root),
        "qualification_run_status": qualification_run_status,
        "blockers": blockers,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "generated_at": now,
        "limitations": limitations,
        "source_evidence_schema": source_evidence.get("schema_version"),
        "audit_reason": (
            f"{source_type.value} business gates failed; candidate remains DRAFT and cannot be approved or activated."
            if gate_result["decision"] == "NO-GO"
            else "Benchmark gates passed; report is READY_FOR_CUSTOMER_DATA and cannot be approved or activated."
            if source_type == DatasetSourceType.OFFICIAL_BENCHMARK and gate_result["decision"] == "GO"
            else "Customer data provenance is incomplete; candidate remains DRAFT and approval is blocked."
            if source_type == DatasetSourceType.CUSTOMER_PILOT and not customer_provenance_valid
            else None
        ),
    }
    summary = {
        "schema_version": "visionqc.pilot-qualification-summary.v1",
        "context_name": factory,
        "category": category,
        "qualification_status": report_status,
        "gate_decision": gate_result["decision"],
        "source_type": source_type.value,
        "data_status": provenance["data_status"],
        "metric_status": (
            "AVAILABLE"
            if metrics is not None
            else "DEMO_ONLY"
            if source_type == DatasetSourceType.DEMO_SYNTHETIC
            else "MISSING"
        ),
        "gate_version": PILOT_GATE_VERSION,
        "model_package_sha256": package_sha,
        "qualification_run_status": qualification_run_status,
        "blockers": blockers,
        "failed_gates": gate_result["failed"],
        "sample_counts": (dataset_receipt or {}).get(
            "counts",
            {
                "train_good_images": 0,
                "test_good_images": 0,
                "test_anomalous_images": 0,
                "ground_truth_masks": 0,
            },
        ),
        "generated_at": now,
        "limitations": limitations,
    }
    write_json(output_dir / "qualification-summary.json", summary)
    write_json(
        output_dir / "metrics.json",
        {
            "schema_version": "visionqc.pilot-metrics.v1",
            "metrics": actual_metrics,
            "sample_counts": summary["sample_counts"],
            "metric_notes": {
                "unavailable_metrics_are_null": metrics is None,
                "reason": actual_metrics.get("unavailable_reason") if metrics is None else None,
            },
            "gates": gate_result,
            "thresholds": thresholds,
        },
    )
    write_json(
        output_dir / "confidence-intervals.json",
        confidence_intervals
        or {
            "available": False,
            "resamples": 0,
            "intervals": {},
            "reason": "No verified benchmark or customer holdout evaluation records are available.",
            "unavailable_metrics": [
                "image_auroc",
                "pixel_auroc",
                "aupro",
                "precision",
                "recall",
                "f1",
                "routing_metrics",
                "latency_metrics",
            ],
        },
    )
    write_json(
        output_dir / "split-manifest.json",
        split_manifest
        or {
            "schema_version": "visionqc.protocol-split.v1",
            "status": "NOT_AVAILABLE",
            "reason": "optional dataset source not provided",
        },
    )
    write_json(output_dir / "provenance.json", provenance)
    write_json(
        output_dir / "error-cases.json",
        error_cases
        or {
            "schema_version": "visionqc.error-cases.v1",
            "cases": [],
            "note": "No cases are asserted without real predictions; populate from a verified holdout evaluation.",
            "gallery": None,
        },
    )
    write_json(output_dir / "source-evidence.json", source_evidence)
    model_identity = model_reference or {
        "id": package_manifest.model_id if package_manifest else None,
        "version": package_manifest.model_version if package_manifest else None,
        "package_sha256": package_sha,
    }
    (output_dir / "model-card.md").write_text(
        f"# VisionQC model card — {provenance['source_type']} / {category}\n\n"
        f"Report status: **{report_status}**. Source type: `{provenance['source_type']}`.\n\n"
        f"Model: `{model_identity.get('id')}` `{model_identity.get('version')}`.\n\n"
        + (
            f"Frozen holdout image AUROC: `{_markdown_value(actual_metrics.get('image_auroc'))}`; "
            f"review+hold recall: `{_markdown_value(actual_metrics.get('review_hold_recall'))}`; "
            f"hold recall: `{_markdown_value(actual_metrics.get('hold_recall'))}`.\n\n"
            if metrics is not None
            else ""
        )
        + "The model reports anomaly evidence and regions only. It does not confirm a defect type or root cause. "
        "MVTec AD evidence is a non-commercial research benchmark and cannot be presented as factory, customer Pilot, or production performance.\n\n"
        + "\n".join(f"- {item}" for item in [*limitations, *blockers])
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "evaluation-report.md").write_text(
        _pilot_evaluation_markdown(
            factory=factory,
            category=category,
            gate_result=gate_result,
            metrics=actual_metrics,
            confidence_intervals=confidence_intervals or {},
            split_manifest=split_manifest,
            thresholds=thresholds,
            evaluation_report=evaluation_report,
            error_cases=error_cases,
            source_evidence=source_evidence,
        ),
        encoding="utf-8",
    )
    # The digest intentionally excludes the two self-referential integrity files.
    evidence_digest = _core_digest(output_dir)
    if gate_result["decision"] == "NO-GO":
        decision_reason = (
            "Customer Pilot business gates failed; integrity-verified candidate must remain DRAFT."
            if source_type == DatasetSourceType.CUSTOMER_PILOT
            else "Benchmark business gates failed; integrity-verified candidate must remain DRAFT."
        )
        if gate_result["failed"]:
            decision_reason += " Failed gates: " + ", ".join(gate_result["failed"]) + "."
    elif source_type == DatasetSourceType.DEMO_SYNTHETIC:
        decision_reason = "DEMO_SYNTHETIC is for workflow demonstration only; no effect claim or approval is allowed."
    elif source_type == DatasetSourceType.OFFICIAL_BENCHMARK:
        decision_reason = (
            "Official benchmark evidence and all mandatory gates are required before Benchmark Qualification. "
            "MVTec cannot be approved or activated."
        )
        if blockers:
            decision_reason += " Blockers: " + "; ".join(blockers) + "."
    else:
        decision_reason = "Customer data provenance and all mandatory gates are required before Pilot approval."
        if blockers:
            decision_reason += " Blockers: " + "; ".join(blockers) + "."
    if source_type == DatasetSourceType.DEMO_SYNTHETIC:
        approval_status = "DEMO_ONLY"
    elif source_type == DatasetSourceType.OFFICIAL_BENCHMARK and gate_result["decision"] == "GO":
        approval_status = "READY_FOR_CUSTOMER_DATA"
    elif source_type == DatasetSourceType.CUSTOMER_PILOT and gate_result["approval_eligible"]:
        approval_status = "PENDING_APPROVAL"
    else:
        approval_status = "DRAFT_ONLY"
    decision = {
        "schema_version": "visionqc.release-decision.v1",
        "decision": report_status,
        "gate_decision": gate_result["decision"],
        "source_type": source_type.value,
        "dataset_fingerprint": dataset_fingerprint,
        "approval_status": approval_status,
        "evidence_package_sha256": evidence_digest,
        "model_package_sha256": package_sha,
        "gate_version": PILOT_GATE_VERSION,
        "gates": gate_result,
        "reason": (
            "Official benchmark gates passed; READY_FOR_CUSTOMER_DATA. Customer provenance is still required before Pilot approval."
            if source_type == DatasetSourceType.OFFICIAL_BENCHMARK and gate_result["decision"] == "GO"
            else "All configured Customer Pilot gates passed; named approval remains required."
            if source_type == DatasetSourceType.CUSTOMER_PILOT and gate_result["decision"] == "GO"
            else decision_reason
        ),
        "audit_reason": (
            "customer_pilot_business_gate_failure_draft_only"
            if source_type == DatasetSourceType.CUSTOMER_PILOT and gate_result["decision"] == "NO-GO"
            else "benchmark_business_gate_failure_draft_only"
            if gate_result["decision"] == "NO-GO"
            else "benchmark_pass_ready_for_customer_data"
            if source_type == DatasetSourceType.OFFICIAL_BENCHMARK and gate_result["decision"] == "GO"
            else "customer_pilot_approval_pending_provenance"
            if source_type == DatasetSourceType.CUSTOMER_PILOT
            else "demo_only"
            if source_type == DatasetSourceType.DEMO_SYNTHETIC
            else f"{source_type.value.lower()}_insufficient_evidence_draft_only"
        ),
        "generated_at": now,
    }
    write_json(output_dir / "release-decision.json", decision)
    inventory = {
        "schema_version": "visionqc.evidence-manifest.v1",
        "files": _top_level_inventory(output_dir),
    }
    write_json(output_dir / "evidence-manifest.json", inventory)
    return {
        "output_dir": str(output_dir),
        "decision": report_status,
        "evidence_package_sha256": evidence_digest,
        "model_package_sha256": package_sha,
    }


def qualify_from_run(
    run_dir: Path,
    *,
    factory: str,
    category: str,
    model_package: Path,
    output_dir: Path,
    dataset_root: Path | None = None,
    source_config: Path | None = None,
    repository_root: Path | None = None,
    source_type: DatasetSourceType = DatasetSourceType.OFFICIAL_BENCHMARK,
    customer_provenance: CustomerDataProvenance | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build source-scoped evidence from one immutable, cross-checked baseline run."""
    source_type = DatasetSourceType(source_type)
    if source_type != DatasetSourceType.OFFICIAL_BENCHMARK:
        raise ValueError(
            "this baseline run is bound to OFFICIAL_BENCHMARK evidence; "
            "customer qualification requires a customer-specific baseline and provenance"
        )
    evidence = load_pilot_evidence(
        run_dir,
        category=category,
        model_package=model_package,
        dataset_root=dataset_root,
        source_config=source_config,
    )
    gallery = evidence["gallery"]
    error_cases = {
        "schema_version": "visionqc.error-cases.v1",
        "cases": gallery["cases"],
        "case_count": gallery["case_count"],
        "case_types": gallery["case_types"],
        "gallery": {
            "source_dir": str(evidence["gallery_dir"]),
            "schema_version": gallery.get("schema_version"),
        },
        "claim_boundary": "anomaly evidence only; semantic defect and root cause require human confirmation",
    }
    limitations = list(evidence["evaluation"].get("limitations", []))
    limitations.extend(
        [
            "MVTec AD is a non-commercial research benchmark and does not establish factory or customer Pilot performance."
            if source_type == DatasetSourceType.OFFICIAL_BENCHMARK
            else "Customer data provenance is required before Pilot approval.",
            "Thresholds are selected from validation only; the held-out test split is used only after thresholds are frozen.",
        ]
    )
    return write_qualification_package(
        output_dir,
        factory=factory,
        category=category,
        source_type=source_type,
        metrics=evidence["metrics"],
        confidence_intervals=evidence["confidence_intervals"],
        split_manifest=evidence["split_manifest"],
        model_package=evidence["package_path"],
        dataset_receipt=evidence["dataset_receipt"],
        repository_root=repository_root,
        limitations=limitations,
        source_evidence=evidence["source_evidence"],
        evaluation_report=evidence["evaluation"],
        error_cases=error_cases,
        thresholds=evidence["thresholds"].model_dump(mode="json"),
        model_reference=evidence["model_reference"],
        dataset_fingerprint=evidence["manifest_meta"].get("dataset_fingerprint"),
        customer_provenance=customer_provenance,
    )


def qualify_from_directory(
    dataset_root: Path,
    *,
    category: str,
    source_config: Path | None,
    output_dir: Path,
    repository_root: Path | None = None,
    license_acknowledged: bool = False,
) -> dict[str, Any]:
    """Validate supplied official data and emit a package scaffold.

    Actual PatchCore predictions are intentionally supplied separately; this
    command never substitutes synthetic values for missing real predictions.
    """
    receipt = validate_user_dataset(
        dataset_root,
        category=category,
        source_config=source_config,
        license_acknowledged=license_acknowledged,
    )
    entries_path = output_dir / "_manifest" / "manifest.jsonl"
    from .dataset import generate_manifest

    meta = generate_manifest(
        dataset_root if (dataset_root / category).is_dir() else dataset_root.parent,
        entries_path.parent,
        category=category,
    )
    split = split_manifest_for_protocol_b(
        __import__("visionqc_ml.dataset", fromlist=["load_manifest"]).load_manifest(entries_path), seed=20260804
    )
    return write_qualification_package(
        output_dir,
        factory="Factory A" if category == "transistor" else "Factory B",
        category=category,
        source_type=DatasetSourceType.OFFICIAL_BENCHMARK,
        split_manifest=split,
        dataset_receipt={**receipt, "manifest_sha256": meta["manifest_sha256"]},
        dataset_fingerprint=meta["dataset_fingerprint"],
        repository_root=repository_root,
        limitations=["Predictions and verified model package must be supplied to calculate final metrics."],
    )
