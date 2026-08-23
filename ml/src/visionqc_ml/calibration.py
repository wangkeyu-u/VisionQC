"""Validation-only calibration for VisionQC review and hold thresholds."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import Field

from .hashing import sha256_file, write_json
from .schemas import StrictModel

CalibrationStrategy = Literal["legacy", "safety_margin"]


class ScoreRecord(StrictModel):
    """Portable per-image output used by calibration and evaluation."""

    schema_version: Literal["visionqc.score-record.v1"] = "visionqc.score-record.v1"
    sample_id: str
    split: Literal["validation", "test", "calibration", "holdout"]
    image_path: str
    label: Literal[0, 1]
    anomaly_subtype: str
    score: float = Field(ge=0.0, le=1.0)
    heatmap_path: str
    latency_ms: float = Field(ge=0.0)
    warm: bool = True
    device: str
    product_category: str | None = Field(default=None, min_length=1)


class CalibrationResult(StrictModel):
    schema_version: Literal["visionqc.threshold-calibration.v1"] = "visionqc.threshold-calibration.v1"
    policy_version: str
    calibrated_at: str
    source_predictions_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_split: Literal["validation"] = "validation"
    review_threshold: float = Field(ge=0.0, le=1.0)
    hold_threshold: float = Field(ge=0.0, le=1.0)
    constraints: dict[str, float]
    achieved: dict[str, float]
    sample_counts: dict[str, int]
    constraints_satisfied: bool
    objective: str = "maximize review threshold subject to false-accept control; maximize hold threshold subject to hold-recall target"
    warnings: list[str]
    strategy: CalibrationStrategy = "legacy"
    safety_margin: float = Field(default=0.0, ge=0.0, le=1.0)
    threshold_selection_split: Literal["validation"] = "validation"
    holdout_records_consumed: Literal[False] = False
    selection_rule: str = (
        "maximize review threshold subject to zero abnormal auto-release; "
        "maximize ordered hold threshold subject to hold-recall target"
    )


def load_score_records(path: Path, required_split: str | None = None) -> list[ScoreRecord]:
    """Load JSONL score records and optionally enforce a single split."""
    records = [ScoreRecord.model_validate_json(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    if not records:
        raise ValueError(f"no score records in {path}")
    if required_split and any(record.split != required_split for record in records):
        raise ValueError(f"{path} contains records outside required split {required_split}")
    return records


def _candidate_thresholds(scores: np.ndarray) -> np.ndarray:
    unique = np.unique(np.clip(scores.astype(np.float64), 0.0, 1.0))
    mids = np.asarray([], dtype=np.float64) if len(unique) == 1 else (unique[:-1] + unique[1:]) / 2.0
    return np.unique(np.concatenate(([0.0], unique, mids, [1.0])))


def _rates(scores: np.ndarray, labels: np.ndarray, review: float, hold: float) -> dict[str, float]:
    anomalous = labels == 1
    normal = labels == 0
    return {
        "false_accept_rate": float(np.mean(scores[anomalous] < review)),
        "false_reject_rate": float(np.mean(scores[normal] >= hold)),
        "review_or_hold_rate": float(np.mean(scores >= review)),
        "hold_rate": float(np.mean(scores >= hold)),
        "hold_recall": float(np.mean(scores[anomalous] >= hold)),
    }


def _legacy_thresholds(
    scores: np.ndarray,
    labels: np.ndarray,
    max_false_accept_rate: float,
    target_hold_recall: float,
) -> tuple[float, float, list[str]]:
    """Return the pre-existing score-candidate policy for reproducibility."""
    candidates = _candidate_thresholds(scores)
    review_candidates = [
        float(candidate)
        for candidate in candidates
        if candidate < 1.0 and float(np.mean(scores[labels == 1] < candidate)) <= max_false_accept_rate
    ]
    review_threshold = max(review_candidates, default=0.0)

    hold_candidates = [
        float(candidate)
        for candidate in candidates
        if candidate > review_threshold and float(np.mean(scores[labels == 1] >= candidate)) >= target_hold_recall
    ]
    warnings: list[str] = []
    if hold_candidates:
        hold_threshold = max(hold_candidates)
    else:
        greater = [float(candidate) for candidate in candidates if candidate > review_threshold]
        hold_threshold = min(greater, default=1.0)
        warnings.append("target_hold_recall could not be met while preserving review_threshold < hold_threshold")
    if hold_threshold <= review_threshold:
        hold_threshold = min(1.0, float(np.nextafter(review_threshold, 1.0)))
    if hold_threshold <= review_threshold:
        raise ValueError("validation scores do not permit two ordered thresholds")
    return review_threshold, hold_threshold, warnings


def calibrate_thresholds(
    predictions_path: Path,
    output_dir: Path,
    policy_version: str,
    max_false_accept_rate: float = 0.0,
    target_hold_recall: float = 0.8,
    *,
    strategy: CalibrationStrategy = "legacy",
    safety_margin: float = 0.0,
) -> CalibrationResult:
    """Select ordered thresholds from validation only.

    ``legacy`` preserves the original score-candidate selection.  The
    ``safety_margin`` strategy first applies that same validation-only
    selection, then moves both thresholds downward by a configurable score
    margin.  Lower thresholds are conservative for anomaly recall: they can
    only route more samples to review/hold on the calibration sample and never
    consume a holdout label.
    """
    if not 0.0 <= max_false_accept_rate <= 1.0 or not 0.0 <= target_hold_recall <= 1.0:
        raise ValueError("calibration constraints must be in [0, 1]")
    if strategy not in {"legacy", "safety_margin"}:
        raise ValueError(f"unsupported calibration strategy: {strategy}")
    if not 0.0 <= safety_margin <= 1.0:
        raise ValueError("safety_margin must be in [0, 1]")
    records = load_score_records(predictions_path, required_split="validation")
    scores = np.asarray([record.score for record in records], dtype=np.float64)
    labels = np.asarray([record.label for record in records], dtype=np.int8)
    if set(labels.tolist()) != {0, 1}:
        raise ValueError("validation calibration requires both normal and anomalous samples")

    review_threshold, hold_threshold, warnings = _legacy_thresholds(
        scores,
        labels,
        max_false_accept_rate,
        target_hold_recall,
    )
    if strategy == "safety_margin":
        if safety_margin > 0.0:
            review_threshold = max(0.0, review_threshold - safety_margin)
            hold_threshold = max(0.0, hold_threshold - safety_margin)
            warnings.append(
                f"validation-only safety margin of {safety_margin:.6f} was applied downward to both thresholds"
            )
        if hold_threshold <= review_threshold:
            hold_threshold = min(1.0, float(np.nextafter(review_threshold, 1.0)))
        if hold_threshold <= review_threshold:
            raise ValueError("validation scores do not permit two ordered thresholds")
    elif safety_margin != 0.0:
        raise ValueError("safety_margin requires the safety_margin calibration strategy")

    candidates = _candidate_thresholds(scores)
    achieved = _rates(scores, labels, review_threshold, hold_threshold)
    constraints_satisfied = (
        achieved["false_accept_rate"] <= max_false_accept_rate and achieved["hold_recall"] >= target_hold_recall
    )
    if not constraints_satisfied and not warnings:
        warnings.append("one or more calibration constraints were not satisfied")

    result = CalibrationResult(
        policy_version=policy_version,
        calibrated_at=datetime.now(timezone.utc).isoformat(),
        source_predictions_sha256=sha256_file(predictions_path),
        review_threshold=review_threshold,
        hold_threshold=hold_threshold,
        constraints={
            "max_false_accept_rate": max_false_accept_rate,
            "target_hold_recall": target_hold_recall,
        },
        achieved=achieved,
        sample_counts={
            "total": len(records),
            "normal": int(np.sum(labels == 0)),
            "anomalous": int(np.sum(labels == 1)),
        },
        constraints_satisfied=constraints_satisfied,
        warnings=warnings,
        strategy=strategy,
        safety_margin=safety_margin,
        holdout_records_consumed=False,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "thresholds.json", result.model_dump(mode="json"))

    scan_path = output_dir / "threshold-scan.csv"
    with scan_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["threshold", "false_accept_rate", "review_or_hold_rate", "anomaly_recall", "normal_alert_rate"],
        )
        writer.writeheader()
        for candidate in candidates:
            threshold = float(candidate)
            writer.writerow(
                {
                    "threshold": f"{threshold:.10f}",
                    "false_accept_rate": f"{float(np.mean(scores[labels == 1] < threshold)):.10f}",
                    "review_or_hold_rate": f"{float(np.mean(scores >= threshold)):.10f}",
                    "anomaly_recall": f"{float(np.mean(scores[labels == 1] >= threshold)):.10f}",
                    "normal_alert_rate": f"{float(np.mean(scores[labels == 0] >= threshold)):.10f}",
                }
            )
    _write_scan_svg(scan_path, output_dir / "threshold-scan.svg", review_threshold, hold_threshold)
    return result


def _write_scan_svg(scan_path: Path, output_path: Path, review: float, hold: float) -> None:
    """Render the threshold scan as dependency-free SVG."""
    rows: list[dict[str, Any]] = []
    with scan_path.open(encoding="utf-8", newline="") as handle:
        rows.extend(csv.DictReader(handle))
    width, height, margin = 760, 420, 48

    def point(x: float, y: float) -> tuple[float, float]:
        return margin + x * (width - 2 * margin), height - margin - y * (height - 2 * margin)

    series = {
        "false accept": ("#c23b22", "false_accept_rate"),
        "review or hold": ("#20639b", "review_or_hold_rate"),
        "anomaly recall": ("#2f855a", "anomaly_recall"),
    }
    polylines = []
    legends = []
    for index, (label, (color, key)) in enumerate(series.items()):
        coords = " ".join(
            f"{point(float(row['threshold']), float(row[key]))[0]:.2f},{point(float(row['threshold']), float(row[key]))[1]:.2f}"
            for row in rows
        )
        polylines.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2"/>')
        legends.append(f'<text x="{margin + index * 180}" y="24" fill="{color}" font-size="13">{label}</text>')
    threshold_lines = []
    for value, label in ((review, "review"), (hold, "hold")):
        x, _ = point(value, 0)
        threshold_lines.append(
            f'<line x1="{x:.2f}" y1="{margin}" x2="{x:.2f}" y2="{height - margin}" stroke="#555" stroke-dasharray="5,4"/>'
            f'<text x="{x + 4:.2f}" y="{height - margin - 6}" font-size="11">{label}</text>'
        )
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        '<rect width="100%" height="100%" fill="white"/>'
        + "".join(legends)
        + f'<line x1="{margin}" y1="{height - margin}" x2="{width - margin}" y2="{height - margin}" stroke="#222"/>'
        + f'<line x1="{margin}" y1="{margin}" x2="{margin}" y2="{height - margin}" stroke="#222"/>'
        + "".join(polylines)
        + "".join(threshold_lines)
        + f'<text x="{width / 2 - 30}" y="{height - 10}" font-size="12">threshold</text>'
        + f'<text x="8" y="{height / 2}" font-size="12" transform="rotate(-90 8 {height / 2})">rate</text>'
        + "</svg>\n"
    )
    output_path.write_text(svg, encoding="utf-8")
