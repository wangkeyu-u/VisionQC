# VisionQC

**工业视觉异常检测与质量处置闭环平台**

VisionQC 不止回答“图片是否异常”，还负责检测之后的企业流程：证据留存、双阈值路由、人工复核、批次暂扣、MES/QMS 动作、模型发布门禁和全链路审计。项目以 Forward Deployed Engineer 的交付方式设计，可通过 Deployment Pack 适配不同工厂的产品、字段、策略和 Connector。

> 当前定位：可运行的企业级作品集 / Pre-Pilot MVP。默认使用演示数据；MVTec 仅作为非商业公开基准，不代表任何工厂现场效果。

![VisionQC 运营总览](docs/portfolio/overview-1440.png)

## 为什么不是普通缺陷检测 Demo

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

### 自动化验证

| 模块 | 当前结果 |
| --- | ---: |
| Backend | 37 passed + Ruff + MyPy |
| ML | 36 passed + Ruff + MyPy |
| Edge Gateway | 17 passed + Ruff |
| Frontend | 7 passed + TypeScript + production build |
| 双客户闭环 | Factory A/B 全链路与跨租户隔离通过 |

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
| `DEMO_SYNTHETIC` | 默认业务演示 | `DEMO_ONLY` |
| `OFFICIAL_BENCHMARK` | 实验室基准验证 | `READY_FOR_CUSTOMER_DATA` |
| `CUSTOMER_PILOT` | 客户现场 Pilot | 完整 provenance 与 Gate 通过后才可审批 |

受控上传会检查许可证确认、扩展名、压缩包路径穿越、特殊文件、文件数量、压缩/解压大小、压缩比和内容哈希。原始数据进入租户隔离对象存储，不进入 Git 或前端静态目录。服务端挂载导入在生产环境还必须配置 `VQC_DATASET_IMPORT_ROOTS`。

## 仓库结构

```text
backend/       FastAPI、质量工作流、RBAC、审计、数据注册、MES/QMS
edge-gateway/  稳定文件检测、图片质量门禁、SQLite 断网队列、幂等补传
frontend/      React + TypeScript 工业质量控制台
ml/            PatchCore、数据 manifest、校准、评测、模型包、Registry
infra/         Docker Compose 与 Mock 外部系统
docs/          架构、部署、验收、案例与演示材料
reports/       可公开的 Benchmark 与模型评测摘要
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
- [简历写法与面试讲解](docs/RESUME.md)
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
