"""Offline image, pixel, business-policy, and latency evaluation."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from scipy import ndimage
from sklearn.metrics import precision_recall_fscore_support, roc_auc_score

from .calibration import CalibrationResult, ScoreRecord, load_score_records
from .dataset import ManifestEntry, load_manifest
from .gallery import build_error_gallery
from .hashing import read_json, sha256_file, write_json


def _classification_metrics(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict[str, Any]:
    predicted = (scores >= threshold).astype(np.int8)
    precision, recall, f1, _ = precision_recall_fscore_support(
        labels,
        predicted,
        average="binary",
        zero_division=0,
    )
    tn = int(np.sum((labels == 0) & (predicted == 0)))
    fp = int(np.sum((labels == 0) & (predicted == 1)))
    fn = int(np.sum((labels == 1) & (predicted == 0)))
    tp = int(np.sum((labels == 1) & (predicted == 1)))
    return {
        "threshold": threshold,
        "precision": float(precision),
        "recall": float(recall),
        "f1": float(f1),
        "confusion_matrix": {"tn": tn, "fp": fp, "fn": fn, "tp": tp},
    }


def _bootstrap_confidence_intervals(
    labels: np.ndarray,
    scores: np.ndarray,
    review_threshold: float,
    hold_threshold: float,
    *,
    seed: int,
    resamples: int = 1000,
) -> dict[str, Any]:
    """Return deterministic stratified image-level percentile bootstrap intervals."""
    normal_indices = np.flatnonzero(labels == 0)
    anomaly_indices = np.flatnonzero(labels == 1)
    if normal_indices.size < 2 or anomaly_indices.size < 2:
        return {
            "method": "stratified percentile bootstrap",
            "resamples": 0,
            "seed": seed,
            "available": False,
            "reason": "at least two normal and two anomalous samples are required",
            "intervals": {},
        }

    def values(sample_labels: np.ndarray, sample_scores: np.ndarray) -> dict[str, float]:
        review = _classification_metrics(sample_labels, sample_scores, review_threshold)
        hold = _classification_metrics(sample_labels, sample_scores, hold_threshold)
        return {
            "image_auroc": float(roc_auc_score(sample_labels, sample_scores)),
            "review_precision": float(review["precision"]),
            "review_recall": float(review["recall"]),
            "review_f1": float(review["f1"]),
            "hold_precision": float(hold["precision"]),
            "hold_recall": float(hold["recall"]),
            "hold_f1": float(hold["f1"]),
            "false_accept_rate": float(np.mean(sample_scores[sample_labels == 1] < review_threshold)),
            "false_reject_rate": float(np.mean(sample_scores[sample_labels == 0] >= hold_threshold)),
        }

    rng = np.random.default_rng(seed)
    samples: dict[str, list[float]] = {}
    for _ in range(resamples):
        sampled_indices = np.concatenate(
            (
                rng.choice(normal_indices, size=normal_indices.size, replace=True),
                rng.choice(anomaly_indices, size=anomaly_indices.size, replace=True),
            )
        )
        sampled_labels = labels[sampled_indices]
        sampled_scores = scores[sampled_indices]
        for name, value in values(sampled_labels, sampled_scores).items():
            samples.setdefault(name, []).append(value)
    intervals = {
        name: {
            "estimate": float(values(labels, scores)[name]),
            "lower": float(np.percentile(observations, 2.5)),
            "upper": float(np.percentile(observations, 97.5)),
            "confidence": 0.95,
        }
        for name, observations in samples.items()
    }
    return {
        "method": "stratified percentile bootstrap",
        "resamples": resamples,
        "seed": seed,
        "available": True,
        "class_counts": {"normal": int(normal_indices.size), "anomalous": int(anomaly_indices.size)},
        "intervals": intervals,
        "pixel_metrics": "No pixel-level CI is reported; pixel estimates remain sample-size and mask-resolution limited.",
    }


def _load_pixel_pairs(
    records: list[ScoreRecord],
    manifest_entries: dict[str, ManifestEntry],
    dataset_root: Path,
    prediction_root: Path,
) -> tuple[list[np.ndarray], list[np.ndarray]]:
    maps: list[np.ndarray] = []
    masks: list[np.ndarray] = []
    for record in records:
        entry = manifest_entries[record.sample_id]
        heatmap_path = Path(record.heatmap_path)
        if not heatmap_path.is_absolute():
            heatmap_path = prediction_root / heatmap_path
        with Image.open(heatmap_path) as image:
            anomaly_map = np.asarray(image.convert("L"), dtype=np.float32) / np.float32(255.0)
        if entry.mask_path:
            with Image.open(dataset_root / entry.mask_path) as source_mask:
                mask_image = source_mask.convert("L").resize(
                    (anomaly_map.shape[1], anomaly_map.shape[0]),
                    resample=Image.Resampling.NEAREST,
                )
                mask = np.asarray(mask_image, dtype=np.uint8) > 0
        else:
            mask = np.zeros(anomaly_map.shape, dtype=bool)
        maps.append(anomaly_map)
        masks.append(mask)
    return maps, masks


def _aupro(maps: list[np.ndarray], masks: list[np.ndarray], max_fpr: float = 0.3) -> float | None:
    components: list[np.ndarray] = []
    negative_scores: list[np.ndarray] = []
    for anomaly_map, mask in zip(maps, masks, strict=True):
        negative_scores.append(anomaly_map[~mask])
        labeled, count = ndimage.label(mask)
        for component_id in range(1, count + 1):
            components.append(anomaly_map[labeled == component_id])
    if not components or not negative_scores:
        return None
    negatives = np.concatenate(negative_scores)
    thresholds = np.linspace(1.0, 0.0, num=201, dtype=np.float64)
    fprs = np.asarray([np.mean(negatives >= threshold) for threshold in thresholds])
    pros = np.asarray([
        np.mean([np.mean(component >= threshold) for component in components]) for threshold in thresholds
    ])
    within = fprs <= max_fpr
    if not np.any(within):
        return None
    xs = np.concatenate(([0.0], fprs[within], [max_fpr]))
    ys = np.concatenate(([pros[within][0]], pros[within], [pros[within][-1]]))
    order = np.argsort(xs)
    return float(np.trapezoid(ys[order], xs[order]) / max_fpr)


def _subtype_metrics(records: list[ScoreRecord], review_threshold: float) -> dict[str, Any]:
    grouped: dict[str, list[ScoreRecord]] = defaultdict(list)
    for record in records:
        grouped[record.anomaly_subtype].append(record)
    result: dict[str, Any] = {}
    for subtype, items in sorted(grouped.items()):
        scores = np.asarray([item.score for item in items])
        result[subtype] = {
            "count": len(items),
            "mean_score": float(np.mean(scores)),
            "review_or_hold_rate": float(np.mean(scores >= review_threshold)),
        }
    return result


def _representative_samples(
    records: list[ScoreRecord],
    review_threshold: float,
    hold_threshold: float,
) -> dict[str, Any]:
    """Select auditable examples without turning subtype labels into predictions."""

    def summarize(record: ScoreRecord | None) -> dict[str, Any] | None:
        if record is None:
            return None
        if record.score < review_threshold:
            route = "AUTO_RELEASE"
        elif record.score < hold_threshold:
            route = "REVIEW_REQUIRED"
        else:
            route = "BATCH_HOLD_AND_REVIEW"
        return {
            "sample_id": record.sample_id,
            "image_path": record.image_path,
            "ground_truth_label": record.label,
            "ground_truth_subtype_for_evaluation_only": record.anomaly_subtype,
            "score": record.score,
            "route": route,
            "heatmap_path": record.heatmap_path,
        }

    anomalous = sorted((record for record in records if record.label == 1), key=lambda item: item.score)
    normal = sorted((record for record in records if record.label == 0), key=lambda item: item.score)
    false_accepts = [record for record in anomalous if record.score < review_threshold]
    normal_alerts = [record for record in normal if record.score >= review_threshold]
    return {
        "detected_anomaly_example": summarize(anomalous[-1] if anomalous else None),
        "false_accept_example": summarize(false_accepts[-1] if false_accepts else None),
        "normal_review_or_hold_example": summarize(normal_alerts[-1] if normal_alerts else None),
        "auto_released_normal_example": summarize(normal[0] if normal else None),
        "semantic_note": "Subtype is benchmark ground truth for error analysis, not a model-predicted defect type.",
    }


def evaluate_predictions(
    predictions_path: Path,
    manifest_path: Path,
    manifest_meta_path: Path,
    dataset_root: Path,
    thresholds_path: Path,
    output_dir: Path,
    model_reference: dict[str, str],
    hardware: dict[str, Any],
    performance_probe_path: Path | None = None,
    gallery_output_dir: Path | None = None,
) -> dict[str, Any]:
    """Evaluate a held-out test prediction file without modifying thresholds."""
    records = load_score_records(predictions_path, required_split="test")
    entries = {entry.sample_id: entry for entry in load_manifest(manifest_path, split="test")}
    if set(entries) != {record.sample_id for record in records}:
        raise ValueError("test predictions do not exactly cover the held-out test manifest")
    calibration = CalibrationResult.model_validate(read_json(thresholds_path))
    meta = read_json(manifest_meta_path)
    record_categories = {record.product_category for record in records if record.product_category is not None}
    if len(record_categories) > 1:
        raise ValueError(f"predictions mix product categories: {sorted(record_categories)}")
    if record_categories and record_categories != {meta.get("category", "unknown")}:
        raise ValueError(
            f"prediction category {sorted(record_categories)} does not match manifest category {meta.get('category')}"
        )
    labels = np.asarray([record.label for record in records], dtype=np.int8)
    scores = np.asarray([record.score for record in records], dtype=np.float64)

    image_auroc = float(roc_auc_score(labels, scores)) if len(np.unique(labels)) == 2 else None
    review_metrics = _classification_metrics(labels, scores, calibration.review_threshold)
    hold_metrics = _classification_metrics(labels, scores, calibration.hold_threshold)
    maps, masks = _load_pixel_pairs(records, entries, dataset_root, predictions_path.parent)
    pixel_labels = np.concatenate([mask.ravel() for mask in masks])
    pixel_scores = np.concatenate([anomaly_map.ravel() for anomaly_map in maps])
    pixel_auroc = float(roc_auc_score(pixel_labels, pixel_scores)) if len(np.unique(pixel_labels)) == 2 else None
    pixel_aupro = _aupro(maps, masks)

    normal = labels == 0
    anomalous = labels == 1
    latencies = np.asarray([record.latency_ms for record in records if record.warm], dtype=np.float64)
    business = {
        "false_accept_rate": float(np.mean(scores[anomalous] < calibration.review_threshold)),
        "false_reject_rate": float(np.mean(scores[normal] >= calibration.hold_threshold)),
        "manual_review_rate": float(np.mean(scores >= calibration.review_threshold)),
        "hold_rate": float(np.mean(scores >= calibration.hold_threshold)),
        "auto_release_rate": float(np.mean(scores < calibration.review_threshold)),
        "human_override_rate": None,
        "human_override_rate_note": "Unavailable offline; requires named review decisions from the business workflow.",
    }
    bootstrap_seed = int(str(meta["dataset_fingerprint"])[:8], 16)
    uncertainty = _bootstrap_confidence_intervals(
        labels,
        scores,
        calibration.review_threshold,
        calibration.hold_threshold,
        seed=bootstrap_seed,
    )
    performance_probe = read_json(performance_probe_path) if performance_probe_path and performance_probe_path.is_file() else {}
    warm_p50 = (
        float(performance_probe["warm_p50_ms"])
        if performance_probe.get("warm_p50_ms") is not None
        else (float(np.percentile(latencies, 50)) if latencies.size else None)
    )
    warm_p95 = (
        float(performance_probe["warm_p95_ms"])
        if performance_probe.get("warm_p95_ms") is not None
        else (float(np.percentile(latencies, 95)) if latencies.size else None)
    )
    gallery_info: dict[str, Any] | None = None
    if gallery_output_dir is not None:
        gallery_info = build_error_gallery(
            records,
            entries,
            dataset_root,
            predictions_path.parent,
            calibration.review_threshold,
            calibration.hold_threshold,
            gallery_output_dir,
        )
    representatives = _representative_samples(
        records,
        calibration.review_threshold,
        calibration.hold_threshold,
    )
    report = {
        "schema_version": "visionqc.evaluation.v1",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "evaluation_split": "test",
        "test_set_usage": "thresholds were frozen from validation before this report",
        "threshold_provenance": {
            "source_split": calibration.source_split,
            "selection_split": calibration.threshold_selection_split,
            "holdout_records_consumed_for_selection": calibration.holdout_records_consumed,
            "selection_rule": calibration.selection_rule,
            "thresholds_sha256": sha256_file(thresholds_path),
        },
        "model": model_reference,
        "dataset": {
            "name": "MVTec AD",
            "category": meta.get("category", "unknown"),
            "license": "CC BY-NC-SA 4.0 (non-commercial)",
            "dataset_fingerprint": meta["dataset_fingerprint"],
            "manifest_sha256": meta["manifest_sha256"],
            "test_split_sha256": meta["split_sha256"]["test"],
            "samples": len(records),
            "label_counts": dict(Counter(str(record.label) for record in records)),
        },
        "thresholds": calibration.model_dump(mode="json"),
        "metrics": {
            "image_level": {
                "auroc": image_auroc,
                "at_review_threshold": review_metrics,
                "at_hold_threshold": hold_metrics,
                "bootstrap_ci": uncertainty,
            },
            "pixel_level": {
                "auroc": pixel_auroc,
                "aupro_at_0_30_fpr": pixel_aupro,
                "aupro_definition": "Mean per-region overlap integrated over pixel false-positive rate [0, 0.30].",
            },
            "business": business,
            "confusion_matrix": {
                "at_review_threshold": review_metrics["confusion_matrix"],
                "at_hold_threshold": hold_metrics["confusion_matrix"],
            },
            "by_subtype": _subtype_metrics(records, calibration.review_threshold),
            "performance": {
                "warm_samples": int(latencies.size),
                "cold_ms": float(performance_probe["cold_ms"]) if performance_probe.get("cold_ms") is not None else None,
                "warm_p50_ms": warm_p50,
                "warm_p95_ms": warm_p95,
                "p50_ms": warm_p50,
                "p95_ms": warm_p95,
                "target_p95_ms": 3000,
                "target_met": bool(warm_p95 < 3000) if warm_p95 is not None else None,
                "hardware": hardware,
            },
        },
        "artifacts": {
            "predictions_sha256": sha256_file(predictions_path),
            "thresholds_sha256": sha256_file(thresholds_path),
        },
        "claim_boundary": {
            "allowed": "anomaly likelihood and anomalous region localization",
            "not_claimed": ["confirmed semantic defect type", "root cause", "factory production readiness"],
        },
        "limitations": [
            "MVTec AD does not represent a specific customer's camera, process, or defect distribution.",
            "Pixel metrics depend on resized heatmaps and benchmark masks.",
            "Offline routing metrics do not include actual human overrides or downstream quality outcomes.",
        ],
        "representative_samples": representatives,
        "gallery": gallery_info,
        "uncertainty_and_limits": [
            "Image-level confidence intervals use stratified bootstrap resampling; they do not represent camera/process uncertainty.",
            "Small benchmark splits can produce wide or unavailable intervals; factory acceptance requires customer data.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "evaluation.json", report)
    write_json(output_dir / "representative-samples.json", representatives)
    (output_dir / "evaluation.md").write_text(_markdown_report(report), encoding="utf-8")
    return report


def _fmt(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _markdown_report(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    business = metrics["business"]
    performance = metrics["performance"]
    return f"""# VisionQC PatchCore offline evaluation

This report evaluates anomaly likelihood and anomalous-region localization only.
It does not confirm a semantic defect type, root cause, or production readiness.

## Technical summary

- Product category: `{report['dataset']['category']}`.
- Thresholds were selected from validation only and frozen before held-out test evaluation.
- Reported image metrics include stratified bootstrap intervals when both classes have enough samples; pixel uncertainty is explicitly limited.

## Provenance

- Model: `{report['model']['id']}` `{report['model']['version']}`
- Dataset: MVTec AD `transistor` (CC BY-NC-SA 4.0, non-commercial)
- Dataset fingerprint: `{report['dataset']['dataset_fingerprint']}`
- Held-out samples: {report['dataset']['samples']}
- Test-set rule: {report['test_set_usage']}

## Model metrics

| Metric | Value |
| --- | ---: |
| Image AUROC | {_fmt(metrics['image_level']['auroc'])} |
| Pixel AUROC | {_fmt(metrics['pixel_level']['auroc'])} |
| Pixel AUPRO @ FPR 0.30 | {_fmt(metrics['pixel_level']['aupro_at_0_30_fpr'])} |
| Precision @ review threshold | {_fmt(metrics['image_level']['at_review_threshold']['precision'])} |
| Recall @ review threshold | {_fmt(metrics['image_level']['at_review_threshold']['recall'])} |
| F1 @ review threshold | {_fmt(metrics['image_level']['at_review_threshold']['f1'])} |
| Precision @ hold threshold | {_fmt(metrics['image_level']['at_hold_threshold']['precision'])} |
| Recall @ hold threshold | {_fmt(metrics['image_level']['at_hold_threshold']['recall'])} |
| F1 @ hold threshold | {_fmt(metrics['image_level']['at_hold_threshold']['f1'])} |

## Routing metrics

| Metric | Value |
| --- | ---: |
| False accept rate | {_fmt(business['false_accept_rate'])} |
| False reject rate | {_fmt(business['false_reject_rate'])} |
| Manual review or hold rate | {_fmt(business['manual_review_rate'])} |
| Hold rate | {_fmt(business['hold_rate'])} |
| Human override rate | n/a (requires business workflow feedback) |

## Confusion matrices

| Threshold | TN | FP | FN | TP |
| --- | ---: | ---: | ---: | ---: |
| Review | {metrics['confusion_matrix']['at_review_threshold']['tn']} | {metrics['confusion_matrix']['at_review_threshold']['fp']} | {metrics['confusion_matrix']['at_review_threshold']['fn']} | {metrics['confusion_matrix']['at_review_threshold']['tp']} |
| Hold | {metrics['confusion_matrix']['at_hold_threshold']['tn']} | {metrics['confusion_matrix']['at_hold_threshold']['fp']} | {metrics['confusion_matrix']['at_hold_threshold']['fn']} | {metrics['confusion_matrix']['at_hold_threshold']['tp']} |

## Grouped indicators

| Benchmark group | Samples | Mean score | Review + hold rate |
| --- | ---: | ---: | ---: |
""" + "".join(
        f"| `{name}` | {values['count']} | {_fmt(values['mean_score'])} | {_fmt(values['review_or_hold_rate'])} |\n"
        for name, values in sorted(metrics.get("by_subtype", {}).items())
    ) + f"""

## Threshold provenance

- Source split: `{report['threshold_provenance']['source_split']}`.
- Holdout records consumed for selection: `{report['threshold_provenance']['holdout_records_consumed_for_selection']}`.
- Selection rule: `{report['threshold_provenance']['selection_rule']}`.
- Threshold artifact SHA-256: `{report['threshold_provenance']['thresholds_sha256']}`.

## Performance

- Cold inference: {_fmt(performance['cold_ms'])} ms
- Warm inference P50: {_fmt(performance['warm_p50_ms'])} ms
- Warm inference P95: {_fmt(performance['warm_p95_ms'])} ms
- Initial target: < {performance['target_p95_ms']} ms P95 on the recorded reference hardware
- Hardware: `{json.dumps(performance['hardware'], sort_keys=True)}`

## Limitations

""" + "".join(f"- {item}\n" for item in report["limitations"])
