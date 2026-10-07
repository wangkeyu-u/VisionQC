"""Pure qualification evidence binding and dataset authorization rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal


def validate_registered_evidence(
    evidence: Mapping[str, Any],
    *,
    evidence_sha256: str,
    dataset_source_type: str | None,
    dataset_fingerprint: str | None,
    dataset_registration_id: str | None,
    require_approval: bool = False,
) -> None:
    """Check freshly verified evidence against its immutable registration."""
    if evidence["evidence_package_sha256"] != evidence_sha256:
        raise ValueError("qualification evidence digest does not match registered digest")
    source_type = str(evidence.get("source_type") or dataset_source_type or "")
    if dataset_source_type and source_type != dataset_source_type:
        raise ValueError(
            "qualification evidence source type does not match the registered dataset"
        )
    if dataset_fingerprint and evidence.get("dataset_fingerprint") != dataset_fingerprint:
        raise ValueError(
            "qualification evidence dataset fingerprint does not match the registration"
        )
    if source_type != "DEMO_SYNTHETIC" and not dataset_registration_id:
        raise ValueError("benchmark/customer evidence must bind a dataset registration")
    # The core digest excludes release-decision.json to avoid a circular hash.
    # Recheck its mutable release metadata rather than relying on cached GO gates.
    if require_approval and (
        evidence.get("gate_decision") != "GO"
        or evidence.get("approval_status") != "PENDING_APPROVAL"
        or source_type != "CUSTOMER_PILOT"
    ):
        raise ValueError("qualification evidence is not eligible for customer approval")


def dataset_authorization_failure(
    *,
    dataset_status: str | None,
    dataset_source_type: str | None,
    dataset_fingerprint: str | None,
    expected_fingerprint: str | None,
    metadata: Mapping[str, Any],
    tenant_id: str,
    require_customer_source: bool,
) -> Literal["registration", "consent"] | None:
    """Return the failed gate; callers retain their lifecycle-specific API errors."""
    if (
        (require_customer_source and dataset_source_type != "CUSTOMER_PILOT")
        or dataset_status != "VALIDATED"
        or dataset_fingerprint != expected_fingerprint
    ):
        return "registration"
    provenance = metadata.get("customer_provenance", {})
    if provenance.get("tenant") != tenant_id or provenance.get("consent") is not True:
        return "consent"
    return None
