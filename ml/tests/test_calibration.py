from __future__ import annotations

import json
from pathlib import Path

import pytest

from visionqc_ml.calibration import ScoreRecord, calibrate_thresholds


def _write_scores(path: Path) -> None:
    rows = [
        ScoreRecord(sample_id="n1", split="validation", image_path="n1.png", label=0, anomaly_subtype="good", score=0.05, heatmap_path="n1.png", latency_ms=1, device="cpu"),
        ScoreRecord(sample_id="n2", split="validation", image_path="n2.png", label=0, anomaly_subtype="good", score=0.20, heatmap_path="n2.png", latency_ms=1, device="cpu"),
        ScoreRecord(sample_id="a1", split="validation", image_path="a1.png", label=1, anomaly_subtype="a", score=0.60, heatmap_path="a1.png", latency_ms=1, device="cpu"),
        ScoreRecord(sample_id="a2", split="validation", image_path="a2.png", label=1, anomaly_subtype="b", score=0.90, heatmap_path="a2.png", latency_ms=1, device="cpu"),
    ]
    path.write_text("".join(json.dumps(row.model_dump(mode="json")) + "\n" for row in rows), encoding="utf-8")


def test_calibration_prioritizes_false_accept_then_hold_recall(tmp_path: Path) -> None:
    predictions = tmp_path / "validation.jsonl"
    _write_scores(predictions)
    result = calibrate_thresholds(
        predictions,
        tmp_path / "calibration",
        "policy-v1",
        max_false_accept_rate=0.0,
        target_hold_recall=0.5,
    )
    assert result.review_threshold == 0.6
    assert result.hold_threshold == 0.9
    assert result.achieved["false_accept_rate"] == 0.0
    assert result.achieved["hold_recall"] == 0.5
    assert result.constraints_satisfied is True
    assert (tmp_path / "calibration" / "threshold-scan.csv").is_file()
    assert (tmp_path / "calibration" / "threshold-scan.svg").is_file()


def test_safety_margin_is_validation_only_and_legacy_remains_reproducible(tmp_path: Path) -> None:
    predictions = tmp_path / "validation.jsonl"
    _write_scores(predictions)
    legacy = calibrate_thresholds(
        predictions,
        tmp_path / "legacy",
        "policy-v1",
        max_false_accept_rate=0.0,
        target_hold_recall=0.5,
    )
    conservative = calibrate_thresholds(
        predictions,
        tmp_path / "conservative",
        "policy-v1",
        max_false_accept_rate=0.0,
        target_hold_recall=0.5,
        strategy="safety_margin",
        safety_margin=0.1,
    )
    assert legacy.strategy == "legacy"
    assert legacy.threshold_selection_split == "validation"
    assert conservative.strategy == "safety_margin"
    assert conservative.threshold_selection_split == "validation"
    assert conservative.review_threshold < legacy.review_threshold
    assert conservative.hold_threshold < legacy.hold_threshold
    assert conservative.achieved["hold_recall"] >= legacy.achieved["hold_recall"]

    mixed = tmp_path / "mixed.jsonl"
    mixed.write_text(
        predictions.read_text(encoding="utf-8")
        + json.dumps(
            ScoreRecord(
                sample_id="test-only",
                split="test",
                image_path="test-only.png",
                label=1,
                anomaly_subtype="a",
                score=0.99,
                heatmap_path="test-only.png",
                latency_ms=1,
                device="cpu",
            ).model_dump(mode="json")
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outside required split validation"):
        calibrate_thresholds(mixed, tmp_path / "mixed-output", "policy-v1")
