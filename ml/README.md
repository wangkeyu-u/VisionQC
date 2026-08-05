# VisionQC ML

## 数据来源模式与 Benchmark Qualification

项目默认不携带也不要求任何数据。`DEMO_SYNTHETIC` 是内置的小型演示 fixture，只用于证明页面、CLI、证据包和 ModelOps 闭环可以启动；它标记为 `DEMO_ONLY`，不得用于效果声明。

可选数据使用统一的 `DatasetSource` / `DatasetRegistration` 契约：

- `DEMO_SYNTHETIC`：默认模式，不读取外部文件。
- `OFFICIAL_BENCHMARK`：受控导入用户在官方页面取得的 MVTec AD 归档/目录；需要许可证确认、SHA-256、目录结构、类别和 manifest 校验。阶段名称是 **Benchmark Qualification / Pre-Pilot Lab Validation**，不是客户 Pilot 或工厂生产证据。
- `CUSTOMER_PILOT`：仅接受带 tenant、site、line、camera、product、capture window、label source、approver、consent、retention provenance 的客户数据；缺项只能保持 `DRAFT`，不能进入 Pilot approval。

默认演示：

```bash
uv sync --extra dev
uv run visionqc-ml pilot --context demo --category transistor \
  --source-type DEMO_SYNTHETIC \
  --output-dir ../reports/pilot-qualification/demo/transistor
```

需要进行可选的官方 benchmark 评测时，先通过受控入口校验本地来源：

```bash
uv sync --extra dev
uv run visionqc-ml data validate \
  --dataset-root /secure/data/mvtec_anomaly_detection \
  --category transistor \
  --source configs/mvtec-ad-transistor.json \
  --acknowledge-license
uv run visionqc-ml data manifest --dataset-root /secure/data/mvtec_anomaly_detection \
  --category transistor --seed 20260804
uv run visionqc-ml data verify --dataset-root /secure/data/mvtec_anomaly_detection \
  --category transistor
uv run visionqc-ml dataset register --source-type OFFICIAL_BENCHMARK \
  --name mvtec-transistor --category transistor \
  --source-path /secure/data/mvtec_anomaly_detection \
  --source-config configs/mvtec-ad-transistor.json \
  --acknowledge-license --output /secure/registrations/mvtec-transistor.json
```

绑定 baseline run 时，必须显式声明 `OFFICIAL_BENCHMARK`。CLI 会校验 run manifest、validation/test predictions、validation-only thresholds、evaluation、performance probe、gallery、dataset receipt 和模型包的路径、SHA-256、类别、模型版本及 dataset fingerprint：

```bash
uv run visionqc-ml pilot --context benchmark-lab --category transistor \
  --source-type OFFICIAL_BENCHMARK \
  --run-dir .artifacts/runs/patchcore-transistor-1.0.0-rc1-real \
  --dataset-root .data/mvtec-ad \
  --source configs/mvtec-ad-transistor.json \
  --model-package .artifacts/model-packages/patchcore-transistor/1.0.0-rc1 \
  --output-dir ../reports/pilot-qualification/benchmark-lab/transistor
```

阈值只从 validation 选择，test 只在阈值冻结后参与 holdout 指标。业务门槛失败会生成完整、可验证的 `BENCHMARK_NO_GO` 包；它不会被解释为 `GO`，Model Registry 也会保持该完整性通过但业务失败的候选为 `DRAFT`。报告状态严格按来源命名：`DEMO_ONLY`、`BENCHMARK_PASS` / `BENCHMARK_NO_GO` / `BENCHMARK_INSUFFICIENT_EVIDENCE`、`CUSTOMER_PILOT_PASS` / `CUSTOMER_PILOT_NO_GO` / `CUSTOMER_PILOT_INSUFFICIENT_EVIDENCE`。MVTec 即使门槛通过，也最多是 `BENCHMARK_PASS / READY_FOR_CUSTOMER_DATA`，不能 `APPROVED` 或 `ACTIVE`。

This directory is a self-contained, reproducible Iteration 0–1 workflow for the
MVTec AD `transistor` PatchCore baseline. It verifies a locally obtained archive
and extracted data, creates a fixed manifest, trains and exports Anomalib PatchCore,
calibrates review/hold
thresholds from validation only, evaluates the held-out test set, builds an
integrity-checked model package, and emits the backend inference contract.

The model output means only **anomaly evidence and an anomalous region**. It does
not confirm a semantic defect type, root cause, rework decision, or scrap
decision. A high score routes to batch hold and human review; it never performs
an irreversible quality action.

## Supported environment

- Python `>=3.10,<3.13` (Python 3.12 is recommended)
- CPU, CUDA, or the accelerator selected by Lightning for fitting
- Anomalib `2.0.0`, PyTorch `2.6.0`, torchvision `0.21.0`
- MVTec AD is CC BY-NC-SA 4.0 and is not licensed for commercial use

The repository does not contain the dataset, pretrained weights, PatchCore
feature bank, or generated model packages. `.gitignore` excludes all such paths.

## Bottle category adaptation

`configs/patchcore-bottle.yaml` and `configs/mvtec-ad-bottle.json` are a
separate category contract. They deliberately use a different input
resolution, coreset ratio, neighbor count, calibration target, model version,
and dataset category from the transistor benchmark baseline. Run the same
`data → baseline → package → verify` workflow when the optional benchmark or
approved customer source is supplied; the checked-in Deployment Pack does not
claim that a placeholder package is production-ready.

Anomalib 2.0.0 imports an OpenVINO result type while importing its deployment
module, even when only the Torch inferencer is used. `visionqc_ml.compat` installs
a narrow type-only shim when OpenVINO is absent or unloadable. The shim does not
implement or advertise OpenVINO inference; this workflow exports and serves only
the Torch model. `python-dotenv` is also pinned because Anomalib's top-level model
module imports its unused VLM backend; VisionQC does not enable that backend.
`requests` is pinned for the same reason: Anomalib's top-level model module also
imports its unused video model helpers.

## Install

From this directory:

```bash
uv sync --python 3.12 --extra model --extra dev
uv run visionqc-ml env
uv run pytest
uv run ruff check src tests
```

`uv.lock` pins the full transitive environment after running `uv lock`. The
first PatchCore run also downloads the ImageNet backbone weights through
torchvision; cache those according to your deployment policy.

## Data acquisition and fixed split

Obtain the MVTec AD archive yourself through the [official MVTec AD download
page](https://www.mvtec.com/research-teaching/datasets/mvtec-ad) after reviewing
the CC BY-NC-SA 4.0 terms. The qualification CLI does not accept the license
or fetch a mirror on your behalf. Give the locally acquired archive to the
verifier; it checks the pinned SHA-256 from Anomalib v2.0.0 and extracts only the
requested category:

```bash
uv run visionqc-ml data download \
  --source configs/mvtec-ad-transistor.json \
  --archive /secure/acquired/mvtec_anomaly_detection.tar.xz \
  --dataset-root /secure/data/mvtec_anomaly_detection \
  --archive-cache /secure/cache/mvtec \
  --category transistor \
  --acknowledge-license
uv run visionqc-ml data manifest
uv run visionqc-ml data verify
```

For an archive obtained separately, pass its path with `--archive` (the default
cache directory is `.cache/downloads`); the same SHA-256 check still applies.
The generated manifest records every image/mask SHA-256, resolution,
source split, fixed assignment, dataset fingerprint, and split hash.

Split rules are deliberately explicit:

- all original `train/good` images remain PatchCore adaptation data;
- original test images are stratified by `good` or anomaly subtype;
- each stratum is ranked by `SHA256(seed + relative path)` and divided into
  validation/test once;
- validation is the only split used for score normalization checks and the two
  business thresholds;
- held-out test is evaluated only after thresholds are frozen.

`failures.jsonl` is always emitted. Corrupt or missing images/masks stop manifest
generation; they are never silently skipped.

## Train, calibrate, evaluate, package

```bash
uv run visionqc-ml baseline
```

The command performs one complete baseline run:

1. verifies every manifest file and split hash;
2. fixes Python/NumPy/PyTorch/Lightning seeds and deterministic execution;
3. builds the PatchCore normal-sample feature bank;
4. exports an Anomalib Torch model with preprocessing and normalization;
5. writes a normalized score, grayscale heatmap, and overlay for every
   validation/test image;
6. calibrates `review_threshold` under a false-accept constraint, then selects
   `hold_threshold` under a hold-recall target; the legacy selector remains
   reproducible, while `strategy: safety_margin` can apply a validation-only
   conservative score margin;
7. evaluates image AUROC, pixel AUROC/AUPRO, precision/recall/F1, false accept,
   false reject, review/hold rates, and warm P50/P95 latency;
8. builds and verifies `.artifacts/model-packages/patchcore-transistor/1.0.0-rc1`.

Generated run metadata records the Git commit (plus dirty marker), dependency
versions, OS, CPU/GPU availability, input manifest, config, timings, and known
limitations. If a calibration constraint cannot be met, the report says so; the
workflow does not present the candidate as passing.

Calibration and evaluation can also be rerun independently:

```bash
uv run visionqc-ml calibrate \
  --predictions .artifacts/runs/patchcore-transistor-rc1/predictions/validation.jsonl \
  --output-dir .artifacts/runs/patchcore-transistor-rc1/calibration-recheck \
  --policy-version factory-a-transistor-1.0.0-rc1

uv run visionqc-ml evaluate \
  --predictions .artifacts/runs/patchcore-transistor-rc1/predictions/test.jsonl \
  --manifest .artifacts/manifests/transistor-v1/manifest.jsonl \
  --manifest-meta .artifacts/manifests/transistor-v1/manifest-meta.json \
  --dataset-root .data/mvtec-ad \
  --thresholds .artifacts/runs/patchcore-transistor-rc1/calibration/thresholds.json \
  --output-dir .artifacts/runs/patchcore-transistor-rc1/evaluation-recheck \
  --model-id patchcore-transistor --model-version 1.0.0-rc1
```

For a conservative validation-only calibration, add `--strategy safety_margin
--safety-margin 0.02`. The default `legacy` strategy reproduces existing
threshold artifacts. No calibration command accepts test/holdout records.

## Single-image inference

```bash
uv run visionqc-ml package \
  .artifacts/model-packages/patchcore-transistor/1.0.0-rc1

uv run visionqc-ml infer \
  --package-dir .artifacts/model-packages/patchcore-transistor/1.0.0-rc1 \
  --image .data/mvtec-ad/transistor/test/good/000.png \
  --inspection-id insp_demo_001
```

Inference verifies the whole model package before loading weights, warms the
model, validates the input, and writes `result.json`, `heatmap.png`, and
`overlay.png`. Score routing uses exact boundaries:

- `score < review_threshold` → `AUTO_RELEASE`
- `review_threshold <= score < hold_threshold` → `REVIEW_REQUIRED`
- `score >= hold_threshold` → `BATCH_HOLD_AND_REVIEW`

Model absence, package tampering, unsupported input, non-finite output, or a
score outside `[0,1]` is an error. The caller must map any such error to
`INFERENCE_FAILED` and human review; it must not auto-release.

## Backend integration contract

The schema is committed at `schemas/inference-result.schema.json` and can be
regenerated with:

```bash
uv run visionqc-ml schema
```

Python workers may use:

```python
from pathlib import Path
from visionqc_ml.inference import VisionQCInferenceService

service = VisionQCInferenceService.from_package(Path(model_package), device="auto")
health = service.health()
service.warmup(Path(representative_image), runs=3)
result = service.infer(Path(input_image), inspection_id, Path(evidence_root))
payload = result.model_dump(mode="json")
```

The stable payload contains input hash/dimensions, model/version/feature-bank and
package hashes, normalized anomaly score, heatmap/overlay references, threshold
policy/version/decision, device, warm flag, and timing breakdown. Both
`semantic_defect_confirmed` and `root_cause_confirmed` are schema constants set
to `false`.

## Known limits

- A full baseline was not run unless local output includes an evaluation report
  and package hash; unit tests do not substitute for that evidence.
- Anomalib v2.0 TorchInferencer selects CPU when CUDA is unavailable; Apple MPS
  fitting and exported inference behavior should be measured separately.
- When running the optional Apple MPS path, keep
  `PYTORCH_ENABLE_MPS_FALLBACK=1` so unsupported operators can fall back safely;
  record the actual device and fallback behavior in the performance evidence.
- P95 `<3 s/image` is a target tied to the hardware and image size recorded in
  each report, not a universal claim.
- MVTec subtype labels are ground truth used only for stratification/reporting;
  they are never emitted as predicted defect semantics.
- Commercial or customer deployment requires authorized factory data, license
  review, customer-specific calibration, robustness testing, and human approval.
