# VisionQC UI 设计说明

VisionQC 当前前端是面向工厂质量团队的工业工作台，而不是营销首页。统一版本的视觉方向是“产线证据台账”：界面紧凑、证据优先、状态可解释，所有重要决定都能追溯到图像、模型、策略、操作者和外部系统回执。

## 信息架构

- **运营总览 `/`**：24 小时检测吞吐、策略路由、复核积压、质量事件、Gateway 在线率/本地队列，以及需要操作的问题。
- **手动上传 `/upload`**：保留图片上传和客户上下文，明确当前 Deployment Pack 与 Mock/API 边界。
- **复核工作台 `/reviews`、`/reviews/:id`**：任务队列 → 图像证据 → 决定面板。高风险决定要求原因和二次确认，提交后显示审计回执。
- **检测详情 `/inspections/:id`**：原图/热力图占据主要区域，右侧展示异常分数、双阈值、模型/特征库/策略版本、上下文、状态与审计时间线。
- **质量事件 `/incidents`、`/incidents/:id`**：紧凑列表、处置状态、时间线及 MES/QMS 外部操作，不使用巨大装饰卡片。
- **Gateway 运营 `/operations`**：工位、在线/离线/陈旧、心跳、版本、队列深度、成功/失败/重试和最近错误。
- **Deployment Pack / ModelOps `/modelops`**：客户、产品、Deployment Pack、模型包校验、评测证据、阈值、限制和发布建议。

顶部框架固定保留客户/工厂切换、当前 Deployment Pack、Gateway 健康、系统健康和当前操作者；侧栏改为紧凑横向导航，避免静态导航占据大量工作区。

## 设计系统

完整 token、组件示例和 Impeccable sidecar 见根目录 [DESIGN.md](../DESIGN.md) 与 [`/.impeccable/design.json`](../.impeccable/design.json)。本轮关键约束：

- 工业白、石墨灰和浅灰画布为主；单一品牌强调色为 signal blue `#155EEF`。
- 绿色 `#18794E` 只表示正常/完成，橙色 `#A65F00` 表示告警/待处理，红色 `#B42318` 表示危险/失败；每个状态同时提供文字。
- 平面 1px 边界和 4–6px 小圆角建立层级；不使用大面积渐变、玻璃拟态、过量阴影或“圆角卡片海”。
- 中文是主要界面语言；分数、时间、哈希、模型/策略/设备标识使用紧凑等宽数字。
- 工作台最低宽度 1024px；1440/1280 保持双栏证据布局，1024 时把次级决策栏置于证据下方。键盘 focus、标签、减少动画和文本状态遵守合理 WCAG AA 目标。

全局持续声明：**异常不等于已确认缺陷**。模型输出只描述异常分数与区域，质量结论必须来自有权限的人工决定。

## 数据边界

首页指标由 `GET /api/v1/operations/summary` 提供，列表和详情分别来自 inspections、reviews、gateways 和 incidents API；没有数据时展示空状态，不用示例数字填充。ModelOps 页面读取 `GET /api/v1/modelops/status`，默认 source 是 `DEMO_SYNTHETIC`：当前 Mock 证据是每个产品 4 张演示 fixture，阈值校准约束未满足，模型候选保持 `DRAFT`，不能当作 benchmark、客户或生产效果。用户导入的 MVTec 只能按 `OFFICIAL_BENCHMARK` 显示，客户数据则必须单独通过 provenance gate。

`VITE_USE_MOCKS=true` 时，前端使用确定性 Mock inspection、Gateway、review 和 ModelOps 数据，以便离线演示；Mock 数据在 shell 和相关页面有标识。MES/QMS 仍是 Pilot 的可替换 Mock Connector，不代表企业生产集成。默认启动不需要数据；`OFFICIAL_BENCHMARK` 只能通过受控入口导入，`CUSTOMER_PILOT` 还必须有完整 provenance。真实相机、Kafka、Kubernetes、OIDC、PostgreSQL RLS 和现场效果评测不在本轮生产化范围内。

## 视觉 QA

最终截图和检查记录见 [`docs/visual-qa/README.md`](visual-qa/README.md)。已检查运营总览、上传、复核队列/工作区、检测详情、Gateway、质量事件/详情和 ModelOps；覆盖 1440、1280、1024 宽度，无水平溢出、断图或浏览器 console error。
