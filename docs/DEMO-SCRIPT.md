# VisionQC 三分钟演示脚本

## 演示目标

三分钟内回答四个问题：系统解决什么业务问题、模型结果如何进入工作流、如何适配不同客户、为什么不安全的模型无法上线。

本次推荐路线是 `VisionQC — Configurable Industrial Quality Platform`。先用三个无品牌 Industry Pack 示例证明同一平台可以切换 electronics、packaging 和 automotive-paint；如需展示汽车涂装客户定制，再单独打开 Dürr concept overlay。该 overlay 是独立作品集概念，不是委托、授权或官方集成；`dxq_mock` 只模拟质量事件。

## 镜头与口播

| 时间 | 页面/动作 | 口播重点 |
| --- | --- | --- |
| 0:00–0:20 | 开始检测 / 运营总览 | “VisionQC 是可配置的工业视觉证据、人工复核和质量闭环平台。” |
| 0:20–0:40 | 输入向导 / Gateway 页面 | “选择示例图、文件夹或 USB 相机；网关完成文件稳定检测、图片质量门禁、断网排队和幂等补传，默认本地处理。” |
| 0:40–1:05 | 上传页面 | 上传一张异常样本；等待检测完成 | “图片与批次、工位、产品上下文一起进入系统。推理失败不会自动放行。” |
| 1:05–1:30 | 检测详情 | 展示原图、热力图、分数、模型版本和策略证据 | “模型只声明异常证据和区域，不直接声称缺陷类型或根因。确定性双阈值决定放行候选、人工复核或批次暂扣。” |
| 1:30–1:55 | 复核工作台 | 认领任务，选择调查/返工并填写原因 | “质量工程师保留最终决定。高风险操作要求理由、确认和版本校验，避免并发覆盖。” |
| 1:55–2:15 | 质量事件 | 查看 simulated MES/QMS，展示时间线 | “人工复核后进入模拟质量闭环；外部动作带幂等键和重试状态。” |
| 2:15–2:35 | 三行业配置 | 依次查看 electronics/transistor、packaging/bottle、automotive-paint | “行业默认值在 Industry Pack，客户现场差异在 tenant/site overlay；切换配置路径即可复用同一套代码。” |
| 2:35–2:55 | ModelOps | 展示数据来源、Benchmark 指标、NO-GO、DRAFT | “公开基准上 AUROC 很高，但异常自动放行率达到 30%，因此业务 Gate 阻止模型审批。高模型分数不等于生产安全。” |
| 2:55–3:00 | 回到总览 | “下一步只有接入带 provenance 的客户现场数据，才能进入真正 Pilot。” |

## 演示前准备

```bash
cd infra
docker compose up --build -d api frontend edge-gateway-selected
cd ../backend
uv run python ../scripts/compose_smoke.py
```

- 浏览器缩放 100%，窗口建议 1440×900；
- 选择 electronics 示例开始，预先确认 packaging 和 automotive-paint pack 可切换；
- 准备一张异常样本和一张正常样本；
- 清理无关终端和浏览器标签；
- 不展示本机绝对路径、Token 或客户数据；
- 录制前确认 ModelOps 显示 `DEMO_ONLY` 或明确的 `BENCHMARK_NO_GO`。

## 录制检查表

- [ ] 页面无加载错误或空白图；
- [ ] 热力图、模型 ID、版本和阈值均可见；
- [ ] 复核理由与高风险确认被展示；
- [ ] MES/QMS 动作仅在审批后执行；
- [ ] 三个行业 pack 切换后数据不串租户；
- [ ] 明确说出 MVTec 不是工厂现场效果；
- [ ] 明确说出 Dürr 概念方案不是委托、授权或官方背书；
- [ ] 默认本地处理，只有显式同意才允许发送原图；
- [ ] 视频控制在 2:50–3:10。
