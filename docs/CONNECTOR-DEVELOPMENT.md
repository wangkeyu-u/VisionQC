# Connector SDK 与开发指南

Connector 是能力边界，不是客户名称。当前稳定 capability 包括 `ingest`、`mes`、`qms`、`notification` 和 `analytics`。连接器注册表为每个实现保存 `ConnectorSpec`：驱动、contract version、endpoint、health path、操作、timeout、retry policy、idempotency header、secret refs 和 simulated 标记。

## 最小接口

```python
class Connector:
    def healthcheck(self) -> bool: ...
    def execute(
        self, operation: str, payload: dict[str, object], idempotency_key: str
    ) -> ConnectorResult: ...
    def get_status(self, external_reference: str) -> ConnectorResult: ...
```

使用 `ConnectorRegistry.register()` 注册名字和 spec；业务服务按 capability/registry 取实现，不按客户名称分支。`RetryingConnectorExecutor` 只重试明确的 retryable error；指数退避有上限，最终失败返回 attempts 和可审计错误。

## Contract 约束

- 每个写操作必须接收稳定的 `Idempotency-Key`；timeout-after-commit 后重试不得创建第二条业务记录；
- 只把允许的 operations 写入 spec，未知 operation 直接是 terminal error；
- health check、timeout、429/5xx、网络断开和冲突要区分；冲突进入人工对账；
- payload 使用 canonical context 映射，不能把原图或 secret 放进日志；
- `secret_refs` 只保存名称和环境变量名。`redact_secrets()` 用于日志、测试报告和审计摘要；
- 所有新实现都要有 neutral contract test、schema/缺字段测试、失败重试测试、幂等 replay 测试和跨租户 key 测试。

## Mock 边界

`generic_qms_mock` 是完全中性的 QMS simulated connector，contract 为 `generic-qms-case.v1`，用于证明平台不依赖任何品牌或客户。`dxq_mock` 仍存在，但只作为 automotive-paint 下的独立 concept 示例，绝不等于官方或私有 API。

运行后端 connector contract tests：

```bash
cd backend
uv run pytest -q tests/test_connector_registry.py
```

真实 Connector 只有在客户合同、认证、网络边界、数据处理协议和回滚策略批准后才替换 mock endpoint；仓库不伪造真实客户集成。
