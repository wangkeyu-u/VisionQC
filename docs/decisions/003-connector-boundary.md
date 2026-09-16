# Keep MES/QMS effects behind auditable connector boundaries

Recorded: 2026-09-15. This document retrospectively records the rationale behind the current implementation. Code-supported reasoning is an interpretation of the implementation, not a claim that an unrecorded historical experiment took place.

## Context
Inference output is not authorization to write to external business systems.

## Options Considered

### Option A
Allow model output to invoke MES/QMS directly. Pros: low integration effort. Cons: uncertain side effects and missing authorization.

### Option B
Map deterministic workflow actions to scoped connectors with recovery. Pros: auditable, testable. Cons: each real system requires an adapter/acceptance process.

## Decision
Use Mock MES/QMS for demonstrated workflows and explicitly mark real integration unverified.

## Why
A successful HTTP response or model label cannot establish a completed external business operation.

## Validation
`backend/tests/test_e2e.py::test_connector_final_failure_remains_recoverable`, `backend/tests/test_deployment_packs.py`.

## Trade-offs
Tenant/connector tests demonstrate code contracts, not real factory integration or operational availability.

## What Would Change My Mind
A real customer system contract with measured idempotency, failure recovery and acceptance evidence.
