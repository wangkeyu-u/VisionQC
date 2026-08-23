# VisionQC model card — OFFICIAL_BENCHMARK / bottle

Report status: **BENCHMARK_INSUFFICIENT_EVIDENCE**. Source type: `OFFICIAL_BENCHMARK`.

Model: `None` `None`.

The model reports anomaly evidence and regions only. It does not confirm a defect type or root cause. MVTec AD evidence is a non-commercial research benchmark and cannot be presented as factory, customer Pilot, or production performance.

- MVTec AD is an official non-commercial research benchmark, not factory or customer Pilot data.
- Passing benchmark gates only means READY_FOR_CUSTOMER_DATA; it never authorizes APPROVED or ACTIVE.
- A verified Anomalib PatchCore model package is not available.
- Protocol A/B split evidence is not available.
- Prediction scores, heatmaps, and thresholded holdout metrics are not available.
- OFFICIAL_BENCHMARK requires an immutable dataset fingerprint.
- OFFICIAL_BENCHMARK requires a verified dataset receipt.
- The baseline source-evidence hash inventory is not available.

Gate contract: `visionqc-pilot-gates.v3`; threshold source: `validation`; frozen holdout consumed for selection: `false`.
