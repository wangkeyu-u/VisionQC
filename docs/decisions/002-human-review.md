# Enforce human review with server-side state and concurrency checks

Recorded: 2026-09-15. This document retrospectively records the rationale behind the current implementation. Code-supported reasoning is an interpretation of the implementation, not a claim that an unrecorded historical experiment took place.

## Context
Multiple reviewers and retries can act on the same quality event.

## Options Considered

### Option A
Use frontend button disabling for review ownership. Pros: easy UI. Cons: stale clients and concurrent requests bypass it.

### Option B
Use server-side claims, optimistic versions and explicit permissions. Pros: consistent decisions. Cons: conflict/retry UX is necessary.

## Decision
Validate claim/version/state/authorization when applying review decisions.

## Why
The model proposes evidence; business disposition belongs to deterministic policy and authorized humans.

## Validation
`backend/tests/test_api_integration.py::test_review_claim_and_decision_use_optimistic_lock`, `backend/tests/test_state_machine.py`.

## Trade-offs
Tests use isolated local services and do not prove database behavior for every deployment topology.

## What Would Change My Mind
Measured conflict rates or a new consistency requirement that justifies a different transaction/locking model.
