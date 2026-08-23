from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import yaml
from PIL import Image

from conftest import write_mask, write_rgb
from visionqc_ml.calibration import ScoreRecord, calibrate_thresholds
from visionqc_ml.dataset import ManifestEntry, generate_manifest, load_manifest
from visionqc_ml.dataset_source import DatasetSourceType
from visionqc_ml.evaluation import evaluate_predictions
from visionqc_ml.hashing import write_json
from visionqc_ml.package import build_model_package
from visionqc_ml.qualification import (
    calibrate_protocol_b,
    evaluate_pilot_gates,
    load_pilot_evidence,
    qualify_from_run,
    split_manifest_for_protocol_b,
    validate_split_manifest,
    verify_evidence_package,
    write_qualification_package,
)
from visionqc_ml.registry import ModelRegistry


def _record(sample_id: str, label: int, score: float, split: str = "holdout") -> ScoreRecord:
    return ScoreRecord(
        sample_id=sample_id,
        split=split,  # type: ignore[arg-type]
        image_path=f"{sample_id}.png",
        label=label,  # type: ignore[arg-type]
        anomaly_subtype="good" if label == 0 else "scratch",
        score=score,
        heatmap_path=f"{sample_id}-heatmap.png",
        latency_ms=20,
        warm=True,
        device="cpu",
    )


def test_gates_do_not_pass_with_missing_real_metrics() -> None:
    result = evaluate_pilot_gates({}, package_verified=False, no_split_leakage=True, evidence_complete=False)
    assert result["decision"] == "INSUFFICIENT_EVIDENCE"
    assert result["checks"]["image_auroc"]["status"] == "INSUFFICIENT_EVIDENCE"


def test_benchmark_gate_pass_is_not_customer_approval() -> None:
    result = evaluate_pilot_gates(
        {
            "image_auroc": 0.99,
            "defect_error_auto_release_rate": 0.0,
            "review_hold_recall": 0.99,
            "hold_recall": 0.9,
            "normal_review_hold_rate": 0.1,
            "warm_p95_ms": 100.0,
        },
        package_verified=True,
        no_split_leakage=True,
        evidence_complete=True,
        source_type=DatasetSourceType.OFFICIAL_BENCHMARK,
    )
    assert result["decision"] == "GO"
    assert result["approval_eligible"] is False
    assert result["checks"]["customer_data_provenance"]["status"] == "NOT_APPLICABLE"


def test_abnormal_auto_release_is_a_hard_zero_gate() -> None:
    result = evaluate_pilot_gates(
        {
            "image_auroc": 0.99,
            "defect_error_auto_release_rate": 0.001,
            "review_hold_recall": 0.99,
            "hold_recall": 0.9,
            "normal_review_hold_rate": 0.1,
            "warm_p95_ms": 100.0,
        },
        package_verified=True,
        no_split_leakage=True,
        evidence_complete=True,
        source_type=DatasetSourceType.OFFICIAL_BENCHMARK,
    )
    assert result["decision"] == "NO-GO"
    assert result["checks"]["defect_error_auto_release_rate"]["gate_class"] == "HARD_GATE"


def test_non_validation_threshold_source_is_rejected() -> None:
    result = evaluate_pilot_gates(
        {
            "image_auroc": 0.99,
            "defect_error_auto_release_rate": 0.0,
            "review_hold_recall": 0.99,
            "hold_recall": 0.9,
            "normal_review_hold_rate": 0.1,
            "warm_p95_ms": 100.0,
        },
        package_verified=True,
        no_split_leakage=True,
        evidence_complete=True,
        source_type=DatasetSourceType.OFFICIAL_BENCHMARK,
        threshold_source_split="holdout",
    )
    assert result["decision"] == "NO-GO"
    assert result["checks"]["threshold_source_split"]["status"] == "FAIL"


def test_evidence_package_propagates_threshold_source_guard(tmp_path: Path) -> None:
    output = tmp_path / "invalid-threshold-source"
    write_qualification_package(
        output,
        factory="benchmark-context",
        category="transistor",
        source_type=DatasetSourceType.OFFICIAL_BENCHMARK,
        thresholds={"source_split": "holdout"},
        repository_root=tmp_path,
    )
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["gates"]["checks"]["threshold_source_split"]["status"] == "FAIL"


def test_customer_missing_provenance_is_source_scoped_draft(tmp_path: Path) -> None:
    output = tmp_path / "customer-evidence"
    result = write_qualification_package(
        output,
        factory="customer-context",
        category="transistor",
        source_type=DatasetSourceType.CUSTOMER_PILOT,
        dataset_fingerprint="a" * 64,
        repository_root=tmp_path,
    )
    release = json.loads((output / "release-decision.json").read_text(encoding="utf-8"))
    metrics = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    assert result["decision"] == "CUSTOMER_PILOT_INSUFFICIENT_EVIDENCE"
    assert release["approval_status"] == "DRAFT_ONLY"
    assert release["source_type"] == "CUSTOMER_PILOT"
    assert metrics["gates"]["checks"]["customer_data_provenance"]["status"] == "INSUFFICIENT_EVIDENCE"
    assert "Customer data provenance" in release["reason"]


def test_demo_report_is_explicitly_non_claiming_and_fingerprinted(tmp_path: Path) -> None:
    output = tmp_path / "demo-evidence"
    write_qualification_package(
        output,
        factory="demo-context",
        category="transistor",
        source_type=DatasetSourceType.DEMO_SYNTHETIC,
        repository_root=tmp_path,
    )
    provenance = json.loads((output / "provenance.json").read_text(encoding="utf-8"))
    report = (output / "evaluation-report.md").read_text(encoding="utf-8")
    assert provenance["source_type"] == "DEMO_SYNTHETIC"
    assert len(provenance["dataset_fingerprint"]) == 64
    assert "不得用于效果声明" in report
    assert verify_evidence_package(output)["valid"] is True


def test_split_manifest_rejects_content_hash_overlap() -> None:
    manifest = {
        "train": [{"sample_id": "a", "image_path": "a.png", "image_sha256": "x"}],
        "calibration": [{"sample_id": "b", "image_path": "b.png", "image_sha256": "x"}],
        "holdout": [],
    }
    with pytest.raises(ValueError, match="overlap"):
        validate_split_manifest(manifest)


def test_protocol_b_rejects_holdout_records_for_threshold_selection() -> None:
    with pytest.raises(ValueError, match="holdout is forbidden"):
        calibrate_protocol_b([_record("normal", 0, 0.1), _record("anomaly", 1, 0.9)])


def test_protocol_b_manifest_uses_validation_and_frozen_holdout_without_test_tuning() -> None:
    entries = [
        ManifestEntry(
            sample_id="sample_0000000000000001",
            split="train",
            source_split="train",
            image_path="train.png",
            image_sha256="a" * 64,
            mask_path=None,
            mask_sha256=None,
            label=0,
            anomaly_subtype="good",
            width=32,
            height=32,
        ),
        ManifestEntry(
            sample_id="sample_0000000000000002",
            split="validation",
            source_split="test",
            image_path="validation.png",
            image_sha256="b" * 64,
            mask_path="validation-mask.png",
            mask_sha256="c" * 64,
            label=1,
            anomaly_subtype="scratch",
            width=32,
            height=32,
        ),
        ManifestEntry(
            sample_id="sample_0000000000000003",
            split="test",
            source_split="test",
            image_path="test.png",
            image_sha256="d" * 64,
            mask_path="test-mask.png",
            mask_sha256="e" * 64,
            label=1,
            anomaly_subtype="scratch",
            width=32,
            height=32,
        ),
    ]
    split = split_manifest_for_protocol_b(entries)
    assert "calibration" not in split
    assert [row["sample_id"] for row in split["validation"]] == ["sample_0000000000000002"]
    assert [row["sample_id"] for row in split["holdout"]] == ["sample_0000000000000003"]
    assert split["threshold_source_split"] == "validation"
    assert split["holdout_records_consumed_for_selection"] is False


def test_insufficient_evidence_package_is_complete_and_tamper_evident(tmp_path: Path) -> None:
    output = tmp_path / "Factory A" / "transistor"
    result = write_qualification_package(
        output,
        factory="Factory A",
        category="transistor",
        source_type=DatasetSourceType.DEMO_SYNTHETIC,
        repository_root=tmp_path,
    )
    assert result["decision"] == "DEMO_ONLY"
    assert verify_evidence_package(output)["valid"] is True
    (output / "model-card.md").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="integrity"):
        verify_evidence_package(output)


def test_blocked_package_exposes_null_metric_surface_and_blockers(tmp_path: Path) -> None:
    output = tmp_path / "Factory B" / "bottle"
    write_qualification_package(
        output,
        factory="Factory B",
        category="bottle",
        source_type=DatasetSourceType.DEMO_SYNTHETIC,
        repository_root=tmp_path,
    )
    payload = json.loads((output / "metrics.json").read_text(encoding="utf-8"))
    metrics = payload["metrics"]
    for key in (
        "image_auroc",
        "pixel_auroc",
        "aupro",
        "precision",
        "recall",
        "f1",
        "defect_error_auto_release_rate",
        "review_hold_recall",
        "hold_recall",
        "manual_review_burden_rate",
        "cold_start_ms",
        "warm_inference_p50_ms",
        "warm_inference_p95_ms",
    ):
        assert metrics[key] is None
    assert metrics["sample_count"] == 0
    assert payload["metric_notes"]["unavailable_metrics_are_null"] is True
    assert (
        json.loads((output / "provenance.json").read_text(encoding="utf-8"))["qualification_run_status"] == "DEMO_ONLY"
    )


def test_evidence_inventory_cannot_omit_a_required_file(tmp_path: Path) -> None:
    output = tmp_path / "Factory A" / "transistor"
    write_qualification_package(
        output,
        factory="Factory A",
        category="transistor",
        source_type=DatasetSourceType.DEMO_SYNTHETIC,
        repository_root=tmp_path,
    )
    inventory_path = output / "evidence-manifest.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    del inventory["files"]["metrics.json"]
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    with pytest.raises(ValueError, match="complete package"):
        verify_evidence_package(output)


def _build_fixture_run(tmp_path: Path) -> tuple[Path, Path, Path]:
    dataset_root = tmp_path / "dataset"
    for index in range(4):
        write_rgb(dataset_root / "bottle" / "train" / "good" / f"{index:03d}.png", 30 + index)
        write_rgb(dataset_root / "bottle" / "test" / "good" / f"{index:03d}.png", 40 + index)
        write_rgb(dataset_root / "bottle" / "test" / "contamination" / f"{index:03d}.png", 140 + index)
        mask_path = dataset_root / "bottle" / "ground_truth" / "contamination" / f"{index:03d}_mask.png"
        write_mask(mask_path)
        with Image.open(mask_path) as mask:
            mask_array = np.asarray(mask.convert("L")).copy()
        mask_array[0, index] = index + 1
        Image.fromarray(mask_array, mode="L").save(mask_path)
    receipt = {
        "schema_version": "visionqc.dataset-directory-receipt.v1",
        "dataset": "MVTec AD",
        "category": "bottle",
        "dataset_root": str(dataset_root.resolve()),
        "license_acknowledged": True,
        "source_archive_sha256": "a" * 64,
    }
    write_json(dataset_root / "bottle.directory-receipt.json", receipt)
    manifest_dir = tmp_path / "manifest"
    generate_manifest(dataset_root, manifest_dir, seed=99, validation_ratio=0.5, category="bottle")
    entries = load_manifest(manifest_dir / "manifest.jsonl")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    write_json(
        run_dir / "run.json",
        {
            "schema_version": "visionqc.model-run.v1",
            "manifest_path": str((manifest_dir / "manifest.jsonl").resolve()),
            "code_commit": "test",
        },
    )
    prediction_rows: dict[str, list[ScoreRecord]] = {"validation": [], "test": []}
    test_anomalies_seen = 0
    for entry in entries:
        if entry.split not in prediction_rows:
            continue
        if entry.label == 0:
            score = 0.1
        elif entry.split == "validation":
            score = 0.9
        else:
            score = 0.9 if test_anomalies_seen == 0 else 0.1
            test_anomalies_seen += 1
        evidence_dir = run_dir / "evidence" / entry.split / entry.sample_id
        write_rgb(evidence_dir / "heatmap.png", 120 if entry.label else 30)
        write_rgb(evidence_dir / "overlay.png", 150 if entry.label else 45)
        record = ScoreRecord(
            sample_id=entry.sample_id,
            split=entry.split,  # type: ignore[arg-type]
            image_path=entry.image_path,
            label=entry.label,
            anomaly_subtype=entry.anomaly_subtype,
            score=score,
            heatmap_path=str((evidence_dir / "heatmap.png").resolve()),
            latency_ms=10.0,
            warm=True,
            device="cpu",
            product_category="bottle",
        )
        prediction_rows[entry.split].append(record)
    for split, rows in prediction_rows.items():
        path = run_dir / "predictions" / f"{split}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")
    calibrate_thresholds(
        run_dir / "predictions" / "validation.jsonl",
        run_dir / "calibration",
        "fixture-policy",
        max_false_accept_rate=0.0,
        target_hold_recall=0.8,
    )
    write_json(
        run_dir / "performance-probe.json",
        {
            "schema_version": "visionqc.performance-probe.v1",
            "category": "bottle",
            "cold_ms": 20.0,
            "warm_p50_ms": 10.0,
            "warm_p95_ms": 12.0,
        },
    )
    evaluate_predictions(
        run_dir / "predictions" / "test.jsonl",
        manifest_dir / "manifest.jsonl",
        manifest_dir / "manifest-meta.json",
        dataset_root,
        run_dir / "calibration" / "thresholds.json",
        run_dir / "evaluation",
        {"id": "patchcore-bottle", "version": "1.0.0", "adapter": "anomalib.patchcore.v2"},
        {"python": "test", "device": "cpu"},
        performance_probe_path=run_dir / "performance-probe.json",
        gallery_output_dir=run_dir / "gallery",
    )
    model_path = tmp_path / "model.pt"
    model_path.write_bytes(b"fixture-model")
    training_path = tmp_path / "training.yaml"
    training_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "visionqc.training-config.v1",
                "model": {
                    "id": "patchcore-bottle",
                    "version": "1.0.0",
                    "anomalib_version": "2.0.0",
                    "backbone": "resnet18",
                },
                "data": {"category": "bottle"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    preprocessing_path = tmp_path / "preprocessing.json"
    write_json(preprocessing_path, {"input_constraints": {"min_width": 1, "min_height": 1, "max_pixels": 10000}})
    notice_path = tmp_path / "notice.md"
    notice_path.write_text("fixture notice\n", encoding="utf-8")
    package = build_model_package(
        tmp_path / "packages",
        model_path,
        training_path,
        preprocessing_path,
        run_dir / "calibration" / "thresholds.json",
        run_dir / "evaluation" / "evaluation.json",
        run_dir / "evaluation" / "evaluation.md",
        manifest_dir / "manifest-meta.json",
        notice_path,
        "patchcore-bottle",
        "1.0.0",
        "test",
    )
    write_json(
        run_dir / "summary.json",
        {
            "run_dir": str(run_dir.resolve()),
            "package_dir": str(package.resolve()),
            "package_sha256": json.loads((package / "model-package.json").read_text())["package_sha256"],
            "dataset_fingerprint": json.loads((manifest_dir / "manifest-meta.json").read_text())["dataset_fingerprint"],
            "category": "bottle",
        },
    )
    return run_dir, package, dataset_root


def test_real_run_contract_maps_metrics_and_keeps_failed_candidate_draft(tmp_path: Path) -> None:
    run_dir, package, dataset_root = _build_fixture_run(tmp_path)
    evidence = load_pilot_evidence(
        run_dir,
        category="bottle",
        model_package=package,
        dataset_root=dataset_root,
    )
    assert evidence["metrics"]["metric_status"] == "AVAILABLE"
    assert evidence["metrics"]["warm_p95_ms"] == 12.0
    output = tmp_path / "evidence"
    result = qualify_from_run(
        run_dir,
        factory="Fixture Factory",
        category="bottle",
        model_package=package,
        dataset_root=dataset_root,
        output_dir=output,
        repository_root=tmp_path,
    )
    assert result["decision"] == "BENCHMARK_NO_GO"
    report = (output / "evaluation-report.md").read_text(encoding="utf-8")
    assert "Image AUROC |" in report and "null" not in report
    assert verify_evidence_package(output, expected_model_package_sha256=evidence["package_manifest"].package_sha256)[
        "valid"
    ]

    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register_draft(package, evidence_package_path=output)
    registry.evaluate("patchcore-bottle", "1.0.0", "evaluator", "Real holdout gate result recorded.")
    assert registry.index.entries[0].lifecycle_status == "DRAFT"
    assert any(
        "qualification_gate_blocked:NO-GO" in reason and "report_status=BENCHMARK_NO_GO" in reason
        for reason in registry.index.entries[0].audit_reasons
    )
    with pytest.raises(ValueError, match="remains DRAFT"):
        registry.approve("patchcore-bottle", "1.0.0", "approver", "Attempted approval of failed business gate.")
    source_path = Path(
        json.loads((output / "source-evidence.json").read_text())["files"]["predictions/test.jsonl"]["path"]
    )
    original_predictions = source_path.read_text(encoding="utf-8")
    source_path.write_text(original_predictions + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source evidence integrity"):
        verify_evidence_package(output)
    source_path.write_text(original_predictions, encoding="utf-8")


def test_real_run_contract_rejects_prediction_tampering_and_path_mismatch(tmp_path: Path) -> None:
    run_dir, package, dataset_root = _build_fixture_run(tmp_path)
    probe_path = run_dir / "performance-probe.json"
    probe_bytes = probe_path.read_bytes()
    probe_path.unlink()
    with pytest.raises(ValueError, match="performance probe is missing"):
        load_pilot_evidence(run_dir, category="bottle", model_package=package, dataset_root=dataset_root)
    probe_path.write_bytes(probe_bytes)
    test_predictions = run_dir / "predictions" / "test.jsonl"
    original = test_predictions.read_text(encoding="utf-8")
    test_predictions.write_text(original.replace('"label":0', '"label":1', 1), encoding="utf-8")
    with pytest.raises(ValueError, match="label/subtype mismatch|prediction SHA-256"):
        load_pilot_evidence(run_dir, category="bottle", model_package=package, dataset_root=dataset_root)
    test_predictions.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError, match="dataset root mismatch"):
        load_pilot_evidence(run_dir, category="bottle", model_package=package, dataset_root=tmp_path / "other")
    with pytest.raises(ValueError, match="manifest category mismatch"):
        load_pilot_evidence(run_dir, category="transistor", model_package=package, dataset_root=dataset_root)

    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["dataset_fingerprint"] = "f" * 64
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="summary dataset fingerprint"):
        load_pilot_evidence(run_dir, category="bottle", model_package=package, dataset_root=dataset_root)

    summary["dataset_fingerprint"] = json.loads(
        (
            Path(json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["manifest_path"]).parent
            / "manifest-meta.json"
        ).read_text(encoding="utf-8")
    )["dataset_fingerprint"]
    other_package = build_model_package(
        tmp_path / "other-packages",
        tmp_path / "model.pt",
        tmp_path / "training.yaml",
        tmp_path / "preprocessing.json",
        run_dir / "calibration" / "thresholds.json",
        run_dir / "evaluation" / "evaluation.json",
        run_dir / "evaluation" / "evaluation.md",
        Path(json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["manifest_path"]).parent
        / "manifest-meta.json",
        tmp_path / "notice.md",
        "patchcore-bottle",
        "2.0.0",
        "test",
    )
    summary["package_dir"] = str(other_package.resolve())
    summary["package_sha256"] = json.loads((other_package / "model-package.json").read_text())["package_sha256"]
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(ValueError, match="evaluation model identity"):
        load_pilot_evidence(run_dir, category="bottle", model_package=other_package, dataset_root=dataset_root)
