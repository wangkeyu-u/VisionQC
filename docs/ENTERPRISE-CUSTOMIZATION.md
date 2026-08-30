# 企业定制指南

## 配置层次

把稳定的行业共性放进 `backend/deployment-packs/industry-packs/*.json`，把客户现场差异放进 overlay：

```text
Industry Pack (electronics / packaging / automotive-paint)
        + tenant/site overlay (tenant, site, product, station, collection)
        -> resolved Deployment Pack v2
        -> API bootstrap / Edge Gateway / Connector registry
```

overlay 可以覆盖产品、工位、字段标签、术语、采集规则、模型引用、风险策略、工作流、Connector、权限、保留期、本地化和 edge gateway 绑定。通用领域状态机不应出现 `if tenant == ...`；如果差异无法由合同表达，应先提升为平台能力并补充兼容测试。

## 推荐接入步骤

1. 选一个最接近的 Industry Pack；不要从客户名称创建新的代码分支。
2. 用 `scripts/visionqc.py init-tenant` 生成 overlay。
3. 由现场确认字段、产品/工位目录、文件夹或相机合同、时区、语言、保留期和审批角色。
4. 运行 `validate-pack`，审阅 schema、完整性 hash、迁移说明和 connector contract。
5. 在现场运行 `preflight`，先使用 `--skip-network` 检查本地边界，再用 approved endpoint 做网络检查。
6. 用 `industry_pack_smoke.py` 和客户自己的 mock contract test 验证，再进入 deployment approval。
7. 注入真实 secret ref、OIDC token 和连接器 endpoint；这些值不能写进 pack、Git、测试输出或日志。

## 不应写入配置的内容

不要把密码、Bearer token、私钥、数据库密码、对象存储 secret、真实客户原图或未经授权的 API URL 写进 JSON。pack 只保存 secret ref，例如 `VQC_MES_API_TOKEN`；实际值由运行环境的 secret provider 提供。CLI 的 `.env.example` 只保留占位符。

## 变更与回滚

每个 overlay 和 resolved pack 都应作为不可变版本审阅。激活新版本前保存旧版本；回滚是重新激活上一个已批准 pack，不修改历史 inspection 的 pack/model/policy snapshot。现场变更至少需要 FDE 校验和质量负责人批准，外部写操作需要单独的审批角色。

## 现场预检的修复语言

常见问题及动作：

- USB 不存在：连接相机、授予操作系统相机权限，或切换到 folder watch；
- 采集目录不是文件夹：选择一个可读写目录，不要把普通文件作为 watch root；
- 端口被占用：换 `VQC_GATEWAY_STATUS_PORT` 或停止占用该端口的进程；
- Connector 不可达：确认 DNS、TLS、代理、allow-list 和 health path；
- secret ref 缺失：在 secret provider 中创建对应名称，不要把值粘贴到 pack；
- 重复文件：保留队列中的 `DUPLICATE` 审计记录，不重复触发外部动作。
