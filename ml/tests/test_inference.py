from __future__ import annotations

from pathlib import Path

import numpy as np

from conftest import write_rgb
from test_package import build_fake_package
from visionqc_ml.inference import BackendPrediction, VisionQCInferenceService
from visionqc_ml.schemas import PolicyDecision


class FakeBackend:
    def __init__(self, score: float) -> None:
        self.score = score
        self.calls = 0

    def predict(self, image_path: Path) -> BackendPrediction:
        assert image_path.is_file()
        self.calls += 1
        anomaly_map = np.linspace(0, 1, 16 * 16, dtype=np.float32).reshape(16, 16)
        return BackendPrediction(self.score, anomaly_map, 12.5, "fake-cpu")


def test_inference_writes_contract_heatmap_and_overlay(tmp_path: Path) -> None:
    package = build_fake_package(tmp_path)
    image = tmp_path / "input.png"
    write_rgb(image, 80)
    backend = FakeBackend(0.85)
    service = VisionQCInferenceService(package, backend)
    service.warmup(image, runs=2)
    result = service.infer(image, "insp_001", tmp_path / "outputs")

    assert result.policy.decision == PolicyDecision.BATCH_HOLD_AND_REVIEW
    assert result.anomaly.semantic_defect_confirmed is False
    assert result.anomaly.root_cause_confirmed is False
    assert result.latency.warm is True
    assert Path(result.anomaly.heatmap.uri).is_file()
    assert Path(result.anomaly.overlay.uri).is_file()  # type: ignore[union-attr]
    assert (tmp_path / "outputs" / "insp_001" / "result.json").is_file()
    assert backend.calls == 3

