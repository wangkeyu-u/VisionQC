from __future__ import annotations

import io

import pytest
from PIL import Image, ImageDraw, ImageFilter

from edge_gateway.quality import QualityReject, assess_image


def sample_image(kind: str) -> bytes:
    image = Image.new("RGB", (128, 96), (70, 110, 90))
    draw = ImageDraw.Draw(image)
    draw.rectangle((12, 12, 116, 84), fill=(170, 190, 165), outline=(245, 245, 230), width=4)
    draw.line((20, 48, 108, 48), fill=(20, 40, 30), width=7)
    if kind == "dark":
        image = Image.new("RGB", image.size, (5, 8, 6))
    elif kind == "overexposed":
        image = Image.new("RGB", image.size, (255, 255, 255))
    elif kind == "blurry":
        image = image.filter(ImageFilter.GaussianBlur(10))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_quality_gate_accepts_a_clear_png(gateway_settings) -> None:
    result = assess_image(sample_image("normal"), "sample.png", gateway_settings)
    assert result.mime_type == "image/png"
    assert result.width == 128
    assert result.metrics["sharpness"] >= gateway_settings.min_sharpness


@pytest.mark.parametrize(
    ("kind", "code"),
    [("dark", "TOO_DARK"), ("overexposed", "OVEREXPOSED"), ("blurry", "BLURRY")],
)
def test_quality_gate_records_operational_rejection_reason(gateway_settings, kind, code) -> None:
    with pytest.raises(QualityReject) as caught:
        assess_image(sample_image(kind), f"{kind}.png", gateway_settings)
    assert caught.value.code == code
    assert caught.value.reason


def test_quality_gate_rejects_corrupt_and_mismatched_payload(gateway_settings) -> None:
    with pytest.raises(QualityReject, match="安全解码") as corrupt:
        assess_image(b"not-an-image", "capture.png", gateway_settings)
    assert corrupt.value.code == "SECURITY_DECODE_FAILED"

    with pytest.raises(QualityReject) as mismatch:
        assess_image(sample_image("normal"), "capture.jpg", gateway_settings)
    assert mismatch.value.code == "FORMAT_MISMATCH"
