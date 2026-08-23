# VisionQC 数据源 Qualification 与发布门禁

状态：Benchmark Qualification / Pre-Pilot Lab Validation 规范，不是客户现场或生产声明。当前项目没有客户/工厂数据；日期：2026-08-05。

## 1. 数据治理与来源模式

项目默认不携带也不要求外部数据。所有 CLI/API 都使用统一的 `DatasetSource` / `DatasetRegistration` 契约：

| source type | 用途 | 允许的报告/生命周期边界 |
| --- | --- | --- |
| `DEMO_SYNTHETIC` | 内置小型 fixture，演示闭环 | `DEMO_ONLY`；不得作效果声明 |
| `OFFICIAL_BENCHMARK` | 用户受控导入官方 MVTec AD | `BENCHMARK_PASS` / `BENCHMARK_NO_GO` / `BENCHMARK_INSUFFICIENT_EVIDENCE`；通过也只能 `READY_FOR_CUSTOMER_DATA`，不能 `APPROVED/ACTIVE` |
| `CUSTOMER_PILOT` | 客户上传/挂载的数据 | 必须有完整 provenance 和客户数据 gate，才可能 `CUSTOMER_PILOT_PASS` 并进入具名审批 |

`DEMO_SYNTHETIC` 是默认模式。页面和报告必须写明“演示数据；不得用于效果声明”。它不读取外部文件，也不要求 MVTec 或客户数据。

`OFFICIAL_BENCHMARK` 通过 `data validate` / `dataset register` 或 backend 受控导入入口接入。用户必须自行从 [MVTec AD 官方页面](https://www.mvtec.com/research-teaching/datasets/mvtec-ad) 取得归档并审核 CC BY-NC-SA 4.0 条款；VisionQC 不从镜像自动下载，也不把归档复制到 Git 或前端静态目录。入口校验 license acknowledgement、声明/实际 SHA-256、压缩包成员路径、扩展名、大小/压缩比、目标类别、`train/good`、`test`、`ground_truth` 结构和 manifest fingerprint。

```bash
cd ml
uv run visionqc-ml dataset register --source-type OFFICIAL_BENCHMARK \
  --name mvtec-transistor --category transistor \
  --source-path /secure/data/mvtec_anomaly_detection \
  --source-config configs/mvtec-ad-transistor.json \
  --acknowledge-license --output /secure/registrations/mvtec-transistor.json
```

`CUSTOMER_PILOT` 必须同时提交 `tenant`、`site`、`line`、`camera`、`product`、`capture_window_start/end`、`label_source`、`approver`、`consent` 和 `retention_policy`。缺项或未确认 consent 时，数据可登记但只能是 `DRAFT`，customer-data gate 阻断 Pilot approval。租户不能读取、绑定、撤销其他租户的 registration。

原始数据由本地 gitignored 数据目录或对象存储适配器流式保存；入口拒绝路径穿越、符号链接、特殊归档成员和压缩炸弹。数据可以撤销/替换，但已有 evidence package 永远绑定原始 fingerprint，撤销只追加审计，不改写历史证据。

当前前端 ModelOps 先展示 source type、registration 状态、fingerprint、风险标签和 approval 边界；原始文件/本地路径导入仍由受权限保护的 API/CLI 完成。后续若增加 ModelOps 的 multipart/挂载入口，必须复用同一 `DatasetRegistration` 校验结果，且不能把原始数据放入前端静态目录。

MVTec 的阶段名称固定为 **Benchmark Qualification / Pre-Pilot Lab Validation**。benchmark 结果最多证明系统和评测流程可运行，不代表任何工厂现场效果、客户 Pilot 效果或生产准备度。

## 2. 评测协议

协议 A：仅用正常训练集构建 PatchCore；阈值只能从 `train/validation` 协议允许的 validation 记录选择。冻结 holdout 只用于一次最终报告，不参与阈值、模型、特征或策略调参。

协议 B：固定 seed，维护 `train / validation / holdout` 三个明确分区。review/hold 阈值只能由 validation 选择；业务指标、错误案例和最终 GO/NO-GO 只在冻结 holdout 计算。split manifest 同时比较 sample ID、路径、图片 hash 和 mask hash，任何 train/validation/holdout 重叠都拒绝发布。报告必须写明 `threshold_source_split=validation` 和 `holdout_records_consumed=false`。

报告必须带样本量、正常/异常数量、`source_type`、小样本限制和 bootstrap 置信区间。样本不足以计算的指标为 `null`，对应门禁为 `INSUFFICIENT_EVIDENCE`；报告状态不能跨来源改名。

## 3. Pilot 初始门槛

以下只是 Pilot 初始门槛，后续须结合现场基线和质量风险评审调整：

| 指标/证据 | 初始要求 |
| --- | ---: |
| image AUROC | ≥ 0.90 |
| 异常样本自动放行率 | = 0（HARD_GATE） |
| Review + Hold 缺陷召回率 | ≥ 95% |
| Hold recall | ≥ 80% |
| 正常样本进入人工复核率 | ≤ 35%（OPERATIONAL_TARGET；数据不支持则报告失败） |
| 热推理 P95 | ≤ 500 ms |
| split 无泄漏、模型包/证据包完整性 | 必须通过 |
| `CUSTOMER_PILOT` provenance / customer-data gate | 进入 Pilot approval 前必须通过；benchmark/demo 为阻断或不适用 |

缺失数据、指标、CI、包摘要或审批证据不能按通过处理，统一为 `INSUFFICIENT_EVIDENCE`。正式评定还需记录 precision、recall、F1、正常误报率、异常自动放行率、review+hold recall、hold recall、正常复核率、冷/热延迟和 bootstrap CI。报告还必须列出 confusion matrix、分组指标、阈值来源、数据版本/fingerprint、运行命令和已知限制。

任何模糊、欠曝、过曝、低对比度、无目标/视角偏差或 OOD 输入都必须进入 `REVIEW_REQUIRED` 或 `BATCH_HOLD_AND_REVIEW`；它们不能成为 `AUTO_RELEASE`。校准失败、数据泄漏、holdout 被调参或证据包不完整时，候选保持 `DRAFT`，不能放宽门禁来制造 PASS。

## 4. 证据包与发布生命周期

`reports/pilot-qualification/<context>/<category>/` 包含 `qualification-summary.json`、`model-card.md`、`evaluation-report.md`、`metrics.json`、`confidence-intervals.json`、`split-manifest.json`、`provenance.json`、`release-decision.json`、`error-cases.json`、`source-evidence.json` 和 `evidence-manifest.json`。包绑定 source type、dataset/split 摘要、模型包 SHA、代码 commit、环境硬件、时间、门槛、限制和审批状态。摘要或任一文件被篡改，后端 evaluate/approve/activate 必须拒绝。

模型生命周期只有 `DRAFT → EVALUATED → APPROVED → ACTIVE → RETIRED`。完整性通过但 benchmark 业务 gate 失败的候选必须保持 `DRAFT`；任何 `OFFICIAL_BENCHMARK` 包都禁止 `APPROVED/ACTIVE`。只有具备完整客户 provenance、客户数据 gate、全部业务 gate 和具名审批，`CUSTOMER_PILOT` 才可能进入批准/激活流程。评测由 ML Engineer 执行；审批由具名 Quality Manager 执行；激活由 Admin/FDE 执行，且不能是前两者。

## 5. 现场与运行边界

Pilot 现场必须完成相机姿态/焦距、曝光、白平衡、灯光色温/亮度、背景和工装标定；建立正常基线和缺陷抽检频率；记录环境/镜头/工位变更。漂移监控至少观察输入质量、分数分布、复核率、误放/误杀和延迟；触发阈值时进入人工复核、冻结变更并重新评测。回滚使用之前已批准且完整性校验通过的包，保留历史结果和审计。

模型输出只表示异常证据和区域，不确认缺陷类型、根因、报废或质量责任。MVTec 指标不包装成客户现场效果；`DEMO_SYNTHETIC` 不包装成 benchmark 或现场效果。上述结果仅证明系统及评测流程可运行，不代表任何工厂现场效果。
