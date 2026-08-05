# VisionQC ModelOps PatchCore 双产品评测报告

## 技术摘要

本轮交付完成了 `transistor` 与 `bottle` 两条 PatchCore ModelOps 路径：可选数据下载/校验/固定切分/指纹、Anomalib PatchCore 训练、feature bank 导出、版本化 Model Package、双阈值校准、离线评测、案例画廊、完整性校验、注册表生命周期、离线 shadow 对比和人工反馈输入契约均已落在 `ml/`。

**发布结论：当前没有任何一个产品可批准为 `APPROVED/ACTIVE`。** 当前没有客户或工厂数据；`transistor` 已使用用户提供的、位于 c014 worktree 的只读官方 MVTec evidence source 完成受控接入，结果为 `BENCHMARK_NO_GO`。`bottle` 仍是 `DEMO_SYNTHETIC` scaffold。MVTec 阶段名称只能是 Benchmark Qualification / Pre-Pilot Lab Validation；任何 benchmark 结果最多证明系统与评测流程可运行，不代表工厂现场效果。

模型输出始终只表示异常证据与异常区域。异常不等于确定缺陷、缺陷类型或根因；暂扣、返工、报废和外部系统写操作仍需确定性策略与授权人工复核。

## 已验证结果与证据边界

| 范围 | transistor | bottle |
| --- | ---: | ---: |
| Anomalib PatchCore smoke（`DEMO_SYNTHETIC` fixture） | 通过 | 通过 |
| memory bank / feature bank 导出合同 | 通过 | 通过 |
| Model Package integrity + category isolation | 通过 | 通过 |
| 单图推理与热力图/overlay | 通过 | 通过 |
| `OFFICIAL_BENCHMARK` 完整导入、训练、评测 | 已接入只读 evidence，`BENCHMARK_NO_GO` | 未导入，`BENCHMARK_INSUFFICIENT_EVIDENCE` |
| 可用于客户 Pilot/生产审批的证据 | 否 | 否 |

Smoke 证据保存在 [`smoke-evidence.json`](./smoke-evidence.json)。其中所有指标都标记为 `synthetic_fixture`；测试集只有 4 张图（正常 2、异常 2），阈值约束均未满足，不能作为质量门槛证据。

## 合成 smoke 的量化结果（不是 MVTec 指标）

| 指标 | transistor smoke | bottle smoke |
| --- | ---: | ---: |
| Image AUROC | 1.0000 | 1.0000 |
| Pixel AUROC | 0.9898 | 0.9882 |
| Pixel AUPRO @ FPR 0.30 | 0.9623 | 0.9570 |
| Precision / Recall / F1 @ review | 0.0000 / 0.0000 / 0.0000 | 1.0000 / 1.0000 / 1.0000 |
| False-accept rate | 1.0000 | 0.0000 |
| Hold recall | 0.0000 | 0.0000 |
| Cold latency (ms) | 4.132 | 3.506 |
| Warm P50 / P95 (ms) | 1.961 / 1.961 | 2.192 / 2.192 |

这些数字只说明代码路径能产生完整的指标结构；尤其 transistor smoke 的异常被自动放行、两个产品的 hold recall 都为 0，正是“约束失败即不发布”的回归证据。像素级指标来自生成的热力图与 synthetic mask，不能外推到 MVTec 或任何现场。

## 官方 benchmark 接入结果（transistor）

本节引用 [`reports/pilot-qualification/Factory A/transistor`](../pilot-qualification/Factory%20A/transistor/) 中由只读 baseline run 生成的完整证据包；仓库不携带 MVTec 图像、压缩包或权重。该包由 ML/backend verifier 通过，并绑定 manifest、validation/test predictions、阈值、evaluation、performance probe、gallery、model package 和 source hashes。

| 指标 | Frozen holdout value | Gate threshold | Status |
| --- | ---: | ---: | --- |
| Image AUROC | 1.000000 | ≥ 0.900000 | PASS |
| Pixel AUROC | 0.972166 | — | reported |
| AUPRO @ FPR 0.30 | 0.941145 | — | reported |
| Defect error auto-release rate | 0.300000 | ≤ 0.050000 | FAIL |
| Review + Hold recall | 0.700000 | ≥ 0.950000 | FAIL |
| Hold recall | 0.500000 | ≥ 0.800000 | FAIL |
| Warm P95 | 96.598491 ms | ≤ 500 ms | PASS |

最终决定是 `BENCHMARK_NO_GO`，候选保持 `DRAFT_ONLY`。阈值来自 validation，50 个 holdout test 样本只用于冻结阈值后的评测；即使这些 gates 将来全部通过，也只能是 `BENCHMARK_PASS / READY_FOR_CUSTOMER_DATA`，不能 `APPROVED/ACTIVE`。

## 数据、指标与实验定义

- **可选 benchmark 范围**：MVTec AD `transistor` 和 `bottle`；官方说明包含正常训练图、正常/异常测试图及像素级标注，并以 CC BY-NC-SA 4.0 发布，禁止商业用途：[MVTec AD 官方页面](https://www.mvtec.com/research-teaching/datasets/mvtec-ad)。本仓库不携带该数据。
- **固定切分**：所有 `train/good` 保留为 PatchCore 适配数据；原始 test 按 anomaly subtype 分层，以 `SHA256(seed + relative_path)` 排序后拆 validation/test。阈值只看 validation，test 只在阈值冻结后评测。
- **数据指纹**：manifest 记录每张图与 mask 的 SHA-256、尺寸、相对路径、split 和标签；`manifest-meta.json` 同时记录 dataset fingerprint、manifest hash、三份 split hash；生成过程失败文件写入 `failures.jsonl` 并阻断。
- **Image AUROC**：按图像标签和归一化 anomaly score 计算。
- **Precision / recall / F1**：分别在 review threshold 与 hold threshold 上按图像计算。
- **误放率（false-accept）**：异常 benchmark 样本的 score 小于 review threshold、从而可能自动放行的比例；它不是“根因判断”。
- **Hold recall**：异常 benchmark 样本 score 大于等于 hold threshold 的比例。
- **Pixel AUROC / AUPRO**：把 heatmap resize 到 mask 尺寸后计算；AUPRO 为像素 FPR `[0, 0.30]` 范围内的区域重叠积分。
- **不确定性**：图像级指标使用按类别分层的 1,000 次 percentile bootstrap（95% CI）；小样本只提供算法区间，不覆盖相机、工艺、批次和人工标签不确定性。像素指标未提供 CI，并在 evaluation JSON 中明确限制。

## 模型规格与可追溯性

两套完整配置均固定 Anomalib 2.0.0、预训练 backbone、层、coreset 比例、邻居数、resize/crop/normalize、阈值目标、随机种子、运行设备与确定性策略。训练后保存：

1. Anomalib Torch 权重；
2. 从已拟合 PatchCore memory bank 导出的 `weights/feature-bank.pt` 及 tensor shape/dtype/count 元数据；
3. 预处理、训练配置、阈值 JSON、评测 JSON/Markdown；
4. 数据 manifest-meta、dataset fingerprint、依赖 lock、许可证与运行时提示；
5. `code_commit`、每个文件 SHA-256、聚合 `package_sha256` 和 package schema。

完整包永远不覆盖已有版本。`verify_model_package` 在加载推理器前验证清单、文件清单、逐文件 hash、feature bank hash、阈值顺序、元数据 identity 和所需文件可加载性。

## 双阈值校准：目标、约束与不确定性

校准目标是先最大化 review threshold（在 false-accept 上限内尽量减少无意义自动放行），再在保持 `review < hold` 的前提下最大化 hold threshold（满足 hold-recall 目标、避免无边界 hold）。校准结果保存 policy version、validation prediction hash、约束、达到值、样本数、objective 和 warning。

Smoke 结果的约束失败会让候选保持不可发布；不会用“AUROC 高”覆盖阈值失败。官方 benchmark 导入后，仍须由质量负责人确认：review 误放上限、hold recall 下限、可接受人工复核率、良品误扣上限、站点 override 和样本量规则；这一步仍不产生现场效果声明。

## 评测与案例画廊

每个完整 run 会生成 `gallery/index.html` 和 `gallery.json`，展示原图、heatmap、overlay、score、review/hold threshold、route、ground-truth label、evaluation-only subtype 和错误类型：`false_positive`、`false_negative`、`gray_zone`、`true_positive`、`true_negative`。画廊带有“异常证据不等于缺陷/根因”的显式边界。smoke 执行生成的画廊位于被忽略的 `ml/.artifacts/smoke/runs/{transistor,bottle}/gallery/index.html`；不把数据或权重提交到仓库。

## 模型注册与离线生命周期

`ml/src/visionqc_ml/registry.py` 提供轻量 JSON Model Registry，状态只允许：

`DRAFT → EVALUATED → APPROVED → ACTIVE → RETIRED`

`activate` 会在同一产品/模型 ID 下将旧 ACTIVE 记录为 RETIRED；`rollback` 是唯一允许 RETIRED → ACTIVE 的显式动作，并且必须给出 rollback condition、actor 和证据摘要。所有转移都追加到 transitions，不覆盖历史。注册、评测、审批和激活都绑定 package/evaluation hash；非法跳转或包被篡改会阻断。

`shadow.py` 只比较离线 prediction JSONL、阈值和 route changes，不调用在线后端、不写 MES/QMS。`feedback.py` 只生成经过 schema 校验、带 image SHA-256 和 reviewer 的新 re-evaluation input；人工反馈不会自动更新生产模型。

## 限制、风险与发布建议

1. **P0 阻断**：当前只读接入的是官方 MVTec benchmark；仓库不携带数据，且 transistor 的业务 gate 已失败（`30%` 异常自动放行、review+hold recall `70%`、hold recall `50%`）。
2. **P0 阻断**：benchmark 训练、阈值校准、评测和画廊完成后，也只能生成 `BENCHMARK_*` 报告，不能绑定为客户/生产 package。
3. **P1 风险**：MVTec benchmark 不代表任何相机、光照、工艺、批次和缺陷分布；进入 Customer Pilot 前必须用客户数据和完整 provenance 重校准。
4. **P1 风险**：macOS smoke 使用 CPU 推理；目标 `<3 s/image` 只是记录硬件上的门槛，不是所有 CUDA/MPS/边缘设备的承诺。
5. **P1 风险**：高风险质量处置必须由策略和人工权限控制；PatchCore 不输出 defect type、root cause、scrap 或 rework 结论。
6. **P2 风险**：需要补充亮度、模糊、旋转、位移和站点 drift 的鲁棒性切片，并把已批准的人审反馈加入新的冻结评测 manifest。

**发布建议：** `transistor` 保持 `DRAFT`，报告为 `BENCHMARK_NO_GO`；`bottle` 保持 `DRAFT`，报告为 `BENCHMARK_INSUFFICIENT_EVIDENCE`。不得 `APPROVED/ACTIVE`。即使 benchmark gate 通过也只能 `BENCHMARK_PASS / READY_FOR_CUSTOMER_DATA`。只有在客户数据 provenance、customer-data gate、业务阈值、shadow、人工 review 和回滚证据全部完成后，才可进入具名审批流程。

## 可复现命令

```bash
cd ml
uv sync --extra model --extra dev
uv run visionqc-ml data download --category transistor --acknowledge-license
uv run visionqc-ml data manifest --category transistor
uv run visionqc-ml data verify --category transistor
uv run visionqc-ml baseline --config configs/patchcore-transistor.yaml

uv run visionqc-ml data download --category bottle --acknowledge-license
uv run visionqc-ml data manifest --category bottle
uv run visionqc-ml data verify --category bottle
uv run visionqc-ml baseline --config configs/patchcore-bottle.yaml

# 不导入可选数据的实现 smoke（使用 Anomalib/PyTorch，fixture 仅在 ignored artifacts）
uv run python scripts/run_modelops_smoke.py
```

当官方归档被手工放入 `.cache/downloads/mvtec_anomaly_detection.tar.xz` 且 SHA-256 匹配时，下载命令不会重复下载；流程仍会做 hash、category-only extraction 和 count 校验。
