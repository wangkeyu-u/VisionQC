# VisionQC model card — OFFICIAL_BENCHMARK / transistor

Report status: **BENCHMARK_NO_GO**. Source type: `OFFICIAL_BENCHMARK`.

Model: `patchcore-transistor` `1.0.0-rc1`.

Frozen holdout image AUROC: `1.000000`; review+hold recall: `0.700000`; hold recall: `0.500000`.

The model reports anomaly evidence and regions only. It does not confirm a defect type or root cause. MVTec AD evidence is a non-commercial research benchmark and cannot be presented as factory, customer Pilot, or production performance.

- MVTec AD is an official non-commercial research benchmark, not factory or customer Pilot data.
- Passing benchmark gates only means READY_FOR_CUSTOMER_DATA; it never authorizes APPROVED or ACTIVE.
- MVTec AD does not represent a specific customer's camera, process, or defect distribution.
- Pixel metrics depend on resized heatmaps and benchmark masks.
- Offline routing metrics do not include actual human overrides or downstream quality outcomes.
- MVTec AD is a non-commercial research benchmark and does not establish factory or customer Pilot performance.
- Thresholds are selected from validation only; the held-out test split is used only after thresholds are frozen.

Gate contract: `visionqc-pilot-gates.v3`; threshold source: `validation`; frozen holdout consumed for selection: `false`.
