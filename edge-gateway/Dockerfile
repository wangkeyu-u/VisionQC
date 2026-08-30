FROM python:3.12.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system visionqc && useradd --system --gid visionqc --create-home visionqc

# The image is built from the repository root so the gateway consumes the
# signed Deployment Pack files rather than a customer-specific code branch.
COPY edge-gateway/pyproject.toml ./
COPY edge-gateway/src ./src
COPY backend/deployment-packs/manifests ./configs
COPY backend/deployment-packs/industry-packs ./configs/industry-packs
COPY backend/deployment-packs/overlays ./configs/overlays
COPY backend/deployment-packs/examples ./configs/examples
COPY backend/deployment-packs/schemas ./configs/schemas

RUN pip install --upgrade pip && pip install . \
    && mkdir -p /var/lib/visionqc-gateway \
    && chown -R visionqc:visionqc /app /var/lib/visionqc-gateway

USER visionqc

EXPOSE 8090
CMD ["uvicorn", "edge_gateway.main:app", "--host", "0.0.0.0", "--port", "8090"]
