from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from conftest import write_rgb
from visionqc_ml.errors import InferenceInputError
from visionqc_ml.preprocessing import preprocess_image, validate_image

PREPROCESSING = {
    "resize": {"width": 32, "height": 32, "interpolation": "bilinear", "antialias": True},
    "center_crop": {"width": 24, "height": 24},
    "normalize": {"mean": [0.485, 0.456, 0.406], "std": [0.229, 0.224, 0.225]},
}


def test_preprocessing_is_byte_deterministic(tmp_path: Path) -> None:
    image = tmp_path / "input.png"
    write_rgb(image, 90)
    first = preprocess_image(image, PREPROCESSING)
    second = preprocess_image(image, PREPROCESSING)
    assert first.shape == (3, 24, 24)
    assert first.dtype == np.float32
    assert first.tobytes() == second.tobytes()


def test_input_constraints_reject_small_and_corrupt_images(tmp_path: Path) -> None:
    constraints = {"min_width": 32, "min_height": 32, "max_pixels": 10_000}
    small = tmp_path / "small.png"
    write_rgb(small, 0, size=(16, 16))
    with pytest.raises(InferenceInputError, match="below configured minimum"):
        validate_image(small, constraints)
    corrupt = tmp_path / "corrupt.png"
    corrupt.write_bytes(b"not an image")
    with pytest.raises(InferenceInputError, match="cannot be decoded"):
        validate_image(corrupt, constraints)

