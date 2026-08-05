from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from visionqc_ml.compat import ensure_anomalib_torch_importable
from visionqc_ml.dataset import generate_manifest
from visionqc_ml.inference import VisionQCInferenceService
from visionqc_ml.training import _build_data_module, _require_model_runtime, run_patchcore_baseline


@pytest.mark.model
def test_anomalib_patchcore_minimal_constructor() -> None:
    pytest.importorskip("anomalib")
    ensure_anomalib_torch_importable()
    from anomalib.models import Patchcore
    from anomalib.post_processing import PostProcessor

    preprocessor = Patchcore.configure_pre_processor(image_size=(64, 64), center_crop_size=(56, 56))
    model = Patchcore(
        backbone="resnet18",
        layers=["layer2", "layer3"],
        pre_trained=False,
        coreset_sampling_ratio=0.1,
        num_neighbors=1,
        pre_processor=preprocessor,
        post_processor=PostProcessor(enable_thresholding=False),
        evaluator=False,
        visualizer=False,
    )
    assert model.coreset_sampling_ratio == 0.1
    assert model.learning_type.value == "one_class"


@pytest.mark.model
def test_manifest_adapter_fits_and_predicts_patchcore(synthetic_dataset: Path, tmp_path: Path) -> None:
    ensure_anomalib_torch_importable()
    from anomalib.engine import Engine
    from anomalib.models import Patchcore
    from anomalib.post_processing import PostProcessor

    manifest_dir = tmp_path / "manifest"
    generate_manifest(synthetic_dataset, manifest_dir, seed=9, validation_ratio=0.5)
    runtime = _require_model_runtime()
    datamodule = _build_data_module(
        runtime,
        manifest_dir / "manifest.jsonl",
        synthetic_dataset,
        seed=9,
        train_batch_size=2,
        eval_batch_size=2,
        num_workers=0,
    )
    model = Patchcore(
        backbone="resnet18",
        layers=["layer2", "layer3"],
        pre_trained=False,
        coreset_sampling_ratio=0.2,
        num_neighbors=1,
        pre_processor=Patchcore.configure_pre_processor(image_size=(64, 64), center_crop_size=(56, 56)),
        post_processor=PostProcessor(enable_thresholding=False),
        evaluator=False,
        visualizer=False,
    )
    engine = Engine(
        default_root_dir=tmp_path / "engine",
        accelerator="cpu",
        devices=1,
        logger=False,
        enable_progress_bar=False,
    )
    engine.fit(model=model, datamodule=datamodule)
    assert model.model.memory_bank.numel() > 0
    predictions = engine.predict(
        model=model,
        dataloaders=datamodule.val_dataloader(),
        return_predictions=True,
    )
    assert predictions
    assert predictions[0].pred_score is not None
    assert predictions[0].anomaly_map is not None


@pytest.mark.model
def test_complete_tiny_baseline_builds_verified_package(synthetic_dataset: Path, tmp_path: Path) -> None:
    manifest_dir = tmp_path / "manifest"
    generate_manifest(synthetic_dataset, manifest_dir, seed=12, validation_ratio=0.5)
    config = {
        "schema_version": "visionqc.training-config.v1",
        "seed": 12,
        "model": {
            "id": "patchcore-transistor-smoke",
            "version": "0.0.1",
            "adapter": "anomalib.patchcore.v2",
            "anomalib_version": "2.0.0",
            "backbone": "resnet18",
            "layers": ["layer2", "layer3"],
            "pretrained": False,
            "coreset_sampling_ratio": 0.2,
            "num_neighbors": 1,
        },
        "preprocessing": {
            "color_mode": "RGB",
            "resize": {"height": 64, "width": 64, "interpolation": "bilinear", "antialias": True},
            "center_crop": {"height": 56, "width": 56},
            "normalize": {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
            "input_constraints": {"min_width": 16, "min_height": 16, "max_pixels": 100_000},
        },
        "data": {"category": "transistor", "train_batch_size": 2, "eval_batch_size": 2, "num_workers": 0},
        "calibration": {"max_false_accept_rate": 0.5, "target_hold_recall": 0.5},
        "performance": {"warmup_runs": 1, "measured_runs": 1, "warm_p95_target_ms": 3000},
        "runtime": {"accelerator": "cpu", "devices": 1, "deterministic": True},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    notice = tmp_path / "NOTICE.md"
    notice.write_text("Synthetic test data only.\n", encoding="utf-8")
    summary = run_patchcore_baseline(
        config_path,
        manifest_dir / "manifest.jsonl",
        manifest_dir / "manifest-meta.json",
        synthetic_dataset,
        tmp_path / "run",
        tmp_path / "packages",
        tmp_path,
        notice,
    )
    assert summary["claim_boundary"] == "anomaly and anomalous-region evidence only"
    assert Path(summary["package_dir"]).joinpath("model-package.json").is_file()
    assert (tmp_path / "run" / "evaluation" / "evaluation.json").is_file()
    assert (tmp_path / "run" / "evidence" / "test").is_dir()

    service = VisionQCInferenceService.from_package(Path(summary["package_dir"]), device="cpu")
    image = synthetic_dataset / "transistor" / "test" / "good" / "000.png"
    service.warmup(image, runs=1)
    first = service.infer(image, "repeat_1", tmp_path / "online")
    second = service.infer(image, "repeat_2", tmp_path / "online")
    assert first.anomaly.score == second.anomaly.score
    assert first.anomaly.heatmap.sha256 == second.anomaly.heatmap.sha256
