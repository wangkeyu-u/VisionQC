"""Explicitly simulated DXQ quality-loop contract.

This module is deliberately named and documented as a mock.  It is not a
private DXQ client, does not make network calls, and must not be described as
an official Dürr integration.  A future customer-approved adapter can satisfy
the same small contract without leaking customer-specific fields into the
inspection workflow.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.connectors import (
    Connector,
    ConnectorResult,
    RetryableConnectorError,
    TerminalConnectorError,
)

DXQ_MOCK_CONTRACT_VERSION = "simulated-dxq-quality-loop.v1"
DXQ_MOCK_REQUIRED_FIELDS = (
    "body_id",
    "workpiece_id",
    "paint_shop",
    "booth_station",
    "line",
    "model_variant",
    "color_code",
    "paint_recipe",
    "shift",
    "timestamp",
    "visual_defect_type",
    "severity",
    "mask_or_heatmap",
    "operator_decision",
    "equipment_alarm_refs",
    "process_parameter_refs",
    "root_cause_candidates",
    "disposition",
    "quality_case_id",
)
DXQ_MOCK_OPERATIONS = (
    "PUBLISH_QUALITY_EVENT",
    "LINK_PROCESS_CONTEXT",
    "ANALYZE_ROOT_CAUSE",
    "CLOSE_QUALITY_CASE",
)


def validate_quality_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the stable, simulated payload boundary used by tests and UI."""

    missing = [
        key
        for key in DXQ_MOCK_REQUIRED_FIELDS
        if key not in payload or payload[key] is None or payload[key] == ""
    ]
    if missing:
        raise ValueError(f"dxq_mock payload is missing fields: {', '.join(missing)}")
    for key in (
        "equipment_alarm_refs",
        "process_parameter_refs",
        "root_cause_candidates",
    ):
        if not isinstance(payload[key], list):
            raise ValueError(f"dxq_mock field {key} must be a list")
    if not isinstance(payload["mask_or_heatmap"], (str, dict, list)):
        raise ValueError("dxq_mock mask_or_heatmap must be a reference or structured evidence")
    return payload


class DxqMockConnector(Connector):
    """In-memory simulated digital-quality record connector.

    The connector is intentionally idempotent and observable so an FDE demo
    can prove the quality event was accepted without pretending to call a
    production DXQ endpoint.
    """

    name = "DXQ_MOCK"

    def __init__(self) -> None:
        self.records: dict[str, ConnectorResult] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.available = True

    def healthcheck(self) -> bool:
        return self.available

    def execute(
        self, operation: str, payload: dict[str, Any], idempotency_key: str
    ) -> ConnectorResult:
        self.calls.append(idempotency_key)
        if not self.available:
            raise RetryableConnectorError("dxq_mock is unavailable (simulated)")
        if operation not in DXQ_MOCK_OPERATIONS:
            raise TerminalConnectorError(f"dxq_mock operation is not supported: {operation}")
        try:
            validated = validate_quality_event(payload)
        except ValueError as exc:
            raise TerminalConnectorError(str(exc)) from exc
        if idempotency_key in self.records:
            return self.records[idempotency_key]
        reference = f"dxq-mock-{len(self.records) + 1:04d}"
        status = "CLOSED" if operation == "CLOSE_QUALITY_CASE" else "COMPLETED"
        result = ConnectorResult(
            external_reference=reference,
            status=status,
            summary={
                "simulated": True,
                "contract_version": DXQ_MOCK_CONTRACT_VERSION,
                "operation": operation,
                "external_reference": reference,
                "status": status,
            },
        )
        self.records[idempotency_key] = result
        self.payloads[idempotency_key] = deepcopy(validated)
        return result

    def get_status(self, external_reference: str) -> ConnectorResult:
        for result in self.records.values():
            if result.external_reference == external_reference:
                return result
        raise TerminalConnectorError("dxq_mock record not found")
