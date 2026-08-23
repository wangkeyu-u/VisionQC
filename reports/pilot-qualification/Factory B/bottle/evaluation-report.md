# VisionQC Benchmark Qualification / Pre-Pilot Lab Validation — bottle

Report status: **BENCHMARK_INSUFFICIENT_EVIDENCE**

本报告仅证明官方 benchmark 上的系统与评测流程可运行, 不代表任何客户数据、工厂现场效果或生产准备度。

Protocols: validation-only threshold calibration followed by an untouched holdout.

## Frozen benchmark holdout metrics

| Metric | Value |
| --- | ---: |
| Image AUROC | None |
| Pixel AUROC | None |
| AUPRO @ FPR 0.30 | None |
| Precision / Recall / F1 @ review | None / None / None |
| Normal review/hold rate | None |
| Defect error auto-release rate | None |
| Review + Hold recall | None |
| Hold recall | None |
| Manual review burden rate | None |
| Warm P50 / P95 (ms) | None / None |

## Pilot Gate checks — visionqc-pilot-gates.v3

| Gate | Value | Threshold | Class | Status |
| --- | ---: | ---: | --- | --- |
| `customer_data_provenance` | None | True | STANDARD | **NOT_APPLICABLE** |
| `defect_error_auto_release_rate` | None | 0.0 | HARD_GATE | **INSUFFICIENT_EVIDENCE** |
| `hold_recall` | None | 0.8 | HARD_GATE | **INSUFFICIENT_EVIDENCE** |
| `image_auroc` | None | 0.9 | STANDARD | **INSUFFICIENT_EVIDENCE** |
| `model_package_integrity` | False | True | STANDARD | **FAIL** |
| `no_split_leakage` | False | True | STANDARD | **FAIL** |
| `normal_review_hold_rate` | None | 0.35 | OPERATIONAL_TARGET | **INSUFFICIENT_EVIDENCE** |
| `review_hold_recall` | None | 0.95 | HARD_GATE | **INSUFFICIENT_EVIDENCE** |
| `warm_p95_ms` | None | 500.0 | STANDARD | **INSUFFICIENT_EVIDENCE** |

## Confusion matrices and grouped metrics

```json
{
  "confusion_matrix": null,
  "group_metrics": {}
}
```

## Threshold provenance

- Source split: `validation`.
- Holdout records consumed for selection: `false`.
- Test labels were not used to select or adjust either threshold.
- Policy contract was re-audited on `2026-08-24`; prediction evidence and dataset/model fingerprints were not changed.

## Split and evidence contract

- Validation samples: `0`; frozen holdout samples: `0`.
- Source artifacts bound by SHA-256: `0`.
- MVTec AD is an official non-commercial research benchmark; these results cannot be presented as factory, customer Pilot, or production evidence.

## Known limitations

- MVTec AD is an official non-commercial research benchmark, not factory or customer Pilot data.
- Passing benchmark gates only means READY_FOR_CUSTOMER_DATA; it never authorizes APPROVED or ACTIVE.
- The checked-in evidence is a historical benchmark run; a real automotive paint-quality pilot still requires new site data and provenance.
