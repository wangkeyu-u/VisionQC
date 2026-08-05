# VisionQC 简历与面试表达

## 英文简历版本

- Built a multi-tenant industrial visual quality platform integrating PatchCore anomaly detection, pixel-level heatmaps, human review, batch quarantine, simulated MES/QMS workflows, and tamper-evident audit trails.
- Developed a reproducible MVTec AD benchmark pipeline with immutable dataset fingerprints, validation-only threshold calibration, frozen holdout evaluation, and integrity-verified model packages; achieved 1.00 image AUROC, 0.972 pixel AUROC, 0.941 AUPRO, and 96.6 ms P95 inference latency.
- Implemented business-safety release gates that kept a high-AUROC candidate in DRAFT after detecting a 30% anomalous auto-release rate, preventing benchmark/demo evidence from being approved or activated.
- Designed tenant-specific Deployment Packs and an offline-capable edge gateway with image quality gates, SQLite buffering, idempotent delivery, and Factory A/B workflow isolation.

## 中文简历版本

- 设计并实现多租户工业视觉质量闭环平台，集成 PatchCore 异常检测、像素级热力图、人工复核、批次隔离、MES/QMS 模拟接口和防篡改审计。
- 构建可复现的 MVTec AD 基准流水线，支持不可变数据指纹、仅验证集阈值校准、冻结留出集评测和模型包完整性验证，取得 Image AUROC 1.00、Pixel AUROC 0.972、AUPRO 0.941、P95 96.6ms。
- 实现业务安全发布门禁，在发现异常自动放行率为 30% 后自动将高 AUROC 模型保持为 DRAFT，禁止演示或 Benchmark 证据进入审批与激活。
- 通过 Deployment Pack 适配 Factory A/B，并实现具备图片质量门禁、SQLite 断网缓存和幂等补传的边缘采集网关。

## 30 秒面试介绍

“我做的不是一个上传图片后返回分数的视觉 Demo，而是一套工业质量闭环。图片从边缘网关进入后，PatchCore 提供异常分数和热力图，确定性策略进行双阈值路由，高风险样本由质量工程师复核，确认后才调用 MES 暂扣批次和 QMS 建单。不同客户通过 Deployment Pack 适配。项目最有价值的一点是模型治理：公开 Benchmark 的 AUROC 达到 1.0，但业务误放率仍有 30%，系统因此自动阻断发布，而不是把模型包装成生产可用。”

## 不应写入简历的表述

- “已在真实工厂部署”——当前没有客户现场证据；
- “缺陷识别准确率 100%”——AUROC 不是准确率，业务召回未通过；
- “自动判断缺陷类型和根因”——模型仅输出异常证据和区域；
- “生产级 Kubernetes/Kafka/OIDC”——当前不在实现范围内。

