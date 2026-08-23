# VisionQC for Dürr — Automotive Paint Quality Edge Pilot

> **面向 Dürr 业务场景设计的独立作品集概念方案 / Independent portfolio concept; not commissioned or endorsed by Dürr.**

本文只使用 Dürr 公开资料做产品判断，不表示 Dürr 委托、合作、授权或认可本项目。仓库不使用 Dürr logo 或受保护视觉资产，不实现真实私有 DXQ 协议，也不声称 `dxq_mock` 与任何官方 API 兼容。

## 1. 为什么选择这个切口

Dürr 公开材料把 Sustainable.Automation、digital@DÜRR、DXQ、数字工厂以及 AI 在质量控制、根因分析和预测性维护中的应用放在同一战略语境中。DXQ 的公开介绍也强调设备数据、数字孪生、系统性故障分析、first-pass yield 与闭环质量。基于这些公开信息，本项目选择一个可验证但不越界的扩展切口：

```text
涂装检查站
  → 边缘捕获 RGB 与质量标记
  → 每个车身/工件的数字质量档案
  → 异常证据 + 热力图 + 工艺上下文
  → 人工复核
  → 模拟 MES/QMS/DXQ 质量事件
  → 根因候选、返工/暂扣/放行记录与审计
```

这里的“扩展”是 FDE 作品集概念：VisionQC 负责边缘证据、人工复核和编排，DXQ 仍是外部概念边界；任何正式产品集成必须经过协议、权限、数据治理和现场验收。

## 2. Dürr demo 场景

`duerr-demo` 是一个保持平台多租户能力的 Deployment Pack，不是单客户硬编码。它采用中性的 `painted_body_panel` / `painted_body_test_coupon`，支持两个模拟涂装检查站 `PAINT-QC-01/02`，并把路径、命名、字段映射、阈值和连接器声明都放在 manifest 中。

车身数字质量档案至少包含：

| 字段 | 用途 |
| --- | --- |
| `body_id` / `workpiece_id` | 车身/工件追踪键 |
| `paint_shop` / `booth_station` / `line` | 涂装车间、喷房/工位、产线 |
| `model_variant` | 车型或变体 |
| `color_code` / `paint_recipe` | 颜色和配方 |
| `shift` / `timestamp` | 班次与采集时间 |
| `visual_defect_type` / `severity` / `mask_or_heatmap` | 视觉证据；模型不把它们当作已确认语义 |
| `operator_decision` / `disposition` | 人工复核与返工/暂扣/放行结果 |
| `equipment_alarm_refs` / `process_parameter_refs` | 只保留引用，不假造工艺数据 |
| `root_cause_candidates` | 供质量工程师调查的候选，不是自动根因结论 |
| `quality_case_id` | 模拟质量事件关联键 |

## 3. 连接器边界

`dxq_mock` 是仓库内显式标记的 in-process simulated connector，契约版本为 `simulated-dxq-quality-loop.v1`。它提供概念层的质量记录、link/analyze/close 操作、幂等键和可审计外部引用；它不访问网络，不包含私有 DXQ endpoint、token、schema 或反向工程字段。

MES/QMS 仍使用现有的 Mock Connector。适配器层的目标是把“质量记录如何映射到外部系统”隔离起来，业务代码只依赖 generic quality record。未来若有正式接口，应新增经过批准的适配器和 contract tests，不把协议散落到检测、复核或 UI 代码中。

## 4. 中国 Pilot 的工程前提

这是基于公开材料与常见现场约束的产品推断，不是 Dürr 的官方要求。概念上优先考虑：

- 本地部署与中文操作，减少对外网和长链路的依赖；
- 默认数据不出厂，原图传输必须有显式用途、同意、保留期限和删除方式；
- 文件夹或 USB 相机低改造接入，现场先用本地队列承接断网；
- Deployment Pack 配置字段、工位、相机和连接器，不把客户 ID 写进核心流程；
- 先 shadow / 人工复核，保留回滚，不执行自动停线、自动放行或 PLC 控制。

## 5. 风险门禁

涂装视觉候选必须遵守 Pilot Gate Recovery：

- 异常样本自动放行率必须为 `0`，这是 hard gate；
- Review + Hold 异常召回率至少 `95%`；
- Hold 异常召回率至少 `80%`；
- 正常样本进入人工复核不超过 `35%` 是运营目标，数据不支持时报告失败；
- 阈值只能从 validation 选择，冻结 holdout 只用于一次最终报告；
- 模糊、过曝、欠曝、低对比度、无目标、视角偏差和 OOD 不得自动放行；
- 校准或 provenance 失败时保持 `DRAFT`，不能为了变绿放宽安全门禁。

Blender 涂装样本的 source type 固定为 `DEMO_SYNTHETIC`，只证明流程、标注和 manifest 可复现，不证明生产准确率。若没有受控 MVTec 或现场数据，ModelOps 必须展示 `DRAFT` / `DEMO_ONLY` 或明确的 NO-GO。

## 6. 公开资料

以下链接是本作品集做业务语境判断时允许引用的 Dürr 官方公开页面：

- [Our digital@DÜRR strategy](https://www.durr-group.com/en/digital-at-duerr/our-digital-at-duerr-strategy)
- [How we work](https://www.durr-group.com/en/digital-at-duerr/how-we-work)
- [DXQ analytics & AI](https://www.durr.com/en/products/software-controls/dxq/analytics-ai)
- [DXQ closed quality loop](https://www.durr.com/en/products/software-controls/dxq/analytics-ai/closed-quality-loop)
- [DXQ anomaly detection](https://www.durr.com/en/products/software-controls/dxq/anomaly-detection)
- [Paint quality inspection](https://www.durr.com/en/products/paint-shop-application-technology/paint-quality-inspection)
- [DXQplant.analytics improves first-run rate](https://www.durr.com/en/media/news/news-detail/view/dxqplantanalytics-improves-first-run-rate-through-systematic-fault-analysis-85807)
- [Dürr and China's automotive industry](https://www.durr.com/en/media/news/news-detail/view/duerr-and-chinas-automotive-industry-three-decades-of-partnership-94407)
- [Chery relies on robots and intelligent software from Dürr](https://www.durr.com/en/media/news/news-detail/view/chery-automobile-relies-on-146-state-of-the-art-robots-and-intelligent-software-from-duerr-86301)

