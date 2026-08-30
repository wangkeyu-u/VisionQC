# Industry Pack 与 Deployment Pack 规范

## Schema 版本

当前合同分为三层：

- `visionqc.industry-pack.v1`：可复用行业默认值；
- `visionqc.tenant-overlay.v1`：客户/工厂/现场覆盖值；
- `visionqc.deployment-pack.v2`：解析后的运行时配置。

旧的 `visionqc.deployment-pack.v1` 仍可读取。迁移不应破坏历史记录；需要新字段时保留后向兼容默认值，并在 `migration` 中说明来源、策略和人工动作。

## Industry Pack 必须包含

每个 pack 至少要有：

| 区域 | 内容 |
| --- | --- |
| identity | `pack_key`、版本、显示名、行业和描述 |
| catalog | 产品、版本、别名和工位 |
| context | canonical 字段映射、字段标签、术语 |
| collection | API/folder/USB 模式、文件合同、相机、队列和隐私默认值 |
| model | 模型 ID/版本/引用、运行时、hash 或未定级声明 |
| risk/workflow | 阈值、fail-safe 路由、人审和外部动作状态 |
| connectors | ingest、MES、QMS、notification、analytics 的 capability/contract/操作 |
| governance | 权限、审批、保留期、本地化和迁移说明 |
| integrity | canonicalization、算法、hash、排除字段 |

参考文件是 `backend/deployment-packs/industry-packs/electronics.json`、`packaging.json` 和 `automotive-paint.json`。三个文件都明确声明是可复用配置，不暗示客户已经接入。

## Overlay 必须绑定

overlay 的 `industry_pack` 同时 pin `key`、版本和 Industry Pack SHA-256；解析器拒绝 hash 不一致的 pack。`tenant.id`、`site.id`、产品/工位和 `edge_gateway.target_tenant_id` 必须一致。解析产物带有 industry/overlay reference、完整性 hash 和 `schema_version`。

## 完整性计算

完整性使用 UTF-8、JSON sort keys、无空白分隔符的 SHA-256。计算前只移除 `integrity.manifest_sha256` 自身；因此改动任何合同字段都会使 hash 失效。验证入口：

```bash
cd backend
uv run python ../scripts/visionqc.py validate-pack deployment-packs/industry-packs
```

生产交付还应把 pack hash、模型包 hash、镜像 digest 和审批记录绑定到发布单。
