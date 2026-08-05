"""Backend-side verification of ML qualification evidence packages."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

REQUIRED_EVIDENCE_FILES = {
    "qualification-summary.json",
    "model-card.md",
    "evaluation-report.md",
    "metrics.json",
    "confidence-intervals.json",
    "split-manifest.json",
    "provenance.json",
    "release-decision.json",
    "error-cases.json",
    "source-evidence.json",
    "evidence-manifest.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def verify_evidence_package(
    path: Path, *, expected_model_package_sha256: str | None = None
) -> dict[str, Any]:
    if not path.is_dir() or not REQUIRED_EVIDENCE_FILES.issubset(
        {item.name for item in path.iterdir() if item.is_file()}
    ):
        raise ValueError("qualification evidence package is incomplete")
    inventory = json.loads((path / "evidence-manifest.json").read_text(encoding="utf-8"))
    if inventory.get("schema_version") != "visionqc.evidence-manifest.v1":
        raise ValueError("qualification evidence manifest schema is invalid")
    expected_inventory = {
        item.name: {"sha256": _sha256(item), "size_bytes": item.stat().st_size}
        for item in sorted(path.iterdir())
        if item.is_file() and item.name != "evidence-manifest.json"
    }
    declared_inventory = inventory.get("files")
    if not isinstance(declared_inventory, dict) or set(declared_inventory) != set(
        expected_inventory
    ):
        raise ValueError("qualification evidence inventory does not cover the complete package")
    for relative, details in inventory.get("files", {}).items():
        candidate_path = Path(relative)
        if (
            candidate_path.is_absolute()
            or candidate_path.name != relative
            or candidate_path.parent != Path(".")
        ):
            raise ValueError(
                f"qualification evidence inventory contains an unsafe path: {relative}"
            )
        candidate = path / relative
        if (
            not candidate.is_file()
            or _sha256(candidate) != details.get("sha256")
            or candidate.stat().st_size != details.get("size_bytes")
        ):
            raise ValueError(f"qualification evidence file mismatch: {relative}")
    provenance = json.loads((path / "provenance.json").read_text(encoding="utf-8"))
    if provenance.get("model_package_sha256") != expected_model_package_sha256:
        raise ValueError("qualification evidence model package digest mismatch")
    release = json.loads((path / "release-decision.json").read_text(encoding="utf-8"))
    core_files = {
        item.name: {"sha256": _sha256(item), "size_bytes": item.stat().st_size}
        for item in sorted(path.iterdir())
        if item.is_file() and item.name not in {"release-decision.json", "evidence-manifest.json"}
    }
    core_digest = _sha256_json(core_files)
    if release.get("evidence_package_sha256") != core_digest:
        raise ValueError("qualification evidence package digest mismatch")
    metrics = json.loads((path / "metrics.json").read_text(encoding="utf-8"))
    summary = json.loads((path / "qualification-summary.json").read_text(encoding="utf-8"))
    if release.get("decision") != summary.get("qualification_status"):
        raise ValueError("qualification summary decision does not match release decision")
    if release.get("decision") != metrics.get("gates", {}).get("decision"):
        if release.get("decision") != metrics.get("gates", {}).get("report_status"):
            raise ValueError("qualification metrics report status does not match release decision")
    if release.get("model_package_sha256") != provenance.get("model_package_sha256"):
        raise ValueError("qualification release and provenance package digests do not match")
    source_type = str(provenance.get("source_type", provenance.get("data_status", "")))
    if source_type not in {"DEMO_SYNTHETIC", "OFFICIAL_BENCHMARK", "CUSTOMER_PILOT"}:
        raise ValueError("qualification evidence source type is invalid")
    if summary.get("source_type", source_type) != source_type:
        raise ValueError("qualification summary and provenance source types do not match")
    if release.get("source_type", source_type) != source_type:
        raise ValueError("qualification release and provenance source types do not match")
    if release.get("dataset_fingerprint") != provenance.get("dataset_fingerprint"):
        raise ValueError("qualification release and provenance dataset fingerprints do not match")
    if source_type == "CUSTOMER_PILOT":
        customer_provenance = provenance.get("customer_provenance")
        required_provenance = {
            "tenant",
            "site",
            "line",
            "camera",
            "product",
            "capture_window_start",
            "capture_window_end",
            "label_source",
            "approver",
            "consent",
            "retention_policy",
        }
        if (
            not isinstance(customer_provenance, dict)
            or not required_provenance.issubset(customer_provenance)
            or not customer_provenance.get("consent")
        ):
            raise ValueError("CUSTOMER_PILOT evidence lacks complete consented customer provenance")
    return {
        "valid": True,
        "evidence_package_sha256": core_digest,
        "decision": release.get("decision"),
        "gate_decision": release.get("gate_decision", metrics.get("gates", {}).get("decision")),
        "source_type": source_type,
        "dataset_fingerprint": provenance.get("dataset_fingerprint"),
        "approval_status": release.get("approval_status"),
        "gates": metrics.get("gates", release.get("gates", {})),
        "metrics": metrics.get("metrics", {}),
        "model_package_sha256": expected_model_package_sha256,
    }
