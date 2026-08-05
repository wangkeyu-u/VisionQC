from __future__ import annotations

import io
from collections.abc import Callable, Generator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app.auth import Role, create_access_token
from app.config import Settings
from app.database import Base
from app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment="test",
        database_url=f"sqlite+pysqlite:///{tmp_path / 'visionqc-test.db'}",
        auth_secret=SecretStr("test-secret-with-sufficient-entropy"),
        local_storage_path=tmp_path / "assets",
        storage_backend="local",
        process_inline=True,
        connector_backoff_seconds=0,
        bootstrap_enabled=True,
    )


@pytest.fixture
def app(settings: Settings):
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    yield application
    Base.metadata.drop_all(application.state.engine)
    application.state.engine.dispose()


@pytest.fixture
def client(app) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def token_factory(settings: Settings) -> Callable[..., str]:
    def make_token(
        *,
        actor_id: str = "inspector-1",
        tenant_id: str = "factory-a",
        roles: list[Role | str] | None = None,
    ) -> str:
        return create_access_token(
            settings,
            actor_id=actor_id,
            tenant_id=tenant_id,
            roles=roles or [Role.INSPECTOR],
        )

    return make_token


@pytest.fixture
def auth_headers(token_factory: Callable[..., str]) -> Callable[..., dict[str, str]]:
    def make_headers(**kwargs: Any) -> dict[str, str]:
        token = token_factory(**kwargs)
        return {"Authorization": f"Bearer {token}"}

    return make_headers


@pytest.fixture
def png_bytes() -> Callable[[int], bytes]:
    def make_png(luminance: int) -> bytes:
        output = io.BytesIO()
        Image.new("RGB", (16, 16), (luminance, luminance, luminance)).save(output, format="PNG")
        return output.getvalue()

    return make_png


@pytest.fixture
def upload_inspection(client: TestClient, auth_headers, png_bytes):
    def upload(
        luminance: int,
        *,
        idempotency_key: str,
        tenant_id: str = "factory-a",
        actor_id: str = "inspector-1",
        roles: list[Role | str] | None = None,
    ):
        headers = auth_headers(actor_id=actor_id, tenant_id=tenant_id, roles=roles)
        headers["Idempotency-Key"] = idempotency_key
        fields = (
            {
                "sku": "bottle",
                "revision": "B-2026.07",
                "lot_id": "LOT-B-001",
                "cell": "CELL-12",
                "captured_at": "2026-08-04T10:00:00Z",
                "source_system": "pytest",
            }
            if tenant_id == "factory-b"
            else {
                "product_code": "transistor",
                "product_revision": "REV-C",
                "batch_no": "BATCH-001",
                "station_code": "ST-01",
                "captured_at": "2026-08-04T10:00:00Z",
                "source": "pytest",
            }
        )
        return client.post(
            "/api/v1/inspections",
            headers=headers,
            files={"image": ("sample.png", png_bytes(luminance), "image/png")},
            data=fields,
        )

    return upload


@pytest.fixture
def db_session(app) -> Generator[Session, None, None]:
    with app.state.session_factory() as session:
        yield session
