# VisionQC Deployment Pack 接入与企业部署手册

本文档说明如何把 VisionQC 从固定演示升级为可复用的客户接入单元。Deployment Pack 是一份版本化、可校验、租户绑定的配置合同；业务工作流只接收 canonical context，不包含客户条件分支。

## 1. 交付边界

一个 Deployment Pack 必须同时定义：

- 客户和 pack key：`tenant.id`、`pack_key`、版本和接入模式。
- 产品目录和工位目录：允许的产品代码/别名、版本、工位、相机 profile。
- 字段映射：canonical 的 `product_code`、`product_revision`、`batch_no`、`station_code`、`captured_at`、`source` 到客户入站字段的映射。
- 模型证据元数据：模型 ID、版本、特征库版本、适配器、包 URI、运行时和限制。
- 策略：默认复核/暂扣阈值以及按产品/工位的覆盖规则。
- Connector 合同：显示名、驱动、外部合同版本、端点、canonical→外部字段映射、固定字段和允许操作。
- Edge Gateway 合同（若启用目录采集）：`gateway_id`、`target_tenant_id`、监听根目录、相对路径/文件名正则、capture map、默认上下文、稳定窗口和模拟器模板。

当前仓库的示例位于：

- `backend/deployment-packs/manifests/factory-a-transistor.json`
- `backend/deployment-packs/manifests/factory-b-bottle.json`

边缘网关的运行与故障排查见 [工业边缘采集网关部署与运维手册](04-edge-gateway-deployment.md)。Gateway 只读取当前 pack 的 tenant/product/station/field mapping，不在代码里写客户条件分支。

Factory B 刻意使用 `sku / lot_id / cell`，瓶体模型元数据、阈值和 `FlowMES / QualityHub` 合同也不同；它不是通过 `if tenant == factory-b` 实现的。

## 2. 接入新客户流程

### 2.1 创建 manifest

复制一份示例并修改客户数据。不要把密码、Bearer token、数据库连接串或对象存储密钥放进 manifest。Connector 的 `endpoint`、固定字段和映射可以提交，凭据必须由部署环境的 secret provider 注入。

### 2.2 离线校验

在提交代码或交付包前运行：

```bash
python scripts/validate_deployment_pack.py \
  backend/deployment-packs/manifests/factory-a-transistor.json \
  backend/deployment-packs/manifests/factory-b-bottle.json
```

校验器会执行 JSON/Pydantic 合同、产品/工位唯一性、字段映射唯一性、策略阈值顺序、策略覆盖冲突和 MES/QMS 合同结构检查。同一批输入不允许出现两个相同 tenant 或 pack key。

### 2.3 创建、预检查和激活

交付系统应以当前租户的 FDE/管理员身份调用：

```text
POST /api/v1/deployments
POST /api/v1/deployments/{deployment_id}/activate
GET  /api/v1/tenant-context
GET  /api/v1/deployments
```

`POST /deployments` 的推荐 body 是 `{ "manifest": <validated manifest> }`。服务端再次校验 manifest 的 tenant ID 和名称必须与 JWT 的 `tenant_id` 及租户注册表一致。激活前会检查策略解析、对象存储、模型运行时、MES 和 QMS health；失败时现有 ACTIVE pack 不变。

激活是租户内切换：旧 pack 进入 `RETIRED`，历史检测仍保留其 `deployment_pack_id`、模型和策略快照，新检测只绑定激活时的 pack。回滚通过激活上一份已校验的 pack 完成，不修改历史结果。

## 3. 租户安全边界

业务租户只来自已签名 JWT 的 `tenant_id` claim。前端的 `X-Tenant-ID`、query parameter 或表单字段不会改变查询边界；API 的所有检测、证据、复核、事件、审计和 Deployment Pack 查询都按该 claim 过滤。

演示环境为展示客户切换提供：

```text
POST /api/v1/auth/switch-tenant { "tenant_id": "factory-b" }
```

它只在 `demo/test` 环境、显式 allow-list（`VQC_DEMO_SWITCHABLE_TENANT_IDS`）和 FDE/管理员角色下工作，返回一个带目标租户 claim 的新短期 JWT。生产环境关闭该接口；生产切换应由 OIDC/企业 IdP 的 membership + step-up 流程签发目标租户 token。不得把租户选择实现为可被浏览器任意设置的 header。

## 4. 默认 Compose 验收

默认演示仍然是单命令启动：

```bash
cd infra
docker compose up --build
```

Compose 会 bootstrap Factory A 和 Factory B，默认模型仍使用轻量 deterministic stub，因此不需要下载大模型。完整冒烟测试通过前端反向代理，并验证：

1. A 的 `product_code / batch_no / station_code` 入站字段、模型 `patchcore-transistor`、A 策略和 A Connector。
2. 使用安全租户切换得到 B token。
3. B 的 `sku / lot_id / cell` 字段、模型 `patchcore-bottle`、不同阈值和不同 Connector 合同。
4. 两个租户分别完成手动上传或目录 Gateway 上传 → 推理 → 复核 → MES/QMS → 关闭。
5. B token 读取 A 的检测和对象证据均返回 404；A 原 token 不会因切换而改变。

```bash
cd backend
uv sync --extra dev
uv run python ../scripts/compose_smoke.py
```

## 5. 生产化替换清单

- 用 OIDC/JWT issuer、租户 membership 和短期 token 替换 demo token/switch endpoint。
- 为每个客户注册实际 PatchCore 包并运行 `ml/configs/patchcore-<product>.yaml` 对应的固定数据、校准、评测和 package integrity verification。
- 将 `ModelAdapter` 扩展为按 `deployment_pack_id` 选择已审批模型包的 registry/worker pool；当前 Compose 的 stub 共享一个轻量运行时，但推理结果使用 pack 的模型证据元数据。
- 将 Connector 端点和 secret 绑定到 secret manager；manifest 和审计只保存脱敏摘要。
- 为每个工位部署一个 tenant-scoped Edge Gateway 进程/容器；生产模式只接受 secret provider 注入的 `edge_gateway` token，不允许 demo mint token。
- 为 Gateway 的 SQLite WAL、spool 和 `.quarantine` 目录配置持久卷与备份；演练断网、进程重启、上传 5xx/429 和相机半写文件恢复。
- 监控 Gateway heartbeat age、queue depth、上传成功/失败、质量拒绝原因和重复样本，不把质量门禁拒绝统计为模型缺陷。
- 使用 PostgreSQL 行级安全或独立 schema 作为纵深防御，并在网关、对象存储和日志管道复测跨租户边界。
- 为真实 MES/QMS 运行共享 Connector 合同测试、幂等重试测试、timeout-after-commit 和对账恢复演练。
- 迁移完成后锁定 Deployment Pack、模型包、数据库迁移和容器镜像 digest，记录审批人和回滚 pack。

## 6. FDE 接入度量

本轮第二客户适配新增一份 manifest、两份 bottle 数据/训练配置示例、共享字段解析器和 Connector payload mapper；核心质量状态机没有客户条件分支。验收重点是“新增客户主要改配置、模型包和 Connector 合同”，若下一客户要求增加不可配置差异，应先把差异提升为平台能力并补充共享合同。
