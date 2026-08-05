"""Validated human-feedback inputs for offline re-evaluation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import Field

from .hashing import sha256_file, sha256_json, write_json
from .schemas import StrictModel


class ModelFeedbackRecord(StrictModel):
    """One reviewer observation; it never mutates a model or threshold."""

    schema_version: Literal["visionqc.model-feedback.v1"] = "visionqc.model-feedback.v1"
    feedback_id: str = Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")
    product_category: str = Field(min_length=1)
    inspection_id: str = Field(min_length=1)
    image_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    image_uri: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    model_feedback: Literal["FALSE_POSITIVE", "SUSPECTED_FALSE_NEGATIVE", "CONFIRMED_NORMAL", "CONFIRMED_ANOMALY", "INCONCLUSIVE"]
    reviewer_id: str = Field(min_length=1)
    reviewer_decision: Literal["PASS", "REWORK", "SCRAP", "INVESTIGATE", "UNABLE_TO_JUDGE"]
    observed_at: str
    notes: str = ""


def load_feedback(path: Path, *, product_category: str | None = None) -> list[ModelFeedbackRecord]:
    """Load and validate JSONL feedback without reading image contents."""
    if not path.is_file():
        raise FileNotFoundError(path)
    records: list[ModelFeedbackRecord] = []
    seen_ids: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = ModelFeedbackRecord.model_validate_json(line)
        except Exception as exc:
            raise ValueError(f"invalid feedback line {line_number}: {exc}") from exc
        if record.feedback_id in seen_ids:
            raise ValueError(f"duplicate feedback_id: {record.feedback_id}")
        if product_category is not None and record.product_category != product_category:
            raise ValueError(
                f"feedback category mismatch: expected {product_category}, got {record.product_category}"
            )
        seen_ids.add(record.feedback_id)
        records.append(record)
    if not records:
        raise ValueError(f"no feedback records in {path}")
    return records


def write_feedback_re_evaluation_input(
    records: list[ModelFeedbackRecord],
    output_dir: Path,
    *,
    source: str = "human_review",
) -> dict[str, object]:
    """Write a stable input contract for a later offline re-evaluation."""
    if not records:
        raise ValueError("feedback input must contain at least one record")
    categories = {record.product_category for record in records}
    if len(categories) != 1:
        raise ValueError(f"feedback input must contain exactly one product category: {categories}")
    output_dir.mkdir(parents=True, exist_ok=True)
    feedback_path = output_dir / "feedback.jsonl"
    lines = [json.dumps(record.model_dump(mode="json"), sort_keys=True, separators=(",", ":")) for record in records]
    feedback_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    meta = {
        "schema_version": "visionqc.feedback-re-evaluation-input.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "product_category": next(iter(categories)),
        "record_count": len(records),
        "feedback_sha256": sha256_file(feedback_path),
        "feedback_fingerprint": sha256_json([record.model_dump(mode="json") for record in records]),
        "use": "offline evaluation input only; requires a new frozen manifest and human approval before model changes",
    }
    write_json(output_dir / "feedback-meta.json", meta)
    return meta


def feedback_json_schema() -> dict[str, object]:
    return ModelFeedbackRecord.model_json_schema()
