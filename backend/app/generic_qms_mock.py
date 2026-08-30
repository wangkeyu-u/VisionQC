"""Neutral, in-memory QMS contract used for connector and onboarding tests.

This module intentionally contains no customer or vendor vocabulary.  It is a
simulated QMS case endpoint that demonstrates the platform connector seam;
production customers replace it with an approved adapter configured by a
Deployment Pack and secret references.
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

GENERIC_QMS_CONTRACT_VERSION = "generic-qms-case.v1"
GENERIC_QMS_OPERATIONS = ("CREATE_TICKET", "UPDATE_TICKET", "CLOSE_TICKET")


def _first_value(payload: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        value = payload.get(name)
        if value is not None and str(value).strip():
            return value
    return None


def validate_qms_case(payload: dict[str, Any]) -> dict[str, Any]:
    """Validate the neutral minimum contract, accepting common mapped aliases."""

    aliases = {
        "case_reference": ("case_reference", "case_id", "inspection_id", "inspection_ref"),
        "batch_reference": ("batch_reference", "batch_no", "lot_id", "body_id"),
        "station_reference": ("station_reference", "station_code", "cell_id", "booth_station"),
        "disposition": ("disposition", "quality_disposition"),
        "reason": ("reason", "containment_reason", "review_reason"),
    }
    missing = [
        canonical for canonical, names in aliases.items() if _first_value(payload, names) is None
    ]
    if missing:
        raise ValueError(f"generic_qms_mock payload is missing fields: {', '.join(missing)}")
    evidence_refs = payload.get("evidence_refs")
    if evidence_refs is not None and not isinstance(evidence_refs, list):
        raise ValueError("generic_qms_mock evidence_refs must be a list")
    return payload


class GenericQmsMockConnector(Connector):
    """Idempotent simulated QMS connector with deterministic failure knobs."""

    name = "GENERIC_QMS_MOCK"

    def __init__(self) -> None:
        self.records: dict[str, ConnectorResult] = {}
        self.payloads: dict[str, dict[str, Any]] = {}
        self.calls: list[str] = []
        self.available = True
        self.fail_after_create_once = False
        self.always_fail = False

    def healthcheck(self) -> bool:
        return self.available and not self.always_fail

    def execute(
        self, operation: str, payload: dict[str, Any], idempotency_key: str
    ) -> ConnectorResult:
        self.calls.append(idempotency_key)
        if not self.available or self.always_fail:
            raise RetryableConnectorError("generic_qms_mock is unavailable (simulated)")
        if operation not in GENERIC_QMS_OPERATIONS:
            raise TerminalConnectorError(
                f"generic_qms_mock operation is not supported: {operation}"
            )
        try:
            validated = validate_qms_case(payload)
        except ValueError as exc:
            raise TerminalConnectorError(str(exc)) from exc
        if idempotency_key in self.records:
            previous = self.records[idempotency_key]
            return ConnectorResult(
                external_reference=previous.external_reference,
                status=previous.status,
                summary={**previous.summary, "deduplicated": True},
            )
        reference = f"generic-qms-{len(self.records) + 1:04d}"
        status = "OPEN" if operation == "CREATE_TICKET" else "COMPLETED"
        result = ConnectorResult(
            external_reference=reference,
            status=status,
            summary={
                "simulated": True,
                "contract_version": GENERIC_QMS_CONTRACT_VERSION,
                "operation": operation,
                "external_reference": reference,
                "status": status,
                "deduplicated": False,
            },
        )
        self.records[idempotency_key] = result
        self.payloads[idempotency_key] = deepcopy(validated)
        if self.fail_after_create_once:
            self.fail_after_create_once = False
            raise RetryableConnectorError("generic_qms_mock timed out after accepting request")
        return result

    def get_status(self, external_reference: str) -> ConnectorResult:
        for result in self.records.values():
            if result.external_reference == external_reference:
                return result
        raise TerminalConnectorError("generic_qms_mock record not found")
