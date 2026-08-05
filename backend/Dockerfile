FROM python:3.12.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system visionqc && useradd --system --gid visionqc --create-home visionqc

COPY pyproject.toml ./
COPY app ./app
COPY migrations ./migrations
COPY deployment-packs ./deployment-packs
COPY alembic.ini ./

RUN pip install --upgrade pip && pip install .

RUN mkdir -p /var/lib/visionqc && chown -R visionqc:visionqc /app /var/lib/visionqc
USER visionqc

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
