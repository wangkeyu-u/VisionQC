# VisionQC

面向工业质量复核的 AI 系统工程原型：把模型证据接入人工审核、ModelOps 发布门禁和可审计的 MES/QMS 动作边界。

## Problem

模型排序分数很高，也可能在选定阈值下自动放行异常品。VisionQC 检查检测之后的决策与操作：哪些样本要复核、谁能确认处置、外部动作失败如何恢复、什么证据允许模型上线。

当前为 Pre-Pilot 原型。默认使用演示数据，MES/QMS 使用 Mock。MVTec 公开基准不代表工厂现场效果。[MVIS](https://github.com/wangkeyu-u/mvis-industrial-vision-pilot) 研究模型、训练和定位评估；本仓库侧重 ModelOps、人工复核、权限和审计。

![VisionQC 运营总览](docs/portfolio/overview-1440.png)

## Engineering Decisions

- [业务门禁优先于单一 AUROC](docs/decisions/001-business-gates.md)：阈值产生的放行/复核/暂扣结果需要独立验证。
- [服务端复核与并发控制](docs/decisions/002-human-review.md)：认领、版本和权限校验防止过期客户端覆盖处置结果。
- [隔离 MES/QMS 写入边界](docs/decisions/003-connector-boundary.md)：用确定性流程控制可审计动作，模型输出不直接授权外部写入。

## System boundaries

| 能力 | VisionQC 的实现 |
| --- | --- |
| 检测 | PatchCore 异常分数、像素级热力图、可校验模型包 |
| 决策 | `AUTO_RELEASE / REVIEW_REQUIRED / BATCH_HOLD_AND_REVIEW` 双阈值策略 |
| 人在回路 | 复核认领、乐观锁、理由与确认门槛、模型反馈 |
| 业务闭环 | Mock MES 暂扣/放行、Mock QMS 工单、事件验证与关闭 |
| 多客户适配 | Factory A/B Deployment Pack、字段映射、产品与 Connector 隔离 |
| ModelOps | DRAFT → EVALUATED → APPROVED → ACTIVE，职责分离与回滚审计 |
| 数据治理 | 演示、官方 Benchmark、客户 Pilot 三种来源；不可变 fingerprint |
| 安全降级 | 推理或证据失败时禁止自动放行；业务 Gate 失败阻断模型上线 |

## 系统闭环

```mermaid
flowchart LR
    A["相机 / 文件夹 / 手动上传"] --> B["Edge Gateway"]
    B --> C["推理与证据服务"]
    C --> D{"确定性质量策略"}
    D -->|低风险| E["候选放行"]
    D -->|灰区| F["人工复核"]
    D -->|高风险| G["批次暂扣 + 人工复核"]
    F --> H["质量事件"]
    G --> H
    H --> I["MES / QMS Connector"]
    I --> J["验证、关闭与审计"]
    F --> K["ModelOps 反馈"]
    K --> L["离线校准与发布门禁"]
```

更完整的组件边界、信任边界和时序见 [系统架构](docs/ARCHITECTURE.md)。

## 已验证结果

下面的模型指标来自保留的历史报告；本次重跑的是软件工作流及合成样本的模型契约测试，未重跑原始 MVTec 基准。

### 公开 Benchmark

MVTec AD `transistor` 使用 213 张正常训练图、50 张 validation 和 50 张冻结 holdout。阈值只由 validation 产生，holdout 不参与调参。

| 指标 | 结果 | 解释 |
| --- | ---: | --- |
| Image AUROC | 1.000 | 排序能力良好 |
| Pixel AUROC | 0.9722 | 异常区域定位能力良好 |
| AUPRO | 0.9411 | 区域重叠质量良好 |
| Warm P95 | 96.6 ms | 当前 Apple Silicon 本地环境 |
| 异常自动放行率 | 30% | **业务 Gate 失败** |
| Review + Hold Recall | 70% | **业务 Gate 失败** |
| Hold Recall | 50% | **业务 Gate 失败** |

最终状态为 `BENCHMARK_NO_GO / DRAFT_ONLY`。这说明高 AUROC 不等于安全可上线；VisionQC 会把不满足业务风险门槛的候选留在 DRAFT，而不是粉饰成生产结果。完整说明见 [Benchmark 评测报告](reports/benchmark-evaluation.md)。

### 自动化验证（2026-09-15 复测）

| 模块 | 当前结果 |
| --- | ---: |
| Backend | 37 passed；隔离数据库和 Mock 外部系统 |
| ML | 36 passed；含小型合成数据 PatchCore 流程 |
| Edge Gateway | 17 passed |

命令、环境与剩余边界见 [验证记录](docs/experiments/workflow-validation.md)。Frontend 与双客户 Compose 冒烟仍保留运行说明，不计入本次上述复测数字。

## Baseline / Failure Cases / Ablation

设计对照是只按模型排序分数放行。真实历史失败是 `AUROC=1.000` 时仍有 30% 异常自动放行；当前门禁把候选留在 DRAFT。见 [失败记录](docs/failures/001-benchmark-no-go.md)。代码测试覆盖推理失败转复核、并发复核冲突、跨租户访问和 Connector 失败恢复。

目前没有测量“增加人工审核降低多少现场缺陷率”的组件消融。业务门禁拒绝错误候选是软件行为证据，不等于生产收益。保守门禁增加复核负担；真实客户需要单独确定可接受阈值。

## 三分钟体验

### 完全不懂代码：双击启动（macOS）

1. 安装并启动 [Docker Desktop](https://www.docker.com/products/docker-desktop/)。
2. 在项目文件夹中双击 `start-demo.command`。
3. 浏览器打开后，点击首页的“使用演示图片开始”。
4. 体验结束后双击 `stop-demo.command`。

详细截图式说明、常见问题和术语解释见 [零基础使用指南](docs/BEGINNER-GUIDE.md)。

### 熟悉终端：命令启动

```bash
cd infra
docker compose up --build
```

服务就绪后打开：

- Web UI：[http://localhost:3000](http://localhost:3000)
- API 文档：[http://localhost:8000/docs](http://localhost:8000/docs)
- Factory A/B Gateway 状态：`8091 / 8092`

推荐演示路径：

1. 在运营总览确认租户、Gateway 和待复核队列。
2. 上传异常图片，查看异常分数、热力图和策略证据。
3. 在复核工作台确认异常并触发批次暂扣。
4. 在质量事件中查看 MES/QMS 幂等动作并完成验证关闭。
5. 在 ModelOps 查看数据来源、Benchmark NO-GO 和模型 DRAFT 状态。

完整口播和镜头表见 [三分钟演示脚本](docs/DEMO-SCRIPT.md)。停止环境：

```bash
cd infra
docker compose down
```

## 可选数据来源

项目不携带、不自动下载、也不要求 Benchmark 或客户数据。

| 来源 | 用途 | 可产生的最高状态 |
| --- | --- | --- |
| `DEMO_SYNTHETIC` | Blender 可复现合成样本与默认业务演示 | `DEMO_ONLY` |
| `OFFICIAL_BENCHMARK` | 实验室基准验证 | `READY_FOR_CUSTOMER_DATA` |
| `CUSTOMER_PILOT` | 客户现场 Pilot | 完整 provenance 与 Gate 通过后才可审批 |

受控上传会检查许可证确认、扩展名、压缩包路径穿越、特殊文件、文件数量、压缩/解压大小、压缩比和内容哈希。原始数据进入租户隔离对象存储，不进入 Git 或前端静态目录。服务端挂载导入在生产环境还必须配置 `VQC_DATASET_IMPORT_ROOTS`。

### Blender 合成演示

内置晶体管样本不是不可追溯的占位图，而是由
[`tools/blender/generate_transistor_demo.py`](tools/blender/generate_transistor_demo.py)
参数化生成。脚本会输出正常样本、弯折引脚缺陷、像素掩码、检测工位全景、SHA-256 清单和可编辑 `.blend` 场景。

```bash
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python tools/blender/generate_transistor_demo.py -- \
  --output-dir frontend/public/mock/blender \
  --blend-file artifacts/blender/visionqc-inspection-station.blend
```

Blender 合成数据只用于新手演示、接口联调和流程测试，不能替代 MVTec Benchmark，更不能证明客户现场效果。完整边界见 [Blender 合成数据说明](docs/07-blender-synthetic-data.md)。

## 仓库结构

```text
backend/       FastAPI、质量工作流、RBAC、审计、数据注册、MES/QMS
edge-gateway/  稳定文件检测、图片质量门禁、SQLite 断网队列、幂等补传
frontend/      React + TypeScript 工业质量控制台
ml/            PatchCore、数据 manifest、校准、评测、模型包、Registry
infra/         Docker Compose 与 Mock 外部系统
docs/          架构、部署、验收、案例与演示材料
reports/       可公开的 Benchmark 与模型评测摘要
tools/blender/ 可复现的工业工位、产品、缺陷和掩码生成器
```

## 安全与声明边界

- 模型只提供异常证据和异常区域，不确认语义缺陷类型或根因。
- 推理失败、模型包损坏或证据不完整时进入安全复核，不自动放行。
- 暂扣、返工、报废和外部系统写操作要求确定性策略与人工权限。
- 校准只读取 validation；冻结 holdout 仅用于最终评测。
- Benchmark 和演示数据永远不能使模型进入 `APPROVED / ACTIVE`。
- 客户 Pilot 需要租户、工厂、产线、相机、产品、采集窗口、标签来源、审批、授权和保留策略。

当前明确未生产化：企业 OIDC、PostgreSQL RLS、真实相机驱动、Kafka、Kubernetes、真实 MES/QMS，以及真实客户现场效果证明。

## 作品集材料

- [系统架构与信任边界](docs/ARCHITECTURE.md)
- [As-Is / To-Be 与 48 小时客户接入案例](docs/CASE-STUDY.md)
- [Benchmark 评测报告](reports/benchmark-evaluation.md)
- [三分钟演示脚本](docs/DEMO-SCRIPT.md)
- [产品需求与系统规格](docs/01-product-requirements.md)
- [Deployment Pack 接入手册](docs/03-deployment-pack-onboarding.md)
- [现场验收测试](docs/06-site-acceptance-test.md)

## 完整回归

```bash
cd backend && uv sync --extra dev && uv run pytest -q
cd ../ml && uv sync --extra model --extra dev && uv run pytest -q
cd ../edge-gateway && uv sync --extra dev && uv run pytest -q
cd ../frontend && npm ci && npm test -- --run && npm run typecheck && npm run build
```

双客户 Compose 冒烟测试：

```bash
cd backend
uv run python ../scripts/compose_smoke.py
```

## AI-assisted Development

[AI 辅助范围与技术责任](docs/AI_ASSISTED_DEVELOPMENT.md) 说明本次代码核查、测试和文档整理方式。架构决策、评估解释与最终验收需要可查证据，历史失败和归属保持可见。
