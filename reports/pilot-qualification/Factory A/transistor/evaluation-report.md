# VisionQC Benchmark Qualification / Pre-Pilot Lab Validation — transistor

Report status: **BENCHMARK_NO_GO**

本报告仅证明官方 benchmark 上的系统与评测流程可运行, 不代表任何客户数据、工厂现场效果或生产准备度。

## Frozen benchmark holdout metrics

| Metric | Value |
| --- | ---: |
| Image AUROC | 1.000000 |
| Pixel AUROC | 0.972166 |
| AUPRO @ FPR 0.30 | 0.941145 |
| Precision / Recall / F1 @ review | 1.000000 / 0.700000 / 0.823529 |
| Normal review/hold rate | 0.000000 |
| Defect error auto-release rate | 0.300000 |
| Review + Hold recall | 0.700000 |
| Hold recall | 0.500000 |
| Manual review burden rate | 0.280000 |
| Cold start (ms) | 259.845334 |
| Warm P50 / P95 (ms) | 92.592229 / 96.598491 |

## Pilot Gate checks

| Gate | Value | Threshold | Status |
| --- | ---: | ---: | --- |
| `image_auroc` | 1.000000 | 0.900000 | **PASS** |
| `defect_error_auto_release_rate` | 0.300000 | 0.050000 | **FAIL** |
| `review_hold_recall` | 0.700000 | 0.950000 | **FAIL** |
| `hold_recall` | 0.500000 | 0.800000 | **FAIL** |
| `normal_review_hold_rate` | 0.000000 | 0.250000 | **PASS** |
| `warm_p95_ms` | 96.598491 | 500.000000 | **PASS** |
| `no_split_leakage` | True | True | **PASS** |
| `model_package_integrity` | True | True | **PASS** |
| `customer_data_provenance` | n/a | True | **NOT_APPLICABLE** |

## Threshold provenance

- Source split: `validation`.
- Strategy: `legacy`; safety margin: `0.000000`.
- Review threshold: `0.505643`; hold threshold: `0.581543`.
- Test labels were not used to select or adjust either threshold.

## Confidence intervals

| Metric | Estimate | Lower | Upper |
| --- | ---: | ---: | ---: |
| `false_accept_rate` | 0.300000 | 0.100000 | 0.500000 |
| `false_reject_rate` | 0.000000 | 0.000000 | 0.000000 |
| `hold_f1` | 0.666667 | 0.461538 | 0.823529 |
| `hold_precision` | 1.000000 | 1.000000 | 1.000000 |
| `hold_recall` | 0.500000 | 0.300000 | 0.700000 |
| `image_auroc` | 1.000000 | 1.000000 | 1.000000 |
| `review_f1` | 0.823529 | 0.666667 | 0.947368 |
| `review_precision` | 1.000000 | 1.000000 | 1.000000 |
| `review_recall` | 0.700000 | 0.500000 | 0.900000 |

## Error cases and claim boundary

- Gallery cases: `50`; case types: `{'false_negative': 6, 'gray_zone': 4, 'true_negative': 30, 'true_positive': 10}`.
- Allowed claim: anomaly likelihood and anomalous-region localization.
- Not claimed: confirmed semantic defect type, root cause, or factory production readiness.

## Split and evidence contract

- Validation samples: `50`; frozen holdout samples: `50`.
- Source artifacts bound by SHA-256: `163`.
- MVTec AD is an official non-commercial research benchmark; these results cannot be presented as factory, customer Pilot, or production evidence.
- Source type: `OFFICIAL_BENCHMARK`; report status: `BENCHMARK_NO_GO`.

- Baseline evaluation timestamp: `2026-08-04T22:22:21.502502+00:00`.
