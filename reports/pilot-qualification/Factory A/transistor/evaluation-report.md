# VisionQC Benchmark Qualification / Pre-Pilot Lab Validation — transistor

Report status: **BENCHMARK_NO_GO**

本报告仅证明官方 benchmark 上的系统与评测流程可运行, 不代表任何客户数据、工厂现场效果或生产准备度。

Protocols: validation-only threshold calibration followed by an untouched holdout.

## Frozen benchmark holdout metrics

| Metric | Value |
| --- | ---: |
| Image AUROC | 1.0 |
| Pixel AUROC | 0.9721664724634458 |
| AUPRO @ FPR 0.30 | 0.9411454515635378 |
| Precision / Recall / F1 @ review | 1.0 / 0.7 / 0.8235294117647058 |
| Normal review/hold rate | 0.0 |
| Defect error auto-release rate | 0.3 |
| Review + Hold recall | 0.7 |
| Hold recall | 0.5 |
| Manual review burden rate | 0.28 |
| Warm P50 / P95 (ms) | 92.59222901891917 / 96.5984909737017 |

## Pilot Gate checks — visionqc-pilot-gates.v3

| Gate | Value | Threshold | Class | Status |
| --- | ---: | ---: | --- | --- |
| `customer_data_provenance` | None | True | STANDARD | **NOT_APPLICABLE** |
| `defect_error_auto_release_rate` | 0.3 | 0.0 | HARD_GATE | **FAIL** |
| `hold_recall` | 0.5 | 0.8 | HARD_GATE | **FAIL** |
| `image_auroc` | 1.0 | 0.9 | STANDARD | **PASS** |
| `model_package_integrity` | True | True | STANDARD | **PASS** |
| `no_split_leakage` | True | True | STANDARD | **PASS** |
| `normal_review_hold_rate` | 0.0 | 0.35 | OPERATIONAL_TARGET | **PASS** |
| `review_hold_recall` | 0.7 | 0.95 | HARD_GATE | **FAIL** |
| `warm_p95_ms` | 96.5984909737017 | 500.0 | STANDARD | **PASS** |

## Confusion matrices and grouped metrics

```json
{
  "confusion_matrix": {
    "hold": {
      "fn": 10,
      "fp": 0,
      "tn": 30,
      "tp": 10
    },
    "review_or_hold": {
      "fn": 6,
      "fp": 0,
      "tn": 30,
      "tp": 14
    }
  },
  "group_metrics": {
    "label": {
      "abnormal": {
        "auto_release_rate": 0.3,
        "count": 20,
        "hold_recall": 0.5,
        "review_or_hold_recall": 0.7
      },
      "normal": {
        "count": 30,
        "review_or_hold_rate": 0.0
      }
    }
  }
}
```

## Threshold provenance

- Source split: `validation`.
- Holdout records consumed for selection: `false`.
- Test labels were not used to select or adjust either threshold.
- Policy contract was re-audited on `2026-08-24`; prediction evidence and dataset/model fingerprints were not changed.

## Split and evidence contract

- Validation samples: `50`; frozen holdout samples: `50`.
- Source artifacts bound by SHA-256: `163`.
- MVTec AD is an official non-commercial research benchmark; these results cannot be presented as factory, customer Pilot, or production evidence.

## Known limitations

- MVTec AD is an official non-commercial research benchmark, not factory or customer Pilot data.
- Passing benchmark gates only means READY_FOR_CUSTOMER_DATA; it never authorizes APPROVED or ACTIVE.
- MVTec AD does not represent a specific customer's camera, process, or defect distribution.
- Pixel metrics depend on resized heatmaps and benchmark masks.
- Offline routing metrics do not include actual human overrides or downstream quality outcomes.
- MVTec AD is a non-commercial research benchmark and does not establish factory or customer Pilot performance.
- Thresholds are selected from validation only; the held-out test split is used only after thresholds are frozen.
- The checked-in evidence is a historical benchmark run; a real automotive paint-quality pilot still requires new site data and provenance.
