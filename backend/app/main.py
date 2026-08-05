from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response

from app.api import router
from app.bootstrap import bootstrap_defaults
from app.config import Settings, get_settings
from app.connectors import Connector, HttpConnector, InMemoryConnector
from app.database import build_engine, build_session_factory
from app.model_adapter import build_model_adapter
from app.schemas import ErrorBody
from app.services import ServiceError, VisionQCService
from app.storage import build_storage

logger = logging.getLogger("visionqc")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or get_settings()
    engine = build_engine(resolved.database_url)
    session_factory = build_session_factory(engine)
    storage = build_storage(resolved)
    model_adapter = build_model_adapter(
        backend=resolved.model_backend,
        package_path=resolved.model_package_path,
        device=resolved.model_device,
    )
    if resolved.environment == "test":
        connectors: dict[str, Connector] = {
            "MES": InMemoryConnector("mes"),
            "QMS": InMemoryConnector("qms"),
        }
    else:
        connectors = {
            "MES": HttpConnector("mes", resolved.mes_base_url),
            "QMS": HttpConnector("qms", resolved.qms_base_url),
        }
    service = VisionQCService(
        settings=resolved,
        session_factory=session_factory,
        storage=storage,
        model_adapter=model_adapter,
        connectors=connectors,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        with session_factory() as session:
            bootstrap_defaults(session, resolved)
            session.commit()
        yield
        engine.dispose()

    app = FastAPI(
        title="VisionQC API",
        version="0.1.0",
        description=(
            "Industrial anomaly evidence and human-accountable quality workflow. "
            "An anomaly is not a confirmed semantic defect."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.service = service

    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved.parsed_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "Idempotency-Key",
            "X-Correlation-ID",
            "X-Gateway-ID",
        ],
        expose_headers=["X-Correlation-ID"],
    )

    @app.middleware("http")
    async def correlation_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied = request.headers.get("X-Correlation-ID")
        request.state.correlation_id = supplied[:128] if supplied else f"corr_{uuid.uuid4().hex}"
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        return response

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        body = ErrorBody(
            code=exc.code,
            message=exc.message,
            correlation_id=request.state.correlation_id,
            details=exc.details,
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        body = ErrorBody(
            code="request_validation_error",
            message="request did not satisfy the API schema",
            correlation_id=request.state.correlation_id,
            details={"errors": jsonable_encoder(exc.errors())},
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, Any]:
        checks = {"database": False, "storage": storage.healthcheck()}
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception:
            logger.exception("database health check failed")
        return {"status": "ok" if all(checks.values()) else "degraded", "checks": checks}

    app.include_router(router)
    return app


app = create_app()
