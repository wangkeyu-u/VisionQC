from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image


def write_rgb(path: Path, value: int, size: tuple[int, int] = (48, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.full((size[1], size[0], 3), value, dtype=np.uint8)
    array[8:16, 10:22, 0] = min(255, value + 30)
    Image.fromarray(array, mode="RGB").save(path)


def write_mask(path: Path, size: tuple[int, int] = (48, 40)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    array = np.zeros((size[1], size[0]), dtype=np.uint8)
    array[8:16, 10:22] = 255
    Image.fromarray(array, mode="L").save(path)


@pytest.fixture
def synthetic_dataset(tmp_path: Path) -> Path:
    root = tmp_path / "dataset"
    for index in range(4):
        write_rgb(root / "transistor" / "train" / "good" / f"{index:03d}.png", 30 + index)
        write_rgb(root / "transistor" / "test" / "good" / f"{index:03d}.png", 40 + index)
    for subtype_index, subtype in enumerate(("bent_lead", "damaged_case")):
        for index in range(4):
            write_rgb(
                root / "transistor" / "test" / subtype / f"{index:03d}.png",
                120 + subtype_index * 20 + index,
            )
            write_mask(root / "transistor" / "ground_truth" / subtype / f"{index:03d}_mask.png")
    return root

