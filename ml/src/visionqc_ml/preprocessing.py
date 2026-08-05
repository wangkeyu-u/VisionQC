"""Deterministic image validation, preprocessing, and evidence rendering."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, UnidentifiedImageError

from .errors import InferenceInputError
from .hashing import sha256_file


@dataclass(frozen=True)
class ImageMetadata:
    path: Path
    sha256: str
    mime_type: str
    width: int
    height: int


def validate_image(path: Path, constraints: dict[str, Any]) -> ImageMetadata:
    """Decode an image and enforce type, dimension, and pixel-count limits."""
    if not path.is_file():
        raise InferenceInputError(f"image does not exist: {path}")
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = image.format
    except (UnidentifiedImageError, OSError) as exc:
        raise InferenceInputError(f"image cannot be decoded: {path}") from exc

    mime_by_format = {"JPEG": "image/jpeg", "PNG": "image/png"}
    if image_format not in mime_by_format:
        raise InferenceInputError(f"unsupported image format: {image_format}")
    if width < int(constraints["min_width"]) or height < int(constraints["min_height"]):
        raise InferenceInputError(f"image dimensions {width}x{height} are below configured minimum")
    if width * height > int(constraints["max_pixels"]):
        raise InferenceInputError(f"image dimensions {width}x{height} exceed configured pixel limit")
    return ImageMetadata(path, sha256_file(path), mime_by_format[image_format], width, height)


def preprocess_image(path: Path, config: dict[str, Any]) -> np.ndarray:
    """Apply the fixed PatchCore preprocessing and return float32 CHW pixels."""
    resize = config["resize"]
    crop = config["center_crop"]
    interpolation = str(resize["interpolation"]).lower()
    interpolation_modes = {
        "nearest": Image.Resampling.NEAREST,
        "bilinear": Image.Resampling.BILINEAR,
        "bicubic": Image.Resampling.BICUBIC,
    }
    if interpolation not in interpolation_modes:
        raise ValueError(f"unsupported interpolation: {interpolation}")

    with Image.open(path) as source:
        image = source.convert("RGB")
        image = image.resize(
            (int(resize["width"]), int(resize["height"])),
            resample=interpolation_modes[interpolation],
        )
        crop_width, crop_height = int(crop["width"]), int(crop["height"])
        left = (image.width - crop_width) // 2
        top = (image.height - crop_height) // 2
        if left < 0 or top < 0:
            raise ValueError("center crop cannot be larger than resized image")
        image = image.crop((left, top, left + crop_width, top + crop_height))
        pixels = np.asarray(image, dtype=np.float32) / np.float32(255.0)

    mean = np.asarray(config["normalize"]["mean"], dtype=np.float32)
    std = np.asarray(config["normalize"]["std"], dtype=np.float32)
    normalized = (pixels - mean) / std
    return np.ascontiguousarray(normalized.transpose(2, 0, 1), dtype=np.float32)


def _heat_colors(values: np.ndarray) -> np.ndarray:
    """Create a compact blue-to-red heat palette without a plotting dependency."""
    clipped = np.clip(values, 0.0, 1.0)
    red = np.clip(1.5 - np.abs(4.0 * clipped - 3.0), 0.0, 1.0)
    green = np.clip(1.5 - np.abs(4.0 * clipped - 2.0), 0.0, 1.0)
    blue = np.clip(1.5 - np.abs(4.0 * clipped - 1.0), 0.0, 1.0)
    return np.stack((red, green, blue), axis=-1)


def render_evidence(
    source_path: Path,
    anomaly_map: np.ndarray,
    heatmap_path: Path,
    overlay_path: Path,
    alpha: float = 0.45,
) -> tuple[ImageMetadata, ImageMetadata, float]:
    """Write normalized grayscale heatmap and RGB overlay at source resolution."""
    started = time.perf_counter()
    values = np.asarray(anomaly_map, dtype=np.float32).squeeze()
    if values.ndim != 2 or not np.isfinite(values).all():
        raise ValueError("anomaly map must be a finite 2D array")
    values = np.clip(values, 0.0, 1.0)

    with Image.open(source_path) as source:
        original = source.convert("RGB")
        map_image = Image.fromarray(np.rint(values * 255.0).astype(np.uint8), mode="L")
        map_image = map_image.resize(original.size, resample=Image.Resampling.BILINEAR)
        resized_values = np.asarray(map_image, dtype=np.float32) / np.float32(255.0)
        colors = Image.fromarray(np.rint(_heat_colors(resized_values) * 255.0).astype(np.uint8), mode="RGB")
        overlay = Image.blend(original, colors, alpha=alpha)

    heatmap_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    map_image.save(heatmap_path, format="PNG", optimize=False)
    overlay.save(overlay_path, format="PNG", optimize=False)

    heatmap_meta = ImageMetadata(heatmap_path, sha256_file(heatmap_path), "image/png", *map_image.size)
    overlay_meta = ImageMetadata(overlay_path, sha256_file(overlay_path), "image/png", *overlay.size)
    return heatmap_meta, overlay_meta, (time.perf_counter() - started) * 1000.0

