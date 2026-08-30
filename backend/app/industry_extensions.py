"""Optional industry adapters kept outside the VisionQC core domain.

The automotive-paint payload here exists only to preserve compatibility with
the explicitly simulated DXQ contract.  None of these identifiers are
required by :class:`InspectionContext`, :class:`Workpiece`, or a generic
quality case.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

AUTOMOTIVE_PAINT_NAMESPACE = "automotive-paint"
AUTOMOTIVE_PAINT_FIELDS = (
    "body_id",
    "workpiece_id",
    "paint_shop",
    "booth_station",
    "line",
    "model_variant",
    "color_code",
    "paint_recipe",
    "shift",
)


def automotive_paint_extension(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return only supplied automotive-paint extension values.

    Legacy clients submit a flat metadata object; the preferred contract uses
    ``metadata.extensions.automotive-paint``.  The adapter accepts both while
    never inventing an automotive identifier when it is absent.
    """

    namespaced = metadata.get("extensions")
    if isinstance(namespaced, Mapping):
        candidate = namespaced.get(AUTOMOTIVE_PAINT_NAMESPACE)
        if isinstance(candidate, Mapping):
            return {
                key: value
                for key, value in candidate.items()
                if key in AUTOMOTIVE_PAINT_FIELDS and value is not None and str(value).strip()
            }
    return {
        key: metadata[key]
        for key in AUTOMOTIVE_PAINT_FIELDS
        if key in metadata and metadata[key] is not None and str(metadata[key]).strip()
    }


def build_simulated_quality_record(
    *,
    metadata: Mapping[str, Any],
    inspection_id: str,
    batch_no: str,
    station_code: str,
    captured_at: str,
    severity: str,
    disposition: str,
    quality_case_id: str,
    reason: str,
    heatmap: Any,
) -> dict[str, Any]:
    """Build the backward-compatible simulated quality record.

    Core values are generic references.  Automotive-paint values are copied
    only from the extension namespace (or the legacy flat shape).
    """

    extension = automotive_paint_extension(metadata)
    payload: dict[str, Any] = {
        **extension,
        "workpiece_id": extension.get("workpiece_id", metadata.get("workpiece_id")),
        "timestamp": captured_at,
        "visual_defect_type": str(metadata.get("visual_defect_type") or "UNCONFIRMED_ANOMALY"),
        "severity": severity,
        "mask_or_heatmap": heatmap,
        "operator_decision": disposition,
        "equipment_alarm_refs": _metadata_list(metadata, "equipment_alarm_refs"),
        "process_parameter_refs": _metadata_list(metadata, "process_parameter_refs"),
        "root_cause_candidates": _metadata_list(
            metadata, "root_cause_candidates", fallback=["PENDING_INVESTIGATION"]
        ),
        "disposition": disposition,
        "quality_case_id": quality_case_id,
        "review_reason": reason,
    }
    # Keep generic references available to an adapter that maps them, without
    # treating them as automotive fields.
    payload.setdefault("inspection_id", inspection_id)
    payload.setdefault("batch_no", batch_no)
    payload.setdefault("station_code", station_code)
    return {key: value for key, value in payload.items() if value is not None}


def _metadata_list(
    metadata: Mapping[str, Any], key: str, fallback: list[str] | None = None
) -> list[Any]:
    value = metadata.get(key)
    if isinstance(value, list):
        return value
    return list(fallback or [])


__all__ = [
    "AUTOMOTIVE_PAINT_FIELDS",
    "AUTOMOTIVE_PAINT_NAMESPACE",
    "automotive_paint_extension",
    "build_simulated_quality_record",
]
