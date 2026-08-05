from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx


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
    def __init__(self, name: str, base_url: str, timeout_seconds: float = 2):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def healthcheck(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/health", timeout=self.timeout_seconds)
            return response.is_success
        except httpx.HTTPError:
            return False

    def execute(
        self, operation: str, payload: dict[str, Any], idempotency_key: str
    ) -> ConnectorResult:
        try:
            response = httpx.post(
                f"{self.base_url}/actions/{operation.lower()}",
                json=payload,
                headers={"Idempotency-Key": idempotency_key},
                timeout=self.timeout_seconds,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise RetryableConnectorError(f"{self.name} request failed") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise RetryableConnectorError(f"{self.name} temporary error: {response.status_code}")
        if response.status_code == 409:
            raise ManualReviewConnectorError(f"{self.name} conflict requires reconciliation")
        if not response.is_success:
            raise TerminalConnectorError(f"{self.name} rejected request: {response.status_code}")
        body = response.json()
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
            response = httpx.get(
                f"{self.base_url}/actions/{external_reference}", timeout=self.timeout_seconds
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise RetryableConnectorError(f"{self.name} status request failed") from exc
        body = response.json()
        return ConnectorResult(
            external_reference=external_reference,
            status=body["status"],
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
class ExecutionOutcome:
    result: ConnectorResult | None
    attempts: int
    error: ConnectorError | None


class RetryingConnectorExecutor:
    def __init__(self, *, max_attempts: int = 3, backoff_seconds: float = 0.05):
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        self.max_attempts = max_attempts
        self.backoff_seconds = backoff_seconds

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
                    time.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        return ExecutionOutcome(result=None, attempts=self.max_attempts, error=last_error)
