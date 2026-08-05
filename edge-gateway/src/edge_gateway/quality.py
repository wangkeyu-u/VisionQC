from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass
from statistics import fmean, pvariance
from typing import Any

from PIL import Image, UnidentifiedImageError

from edge_gateway.config import GatewaySettings


class QualityReject(ValueError):
    """A deterministic, auditable input quality rejection."""

    def __init__(self, code: str, reason: str, metrics: dict[str, Any] | None = None):
        super().__init__(reason)
        self.code = code
        self.reason = reason
        self.metrics = metrics or {}


@dataclass(frozen=True)
class QualityAssessment:
    data: bytes
    sha256: str
    mime_type: str
    extension: str
    width: int
    height: int
    metrics: dict[str, float]


def _sample_grayscale(image: Image.Image) -> list[int]:
    gray = image.convert("L")
    max_side = 256
    if max(gray.size) > max_side:
        scale = max_side / max(gray.size)
        gray = gray.resize(
            (max(2, int(gray.width * scale)), max(2, int(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    get_flattened_data = getattr(gray, "get_flattened_data", None)
    pixels = get_flattened_data() if callable(get_flattened_data) else gray.getdata()
    return [int(value) for value in pixels]


def _image_metrics(image: Image.Image) -> dict[str, float]:
    gray = image.convert("L")
    if max(gray.size) > 256:
        scale = 256 / max(gray.size)
        gray = gray.resize(
            (max(2, int(gray.width * scale)), max(2, int(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    pixels = _sample_grayscale(gray)
    width, height = gray.size
    horizontal: list[float] = []
    vertical: list[float] = []
    for y in range(height):
        row_offset = y * width
        for x in range(width - 1):
            horizontal.append(abs(pixels[row_offset + x] - pixels[row_offset + x + 1]))
    for y in range(height - 1):
        row_offset = y * width
        next_offset = (y + 1) * width
        for x in range(width):
            vertical.append(abs(pixels[row_offset + x] - pixels[next_offset + x]))
    edges = horizontal + vertical
    mean_luminance = fmean(pixels) if pixels else 0.0
    return {
        "mean_luminance": round(mean_luminance, 4),
        "dark_pixel_ratio": round(sum(value <= 12 for value in pixels) / max(1, len(pixels)), 6),
        "overexposed_pixel_ratio": round(
            sum(value >= 250 for value in pixels) / max(1, len(pixels)), 6
        ),
        # Edge energy is deliberately simple and dependency-free.  It is a
        # gate, not a model feature, and is logged so an operator can tune it.
        "sharpness": round(fmean(edges) if edges else 0.0, 4),
        "sharpness_variance": round(pvariance(edges) if len(edges) > 1 else 0.0, 4),
    }


def assess_image(data: bytes, filename: str, settings: GatewaySettings) -> QualityAssessment:
    """Validate format, decoding safety, dimensions, focus and illumination."""

    if not data:
        raise QualityReject("EMPTY_FILE", "文件为空，未进入上传队列。")
    if len(data) > settings.max_upload_bytes:
        raise QualityReject(
            "FILE_TOO_LARGE",
            "文件超过网关配置的字节上限，已隔离。",
            {"bytes": len(data), "max_bytes": settings.max_upload_bytes},
        )

    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    extension_to_mime = {
        "png": ("PNG", "image/png"),
        "jpg": ("JPEG", "image/jpeg"),
        "jpeg": ("JPEG", "image/jpeg"),
    }
    if suffix not in extension_to_mime:
        raise QualityReject("UNSUPPORTED_FORMAT", "仅允许 PNG/JPEG 文件。", {"extension": suffix})

    expected_format, mime_type = extension_to_mime[suffix]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                detected_format = image.format
                width, height = image.size
                if width <= 0 or height <= 0 or width * height > settings.max_image_pixels:
                    raise QualityReject(
                        "IMAGE_DIMENSIONS_UNSAFE",
                        "图像尺寸或像素总数超过安全上限。",
                        {
                            "width": width,
                            "height": height,
                            "max_pixels": settings.max_image_pixels,
                        },
                    )
                image.load()
                metrics = _image_metrics(image)
    except QualityReject:
        raise
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombWarning,
        Image.DecompressionBombError,
    ) as exc:
        raise QualityReject(
            "SECURITY_DECODE_FAILED",
            "图像无法安全解码，未进入正式上传区。",
            {"decoder_error": type(exc).__name__},
        ) from exc

    if detected_format != expected_format:
        raise QualityReject(
            "FORMAT_MISMATCH",
            "文件扩展名与实际图像格式不一致。",
            {"declared_extension": suffix, "detected_format": detected_format},
        )
    if width < settings.min_width or height < settings.min_height:
        raise QualityReject(
            "IMAGE_TOO_SMALL",
            "图像尺寸低于工位采集的最小要求。",
            {
                "width": width,
                "height": height,
                "min_width": settings.min_width,
                "min_height": settings.min_height,
            },
        )
    if metrics["mean_luminance"] <= settings.dark_mean_threshold:
        raise QualityReject(
            "TOO_DARK",
            "图像整体过暗，无法可靠进行视觉检测。",
            metrics,
        )
    if (
        metrics["mean_luminance"] >= settings.overexposed_mean_threshold
        or metrics["overexposed_pixel_ratio"] >= settings.overexposed_pixel_ratio
    ):
        raise QualityReject(
            "OVEREXPOSED",
            "图像存在过曝或大面积饱和区域，无法可靠进行视觉检测。",
            metrics,
        )
    if metrics["sharpness"] < settings.min_sharpness:
        raise QualityReject(
            "BLURRY",
            "图像清晰度低于工位门禁阈值，已隔离等待复查。",
            metrics,
        )

    return QualityAssessment(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        mime_type=mime_type,
        extension="jpg" if suffix in {"jpg", "jpeg"} else "png",
        width=width,
        height=height,
        metrics=metrics,
    )
