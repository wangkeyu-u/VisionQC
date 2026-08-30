# VisionQC Compose 部署

默认的可配置入口是 `edge-gateway-selected`。它通过 `VQC_GATEWAY_PACK_PATH` 选择 resolved Deployment Pack；`VQC_GATEWAY_ID` 可使用 `gateway-local`（本地配置选择器）或 pack 中声明的 gateway id。

```bash
VQC_GATEWAY_PACK_PATH=/app/configs/examples/electronics-transistor/resolved-deployment-pack.json \
VQC_GATEWAY_ID=gateway-local \
docker compose -f infra/docker-compose.yml up --build api frontend edge-gateway-selected
```

三个行业示例是 opt-in profile：

```bash
docker compose -f infra/docker-compose.yml --profile industry-examples up --build api \
  edge-gateway-electronics-example edge-gateway-packaging-example \
  edge-gateway-automotive-paint-example

python scripts/compose_industry_smoke.py
```

示例默认关闭原图上传和 consent，外部服务是本地 simulated mock。Compose 仅验证本地开发边界；生产部署需要 secret provider、TLS、身份提供商、持久卷、网络 allow-list、备份和现场审批。
