from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt

from edge_gateway.config import GatewaySettings
from edge_gateway.deployment import GatewayDeploymentPack
from edge_gateway.queue import QueueItem


class UploadError(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


@dataclass(frozen=True)
class UploadResult:
    inspection_id: str
    idempotent_replay: bool
    status: str


class GatewayTokenProvider:
    """Provide a tenant-scoped token without ever selecting a tenant in a request body."""

    def __init__(self, settings: GatewaySettings, pack: GatewayDeploymentPack):
        self.settings = settings
        self.pack = pack
        settings.validate_mode()
        if settings.gateway_id not in {"gateway-local", pack.gateway_id}:
            raise ValueError("VQC_GATEWAY_ID does not match the Deployment Pack gateway_id")

    @property
    def gateway_id(self) -> str:
        return (
            self.pack.gateway_id
            if self.settings.gateway_id == "gateway-local"
            else self.settings.gateway_id
        )

    def token(self) -> str:
        if self.settings.auth_token is not None:
            return self.settings.auth_token.get_secret_value()
        if self.settings.mode != "demo":
            raise UploadError(
                "AUTH_CONFIGURATION_ERROR",
                "生产网关未配置由 IdP/Secret Provider 注入的 token。",
                retryable=False,
            )
        now = datetime.now(UTC)
        return str(
            jwt.encode(
                {
                    "sub": self.gateway_id,
                    "tenant_id": self.pack.tenant_id,
                    "roles": ["edge_gateway"],
                    "iss": self.settings.auth_issuer,
                    "iat": now,
                    "exp": now + timedelta(minutes=5),
                },
                self.settings.auth_secret.get_secret_value(),
                algorithm=self.settings.auth_algorithm,
            )
        )


class BackendUploader:
    def __init__(
        self,
        settings: GatewaySettings,
        pack: GatewayDeploymentPack,
        token_provider: GatewayTokenProvider | None = None,
        client: httpx.Client | None = None,
    ):
        self.settings = settings
        self.pack = pack
        self.token_provider = token_provider or GatewayTokenProvider(settings, pack)
        self.client = client or httpx.Client(
            base_url=settings.backend_url.rstrip("/"),
            timeout=settings.request_timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def _headers(self, item: QueueItem | None = None) -> dict[str, str]:
        gateway_id = self.token_provider.gateway_id
        correlation = f"gw_{gateway_id}_{item.id}" if item else f"gw_{gateway_id}_heartbeat"
        return {
            "Authorization": f"Bearer {self.token_provider.token()}",
            "X-Gateway-ID": gateway_id,
            "X-Correlation-ID": correlation[:128],
            "Accept": "application/json",
        }

    def upload(self, item: QueueItem, data: bytes) -> UploadResult:
        if not item.idempotency_key or not item.mime_type:
            raise UploadError(
                "QUEUE_ITEM_INVALID",
                "队列项缺少幂等键或媒体类型，已保留待人工处理。",
                retryable=False,
            )
        form = {
            self.pack.field_mapping.key_for(canonical): value
            for canonical, value in item.context.items()
            if canonical
            in {
                "product_code",
                "product_revision",
                "batch_no",
                "station_code",
                "captured_at",
                "source",
            }
        }
        try:
            response = self.client.post(
                "/inspections",
                headers={**self._headers(item), "Idempotency-Key": item.idempotency_key},
                files={"image": (item.original_filename, data, item.mime_type)},
                data=form,
            )
        except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError) as exc:
            raise UploadError(
                "UPLOAD_TRANSPORT_ERROR",
                f"后端暂不可达，图片保留在本地队列：{type(exc).__name__}。",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            raise UploadError(
                "UPLOAD_HTTP_CLIENT_ERROR",
                f"上传请求失败，图片保留在本地队列：{type(exc).__name__}。",
                retryable=True,
            ) from exc

        if response.status_code not in {200, 201, 202}:
            message = "后端拒绝了网关上传。"
            try:
                payload = response.json()
                message = str(payload.get("message") or payload.get("detail") or message)[:300]
            except (ValueError, TypeError):
                pass
            retryable = response.status_code == 429 or response.status_code >= 500
            raise UploadError(
                "UPLOAD_RETRYABLE" if retryable else "UPLOAD_REJECTED",
                message,
                retryable=retryable,
            )
        try:
            payload = response.json()
            inspection_id = str(payload["inspection_id"])
            status = str(payload.get("status", "RECEIVED"))
            replay = bool(payload.get("idempotent_replay", False))
        except (ValueError, KeyError, TypeError) as exc:
            raise UploadError(
                "UPLOAD_RESPONSE_INVALID",
                "后端返回缺少 inspection_id，图片保留在本地队列。",
                retryable=True,
            ) from exc
        return UploadResult(inspection_id=inspection_id, idempotent_replay=replay, status=status)

    def heartbeat(self, payload: dict[str, Any]) -> bool:
        try:
            response = self.client.post(
                "/gateways/heartbeat",
                headers=self._headers(),
                json=payload,
            )
            return response.status_code in {200, 201, 202}
        except httpx.HTTPError:
            return False


def deterministic_idempotency_key(
    *,
    tenant_id: str,
    pack_key: str,
    pack_version: str,
    content_sha256: str,
    context: dict[str, str],
) -> str:
    material = {
        "schema": "visionqc-edge-idempotency.v1",
        "tenant_id": tenant_id,
        "pack_key": pack_key,
        "pack_version": pack_version,
        "content_sha256": content_sha256,
        "context": context,
    }
    digest = hashlib.sha256(
        json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"edge_{digest}"
