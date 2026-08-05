# VisionQC 双产品 PatchCore 对比

## 契约与隔离

| 维度 | Factory A / transistor | Factory B / bottle |
| --- | --- | --- |
| 产品类别 | `transistor` | `bottle` |
| Model ID / version | `patchcore-transistor` / `1.0.0-rc1` | `patchcore-bottle` / `2.3.0` |
| Feature bank contract | `fb-transistor-20260804` | `fb-bottle-20260802` |
| Backbone / 输入 | `wide_resnet50_2`, 256→224 | `resnet50`, 320→288 |
| Coreset / neighbors | 0.10 / 9 | 0.05 / 7 |
| Dataset source config | `ml/configs/mvtec-ad-transistor.json` | `ml/configs/mvtec-ad-bottle.json` |
| Calibration policy | `factory-a-transistor-policy-1.0.0` | `factory-b-bottle-policy-2.1.0` |
| Default pack thresholds | review 0.40 / hold 0.80 | review 0.28 / hold 0.68 |
| Pack station override | 无 | `CELL-12`: review 0.25 / hold 0.62 |
| `OFFICIAL_BENCHMARK` 评测 | 只读 evidence 已接入；`BENCHMARK_NO_GO` | 未导入；`BENCHMARK_INSUFFICIENT_EVIDENCE` |
| smoke 包 | `patchcore-transistor-smoke@0.0.1-smoke` | `patchcore-bottle-smoke@0.0.1-smoke` |

两个产品共享算法和 inference schema，但不共享数据指纹、feature bank、阈值、package identity 或 registry category。`verify_model_package(..., expected_category=...)` 可在加载模型前阻断错绑；训练时 config category、manifest category 和 prediction category 必须一致。

## Smoke 证据对比

| 指标（synthetic fixture，仅用于合同验证） | transistor | bottle |
| --- | ---: | ---: |
| package verified | yes | yes |
| test samples | 4 | 4 |
| Image AUROC | 1.0000 | 1.0000 |
| Pixel AUROC / AUPRO | 0.9898 / 0.9623 | 0.9882 / 0.9570 |
| Review precision / recall / F1 | 0 / 0 / 0 | 1 / 1 / 1 |
| False-accept / hold recall | 1 / 0 | 0 / 0 |
| Calibration constraints | failed | failed |
| Warm P95 (ms) | 1.961 | 2.192 |

两行都不能当作 MVTec 或工厂性能；transistor 的 smoke 误放和两个产品的 hold recall=0 说明发布门禁确实会阻断不合格候选。

transistor 的官方 benchmark holdout 真实结果另见 [`real-mvtec-run.json`](../pilot-qualification/real-mvtec-run.json) 和 [`Factory A/transistor/evaluation-report.md`](../pilot-qualification/Factory%20A/transistor/evaluation-report.md)：Image AUROC `1.0`，Pixel AUROC `0.972166`，AUPRO `0.941145`，但异常自动放行率 `30%`、review+hold recall `70%`、hold recall `50%`，因此只能保持 `DRAFT_ONLY`。

## Deployment Pack 集成边界

现有 Deployment Pack manifest 保持不变。模型包最终注册后，应将其真实 `package_sha256`、dataset fingerprint、feature bank version 和批准证据填入部署发布流程；当前 manifest 中的 `demo-*-package-sha256` 是演示占位值，不能用来激活真实模型。具体映射见 [`integration-notes.md`](./integration-notes.md)。
