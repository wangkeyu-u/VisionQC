# VisionQC 平台快速开始

VisionQC 是配置优先的工业视觉质量闭环平台。`Industry Pack` 提供某个行业的可复用默认值；`tenant/site overlay` 绑定一个客户、工厂、产品、工位和现场采集规则；解析后的 Deployment Pack 才是 edge 和 API 运行时读取的配置。切换客户只需要切换配置路径，不需要改源代码或 fork 仓库。

## 1. 生成一个客户配置

在仓库根目录运行以下命令。命令只生成 JSON 配置和 `.env.example`，不会生成真实秘密：

```bash
cd backend
uv sync --extra dev
uv run python ../scripts/visionqc.py init-tenant \
  --industry electronics \
  --tenant-id acme-electronics \
  --tenant-name "Acme Electronics" \
  --site-id site-shanghai-01 \
  --product-code transistor \
  --station-code ST-07 \
  --output-dir deployment-packs/tenants/acme-electronics
```

可选行业是 `electronics`、`packaging` 和 `automotive-paint`。生成目录包含：

- `tenant-overlay.json`：客户可审阅、可版本化的覆盖配置；
- `resolved-deployment-pack.json`：供运行时消费的完整配置；
- `.env.example`：路径、端口和 secret ref 的示例，不包含 secret value。

## 2. 校验和现场预检

```bash
uv run python ../scripts/visionqc.py validate-pack \
  deployment-packs/tenants/acme-electronics

uv run python ../scripts/visionqc.py preflight \
  --pack deployment-packs/tenants/acme-electronics/resolved-deployment-pack.json \
  --watch-root /tmp/acme-electronics-incoming \
  --data-dir /tmp/acme-electronics-state \
  --skip-network
```

`preflight` 会检查依赖、目录读写权限、端口、相机（启用时）、secret ref 和 Connector 可达性；每个失败项都给出普通人可执行的修复建议。`--skip-network` 只适合离线演示，生产预检应验证真实的 approved endpoint。

## 3. 启动 edge

最小 edge 进程只需要一个配置路径：

```bash
cd edge-gateway
uv sync --extra dev
VQC_GATEWAY_PACK_PATH=../backend/deployment-packs/tenants/acme-electronics/resolved-deployment-pack.json \
VQC_GATEWAY_ID=gateway-local \
VQC_GATEWAY_WATCH_ROOT=/tmp/acme-electronics-incoming \
VQC_GATEWAY_DATA_DIR=/tmp/acme-electronics-state \
uv run uvicorn edge_gateway.main:app --host 127.0.0.1 --port 8090
```

默认是本地处理：`VQC_GATEWAY_UPLOAD_ENABLED=false`。只有同时显式设置上传和 `VQC_GATEWAY_DATA_CONSENT=true` 才会发送客户原图；生产模式还必须注入短期 token 和状态 token。

## 4. Compose 选择租户

Compose 内的 `edge-gateway-selected` 是环境变量控制的入口：

```bash
cd infra
VQC_GATEWAY_PACK_PATH=/app/configs/examples/packaging-bottle/resolved-deployment-pack.json \
VQC_GATEWAY_ID=example-packaging-gateway \
docker compose up --build api frontend edge-gateway-selected
```

三个无品牌 synthetic configuration 示例可用 profile 一起启动：

```bash
docker compose --profile industry-examples up --build api \
  edge-gateway-electronics-example \
  edge-gateway-packaging-example \
  edge-gateway-automotive-paint-example

python ../scripts/compose_industry_smoke.py
```

离线、无需 Docker 的完整三行业检查是：

```bash
cd backend
uv run python ../scripts/industry_pack_smoke.py
```

这不是客户现场验收，也不证明模型效果；它只证明配置合同、edge 边界和 neutral mock connector 可以贯通。
