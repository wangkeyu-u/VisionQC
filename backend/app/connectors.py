from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from os import environ
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


class ConnectorCapability(StrEnum):
    """Capabilities are stable platform contracts, not customer names."""

    INGEST = "ingest"
    MES = "mes"
    QMS = "qms"
    NOTIFICATION = "notification"
    ANALYTICS = "analytics"


class ConnectorSecretRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    env_var: str = Field(min_length=1, max_length=128, pattern=r"^[A-Z][A-Z0-9_]*$")
    required: bool = True


class ConnectorRetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_attempts: int = Field(default=3, ge=1, le=20)
    backoff_seconds: float = Field(default=0.5, ge=0, le=300)
    max_backoff_seconds: float = Field(default=30, ge=0, le=3600)
    retryable_status_codes: list[int] = Field(
        default_factory=lambda: [408, 425, 429, 500, 502, 503, 504], max_length=30
    )


class ConnectorSpec(BaseModel):
    """Portable connector metadata used by the registry and preflight CLI."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    capability: ConnectorCapability | str
    driver: str = Field(min_length=1, max_length=128)
    contract_version: str = Field(min_length=1, max_length=128)
    endpoint: str = Field(min_length=1, max_length=1000)
    health_path: str = Field(default="/health", min_length=1, max_length=200)
    operations: list[str] = Field(min_length=1, max_length=50)
    timeout_seconds: float = Field(default=10, gt=0, le=300)
    retry: ConnectorRetryPolicy = Field(default_factory=ConnectorRetryPolicy)
    idempotency_header: str = Field(default="Idempotency-Key", min_length=1, max_length=128)
    secret_refs: list[ConnectorSecretRef] = Field(default_factory=list, max_length=20)
    simulated: bool = False


SENSITIVE_KEY_MARKERS = (
    "authorization",
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
)


def redact_secrets(value: Any, *, secret_values: tuple[str, ...] = ()) -> Any:
    """Redact secret-looking fields and injected values before logging/auditing."""

    if isinstance(value, Mapping):
        return {
            str(key): (
                "[REDACTED]"
                if any(marker in str(key).lower() for marker in SENSITIVE_KEY_MARKERS)
                else redact_secrets(item, secret_values=secret_values)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item, secret_values=secret_values) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets(item, secret_values=secret_values) for item in value)
    if isinstance(value, str):
        redacted = value
        for secret in secret_values:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED]")
        return redacted
    return value


def resolve_secret_refs(
    refs: list[ConnectorSecretRef], *, env: Mapping[str, str] | None = None
) -> tuple[dict[str, str], list[str]]:
    """Resolve only the names needed at runtime; never serialize the values."""

    source = environ if env is None else env
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for ref in refs:
        value = source.get(ref.env_var, "")
        if value:
            resolved[ref.name] = value
        elif ref.required:
            missing.append(ref.env_var)
    return resolved, missing


class ConnectorError(RuntimeError):
    retryable = False
    requires_manual_review = False


class RetryableConnectorError(ConnectorError):
    retryable = True


class TerminalConnectorError(ConnectorError):
    pass


class ManualReviewConnectorError(ConnectorError):
    requires_manual_review = True


@dataclass(frozen=True)
class ConnectorResult:
    external_reference: str
    status: str
    summary: dict[str, Any]


class Connector(ABC):
    name: str

    @abstractmethod
    def healthcheck(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def execute(
        self, operation: str, payload: dict[str, Any], idempotency_key: str
    ) -> ConnectorResult:
        raise NotImplementedError

    @abstractmethod
    def get_status(self, external_reference: str) -> ConnectorResult:
        raise NotImplementedError


class HttpConnector(Connector):
    def __init__(
        self,
        name: str,
        base_url: str,
        timeout_seconds: float = 2,
        *,
        spec: ConnectorSpec | None = None,
        client: httpx.Client | None = None,
        headers: Mapping[str, str] | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.spec = spec
        self.timeout_seconds = spec.timeout_seconds if spec else timeout_seconds
        self._client = client
        self._headers = dict(headers or {})

    def _url(self, suffix: str) -> str:
        return f"{self.base_url}/{suffix.lstrip('/')}"

    def _get(self, url: str) -> httpx.Response:
        if self._client is not None:
            return self._client.get(url, headers=self._headers, timeout=self.timeout_seconds)
        return httpx.get(url, headers=self._headers, timeout=self.timeout_seconds)

    def _post(self, url: str, *, payload: dict[str, Any], idempotency_key: str) -> httpx.Response:
        headers = {**self._headers, "Idempotency-Key": idempotency_key}
        if self.spec is not None:
            headers[self.spec.idempotency_header] = headers.pop("Idempotency-Key")
        if self._client is not None:
            return self._client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        return httpx.post(
            url,
            json=payload,
            headers=headers,
            timeout=self.timeout_seconds,
        )

    def healthcheck(self) -> bool:
        try:
            health_path = self.spec.health_path if self.spec else "/health"
            response = self._get(self._url(health_path))
            return response.is_success
        except httpx.HTTPError:
            return False

    def execute(
        self, operation: str, payload: dict[str, Any], idempotency_key: str
    ) -> ConnectorResult:
        if self.spec is not None and operation not in self.spec.operations:
            raise TerminalConnectorError(f"{self.name} operation is not configured: {operation}")
        try:
            response = self._post(
                self._url(f"actions/{operation.lower()}"),
                payload=payload,
                idempotency_key=idempotency_key,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableConnectorError(f"{self.name} request failed") from exc
        retryable_statuses = (
            self.spec.retry.retryable_status_codes
            if self.spec is not None
            else [408, 425, 429, 500, 502, 503, 504]
        )
        if response.status_code in retryable_statuses:
            raise RetryableConnectorError(f"{self.name} temporary error: {response.status_code}")
        if response.status_code == 409:
            raise ManualReviewConnectorError(f"{self.name} conflict requires reconciliation")
        if not response.is_success:
            raise TerminalConnectorError(f"{self.name} rejected request: {response.status_code}")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise TerminalConnectorError(f"{self.name} returned invalid JSON") from exc
        if not isinstance(body, dict) or "external_reference" not in body or "status" not in body:
            raise TerminalConnectorError(f"{self.name} returned an invalid action contract")
        return ConnectorResult(
            external_reference=body["external_reference"],
            status=body["status"],
            summary={
                "external_reference": body["external_reference"],
                "status": body["status"],
                "deduplicated": bool(body.get("deduplicated", False)),
            },
        )

    def get_status(self, external_reference: str) -> ConnectorResult:
        try:
            response = self._get(self._url(f"actions/{external_reference}"))
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableConnectorError(f"{self.name} status request failed") from exc
        except httpx.HTTPError as exc:
            raise RetryableConnectorError(f"{self.name} status request failed") from exc
        retryable_statuses = [408, 425, 429, 500, 502, 503, 504]
        if self.spec is not None:
            retryable_statuses = self.spec.retry.retryable_status_codes
        if response.status_code in retryable_statuses:
            raise RetryableConnectorError(
                f"{self.name} status request failed: {response.status_code}"
            )
        if not response.is_success:
            raise TerminalConnectorError(f"{self.name} status rejected: {response.status_code}")
        try:
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise TerminalConnectorError(f"{self.name} returned invalid status JSON") from exc
        if not isinstance(body, dict) or "status" not in body:
            raise TerminalConnectorError(f"{self.name} returned an invalid status contract")
        return ConnectorResult(
            external_reference=external_reference,
            status=str(body["status"]),
            summary={"external_reference": external_reference, "status": body["status"]},
        )


class InMemoryConnector(Connector):
    def __init__(self, name: str):
        self.name = name
        self.records: dict[str, ConnectorResult] = {}
        self.calls: list[str] = []
        self.fail_after_create_once = False
        self.always_fail = False

    def healthcheck(self) -> bool:
        return not self.always_fail

    def execute(
        self, operation: str, payload: dict[str, Any], idempotency_key: str
    ) -> ConnectorResult:
        del payload
        self.calls.append(idempotency_key)
        if idempotency_key in self.records:
            return self.records[idempotency_key]
        if self.always_fail:
            raise RetryableConnectorError(f"{self.name} injected failure")
        result = ConnectorResult(
            external_reference=f"{self.name}-{len(self.records) + 1}",
            status="OPEN" if operation == "CREATE_TICKET" else "COMPLETED",
            summary={"status": "accepted", "operation": operation},
        )
        self.records[idempotency_key] = result
        if self.fail_after_create_once:
            self.fail_after_create_once = False
            raise RetryableConnectorError(f"{self.name} timed out after accepting request")
        return result

    def get_status(self, external_reference: str) -> ConnectorResult:
        for result in self.records.values():
            if result.external_reference == external_reference:
                return result
        raise TerminalConnectorError("external record not found")


@dataclass(frozen=True)
class RegisteredConnector:
    name: str
    connector: Connector
    spec: ConnectorSpec


class ConnectorRegistry:
    """Registry for capability-based connectors with a stable test seam."""

    def __init__(self, *, executor: RetryingConnectorExecutor | None = None):
        self.executor = executor
        self._entries: dict[str, RegisteredConnector] = {}

    def register(
        self,
        name: str,
        connector: Connector,
        spec: ConnectorSpec | Mapping[str, Any] | None = None,
    ) -> Connector:
        key = name.upper()
        if key in self._entries:
            raise ValueError(f"connector {key} is already registered")
        if spec is None:
            resolved_spec = ConnectorSpec(
                name=key,
                capability=ConnectorCapability.QMS,
                driver=type(connector).__name__,
                contract_version="in-memory.v1",
                endpoint="memory://local",
                operations=["CREATE_TICKET"],
                simulated=True,
            )
        else:
            resolved_spec = (
                spec if isinstance(spec, ConnectorSpec) else ConnectorSpec.model_validate(spec)
            )
        if resolved_spec.name.upper() != key:
            raise ValueError("connector registry name must match ConnectorSpec.name")
        self._entries[key] = RegisteredConnector(key, connector, resolved_spec)
        return connector

    def get(self, name: str) -> Connector | None:
        entry = self._entries.get(name.upper())
        return entry.connector if entry else None

    def spec(self, name: str) -> ConnectorSpec:
        try:
            return self._entries[name.upper()].spec
        except KeyError as exc:
            raise KeyError(f"connector {name!r} is not registered") from exc

    @property
    def connectors(self) -> dict[str, Connector]:
        return {name: entry.connector for name, entry in self._entries.items()}

    @property
    def specs(self) -> dict[str, ConnectorSpec]:
        return {name: entry.spec for name, entry in self._entries.items()}

    def for_capability(self, capability: str | ConnectorCapability) -> dict[str, Connector]:
        value = str(capability)
        return {
            name: entry.connector
            for name, entry in self._entries.items()
            if str(entry.spec.capability) == value
        }

    def healthcheck(self) -> dict[str, bool]:
        results: dict[str, bool] = {}
        for name, entry in self._entries.items():
            try:
                results[name] = bool(entry.connector.healthcheck())
            except Exception:
                results[name] = False
        return results

    def execute(
        self,
        name: str,
        operation: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExecutionOutcome:
        entry = self._entries.get(name.upper())
        if entry is None:
            return ExecutionOutcome(
                result=None,
                attempts=0,
                error=TerminalConnectorError(f"connector {name!r} is not registered"),
            )
        executor = self.executor or RetryingConnectorExecutor(
            max_attempts=entry.spec.retry.max_attempts,
            backoff_seconds=entry.spec.retry.backoff_seconds,
            max_backoff_seconds=entry.spec.retry.max_backoff_seconds,
        )
        return executor.execute(entry.connector, operation, payload, idempotency_key)


@dataclass(frozen=True)
class ExecutionOutcome:
    result: ConnectorResult | None
    attempts: int
    error: ConnectorError | None


class RetryingConnectorExecutor:
    def __init__(
        self,
        *,
        max_attempts: int = 3,
        backoff_seconds: float = 0.05,
        max_backoff_seconds: float = 60,
    ):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if backoff_seconds < 0 or max_backoff_seconds < 0:
            raise ValueError("backoff values must be non-negative")
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds
        self.max_backoff_seconds = max_backoff_seconds

    def execute(
        self,
        connector: Connector,
        operation: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> ExecutionOutcome:
        last_error: ConnectorError | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                result = connector.execute(operation, payload, idempotency_key)
                return ExecutionOutcome(result=result, attempts=attempt, error=None)
            except ConnectorError as exc:
                last_error = exc
                if not exc.retryable or attempt == self.max_attempts:
                    return ExecutionOutcome(result=None, attempts=attempt, error=exc)
                if self.backoff_seconds:
                    delay = min(
                        self.max_backoff_seconds, self.backoff_seconds * (2 ** (attempt - 1))
                    )
                    time.sleep(delay)
        return ExecutionOutcome(result=None, attempts=self.max_attempts, error=last_error)
