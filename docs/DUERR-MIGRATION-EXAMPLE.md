# 从 Dürr 定制迁移为示例

本页只说明如何把一个客户化 automotive-paint 场景表达成 overlay；它不是 Dürr 产品说明，不是官方集成，也不包含任何私有 API、凭据或客户数据。

## 迁移方式

1. 以中性的 `automotive-paint` Industry Pack 作为基线。
2. 创建一个独立 overlay，例如 `backend/deployment-packs/overlays/examples/duerr-concept.json`。
3. 只在 overlay 中声明车身/工件字段、paint shop/booth/line 上下文、现场术语、审批和保留期差异。
4. 如果需要概念质量闭环，显式选择 `dxq_mock`，并把 `simulated=true`、contract version 和无官方 API 声明一起保留。
5. 解析、校验、预检和 smoke 通过后，仍不能把该配置标为客户已接入或生产批准。

```bash
cd backend
uv run python ../scripts/visionqc.py validate-pack \
  deployment-packs/industry-packs/automotive-paint.json \
  deployment-packs/overlays/examples/duerr-concept.json
```

该 overlay 的作用是证明客户差异可以留在配置和 connector seam 中，而不是让默认 README、Compose 或业务代码变成品牌专属产品。真实接入必须另行获得授权、协议、网络和数据处理确认。
