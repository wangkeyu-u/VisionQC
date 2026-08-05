from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditEvent

SENSITIVE_MARKERS = ("authorization", "password", "secret", "token", "access_key")


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): (
                "[REDACTED]"
                if any(marker in str(key).lower() for marker in SENSITIVE_MARKERS)
                else redact(item)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def canonical_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
    sanitized = redact(payload)
    serialized = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), default=str)
    return sanitized, hashlib.sha256(serialized.encode()).hexdigest()


def record_audit(
    session: Session,
    *,
    tenant_id: str,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    correlation_id: str,
    payload: dict[str, Any],
) -> AuditEvent:
    sanitized, digest = canonical_payload(payload)
    event = AuditEvent(
        tenant_id=tenant_id,
        actor=actor,
        action=action,
        target_type=target_type,
        target_id=target_id,
        correlation_id=correlation_id,
        payload=sanitized,
        payload_digest=digest,
    )
    session.add(event)
    return event
