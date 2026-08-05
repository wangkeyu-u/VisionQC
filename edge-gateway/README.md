# VisionQC Edge Gateway

`edge-gateway` is a standalone Python process for a factory workstation. It watches a Deployment Pack-defined directory contract, waits for files to stop changing, runs local image input quality gates, and sends accepted images to VisionQC through the tenant-scoped upload API.

The gateway never accepts a tenant ID from a filename, form field, or browser header. The target tenant comes from the signed Deployment Pack and the JWT supplied by the deployment environment. In `demo` mode it may mint a five-minute `edge_gateway` token from the local shared secret; `production` mode refuses to start without `VQC_GATEWAY_AUTH_TOKEN` injected by an IdP/secret provider.

## Local run

```bash
cd edge-gateway
uv sync --extra dev
VQC_GATEWAY_PACK_PATH=../backend/deployment-packs/manifests/factory-a-transistor.json \
VQC_GATEWAY_WATCH_ROOT=/tmp/visionqc-factory-a \
VQC_GATEWAY_BACKEND_URL=http://localhost:8000/api/v1 \
uv run uvicorn edge_gateway.main:app --host 127.0.0.1 --port 8090
```

The local API is `GET /status`, `GET /queue?limit=100`, and `POST /queue/{id}/retry`. The status API binds to localhost by default; production mode also requires `VQC_GATEWAY_STATUS_TOKEN` before the API can start.

## Simulator

The simulator uses the same pack rules as the gateway and does not require a camera:

```bash
uv run python -m edge_gateway.simulator \
  --pack ../backend/deployment-packs/manifests/factory-a-transistor.json \
  --root /tmp/visionqc-factory-a \
  --kind normal anomaly dark overexposed corrupt duplicate \
  --count 12 --interval 0.5
```

Use `--continuous` for a continuous directory source. `normal`, `anomaly`, `dark`, `overexposed`, `blurry`, `corrupt`, `jpeg`, and `duplicate` are supported sample kinds.

## Durable behavior

- Stable-file detection requires an unchanged size and mtime for the pack's `stable_for_seconds` window, then rechecks the file before reading it.
- Every accepted input is copied atomically to a local spool before it is eligible for upload.
- SQLite WAL stores every accepted, rejected, duplicate, uploading, failed, and uploaded observation.
- The idempotency key is SHA-256 over tenant, pack version, image content hash, and canonical context. Duplicate files are recorded as `DUPLICATE` and are never uploaded a second time.
- Network/5xx failures remain in the queue with exponential backoff. A process restart converts `UPLOADING` rows back to retryable failures.
- Quality failures are durable `REJECTED` rows with a reason code and metrics. They are input-quality decisions, not semantic defect decisions.

## Configuration boundary

Factory A and Factory B use different folder and filename contracts in the checked-in Deployment Packs. The gateway code only evaluates `relative_path_regex`, `filename_regex`, `capture_map`, `defaults`, and `field_mapping`; it contains no customer ID branch.
