from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, SecretStr

from edge_gateway.config import GatewaySettings, get_settings
from edge_gateway.deployment import GatewayDeploymentPack
from edge_gateway.queue import QueueItem
from edge_gateway.runtime import GatewayRuntime


class GatewayQueueItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    original_filename: str
    content_sha256: str | None
    idempotency_key: str | None
    context: dict[str, str]
    attempts: int
    next_attempt_at: str | None
    error_code: str | None
    last_error: str | None
    rejection_reason: str | None
    inspection_id: str | None
    dedup_of_id: int | None
    created_at: str
    updated_at: str


class GatewayStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    gateway_id: str
    tenant_id: str
    pack_key: str
    pack_version: str
    gateway_version: str
    station_code: str
    status: str
    backend_reachable: bool
    queue_depth: int
    queue_counts: dict[str, int]
    last_heartbeat_at: str | None
    last_upload_succeeded_at: str | None
    last_upload_failed_at: str | None
    recent_error: dict[str, Any] | None
    recent_errors: list[dict[str, Any]]


def _item_response(item: QueueItem) -> GatewayQueueItemResponse:
    return GatewayQueueItemResponse(
        id=item.id,
        status=item.status,
        original_filename=item.original_filename,
        content_sha256=item.content_sha256,
        idempotency_key=item.idempotency_key,
        context=item.context,
        attempts=item.attempts,
        next_attempt_at=item.next_attempt_at,
        error_code=item.error_code,
        last_error=item.last_error,
        rejection_reason=item.rejection_reason,
        inspection_id=item.inspection_id,
        dedup_of_id=item.dedup_of_id,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _status_guard(request: Request) -> None:
    settings: GatewaySettings = request.app.state.settings
    configured: SecretStr | None = settings.status_token
    if configured is None:
        return
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {configured.get_secret_value()}"
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="gateway status authentication required")


def create_app(
    settings: GatewaySettings | None = None, runtime: GatewayRuntime | None = None
) -> FastAPI:
    resolved = settings or get_settings()
    pack_path = resolved.pack_path
    if not pack_path.is_absolute() and not pack_path.exists():
        repository_root = Path(__file__).resolve().parents[3]
        candidates = [
            repository_root
            / (
                "backend/deployment-packs/examples/electronics-transistor/"
                "resolved-deployment-pack.json"
            ),
            repository_root / "backend/deployment-packs/manifests" / pack_path.name,
        ]
        for candidate in candidates:
            if candidate.exists():
                pack_path = candidate
                break
    pack = GatewayDeploymentPack.load(pack_path)
    resolved.gateway_id = (
        pack.gateway_id if resolved.gateway_id == "gateway-local" else resolved.gateway_id
    )
    active_runtime = runtime or GatewayRuntime(resolved, pack)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.worker_stop = asyncio.Event()

        async def loop() -> None:
            while not app.state.worker_stop.is_set():
                await asyncio.to_thread(active_runtime.run_cycle)
                try:
                    await asyncio.wait_for(
                        app.state.worker_stop.wait(), timeout=resolved.poll_interval_seconds
                    )
                except TimeoutError:
                    pass

        task = asyncio.create_task(loop())
        try:
            yield
        finally:
            app.state.worker_stop.set()
            await task
            active_runtime.close()

    app = FastAPI(
        title="VisionQC Edge Gateway",
        version=resolved.version,
        description=(
            "Tenant-scoped industrial directory gateway. Quality rejection is an input gate; "
            "model output remains anomaly evidence and is never a semantic defect verdict."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.runtime = active_runtime

    @app.get("/healthz", response_model=GatewayStatusResponse)
    def healthz(_: None = Depends(_status_guard)) -> GatewayStatusResponse:
        return GatewayStatusResponse.model_validate(active_runtime.status_payload())

    @app.get("/status", response_model=GatewayStatusResponse)
    def status(_: None = Depends(_status_guard)) -> GatewayStatusResponse:
        return GatewayStatusResponse.model_validate(active_runtime.status_payload())

    @app.get("/queue", response_model=list[GatewayQueueItemResponse])
    def queue(
        _: None = Depends(_status_guard),
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
    ) -> list[GatewayQueueItemResponse]:
        return [_item_response(item) for item in active_runtime.queue.list_items(limit)]

    @app.get("/queue/items", response_model=list[GatewayQueueItemResponse])
    def queue_items(
        _: None = Depends(_status_guard),
        limit: int = 100,
    ) -> list[GatewayQueueItemResponse]:
        return [_item_response(item) for item in active_runtime.queue.list_items(limit)]

    @app.post("/queue/{item_id}/retry", response_model=GatewayQueueItemResponse)
    def retry_queue_item(
        item_id: int, _: None = Depends(_status_guard)
    ) -> GatewayQueueItemResponse:
        try:
            return _item_response(active_runtime.queue.retry(item_id))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/cycle", response_model=dict[str, Any])
    def run_cycle(_: None = Depends(_status_guard)) -> dict[str, Any]:
        return active_runtime.run_cycle()

    return app


app = create_app()
