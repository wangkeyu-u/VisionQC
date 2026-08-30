from __future__ import annotations

import httpx
import pytest

from app.connectors import (
    ConnectorCapability,
    ConnectorRegistry,
    ConnectorSecretRef,
    ConnectorSpec,
    HttpConnector,
    InMemoryConnector,
    RetryableConnectorError,
    RetryingConnectorExecutor,
    redact_secrets,
    resolve_secret_refs,
)
from app.generic_qms_mock import GenericQmsMockConnector, validate_qms_case


def _qms_payload() -> dict[str, object]:
    return {
        "case_reference": "case-001",
        "batch_reference": "batch-001",
        "station_reference": "station-01",
        "disposition": "INVESTIGATE",
        "reason": "review required",
        "evidence_refs": ["asset://heatmap-001"],
    }


def test_generic_qms_contract_is_neutral_and_idempotent() -> None:
    connector = GenericQmsMockConnector()
    first = connector.execute("CREATE_TICKET", _qms_payload(), "case-key-1")
    replay = connector.execute("CREATE_TICKET", _qms_payload(), "case-key-1")
    assert first.external_reference == replay.external_reference
    assert first.summary["simulated"] is True
    assert first.summary["contract_version"] == "generic-qms-case.v1"
    assert replay.summary["deduplicated"] is True
    assert connector.calls == ["case-key-1", "case-key-1"]


def test_generic_qms_contract_rejects_missing_business_reference() -> None:
    payload = _qms_payload()
    payload.pop("batch_reference")
    with pytest.raises(ValueError, match="batch_reference"):
        validate_qms_case(payload)


def test_registry_groups_capabilities_and_retries_with_same_key() -> None:
    connector = InMemoryConnector("qms")
    connector.fail_after_create_once = True
    registry = ConnectorRegistry(
        executor=RetryingConnectorExecutor(max_attempts=2, backoff_seconds=0)
    )
    registry.register(
        "QMS",
        connector,
        ConnectorSpec(
            name="QMS",
            capability=ConnectorCapability.QMS,
            driver="in_memory_mock",
            contract_version="generic-qms-case.v1",
            endpoint="memory://qms",
            operations=["CREATE_TICKET"],
            simulated=True,
        ),
    )
    outcome = registry.execute("qms", "CREATE_TICKET", _qms_payload(), "same-key")
    assert outcome.error is None
    assert outcome.attempts == 2
    assert connector.calls == ["same-key", "same-key"]
    assert list(registry.for_capability(ConnectorCapability.QMS)) == ["QMS"]
    assert registry.healthcheck() == {"QMS": True}


def test_secret_refs_resolve_without_being_serialized_and_redaction_is_recursive() -> None:
    refs = [ConnectorSecretRef(name="api", env_var="VQC_API_TOKEN")]
    values, missing = resolve_secret_refs(refs, env={"VQC_API_TOKEN": "top-secret"})
    assert values == {"api": "top-secret"}
    assert missing == []
    assert resolve_secret_refs(refs, env={})[1] == ["VQC_API_TOKEN"]
    redacted = redact_secrets(
        {
            "authorization": "Bearer top-secret",
            "nested": {"token": "top-secret"},
            "url": "top-secret",
        },
        secret_values=("top-secret",),
    )
    assert redacted == {
        "authorization": "[REDACTED]",
        "nested": {"token": "[REDACTED]"},
        "url": "[REDACTED]",
    }


def test_retryable_error_is_not_silently_successful() -> None:
    connector = InMemoryConnector("qms")
    connector.always_fail = True
    outcome = RetryingConnectorExecutor(max_attempts=2, backoff_seconds=0).execute(
        connector, "CREATE_TICKET", {}, "failure-key"
    )
    assert isinstance(outcome.error, RetryableConnectorError)
    assert outcome.result is None


def test_http_connector_honors_contract_health_idempotency_and_timeout() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.url.path, dict(request.headers)))
        if request.url.path == "/ready":
            return httpx.Response(200, json={"status": "ok"})
        return httpx.Response(
            200,
            json={"external_reference": "qms-001", "status": "OPEN"},
        )

    spec = ConnectorSpec(
        name="QMS_HTTP",
        capability=ConnectorCapability.QMS,
        driver="http",
        contract_version="generic-qms-case.v1",
        endpoint="http://qms.local",
        health_path="/ready",
        operations=["CREATE_TICKET"],
        idempotency_header="X-Request-Key",
    )
    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = HttpConnector("qms", "http://qms.local", spec=spec, client=client)
    assert connector.healthcheck() is True
    result = connector.execute("CREATE_TICKET", {}, "stable-key")
    assert result.external_reference == "qms-001"
    assert calls[0][0] == "/ready"
    assert calls[1][0] == "/actions/create_ticket"
    assert calls[1][1]["x-request-key"] == "stable-key"
    client.close()
