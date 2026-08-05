from __future__ import annotations

import json
import tarfile
from pathlib import Path

import pytest
import yaml

from conftest import write_mask, write_rgb
from visionqc_ml.calibration import ScoreRecord
from visionqc_ml.dataset import download_dataset, generate_manifest, verify_manifest
from visionqc_ml.dataset_source import DatasetSourceType
from visionqc_ml.feedback import ModelFeedbackRecord, write_feedback_re_evaluation_input
from visionqc_ml.gallery import build_error_gallery
from visionqc_ml.hashing import sha256_file, write_json
from visionqc_ml.inference import VisionQCInferenceService
from visionqc_ml.package import build_model_package, verify_model_package
from visionqc_ml.qualification import write_qualification_package
from visionqc_ml.registry import ModelRegistry
from visionqc_ml.shadow import run_shadow_evaluation
from visionqc_ml.training import run_patchcore_baseline


def _bottle_dataset(root: Path) -> Path:
    for index in range(4):
        write_rgb(root / "bottle" / "train" / "good" / f"{index:03d}.png", 30 + index)
        write_rgb(root / "bottle" / "test" / "good" / f"{index:03d}.png", 40 + index)
        write_rgb(root / "bottle" / "test" / "contamination" / f"{index:03d}.png", 140 + index)
        write_mask(root / "bottle" / "ground_truth" / "contamination" / f"{index:03d}_mask.png")
    return root


def test_bottle_download_manifest_and_fingerprint(tmp_path: Path) -> None:
    source_dataset = _bottle_dataset(tmp_path / "source")
    archive = tmp_path / "source.tar.xz"
    with tarfile.open(archive, "w:xz") as bundle:
        bundle.add(source_dataset / "bottle", arcname="mvtec_anomaly_detection/bottle")
    source = tmp_path / "source.json"
    write_json(
        source,
        {
            "category": "bottle",
            "archive_url": archive.resolve().as_uri(),
            "archive_filename": "dataset.tar.xz",
            "archive_sha256": sha256_file(archive),
            "source_page": "https://example.invalid/mvtec",
            "expected": {
                "train_good_images": 4,
                "test_good_images": 4,
                "test_anomalous_images": 4,
                "ground_truth_masks": 4,
            },
            "license": {"name": "CC BY-NC-SA 4.0", "commercial_use": False},
        },
    )
    dataset_root = tmp_path / "downloaded"
    receipt = download_dataset(source, dataset_root, tmp_path / "cache", license_acknowledged=True)
    assert receipt["extracted_category"] == "bottle"
    assert receipt["license_acknowledged"] is True
    manifest_dir = tmp_path / "manifest"
    meta = generate_manifest(dataset_root, manifest_dir, seed=99, validation_ratio=0.5, category="bottle")
    assert meta["category"] == "bottle"
    assert (
        meta["dataset_fingerprint"]
        == json.loads((manifest_dir / "dataset-fingerprint.json").read_text())["fingerprint"]
    )
    assert (
        verify_manifest(
            manifest_dir / "manifest.jsonl",
            dataset_root,
            manifest_dir / "manifest-meta.json",
        )["valid"]
        is True
    )


def _fake_package(tmp_path: Path, model_id: str, version: str, category: str) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    files = {
        "model": tmp_path / f"{version}-model.pt",
        "training": tmp_path / f"{version}-training.yaml",
        "preprocessing": tmp_path / f"{version}-preprocessing.json",
        "thresholds": tmp_path / f"{version}-thresholds.json",
        "evaluation_json": tmp_path / f"{version}-evaluation.json",
        "evaluation_md": tmp_path / f"{version}-evaluation.md",
        "meta": tmp_path / f"{version}-manifest-meta.json",
        "notice": tmp_path / f"{version}-NOTICE.md",
        "feature_bank": tmp_path / f"{version}-feature-bank.pt",
    }
    files["model"].write_bytes(f"model-{version}".encode())
    files["feature_bank"].write_bytes(f"feature-bank-{version}".encode())
    files["training"].write_text(
        f"seed: 1\nmodel:\n  anomalib_version: 2.0.0\n  backbone: resnet18\ndata:\n  category: {category}\n",
        encoding="utf-8",
    )
    write_json(
        files["preprocessing"],
        {"input_constraints": {"min_width": 1, "min_height": 1, "max_pixels": 10_000}},
    )
    write_json(files["thresholds"], {"policy_version": "p1", "review_threshold": 0.4, "hold_threshold": 0.8})
    write_json(
        files["evaluation_json"],
        {
            "metrics": {
                "image_level": {
                    "auroc": 0.9,
                    "at_review_threshold": {"f1": 0.7},
                    "at_hold_threshold": {"recall": 0.8},
                },
                "business": {"false_accept_rate": 0.0, "false_reject_rate": 0.1},
                "performance": {"warm_p95_ms": 20},
            }
        },
    )
    files["evaluation_md"].write_text("evaluation\n", encoding="utf-8")
    write_json(files["meta"], {"category": category, "dataset_fingerprint": "b" * 64, "manifest_sha256": "c" * 64})
    files["notice"].write_text("license notice\n", encoding="utf-8")
    return build_model_package(
        tmp_path / "packages",
        files["model"],
        files["training"],
        files["preprocessing"],
        files["thresholds"],
        files["evaluation_json"],
        files["evaluation_md"],
        files["meta"],
        files["notice"],
        model_id,
        version,
        "deadbeef",
        feature_bank_path=files["feature_bank"],
        feature_bank_version=f"fb-{category}-{version}",
    )


def test_package_feature_bank_and_registry_lifecycle(tmp_path: Path) -> None:
    first = _fake_package(tmp_path / "first", "patchcore-transistor", "1.0.0", "transistor")
    second = _fake_package(tmp_path / "second", "patchcore-transistor", "1.1.0", "transistor")
    first_manifest = verify_model_package(first, expected_category="transistor")
    assert first_manifest.feature_bank_file == "weights/feature-bank.pt"
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register_draft(first)
    with pytest.raises(ValueError, match="only APPROVED"):
        registry.activate("patchcore-transistor", "1.0.0", "ops", "too early")
    registry.evaluate("patchcore-transistor", "1.0.0", "eval", "Synthetic evaluation evidence recorded.")
    registry.approve("patchcore-transistor", "1.0.0", "quality", "Quality owner approved the evidence.")
    registry.activate("patchcore-transistor", "1.0.0", "release", "Activation gate and rollback plan recorded.")
    registry.register_draft(second)
    registry.evaluate("patchcore-transistor", "1.1.0", "eval", "Candidate evaluation evidence recorded.")
    registry.approve("patchcore-transistor", "1.1.0", "quality", "Candidate evidence approved for activation.")
    registry.activate("patchcore-transistor", "1.1.0", "release", "Candidate gate passed with rollback evidence.")
    statuses = {(item.model_version, item.lifecycle_status) for item in registry.index.entries}
    assert ("1.0.0", "RETIRED") in statuses
    assert ("1.1.0", "ACTIVE") in statuses
    registry.rollback(
        "patchcore-transistor",
        "1.0.0",
        "release",
        "Rollback evidence is attached and reviewed.",
        "candidate hold recall regressed on approved cohort",
    )
    statuses = {(item.model_version, item.lifecycle_status) for item in registry.index.entries}
    assert ("1.0.0", "ACTIVE") in statuses
    assert ("1.1.0", "RETIRED") in statuses


def test_registry_blocks_activation_when_evidence_is_insufficient(tmp_path: Path) -> None:
    package = _fake_package(tmp_path / "candidate", "patchcore-transistor", "1.0.0", "transistor")
    evidence = tmp_path / "evidence" / "Factory A" / "transistor"
    write_qualification_package(
        evidence,
        factory="Factory A",
        category="transistor",
        source_type=DatasetSourceType.DEMO_SYNTHETIC,
        model_package=package,
        repository_root=tmp_path,
    )
    registry = ModelRegistry(tmp_path / "registry.json")
    registry.register_draft(package, evidence_package_path=evidence)
    registry.evaluate(
        "patchcore-transistor",
        "1.0.0",
        "ml-evaluator",
        "Insufficient evidence blocker recorded for the candidate.",
    )
    with pytest.raises(ValueError, match="not GO"):
        registry.approve(
            "patchcore-transistor",
            "1.0.0",
            "quality-manager",
            "Approval requested despite missing real-data evidence.",
        )
    assert registry.index.entries[0].lifecycle_status == "DRAFT"
    assert any(
        reason.startswith("qualification_gate_blocked:INSUFFICIENT_EVIDENCE")
        for reason in registry.index.entries[0].audit_reasons
    )


def test_shadow_gallery_and_feedback_contracts(tmp_path: Path) -> None:
    image_root = tmp_path / "images"
    prediction_root = tmp_path / "predictions"
    rows = []
    candidate_rows = []
    for index, (label, active_score, candidate_score) in enumerate(((0, 0.1, 0.5), (1, 0.2, 0.9))):
        image = image_root / f"{index}.png"
        write_rgb(image, 90 + index)
        evidence = prediction_root / f"{index}"
        write_rgb(evidence / "heatmap.png", 100 + index)
        write_rgb(evidence / "overlay.png", 120 + index)
        rows.append(
            ScoreRecord(
                sample_id=f"sample_{index}",
                split="test",
                image_path=str(image.relative_to(image_root)),
                label=label,
                anomaly_subtype="good" if label == 0 else "scratch",
                score=active_score,
                heatmap_path=str((evidence / "heatmap.png").resolve()),
                latency_ms=2,
                device="cpu",
                product_category="bottle",
            )
        )
        candidate_rows.append(rows[-1].model_copy(update={"score": candidate_score}))
    active_path = tmp_path / "active.jsonl"
    candidate_path = tmp_path / "candidate.jsonl"
    active_path.write_text("".join(row.model_dump_json() + "\n" for row in rows), encoding="utf-8")
    candidate_path.write_text("".join(row.model_dump_json() + "\n" for row in candidate_rows), encoding="utf-8")
    active_thresholds = tmp_path / "active-thresholds.json"
    candidate_thresholds = tmp_path / "candidate-thresholds.json"
    write_json(active_thresholds, {"review_threshold": 0.4, "hold_threshold": 0.8})
    write_json(candidate_thresholds, {"review_threshold": 0.3, "hold_threshold": 0.7})
    shadow = run_shadow_evaluation(
        active_path,
        candidate_path,
        active_thresholds,
        candidate_thresholds,
        tmp_path / "shadow.json",
        product_category="bottle",
    )
    assert shadow["changed_sample_count"] == 2

    manifest = {
        row.sample_id: type("Entry", (), {"image_path": row.image_path, "category": "bottle"})() for row in rows
    }
    gallery = build_error_gallery(
        rows + candidate_rows,
        manifest,  # type: ignore[arg-type]
        image_root,
        prediction_root,
        0.3,
        0.7,
        tmp_path / "gallery",
        max_cases=4,
    )
    assert gallery["case_count"] == 4
    assert (tmp_path / "gallery" / "index.html").is_file()
    assert "root cause" in (tmp_path / "gallery" / "index.html").read_text(encoding="utf-8")

    feedback = ModelFeedbackRecord(
        feedback_id="fb-1",
        product_category="bottle",
        inspection_id="insp-1",
        image_sha256="a" * 64,
        image_uri="/evidence/input.png",
        model_id="patchcore-bottle",
        model_version="2.3.0",
        model_feedback="SUSPECTED_FALSE_NEGATIVE",
        reviewer_id="qa-1",
        reviewer_decision="INVESTIGATE",
        observed_at="2026-08-04T00:00:00Z",
        notes="Review against the next frozen evaluation manifest.",
    )
    meta = write_feedback_re_evaluation_input([feedback], tmp_path / "feedback")
    assert meta["product_category"] == "bottle"
    assert (tmp_path / "feedback" / "feedback.jsonl").is_file()


@pytest.mark.model
def test_bottle_patchcore_smoke_builds_isolated_package(tmp_path: Path) -> None:
    dataset = _bottle_dataset(tmp_path / "dataset")
    manifest_dir = tmp_path / "manifest"
    generate_manifest(dataset, manifest_dir, seed=20260804, validation_ratio=0.5, category="bottle")
    config = yaml.safe_load(
        (Path(__file__).parents[1] / "configs" / "patchcore-smoke-bottle.yaml").read_text(encoding="utf-8")
    )
    config_path = tmp_path / "patchcore-smoke-bottle.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    notice = tmp_path / "MVTEC-AD-NOTICE.md"
    notice.write_text("Synthetic smoke data only; no real MVTec data is included.\n", encoding="utf-8")
    summary = run_patchcore_baseline(
        config_path,
        manifest_dir / "manifest.jsonl",
        manifest_dir / "manifest-meta.json",
        dataset,
        tmp_path / "run",
        tmp_path / "packages",
        tmp_path,
        notice,
    )
    assert summary["category"] == "bottle"
    assert summary["feature_bank_version"] == "fb-bottle-smoke"
    manifest = verify_model_package(Path(summary["package_dir"]), expected_category="bottle")
    assert manifest.feature_bank_file == "weights/feature-bank.pt"
    service = VisionQCInferenceService.from_package(
        Path(summary["package_dir"]), device="cpu", expected_category="bottle"
    )
    result = service.infer(dataset / "bottle" / "test" / "good" / "000.png", "bottle_smoke", tmp_path / "online")
    assert result.model.id == "patchcore-bottle-smoke"
