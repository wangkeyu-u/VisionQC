"""Anomalib PatchCore training and complete Iteration-1 baseline orchestration."""

from __future__ import annotations

import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

import numpy as np
import yaml

from .calibration import CalibrationStrategy, ScoreRecord, calibrate_thresholds
from .compat import ensure_anomalib_torch_importable
from .dataset import ManifestEntry, load_manifest, verify_manifest
from .errors import ModelRuntimeUnavailable
from .evaluation import evaluate_predictions
from .hashing import write_json
from .package import build_model_package, verify_model_package
from .preprocessing import render_evidence
from .provenance import git_commit, runtime_environment


def _require_model_runtime() -> dict[str, Any]:
    openvino_type_shim = ensure_anomalib_torch_importable()
    try:
        import pandas as pd
        import torch
        from anomalib.data.datasets.base.image import AnomalibDataset
        from anomalib.deploy import TorchInferencer
        from anomalib.engine import Engine
        from anomalib.models import Patchcore
        from anomalib.post_processing import PostProcessor
        from lightning import LightningDataModule, seed_everything
        from torch.utils.data import DataLoader
    except ImportError as exc:
        raise ModelRuntimeUnavailable(
            "PatchCore workflow requires `uv sync --extra model --extra dev` under Python 3.10-3.12"
        ) from exc
    return {
        "pd": pd,
        "torch": torch,
        "AnomalibDataset": AnomalibDataset,
        "TorchInferencer": TorchInferencer,
        "Engine": Engine,
        "Patchcore": Patchcore,
        "PostProcessor": PostProcessor,
        "LightningDataModule": LightningDataModule,
        "seed_everything": seed_everything,
        "DataLoader": DataLoader,
        "openvino_type_shim": openvino_type_shim,
    }


def _build_data_module(
    runtime: dict[str, Any],
    manifest_path: Path,
    dataset_root: Path,
    seed: int,
    train_batch_size: int,
    eval_batch_size: int,
    num_workers: int,
    category: str = "transistor",
) -> Any:
    pd = runtime["pd"]
    torch = runtime["torch"]
    AnomalibDataset = runtime["AnomalibDataset"]
    LightningDataModule = runtime["LightningDataModule"]
    DataLoader = runtime["DataLoader"]
    entries = load_manifest(manifest_path)
    category_name = category

    class ManifestDataset(AnomalibDataset):  # type: ignore[misc, valid-type]
        def __init__(self, selected: list[ManifestEntry], split_name: str) -> None:
            super().__init__(augmentations=None)
            frame = pd.DataFrame([
                {
                    "image_path": str((dataset_root / entry.image_path).resolve()),
                    "label_index": entry.label,
                    "mask_path": str((dataset_root / entry.mask_path).resolve()) if entry.mask_path else "",
                    "split": split_name,
                }
                for entry in selected
            ])
            frame.attrs["task"] = "segmentation"
            self.samples = frame
            self.category = category_name

        @property
        def name(self) -> str:
            return "VisionQCManifest"

    class ManifestDataModule(LightningDataModule):  # type: ignore[misc, valid-type]
        name = "VisionQCManifest"
        category = category_name

        def __init__(self) -> None:
            super().__init__()
            self.train_data = ManifestDataset([entry for entry in entries if entry.split == "train"], "train")
            self.val_data = ManifestDataset(
                [entry for entry in entries if entry.split == "validation"], "validation"
            )
            self.test_data = ManifestDataset([entry for entry in entries if entry.split == "test"], "test")

        def setup(self, stage: str | None = None) -> None:
            del stage

        @staticmethod
        def _seed_worker(worker_id: int) -> None:
            worker_seed = seed + worker_id
            random.seed(worker_seed)
            np.random.seed(worker_seed % (2**32))

        def _loader(self, dataset: Any, batch_size: int, shuffle: bool) -> Any:
            generator = torch.Generator().manual_seed(seed)
            return DataLoader(
                dataset,
                batch_size=batch_size,
                shuffle=shuffle,
                num_workers=num_workers,
                collate_fn=dataset.collate_fn,
                worker_init_fn=self._seed_worker,
                generator=generator,
                persistent_workers=num_workers > 0,
            )

        def train_dataloader(self) -> Any:
            return self._loader(self.train_data, train_batch_size, True)

        def val_dataloader(self) -> Any:
            return self._loader(self.val_data, eval_batch_size, False)

        def test_dataloader(self) -> Any:
            return self._loader(self.test_data, eval_batch_size, False)

        def predict_dataloader(self) -> Any:
            return self.test_dataloader()

    return ManifestDataModule()


def _write_preprocessing(config: dict[str, Any], destination: Path) -> None:
    preprocessing = dict(config["preprocessing"])
    write_json(destination, preprocessing)


def _predict_split(
    inferencer: Any,
    entries: list[ManifestEntry],
    dataset_root: Path,
    run_dir: Path,
    split: str,
    category: str,
) -> Path:
    predictions_path = run_dir / "predictions" / f"{split}.jsonl"
    predictions_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for entry in entries:
        image_path = dataset_root / entry.image_path
        started = time.perf_counter()
        prediction = inferencer.predict(image_path)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if prediction.pred_score is None or prediction.anomaly_map is None:
            raise RuntimeError(f"missing PatchCore outputs for {entry.image_path}")
        score = float(prediction.pred_score.detach().cpu().reshape(-1)[0].item())
        if not np.isfinite(score) or not -1e-6 <= score <= 1.0 + 1e-6:
            raise RuntimeError(f"non-normalized score {score} for {entry.image_path}")
        score = float(np.clip(score, 0.0, 1.0))
        anomaly_map = prediction.anomaly_map.detach().cpu().numpy().squeeze()
        sample_dir = run_dir / "evidence" / split / entry.sample_id
        heatmap_meta, _, _ = render_evidence(
            image_path,
            anomaly_map,
            sample_dir / "heatmap.png",
            sample_dir / "overlay.png",
        )
        record = ScoreRecord(
            sample_id=entry.sample_id,
            split=split,  # type: ignore[arg-type]
            image_path=entry.image_path,
            label=entry.label,
            anomaly_subtype=entry.anomaly_subtype,
            score=score,
            heatmap_path=str(heatmap_meta.path.resolve()),
            latency_ms=elapsed_ms,
            warm=True,
            device=str(inferencer.device),
            product_category=category,
        )
        lines.append(json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
    predictions_path.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    return predictions_path


def run_patchcore_baseline(
    config_path: Path,
    manifest_path: Path,
    manifest_meta_path: Path,
    dataset_root: Path,
    run_dir: Path,
    package_root: Path,
    repository_root: Path,
    dataset_notice_path: Path,
) -> dict[str, Any]:
    """Train, calibrate, evaluate, benchmark, and package the PatchCore baseline."""
    if run_dir.exists() and any(run_dir.iterdir()):
        raise FileExistsError(f"run directory is not empty and will not be overwritten: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    category = str(config["data"]["category"])
    verify_manifest(manifest_path, dataset_root, manifest_meta_path)
    manifest_categories = {entry.category for entry in load_manifest(manifest_path)}
    if manifest_categories != {category}:
        raise ValueError(f"training config category {category} does not match manifest categories {manifest_categories}")
    seed = int(config["seed"])
    runtime = _require_model_runtime()
    runtime["seed_everything"](seed, workers=True)
    runtime["torch"].use_deterministic_algorithms(bool(config["runtime"]["deterministic"]), warn_only=True)

    environment = runtime_environment()
    environment["anomalib_openvino_type_shim"] = runtime["openvino_type_shim"]
    commit = git_commit(repository_root)
    run_metadata = {
        "schema_version": "visionqc.model-run.v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "config_path": str(config_path.resolve()),
        "manifest_path": str(manifest_path.resolve()),
        "code_commit": commit,
        "seed": seed,
        "environment": environment,
    }
    write_json(run_dir / "run.json", run_metadata)
    preprocessing_path = run_dir / "preprocessing.json"
    _write_preprocessing(config, preprocessing_path)

    data = config["data"]
    datamodule = _build_data_module(
        runtime,
        manifest_path,
        dataset_root,
        seed,
        int(data["train_batch_size"]),
        int(data["eval_batch_size"]),
        int(data["num_workers"]),
        category,
    )
    model_config = config["model"]
    preprocessing = config["preprocessing"]
    model = runtime["Patchcore"](
        backbone=model_config["backbone"],
        layers=model_config["layers"],
        pre_trained=bool(model_config["pretrained"]),
        coreset_sampling_ratio=float(model_config["coreset_sampling_ratio"]),
        num_neighbors=int(model_config["num_neighbors"]),
        pre_processor=runtime["Patchcore"].configure_pre_processor(
            image_size=(int(preprocessing["resize"]["height"]), int(preprocessing["resize"]["width"])),
            center_crop_size=(
                int(preprocessing["center_crop"]["height"]),
                int(preprocessing["center_crop"]["width"]),
            ),
        ),
        # Keep validation-derived min/max normalization, but disable Anomalib's
        # adaptive F1 threshold. VisionQC freezes routing thresholds separately
        # under the business calibration policy below.
        post_processor=runtime["PostProcessor"](enable_thresholding=False),
        evaluator=False,
        visualizer=False,
    )
    engine = runtime["Engine"](
        default_root_dir=run_dir / "engine",
        accelerator=config["runtime"]["accelerator"],
        devices=config["runtime"]["devices"],
        deterministic=bool(config["runtime"]["deterministic"]),
        logger=False,
        enable_progress_bar=True,
    )
    engine.fit(model=model, datamodule=datamodule)
    exported_path = engine.export(
        model=model,
        export_type="torch",
        export_root=run_dir / "export",
        model_file_name="model",
    )
    if exported_path is None:
        raise RuntimeError("Anomalib did not return an exported Torch model path")

    feature_bank_path = run_dir / "feature-bank.pt"
    memory_bank = getattr(getattr(model, "model", None), "memory_bank", None)
    if memory_bank is None:
        raise RuntimeError("PatchCore fit did not produce a memory bank")
    memory_bank_tensor = memory_bank.detach().cpu()
    runtime["torch"].save({"memory_bank": memory_bank_tensor}, feature_bank_path)
    feature_bank_metadata_path = run_dir / "feature-bank.json"
    write_json(
        feature_bank_metadata_path,
        {
            "schema_version": "visionqc.feature-bank.v1",
            "model_id": model_config["id"],
            "model_version": model_config["version"],
            "category": category,
            "feature_bank_version": model_config.get("feature_bank_version"),
            "tensor_shape": list(memory_bank_tensor.shape),
            "tensor_dtype": str(memory_bank_tensor.dtype),
            "vector_count": int(memory_bank_tensor.shape[0]) if memory_bank_tensor.ndim else 0,
            "embedding_dimension": int(memory_bank_tensor.shape[-1]) if memory_bank_tensor.ndim else 0,
            "source": "Anomalib PatchCore fitted memory bank",
        },
    )

    inferencer = runtime["TorchInferencer"](path=exported_path, device="auto")
    entries = load_manifest(manifest_path)
    representative = dataset_root / next(entry.image_path for entry in entries if entry.split == "train")
    cold_started = time.perf_counter()
    inferencer.predict(representative)
    cold_ms = (time.perf_counter() - cold_started) * 1000.0
    warmup_ms: list[float] = []
    warmup_runs = int(config["performance"].get("warmup_runs", 0))
    measured_runs = int(config["performance"].get("measured_runs", max(1, warmup_runs)))
    if measured_runs < 1:
        raise ValueError("performance.measured_runs must be at least 1")
    for _ in range(warmup_runs):
        started = time.perf_counter()
        inferencer.predict(representative)
        warmup_ms.append((time.perf_counter() - started) * 1000.0)
    measured_ms: list[float] = []
    for _ in range(measured_runs):
        started = time.perf_counter()
        inferencer.predict(representative)
        measured_ms.append((time.perf_counter() - started) * 1000.0)
    write_json(
        run_dir / "performance-probe.json",
        {
            "schema_version": "visionqc.performance-probe.v1",
            "device": str(inferencer.device),
            "cold_ms": cold_ms,
            "warmup_ms": warmup_ms,
            "measured_ms": measured_ms,
            "warm_p50_ms": float(np.percentile(measured_ms, 50)) if measured_ms else None,
            "warm_p95_ms": float(np.percentile(measured_ms, 95)) if measured_ms else None,
            "warm_sample_count": len(measured_ms),
            "environment": environment,
            "input": next(entry.image_path for entry in entries if entry.split == "train"),
            "category": category,
        },
    )

    validation_predictions = _predict_split(
        inferencer,
        [entry for entry in entries if entry.split == "validation"],
        dataset_root,
        run_dir,
        "validation",
        category,
    )
    calibration_config = config["calibration"]
    policy_version = str(
        calibration_config.get(
            "policy_version",
            f"{category}-{model_config['version']}-policy",
        )
    )
    calibration = calibrate_thresholds(
        validation_predictions,
        run_dir / "calibration",
        policy_version,
        float(calibration_config["max_false_accept_rate"]),
        float(calibration_config["target_hold_recall"]),
        strategy=cast(CalibrationStrategy, str(calibration_config.get("strategy", "legacy"))),
        safety_margin=float(calibration_config.get("safety_margin", 0.0)),
    )

    test_predictions = _predict_split(
        inferencer,
        [entry for entry in entries if entry.split == "test"],
        dataset_root,
        run_dir,
        "test",
        category,
    )
    report = evaluate_predictions(
        test_predictions,
        manifest_path,
        manifest_meta_path,
        dataset_root,
        run_dir / "calibration" / "thresholds.json",
        run_dir / "evaluation",
        {
            "id": model_config["id"],
            "version": model_config["version"],
            "adapter": model_config["adapter"],
        },
        environment,
        performance_probe_path=run_dir / "performance-probe.json",
        gallery_output_dir=run_dir / "gallery",
    )
    package_dir = build_model_package(
        package_root,
        exported_path,
        config_path,
        preprocessing_path,
        run_dir / "calibration" / "thresholds.json",
        run_dir / "evaluation" / "evaluation.json",
        run_dir / "evaluation" / "evaluation.md",
        manifest_meta_path,
        dataset_notice_path,
        model_config["id"],
        model_config["version"],
        commit,
        dependency_lock_path=Path(__file__).resolve().parents[2] / "uv.lock",
        runtime_notice_path=Path(__file__).resolve().parents[2] / "licenses" / "MODEL-RUNTIME-NOTICE.md",
        feature_bank_path=feature_bank_path,
        feature_bank_metadata_path=feature_bank_metadata_path,
        feature_bank_version=model_config.get("feature_bank_version"),
    )
    package_manifest = verify_model_package(package_dir)
    summary = {
        "run_dir": str(run_dir.resolve()),
        "package_dir": str(package_dir.resolve()),
        "package_sha256": package_manifest.package_sha256,
        "dataset_fingerprint": package_manifest.dataset_fingerprint,
        "category": category,
        "feature_bank_version": package_manifest.feature_bank_version,
        "review_threshold": calibration.review_threshold,
        "hold_threshold": calibration.hold_threshold,
        "constraints_satisfied": calibration.constraints_satisfied,
        "image_auroc": report["metrics"]["image_level"]["auroc"],
        "pixel_auroc": report["metrics"]["pixel_level"]["auroc"],
        "warm_p95_ms": report["metrics"]["performance"]["p95_ms"],
        "cold_ms": report["metrics"]["performance"].get("cold_ms"),
        "claim_boundary": "anomaly and anomalous-region evidence only",
    }
    write_json(run_dir / "summary.json", summary)
    return summary
