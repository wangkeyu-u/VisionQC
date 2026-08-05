"""Build a local, dependency-free error and gray-zone case gallery."""

from __future__ import annotations

import html
import shutil
from pathlib import Path
from typing import Any

from .calibration import ScoreRecord
from .dataset import ManifestEntry
from .hashing import write_json


def _route(score: float, review_threshold: float, hold_threshold: float) -> str:
    if score < review_threshold:
        return "AUTO_RELEASE"
    if score < hold_threshold:
        return "REVIEW_REQUIRED"
    return "BATCH_HOLD_AND_REVIEW"


def _case_type(record: ScoreRecord, review_threshold: float, hold_threshold: float) -> tuple[str, str]:
    if review_threshold <= record.score < hold_threshold:
        detail = "anomalous sample in review band" if record.label else "normal sample in review band"
        return "gray_zone", detail
    if record.label == 1 and record.score < review_threshold:
        return "false_negative", "anomalous benchmark sample routed to auto-release"
    if record.label == 0 and record.score >= review_threshold:
        return "false_positive", "normal benchmark sample routed to review or hold"
    if record.label == 1:
        return "true_positive", "anomalous benchmark sample detected"
    return "true_negative", "normal benchmark sample auto-released"


def _asset_copy(source: Path, destination: Path) -> str:
    if not source.is_file():
        raise FileNotFoundError(f"gallery evidence is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.relative_to(destination.parents[2]).as_posix()


def build_error_gallery(
    records: list[ScoreRecord],
    manifest_entries: dict[str, ManifestEntry],
    dataset_root: Path,
    prediction_root: Path,
    review_threshold: float,
    hold_threshold: float,
    output_dir: Path,
    *,
    max_cases: int = 200,
) -> dict[str, Any]:
    """Copy auditable evidence into a browsable HTML gallery.

    The gallery deliberately labels MVTec subtype as evaluation-only ground
    truth. It never turns a benchmark anomaly into a confirmed factory defect or
    root-cause claim.
    """
    if max_cases < 1:
        raise ValueError("max_cases must be positive")
    selected = list(records)
    priorities = {"false_negative": 0, "false_positive": 1, "gray_zone": 2, "true_positive": 3, "true_negative": 4}
    selected.sort(
        key=lambda record: (
            priorities[_case_type(record, review_threshold, hold_threshold)[0]],
            -record.score,
            record.sample_id,
        )
    )
    selected = selected[:max_cases]

    assets_root = output_dir / "assets"
    cases: list[dict[str, Any]] = []
    for record in selected:
        entry = manifest_entries.get(record.sample_id)
        if entry is None:
            raise ValueError(f"gallery record is not present in the manifest: {record.sample_id}")
        heatmap_source = Path(record.heatmap_path)
        if not heatmap_source.is_absolute():
            heatmap_source = prediction_root / heatmap_source
        overlay_source = heatmap_source.parent / "overlay.png"
        case_type, detail = _case_type(record, review_threshold, hold_threshold)
        original_rel = _asset_copy(
            dataset_root / entry.image_path,
            assets_root / "originals" / f"{record.sample_id}.png",
        )
        heatmap_rel = _asset_copy(
            heatmap_source,
            assets_root / "heatmaps" / f"{record.sample_id}.png",
        )
        overlay_rel = _asset_copy(
            overlay_source,
            assets_root / "overlays" / f"{record.sample_id}.png",
        )
        cases.append(
            {
                "sample_id": record.sample_id,
                "case_type": case_type,
                "case_detail": detail,
                "original": original_rel,
                "heatmap": heatmap_rel,
                "overlay": overlay_rel,
                "image_path": entry.image_path,
                "score": record.score,
                "review_threshold": review_threshold,
                "hold_threshold": hold_threshold,
                "route": _route(record.score, review_threshold, hold_threshold),
                "ground_truth_label": record.label,
                "ground_truth_subtype_for_evaluation_only": record.anomaly_subtype,
                "product_category": entry.category,
                "claim_boundary": "anomaly evidence only; semantic defect and root cause require human confirmation",
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    gallery = {
        "schema_version": "visionqc.error-gallery.v1",
        "title": "VisionQC PatchCore error and gray-zone gallery",
        "thresholds": {"review": review_threshold, "hold": hold_threshold},
        "cases": cases,
        "limitations": [
            "MVTec subtype is benchmark ground truth for evaluation only, not a predicted defect type.",
            "Anomaly evidence is not confirmation of a semantic defect, root cause, or disposition.",
        ],
    }
    write_json(output_dir / "gallery.json", gallery)
    (output_dir / "index.html").write_text(_render_html(gallery), encoding="utf-8")
    return {
        "path": str((output_dir / "index.html").resolve()),
        "json": str((output_dir / "gallery.json").resolve()),
        "case_count": len(cases),
        "case_types": {
            case_type: sum(case["case_type"] == case_type for case in cases)
            for case_type in sorted({case["case_type"] for case in cases})
        },
    }


def _render_html(gallery: dict[str, Any]) -> str:
    cards: list[str] = []
    for case in gallery["cases"]:
        cards.append(
            """
            <article class="case">
              <div class="images">
                <figure><figcaption>Original</figcaption><img src="{original}" alt="Original image for {sample_id}"></figure>
                <figure><figcaption>Heatmap</figcaption><img src="{heatmap}" alt="Anomaly heatmap for {sample_id}"></figure>
                <figure><figcaption>Overlay</figcaption><img src="{overlay}" alt="Anomaly overlay for {sample_id}"></figure>
              </div>
              <div class="details">
                <span class="badge {case_type}">{case_type}</span>
                <strong>{sample_id}</strong>
                <span>{detail}</span>
                <dl>
                  <dt>Score</dt><dd>{score:.4f}</dd>
                  <dt>Review / hold</dt><dd>{review:.4f} / {hold:.4f}</dd>
                  <dt>Route</dt><dd>{route}</dd>
                  <dt>Ground truth</dt><dd>{label} · {subtype}</dd>
                  <dt>Input</dt><dd>{image_path}</dd>
                </dl>
              </div>
            </article>
            """.format(
                original=html.escape(case["original"]),
                heatmap=html.escape(case["heatmap"]),
                overlay=html.escape(case["overlay"]),
                sample_id=html.escape(case["sample_id"]),
                case_type=html.escape(case["case_type"]),
                detail=html.escape(case["case_detail"]),
                score=float(case["score"]),
                review=float(case["review_threshold"]),
                hold=float(case["hold_threshold"]),
                route=html.escape(case["route"]),
                label=int(case["ground_truth_label"]),
                subtype=html.escape(case["ground_truth_subtype_for_evaluation_only"]),
                image_path=html.escape(case["image_path"]),
            )
        )
    template = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VisionQC PatchCore error gallery</title>
<style>
:root { color-scheme: light dark; --bg:#f7f8fa; --ink:#18212b; --muted:#5e6b78; --card:#fff; --line:#d8dee6; }
@media (prefers-color-scheme: dark) { :root { --bg:#101418; --ink:#e8edf2; --muted:#aab6c2; --card:#182027; --line:#384550; } }
body { margin:0; padding:28px; background:var(--bg); color:var(--ink); font:15px/1.45 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif; }
main { max-width:1280px; margin:0 auto; } h1 { margin:0 0 8px; } .note { color:var(--muted); max-width:900px; }
.case { display:grid; grid-template-columns:minmax(0,2.2fr) minmax(240px,1fr); gap:18px; margin:22px 0; padding:16px; background:var(--card); border:1px solid var(--line); border-radius:14px; }
.images { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:10px; } figure { margin:0; } figcaption { color:var(--muted); font-size:12px; margin-bottom:5px; } img { display:block; width:100%; aspect-ratio:1; object-fit:contain; background:#111; border-radius:8px; }
.details { display:flex; flex-direction:column; gap:8px; } .badge { display:inline-block; width:max-content; padding:3px 8px; border-radius:999px; font-size:12px; font-weight:700; background:#dce8f5; color:#163b5d; } .false_negative { background:#f8d8d3; color:#6c1f14; } .false_positive { background:#f6e5ba; color:#61430a; } .gray_zone { background:#e4ddf7; color:#433275; }
dl { display:grid; grid-template-columns:max-content 1fr; gap:5px 12px; margin:8px 0 0; } dt { color:var(--muted); } dd { margin:0; overflow-wrap:anywhere; }
@media (max-width:760px) { body { padding:16px; } .case { grid-template-columns:1fr; } }
</style></head><body><main>
<h1>__TITLE__</h1>
<p class="note">__COUNT__ cases. Review threshold: <strong>__REVIEW__</strong>; hold threshold: <strong>__HOLD__</strong>.</p>
<p class="note">This gallery shows anomaly evidence and benchmark labels only. MVTec subtype names are evaluation ground truth, not predicted defect semantics; no case confirms a defect or root cause.</p>
__CARDS__
</main></body></html>
"""
    return (
        template.replace("__TITLE__", html.escape(str(gallery["title"])))
        .replace("__COUNT__", str(len(gallery["cases"])))
        .replace("__REVIEW__", f"{float(gallery['thresholds']['review']):.4f}")
        .replace("__HOLD__", f"{float(gallery['thresholds']['hold']):.4f}")
        .replace("__CARDS__", "\n".join(cards))
    )
