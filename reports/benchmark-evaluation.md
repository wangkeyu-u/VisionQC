# VisionQC MVTec AD Benchmark Evaluation

## Executive decision

**Decision: `BENCHMARK_NO_GO / DRAFT_ONLY`.**

PatchCore 在 MVTec AD `transistor` 冻结 holdout 上取得优秀的排序和区域定位指标，但未满足 VisionQC 的业务安全 Gate。该候选不得审批或激活，也不得解释为真实工厂效果。

## Evidence scope

| 项目 | 内容 |
| --- | --- |
| 数据来源 | MVTec AD official benchmark，CC BY-NC-SA 4.0，非商业 |
| 类别 | `transistor` |
| 正常训练样本 | 213 |
| Validation | 50（30 normal / 20 anomalous） |
| Frozen holdout | 50（30 normal / 20 anomalous） |
| 模型 | PatchCore / WideResNet50-2 / Anomalib 2.0.0 |
| 切分规则 | 按异常 subtype 进行确定性 SHA-256 分层 |
| 数据 fingerprint | `508950233c88cbf52520899e22587fbbb8ecb1ab1b43d5184fa0599f44c59005` |

阈值只由 validation 产生。Holdout 仅在阈值冻结后执行一次正式评测，不参与阈值选择。

## Model metrics

| 指标 | 估计值 |
| --- | ---: |
| Image AUROC | 1.0000 |
| Pixel AUROC | 0.9722 |
| AUPRO @ pixel FPR 0–0.30 | 0.9411 |
| Warm inference P50 | 92.6 ms |
| Warm inference P95 | 96.6 ms |
| Cold start | 259.8 ms |

运行环境：Apple Silicon arm64、Python 3.12、PyTorch 2.6、MPS 可用；不支持的算子通过 `PYTORCH_ENABLE_MPS_FALLBACK=1` 回退并在性能证据中记录。

## Business gates

| Gate | 要求 | 结果 | 状态 |
| --- | ---: | ---: | --- |
| Image AUROC | ≥ 0.90 | 1.00 | PASS |
| 异常自动放行率 | ≤ 5% | 30% | **FAIL** |
| Review + Hold Recall | ≥ 95% | 70% | **FAIL** |
| Hold Recall | ≥ 80% | 50% | **FAIL** |
| 正常 Review/Hold Rate | ≤ 25% | 0% | PASS |
| Warm P95 | ≤ 500 ms | 96.6 ms | PASS |
| Split leakage | 0 | 0 | PASS |
| Model package integrity | valid | valid | PASS |

## Error analysis

- 20 个 holdout 异常中有 6 个落入自动放行区；
- False negatives 主要集中在 `misplaced`（3/5）和 `bent_lead`（2/5）；
- 正常样本没有进入 Review/Hold，说明当前阈值偏向低人工负担，但牺牲了缺陷召回；
- 不能根据 holdout 结果反向降低阈值，否则会造成测试集泄漏。

## Confidence and limitations

Image AUROC 的分层 bootstrap 区间接近 `[1.0, 1.0]`，但业务召回指标受 20 个异常样本的小样本规模限制。MVTec 的背景、相机、照明和缺陷分布均不代表任何客户现场。

## Required next step

1. 保持当前模型 `DRAFT_ONLY`；
2. 收集带完整 provenance 的客户正常/异常样本；
3. 在新数据上重新固定 calibration/holdout；
4. 仅用 calibration 选择安全裕量；
5. 重跑业务 Gate、现场延迟和人工负担测试；
6. 只有客户数据、全部 Gate 和职责分离审批均通过，才允许进入 ACTIVE。

