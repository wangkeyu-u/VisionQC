# 数据与安全边界

## 租户来源

业务租户边界来自签名 JWT 的 `tenant_id`。Edge Gateway 的 tenant、pack key 和版本来自已校验 Deployment Pack；客户端 header 只能作为一致性校验，不能切换查询边界。上传请求会带 `X-Gateway-ID`、`X-Tenant-ID`、`X-Deployment-Pack` 和 `X-Deployment-Pack-Version`，服务端会与 JWT/active pack 比对。

## Edge 本地边界

USB 相机和文件夹输入先进入本地质量门禁、SQLite WAL 队列和本地 spool。文件在稳定窗口后读取；坏文件、路径不匹配、重复文件、目录错误、断网和恢复都留下可审计状态。队列使用至少一次补传和稳定幂等 key，重复输入变成 `DUPLICATE`，不重复触发 API/外部动作。

默认 `upload_enabled=false` 且 `data_consent=false`。上传客户原图前必须明确设置 consent；生产环境必须由 secret provider 注入 token。保留期、删除策略、legal hold 和本地处理默认值由 pack/overlay 声明，实际存储生命周期还需要部署平台执行。

## Connector 与日志

Connector endpoint 可以出现在配置，但 credentials 只能通过 secret ref 注入。日志、health 输出和 test report 必须做 secret redaction。外部 MES/QMS/notification/analytics 写操作要有审批、幂等、超时、重试和对账路径。所有仓库中的 external endpoint 都是 mock 或明确标为 simulated。

## 当前非生产化边界

本仓库仍把 OIDC/企业 IdP、PostgreSQL RLS、真实相机驱动、Kafka/Kubernetes、真实 MES/QMS 和生产模型资格留作部署阶段工作。高 AUROC、合成图片或 demo mock 不能成为生产批准依据；模型输出只是 anomaly evidence，风险决策仍受确定性策略和人工审批约束。
