from __future__ import annotations

import io
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps


class ModelUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelOutput:
    score: float
    heatmap_png: bytes
    model_id: str
    model_version: str
    feature_bank_version: str
    runtime_device: str
    latency_ms: int


class ModelAdapter(ABC):
    @abstractmethod
    def infer(self, image_bytes: bytes) -> ModelOutput:
        raise NotImplementedError

    @abstractmethod
    def healthcheck(self) -> bool:
        raise NotImplementedError


class StubModelAdapter(ModelAdapter):
    """Deterministic adapter: darker images receive higher anomaly scores."""

    def __init__(self, *, available: bool = True):
        self.available = available
        self.calls = 0

    def infer(self, image_bytes: bytes) -> ModelOutput:
        if not self.available:
            raise ModelUnavailable("stub model is unavailable")
        self.calls += 1
        started = time.perf_counter()
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        grayscale = ImageOps.grayscale(image)
        histogram = grayscale.histogram()
        luminance_total = sum(value * count for value, count in enumerate(histogram))
        mean_luminance = luminance_total / (grayscale.width * grayscale.height * 255)
        score = round(max(0.0, min(1.0, 1.0 - mean_luminance)), 6)
        heatmap = ImageOps.colorize(grayscale, black="#ff0000", white="#000000")
        output = io.BytesIO()
        heatmap.save(output, format="PNG")
        latency_ms = max(1, int((time.perf_counter() - started) * 1000))
        return ModelOutput(
            score=score,
            heatmap_png=output.getvalue(),
            model_id="stub-anomaly-adapter",
            model_version="1.0.0",
            feature_bank_version="stub-fb-1",
            runtime_device="cpu",
            latency_ms=latency_ms,
        )

    def healthcheck(self) -> bool:
        return self.available


class PatchCoreModelAdapter(ModelAdapter):
    """Adapter for a verified ``visionqc-ml`` model package.

    The import is intentionally lazy so the default demo image remains small.
    Production-like deployments install ``visionqc-ml[model]`` and provide a
    verified package through ``VQC_MODEL_PACKAGE_PATH``.
    """

    def __init__(self, package_path: Path, *, device: str = "auto") -> None:
        try:
            from visionqc_ml.inference import (  # type: ignore[import-not-found]
                VisionQCInferenceService,
            )
        except ImportError as exc:
            raise ModelUnavailable(
                "patchcore backend requires the visionqc-ml model runtime"
            ) from exc
        try:
            self._service: Any = VisionQCInferenceService.from_package(
                package_path.resolve(), device=device
            )
        except Exception as exc:
            raise ModelUnavailable(f"unable to load verified model package: {exc}") from exc

    def infer(self, image_bytes: bytes) -> ModelOutput:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="visionqc-inference-") as directory:
            root = Path(directory)
            image_path = root / "input.png"
            try:
                image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
                image.save(image_path, format="PNG")
                result = self._service.infer(image_path, "online", root / "evidence")
                heatmap_png = Path(result.anomaly.heatmap.uri).read_bytes()
            except Exception as exc:
                raise ModelUnavailable(f"patchcore inference failed: {type(exc).__name__}") from exc
        latency_ms = max(1, int((time.perf_counter() - started) * 1000))
        return ModelOutput(
            score=float(result.anomaly.score),
            heatmap_png=heatmap_png,
            model_id=result.model.id,
            model_version=result.model.version,
            feature_bank_version=result.model.feature_bank_version,
            runtime_device=result.model.device,
            latency_ms=latency_ms,
        )

    def healthcheck(self) -> bool:
        try:
            return bool(self._service.health().get("ready"))
        except Exception:
            return False


def build_model_adapter(*, backend: str, package_path: Path | None, device: str) -> ModelAdapter:
    if backend == "patchcore":
        if package_path is None:
            raise ModelUnavailable("patchcore backend requires a model package path")
        return PatchCoreModelAdapter(package_path, device=device)
    return StubModelAdapter()
