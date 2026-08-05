# VisionQC backend

The backend is a FastAPI modular monolith backed by PostgreSQL and an outbox worker. It deliberately treats model output as anomaly evidence, never as a confirmed semantic defect.

## Local test

```bash
cd backend
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

## Compose

```bash
docker compose -f infra/docker-compose.yml up --build
```

OpenAPI is available at `http://localhost:8000/docs`; Mock MES/QMS is at `http://localhost:8081/docs`.

Business endpoints require an HS256 JWT whose claims include `sub`, `tenant_id`, `roles`, and issuer `visionqc`. Generate a local token with `app.auth.create_access_token`; do not use the compose development secret outside local/demo environments.

The upload endpoint is multipart and requires `Idempotency-Key`, `image`, `product_code`, `batch_no`, `station_code`, and `captured_at`. Worker delivery and Connector writes are at-least-once; domain uniqueness and stable idempotency keys make their effects exactly-once from the business perspective.

## Optional dataset source contract

The application starts without a dataset and reports the built-in
`DEMO_SYNTHETIC` source as `DEMO_ONLY`. Optional sources use the same
`DatasetSource` / `DatasetRegistration` contract exposed by the API:

- `OFFICIAL_BENCHMARK`: `POST /api/v1/datasets/registrations` or the multipart
  upload endpoint. The request must acknowledge the MVTec license; the backend
  streams the source, rejects unsafe archive members, validates the category
  layout and extension/size/compression limits, and records immutable
  manifest/source SHA-256 values. MVTec is **Benchmark Qualification /
  Pre-Pilot Lab Validation**, not factory or customer evidence.
- `CUSTOMER_PILOT`: the source may be registered as `DRAFT`, but Pilot approval
  is blocked until tenant, site, line, camera, product, capture window, label
  source, approver, consent and retention provenance are complete and consent
  is true.

Raw bytes are stored below the configured local object-storage root or S3
adapter, never in Git or frontend static assets. Revocation changes lifecycle
state and appends an audit event; it does not rewrite the fingerprint recorded
by an existing evidence package. Dataset listing, binding and revocation are
tenant-scoped.

## Edge Gateway integration

The standalone `../edge-gateway` process uses a tenant-scoped JWT with the
`edge_gateway` role to call `POST /api/v1/inspections` and
`POST /api/v1/gateways/heartbeat`. It never submits a tenant selector. Human
operators can read their own tenant's `GET /api/v1/gateways/status` dashboard;
cross-tenant gateway and inspection reads remain filtered by the signed JWT
claim.
