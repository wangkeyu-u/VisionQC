# VisionQC 视觉 QA 记录

日期：2026-08-04  
环境：Vite 本地演示服务，`VITE_USE_MOCKS=true`，Chromium in-app Browser  
视口：1440×900、1280×800、1024×760

## 检查范围

| 页面 | 1440 截图 | 检查重点 |
| --- | --- | --- |
| 运营总览 | [overview-1440.png](overview-1440.png) | API/Mock 指标、空状态、异常路由、复核积压、Gateway 状态 |
| 复核队列 | [reviews-1440.png](reviews-1440.png) | 队列密度、优先级、键盘/操作入口 |
| 复核工作区 | [review-workbench-1440.png](review-workbench-1440.png) | 证据主区域、决定面板、高风险确认和提交回执 |
| 检测详情 | [inspection-1440.png](inspection-1440.png) | 原图/热力图、分数/阈值、模型/策略/审计证据 |
| Gateway 运营 | [gateway-1440.png](gateway-1440.png) | 工位、心跳、队列、上传成功/失败、最近错误 |
| 质量事件 | [incidents-1440.png](incidents-1440.png) | 紧凑列表、状态文字、批次/工位上下文 |
| 事件详情 | [incident-detail-1440.png](incident-detail-1440.png) | 处置时间线、MES/QMS 操作和关闭证据 |
| Deployment Pack / ModelOps | [modelops-1440.png](modelops-1440.png) | 当前包、模型状态、synthetic smoke 边界、阈值和限制 |
| 手动上传 | [upload-1440.png](upload-1440.png) | 标签、客户上下文、Mock/API 边界、错误恢复 |

补充：1024px 复核工作区见 [review-workbench-1024.png](review-workbench-1024.png)。1280px 运营总览在浏览器中检查，布局保持单行指标和可读的主内容区。

## 结果

- 1440px 和 1280px：全局导航、上下文条和主要工作区保持紧凑；检测/复核页面的图像证据是主要视觉区域。
- 1024px：工作台仍可操作；次级决定栏在证据下方堆叠，不强行压缩图像或制造横向滚动。
- 最终检查没有发现水平溢出、断图、空白页面或浏览器 `error`/`warning` 级别 console 日志。
- 状态均有文字；颜色语义固定为绿色正常、橙色告警、红色危险，signal blue 只用于交互。
- ModelOps 页面明确显示 synthetic fixture smoke、未运行 MVTec、校准未满足和 `DRAFT` 发布边界，没有伪装成生产效果。

## 数据与限制

截图中的演示记录来自确定性 Mock/API fixture，仅用于验证页面结构和操作闭环。首页不写死业务指标；实际运行时通过 API 返回值或诚实空状态渲染。截图不能证明真实相机吞吐、正式 MVTec 指标、企业 MES/QMS、OIDC、Kafka、Kubernetes 或 PostgreSQL RLS 已生产化。
