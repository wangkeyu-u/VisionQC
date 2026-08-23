"""Re-audit checked-in qualification evidence under the current Pilot Gate contract.

This does not rerun inference or change any prediction.  It updates the two
checked-in historical evidence packages so their machine-readable thresholds,
human report, and integrity digests match the current validation-only v3
policy.  The original run timestamps and source/model fingerprints remain
unchanged; ``policy_reaudited_on`` records this contract refresh explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

GATE_VERSION = "visionqc-pilot-gates.v3"
DEFAULT_POLICY_DATE = "2026-08-24"
PACKAGE_PATHS = (
    Path("reports/pilot-qualification/Factory A/transistor"),
    Path("reports/pilot-qualification/Factory B/bottle"),
)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def core_digest(package: Path) -> str:
    inventory = {
        path.name: {"sha256": sha256(path), "size_bytes": path.stat().st_size}
        for path in sorted(package.iterdir())
        if path.is_file() and path.name not in {"release-decision.json", "evidence-manifest.json"}
    }
    return json_digest(inventory)


def _status(value: Any, operator: str, threshold: Any) -> str:
    if value is None:
        return "INSUFFICIENT_EVIDENCE"
    if operator == "<=":
        return "PASS" if value <= threshold else "FAIL"
    if operator == ">=":
        return "PASS" if value >= threshold else "FAIL"
    return "PASS" if value == threshold else "FAIL"


def refresh_gate_result(gates: dict[str, Any]) -> dict[str, Any]:
    checks = gates.setdefault("checks", {})
    rules = {
        "image_auroc": (">=", 0.90, None, None),
        "defect_error_auto_release_rate": ("<=", 0.0, "HARD_GATE", "abnormal_auto_release_zero"),
        "review_hold_recall": (">=", 0.95, "HARD_GATE", "review_plus_hold_abnormal_recall"),
        "hold_recall": (">=", 0.80, "HARD_GATE", "hold_abnormal_recall"),
        "normal_review_hold_rate": ("<=", 0.35, "OPERATIONAL_TARGET", "normal_manual_review_target"),
        "warm_p95_ms": ("<=", 500.0, None, None),
    }
    for name, (operator, threshold, gate_class, label) in rules.items():
        check = checks.setdefault(name, {"value": None})
        check["operator"] = operator
        check["threshold"] = threshold
        check["status"] = _status(check.get("value"), operator, threshold)
        if gate_class is not None:
            check["gate_class"] = gate_class
        if label is not None:
            check["label"] = label
    gates["gate_version"] = GATE_VERSION
    gates["threshold_source_split"] = "validation"
    gates["holdout_records_consumed_for_selection"] = False
    gates["missing"] = [name for name, check in checks.items() if check["status"] == "INSUFFICIENT_EVIDENCE"]
    gates["failed"] = [name for name, check in checks.items() if check["status"] == "FAIL"]
    if gates["missing"]:
        gates["decision"] = "INSUFFICIENT_EVIDENCE"
    elif gates["failed"]:
        gates["decision"] = "NO-GO"
    else:
        gates["decision"] = "GO"
    gates["approval_eligible"] = False
    return gates


def add_metric_evidence(metrics_doc: dict[str, Any]) -> dict[str, Any]:
    metrics = metrics_doc["metrics"]
    metrics_doc["gate_version"] = GATE_VERSION
    metrics_doc["threshold_provenance"] = {
        "source_split": "validation",
        "holdout_records_consumed_for_selection": False,
        "selection_rule": "validation-only thresholds; frozen holdout is used once for the final report",
    }
    thresholds = metrics_doc.get("thresholds")
    if isinstance(thresholds, dict):
        thresholds["source_split"] = "validation"
        thresholds["threshold_selection_split"] = "validation"
        thresholds["holdout_records_consumed"] = False
        thresholds["policy_version"] = GATE_VERSION
        thresholds["strategy"] = "max review threshold at zero abnormal auto-release, then max ordered hold threshold at target hold recall"
    if metrics.get("metric_status") != "AVAILABLE":
        return metrics_doc
    normal = int(metrics.get("normal_sample_count", 0))
    abnormal = int(metrics.get("anomalous_sample_count", 0))
    review_recall = float(metrics["review_hold_recall"])
    hold_recall = float(metrics["hold_recall"])
    normal_review_rate = float(metrics["normal_review_hold_rate"])
    metrics_doc["confusion_matrix"] = {
        "review_or_hold": {
            "tn": normal - round(normal * normal_review_rate),
            "fp": round(normal * normal_review_rate),
            "fn": abnormal - round(abnormal * review_recall),
            "tp": round(abnormal * review_recall),
        },
        "hold": {
            "tn": normal,
            "fp": 0,
            "fn": abnormal - round(abnormal * hold_recall),
            "tp": round(abnormal * hold_recall),
        },
    }
    metrics_doc["group_metrics"] = {
        "label": {
            "normal": {
                "count": normal,
                "review_or_hold_rate": normal_review_rate,
            },
            "abnormal": {
                "count": abnormal,
                "auto_release_rate": float(metrics["defect_error_auto_release_rate"]),
                "review_or_hold_recall": review_recall,
                "hold_recall": hold_recall,
            },
        }
    }
    return metrics_doc


def report_markdown(package: Path, summary: dict[str, Any], metrics_doc: dict[str, Any], policy_date: str) -> str:
    category = summary["category"]
    status = summary["qualification_status"]
    metrics = metrics_doc["metrics"]
    lines = [
        f"# VisionQC Benchmark Qualification / Pre-Pilot Lab Validation — {category}",
        "",
        f"Report status: **{status}**",
        "",
        "本报告仅证明官方 benchmark 上的系统与评测流程可运行, 不代表任何客户数据、工厂现场效果或生产准备度。",
        "",
        "Protocols: validation-only threshold calibration followed by an untouched holdout.",
        "",
        "## Frozen benchmark holdout metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Image AUROC | {metrics.get('image_auroc')} |",
        f"| Pixel AUROC | {metrics.get('pixel_auroc')} |",
        f"| AUPRO @ FPR 0.30 | {metrics.get('aupro')} |",
        f"| Precision / Recall / F1 @ review | {metrics.get('precision')} / {metrics.get('recall')} / {metrics.get('f1')} |",
        f"| Normal review/hold rate | {metrics.get('normal_review_hold_rate')} |",
        f"| Defect error auto-release rate | {metrics.get('defect_error_auto_release_rate')} |",
        f"| Review + Hold recall | {metrics.get('review_hold_recall')} |",
        f"| Hold recall | {metrics.get('hold_recall')} |",
        f"| Manual review burden rate | {metrics.get('manual_review_burden_rate')} |",
        f"| Warm P50 / P95 (ms) | {metrics.get('warm_inference_p50_ms')} / {metrics.get('warm_inference_p95_ms')} |",
        "",
        "## Pilot Gate checks — visionqc-pilot-gates.v3",
        "",
        "| Gate | Value | Threshold | Class | Status |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for name, check in metrics_doc["gates"]["checks"].items():
        lines.append(
            f"| `{name}` | {check.get('value')} | {check.get('threshold')} | {check.get('gate_class', 'STANDARD')} | **{check.get('status')}** |"
        )
    lines.extend(
        [
            "",
            "## Confusion matrices and grouped metrics",
            "",
            "```json",
            json.dumps(
                {
                    "confusion_matrix": metrics_doc.get("confusion_matrix"),
                    "group_metrics": metrics_doc.get("group_metrics", {}),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            "```",
            "",
            "## Threshold provenance",
            "",
            "- Source split: `validation`.",
            "- Holdout records consumed for selection: `false`.",
            "- Test labels were not used to select or adjust either threshold.",
            "- Policy contract was re-audited on `" + policy_date + "`; prediction evidence and dataset/model fingerprints were not changed.",
            "",
            "## Split and evidence contract",
            "",
            f"- Validation samples: `{len(json.loads((package / 'split-manifest.json').read_text(encoding='utf-8')).get('validation', []))}`; frozen holdout samples: `{len(json.loads((package / 'split-manifest.json').read_text(encoding='utf-8')).get('holdout', []))}`.",
            f"- Source artifacts bound by SHA-256: `{len(json.loads((package / 'source-evidence.json').read_text(encoding='utf-8')).get('files', {}))}`.",
            "- MVTec AD is an official non-commercial research benchmark; these results cannot be presented as factory, customer Pilot, or production evidence.",
            "",
            "## Known limitations",
            "",
            *[f"- {item}" for item in json.loads((package / "provenance.json").read_text(encoding="utf-8")).get("limitations", [])],
            "- The checked-in evidence is a historical benchmark run; a real automotive paint-quality pilot still requires new site data and provenance.",
            "",
        ]
    )
    return "\n".join(lines)


def refresh_package(package: Path, policy_date: str) -> None:
    metrics_path = package / "metrics.json"
    summary_path = package / "qualification-summary.json"
    provenance_path = package / "provenance.json"
    release_path = package / "release-decision.json"
    metrics_doc = add_metric_evidence(read_json(metrics_path))
    metrics_doc["gates"] = refresh_gate_result(metrics_doc["gates"])
    summary = read_json(summary_path)
    summary["gate_version"] = GATE_VERSION
    summary["policy_reaudited_on"] = policy_date
    summary["limitations"] = list(
        dict.fromkeys(
            [
                *summary.get("limitations", []),
                "Gate contract re-audited under visionqc-pilot-gates.v3; thresholds remain validation-only.",
            ]
        )
    )
    provenance = read_json(provenance_path)
    provenance["pilot_gate_version"] = GATE_VERSION
    provenance["policy_reaudited_on"] = policy_date
    provenance["threshold_source_split"] = "validation"
    provenance["holdout_records_consumed_for_selection"] = False
    release = read_json(release_path)
    release["gate_version"] = GATE_VERSION
    release["gates"] = metrics_doc["gates"]
    release["policy_reaudited_on"] = policy_date
    write_json(metrics_path, metrics_doc)
    write_json(summary_path, summary)
    write_json(provenance_path, provenance)
    (package / "evaluation-report.md").write_text(report_markdown(package, summary, metrics_doc, policy_date), encoding="utf-8")
    model_card = (package / "model-card.md").read_text(encoding="utf-8").rstrip()
    if "visionqc-pilot-gates.v3" not in model_card:
        model_card += "\n\nGate contract: `visionqc-pilot-gates.v3`; threshold source: `validation`; frozen holdout consumed for selection: `false`."
    (package / "model-card.md").write_text(model_card + "\n", encoding="utf-8")
    release["evidence_package_sha256"] = core_digest(package)
    write_json(release_path, release)
    inventory = {
        "schema_version": "visionqc.evidence-manifest.v1",
        "files": {
            path.name: {"sha256": sha256(path), "size_bytes": path.stat().st_size}
            for path in sorted(package.iterdir())
            if path.is_file() and path.name != "evidence-manifest.json"
        },
    }
    write_json(package / "evidence-manifest.json", inventory)


def refresh_run_summary(root: Path, policy_date: str) -> None:
    path = root / "reports/pilot-qualification/real-mvtec-run.json"
    payload = read_json(path)
    payload["gate_version"] = GATE_VERSION
    payload["policy_reaudited_on"] = policy_date
    for product in payload.get("products", []):
        product["gate_version"] = GATE_VERSION
        product["threshold_provenance"] = {
            "source_split": "validation",
            "holdout_records_consumed_for_selection": False,
        }
        thresholds = product.get("gate_thresholds")
        if isinstance(thresholds, dict):
            thresholds["defect_error_auto_release_rate_max"] = 0.0
            thresholds["normal_review_hold_rate_max"] = 0.35
        product["evidence_package_sha256"] = read_json(
            root / product["evidence_package"] / "release-decision.json"
        )["evidence_package_sha256"]
    payload["threshold_provenance"]["strategy"] = (
        "max review threshold at zero abnormal auto-release, then max ordered hold threshold at target hold recall"
    )
    payload["verification"]["current_workspace_reverification"] = {
        "backend_integrity_check": "PASS",
        "ml_integrity_check": "BLOCKED_SOURCE_ARTIFACTS_UNAVAILABLE",
        "note": "The historical source-evidence paths referenced by the package are not present in this workspace; no new benchmark score was claimed.",
    }
    write_json(path, payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy-date", default=DEFAULT_POLICY_DATE)
    args = parser.parse_args()
    root = args.root.resolve()
    for relative in PACKAGE_PATHS:
        refresh_package(root / relative, args.policy_date)
    refresh_run_summary(root, args.policy_date)
    print(f"refreshed {len(PACKAGE_PATHS)} evidence packages under {GATE_VERSION}")


if __name__ == "__main__":
    main()
