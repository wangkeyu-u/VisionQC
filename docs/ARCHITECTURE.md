# VisionQC 系统架构

## 1. 架构目标

VisionQC 将视觉模型限制在“提供异常证据”的职责内，把业务安全交给可解释、可审计的确定性工作流。平台需要同时支持现场网络不稳定、客户字段不同、模型版本变化、人工审批和外部系统幂等写入。

## 2. 逻辑架构

```mermaid
flowchart TB
    subgraph Edge["工厂边缘域"]
        Camera["相机 / 采集文件夹"]
        Gateway["Edge Gateway\n稳定检测·质量门禁·断网队列"]
        Camera --> Gateway
    end

    subgraph Platform["VisionQC 平台域"]
        API["FastAPI / RBAC / Tenant Context"]
        Workflow["Inspection & Review Workflow"]
        Policy["Deterministic Policy Engine"]
        Inference["Stub / PatchCore Adapter"]
        Evidence["Object Evidence Store"]
        DB["PostgreSQL / Audit Log"]
        ModelOps["Qualification & Model Registry"]
        UI["React Quality Console"]

        API --> Workflow
        Workflow --> Inference
        Workflow --> Policy
        Workflow --> Evidence
        Workflow --> DB
        ModelOps --> DB
        UI --> API
    end

    subgraph Enterprise["客户企业系统域"]
        MES["MES Connector"]
        QMS["QMS Connector"]
        IdP["Enterprise IdP（未来）"]
    end

    Gateway -->|"JWT + idempotency key"| API
    Workflow -->|"审批后的幂等动作"| MES
    Workflow -->|"审批后的幂等动作"| QMS
    IdP -.->|"OIDC future scope"| API
```

## 3. 关键时序

```mermaid
sequenceDiagram
    participant G as Edge Gateway
    participant A as VisionQC API
    participant M as Model Adapter
    participant P as Policy Engine
    participant Q as Quality Engineer
    participant E as MES/QMS

    G->>A: 上传图片 + 生产上下文 + 幂等键
    A->>A: 校验租户、格式、像素和内容哈希
    A->>M: 请求异常推理
    M-->>A: score + heatmap + model identity
    A->>P: score + frozen thresholds
    P-->>A: AUTO_RELEASE / REVIEW / HOLD
    A-->>Q: 创建复核任务与证据时间线
    Q->>A: 带版本号的复核决定
    A->>E: 经确认的暂扣/工单动作
    E-->>A: 外部引用或可重试错误
    A->>A: 写入审计、反馈和关闭验证
```

## 4. 数据与模型发布门禁

```mermaid
flowchart LR
    S{"数据来源"}
    S -->|DEMO_SYNTHETIC| D["DEMO_ONLY"]
    S -->|OFFICIAL_BENCHMARK| B["Benchmark Qualification"]
    S -->|CUSTOMER_PILOT| C["Customer Provenance Gate"]
    B --> BG{"业务 Gate"}
    BG -->|失败| BN["BENCHMARK_NO_GO\nDRAFT_ONLY"]
    BG -->|通过| BR["READY_FOR_CUSTOMER_DATA"]
    C -->|缺失| CD["DRAFT / BLOCKED"]
    C -->|完整| CG{"业务 Gate + 职责分离"}
    CG -->|通过| CA["APPROVED → ACTIVE"]
    CG -->|失败| CN["NO_GO / DRAFT"]
```

## 5. 信任边界与控制

| 边界 | 主要风险 | 控制措施 |
| --- | --- | --- |
| 图片/归档进入平台 | 路径穿越、压缩炸弹、恶意格式 | 后缀白名单、特殊文件拒绝、大小/数量/压缩比限制、哈希 |
| 边缘到 API | 重放、跨租户上传、网络中断 | JWT tenant claim、幂等键、SQLite 队列、指数退避 |
| 模型到业务决策 | 幻觉式语义结论、错误自动放行 | 仅输出 anomaly evidence、冻结阈值、安全降级、人工复核 |
| 人工操作 | 越权、并发覆盖、缺乏追责 | RBAC、乐观锁、理由/确认字段、审计日志 |
| 外部系统写入 | 重复暂扣/重复工单 | Connector 幂等键、重试状态机、外部引用记录 |
| 模型发布 | 数据泄漏、测试集调参、证据篡改 | 固定 manifest、validation-only 校准、holdout 隔离、SHA-256 清单 |

## 6. 多客户适配

Deployment Pack 将客户差异从核心工作流中分离：

- 产品代码、字段映射和图片约束；
- 模型 ID、版本、包摘要和阈值策略；
- MES/QMS Connector 地址与动作映射；
- Gateway 路径、扩展名、站点与产线；
- 租户 UI 标签、风险策略和部署版本。

核心代码不根据客户名称写条件分支；运行时只加载并验证当前租户的 Pack。

## 7. 当前部署与生产化差距

当前 Docker Compose 用于可重复演示和集成验证。生产化仍需企业 OIDC、密钥托管、PostgreSQL RLS、对象存储生命周期策略、真实相机 SDK、消息总线、Kubernetes、真实 MES/QMS 沙箱和客户现场监控。

