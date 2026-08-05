"""PatchCore inference adapter and backend-facing VisionQC result assembly."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .compat import ensure_anomalib_torch_importable
from .errors import ModelRuntimeUnavailable
from .hashing import read_json, write_json
from .package import verify_model_package
from .policy import ThresholdPolicy
from .preprocessing import render_evidence, validate_image
from .schemas import (
    AnomalyEvidence,
    ImageReference,
    InferenceResult,
    InputReference,
    LatencyEvidence,
    ModelReference,
    PolicyEvidence,
)


@dataclass(frozen=True)
class BackendPrediction:
    """Minimal model-specific output before VisionQC contract conversion."""

    score: float
    anomaly_map: np.ndarray
    inference_ms: float
    device: str


class AnomalyBackend(Protocol):
    """Injectable backend interface used by tests and online workers."""

    def predict(self, image_path: Path) -> BackendPrediction:
        """Return normalized anomaly evidence for one image."""


class AnomalibTorchBackend:
    """Minimal adapter over Anomalib 2.0 TorchInferencer."""

    def __init__(self, model_path: Path, device: str = "auto") -> None:
        ensure_anomalib_torch_importable()
        try:
            import torch
            from anomalib.deploy import TorchInferencer
        except ImportError as exc:
            raise ModelRuntimeUnavailable(
                "Anomalib runtime is unavailable; install with `uv sync --extra model`"
            ) from exc
        self._torch = torch
        self._inferencer = TorchInferencer(path=model_path, device=device)
        self.device = str(self._inferencer.device)

    def predict(self, image_path: Path) -> BackendPrediction:
        started = time.perf_counter()
        with self._torch.inference_mode():
            prediction = self._inferencer.predict(image_path)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if prediction.pred_score is None or prediction.anomaly_map is None:
            raise RuntimeError("PatchCore output is missing pred_score or anomaly_map")
        score = float(prediction.pred_score.detach().cpu().reshape(-1)[0].item())
        anomaly_map = prediction.anomaly_map.detach().cpu().numpy().squeeze()
        return BackendPrediction(score, anomaly_map, elapsed_ms, self.device)


class VisionQCInferenceService:
    """Verified model package loader with deterministic policy and evidence output."""

    def __init__(self, package_dir: Path, backend: AnomalyBackend, expected_category: str | None = None) -> None:
        self.package_dir = package_dir
        self.package_manifest = verify_model_package(package_dir, expected_category=expected_category)
        self.backend = backend
        self.preprocessing = read_json(package_dir / "config" / "preprocessing.json")
        thresholds = read_json(package_dir / "config" / "thresholds.json")
        self.policy = ThresholdPolicy(
            version=thresholds["policy_version"],
            review_threshold=float(thresholds["review_threshold"]),
            hold_threshold=float(thresholds["hold_threshold"]),
        )
        self.metadata = read_json(package_dir / "metadata.json")
        self._warm = False

    @classmethod
    def from_package(
        cls,
        package_dir: Path,
        device: str = "auto",
        expected_category: str | None = None,
    ) -> VisionQCInferenceService:
        """Verify a package before loading its Anomalib model."""
        verify_model_package(package_dir, expected_category=expected_category)
        backend = AnomalibTorchBackend(package_dir / "weights" / "model.pt", device=device)
        return cls(package_dir, backend, expected_category=expected_category)

    def warmup(self, image_path: Path, runs: int = 3) -> list[float]:
        """Warm the model using a valid representative image and return run timings."""
        if runs < 1:
            raise ValueError("warmup runs must be positive")
        validate_image(image_path, self.preprocessing["input_constraints"])
        timings = [self.backend.predict(image_path).inference_ms for _ in range(runs)]
        self._warm = True
        return timings

    def health(self) -> dict[str, Any]:
        """Return package/runtime readiness without claiming model accuracy."""
        return {
            "ready": True,
            "model_id": self.package_manifest.model_id,
            "model_version": self.package_manifest.model_version,
            "category": self.package_manifest.category,
            "package_sha256": self.package_manifest.package_sha256,
            "warm": self._warm,
        }

    def infer(self, image_path: Path, inspection_id: str, output_dir: Path) -> InferenceResult:
        """Run one image and persist JSON, heatmap, and overlay evidence."""
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", inspection_id):
            raise ValueError("inspection_id contains unsafe characters")
        total_started = time.perf_counter()
        preprocess_started = time.perf_counter()
        image_meta = validate_image(image_path, self.preprocessing["input_constraints"])
        preprocess_ms = (time.perf_counter() - preprocess_started) * 1000.0
        prediction = self.backend.predict(image_path)
        if not np.isfinite(prediction.score) or prediction.score < -1e-6 or prediction.score > 1.0 + 1e-6:
            raise RuntimeError(f"model returned a non-normalized anomaly score: {prediction.score}")
        score = float(np.clip(prediction.score, 0.0, 1.0))
        decision, reason = self.policy.route(score)

        evidence_dir = output_dir / inspection_id
        heatmap_meta, overlay_meta, postprocess_ms = render_evidence(
            image_path,
            prediction.anomaly_map,
            evidence_dir / "heatmap.png",
            evidence_dir / "overlay.png",
        )
        total_ms = (time.perf_counter() - total_started) * 1000.0
        result = InferenceResult(
            inspection_id=inspection_id,
            model=ModelReference(
                id=self.package_manifest.model_id,
                version=self.package_manifest.model_version,
                feature_bank_version=self.package_manifest.feature_bank_version,
                package_sha256=self.package_manifest.package_sha256,
                runtime="anomalib==2.0.0",
                device=prediction.device,
            ),
            input=InputReference(
                uri=str(image_path.resolve()),
                sha256=image_meta.sha256,
                mime_type=image_meta.mime_type,  # type: ignore[arg-type]
                width=image_meta.width,
                height=image_meta.height,
            ),
            anomaly=AnomalyEvidence(
                score=score,
                heatmap=ImageReference(
                    uri=str(heatmap_meta.path.resolve()),
                    sha256=heatmap_meta.sha256,
                    width=heatmap_meta.width,
                    height=heatmap_meta.height,
                ),
                overlay=ImageReference(
                    uri=str(overlay_meta.path.resolve()),
                    sha256=overlay_meta.sha256,
                    width=overlay_meta.width,
                    height=overlay_meta.height,
                ),
            ),
            policy=PolicyEvidence(
                version=self.policy.version,
                review_threshold=self.policy.review_threshold,
                hold_threshold=self.policy.hold_threshold,
                decision=decision,
                reason=reason,
            ),
            latency=LatencyEvidence(
                preprocess_ms=preprocess_ms,
                inference_ms=prediction.inference_ms,
                postprocess_ms=postprocess_ms,
                total_ms=total_ms,
                warm=self._warm,
            ),
            warnings=["Model output is anomaly evidence, not a confirmed semantic defect or root cause."],
        )
        write_json(evidence_dir / "result.json", result.model_dump(mode="json"))
        return result
