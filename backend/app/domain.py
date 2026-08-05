from __future__ import annotations

from enum import StrEnum


class DomainConflict(ValueError):
    pass


class InspectionStatus(StrEnum):
    RECEIVED = "RECEIVED"
    VALIDATED = "VALIDATED"
    INFERENCING = "INFERENCING"
    SCORED = "SCORED"
    AUTO_RELEASED = "AUTO_RELEASED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BATCH_HELD = "BATCH_HELD"
    RELEASE_APPROVED = "RELEASE_APPROVED"
    NONCONFORMANCE_CONFIRMED = "NONCONFORMANCE_CONFIRMED"
    ACTION_PENDING = "ACTION_PENDING"
    ACTION_EXECUTING = "ACTION_EXECUTING"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    ACTION_FAILED = "ACTION_FAILED"
    VERIFYING = "VERIFYING"
    CLOSED = "CLOSED"
    REJECTED_INPUT = "REJECTED_INPUT"
    INFERENCE_FAILED = "INFERENCE_FAILED"
    ESCALATED = "ESCALATED"


INSPECTION_TRANSITIONS: dict[InspectionStatus, frozenset[InspectionStatus]] = {
    InspectionStatus.RECEIVED: frozenset(
        {InspectionStatus.VALIDATED, InspectionStatus.REJECTED_INPUT}
    ),
    InspectionStatus.VALIDATED: frozenset({InspectionStatus.INFERENCING}),
    InspectionStatus.INFERENCING: frozenset(
        {InspectionStatus.SCORED, InspectionStatus.INFERENCE_FAILED}
    ),
    InspectionStatus.INFERENCE_FAILED: frozenset({InspectionStatus.REVIEW_REQUIRED}),
    InspectionStatus.SCORED: frozenset(
        {
            InspectionStatus.AUTO_RELEASED,
            InspectionStatus.REVIEW_REQUIRED,
            InspectionStatus.BATCH_HELD,
        }
    ),
    InspectionStatus.REVIEW_REQUIRED: frozenset(
        {
            InspectionStatus.RELEASE_APPROVED,
            InspectionStatus.NONCONFORMANCE_CONFIRMED,
            InspectionStatus.ESCALATED,
        }
    ),
    InspectionStatus.BATCH_HELD: frozenset(
        {
            InspectionStatus.RELEASE_APPROVED,
            InspectionStatus.NONCONFORMANCE_CONFIRMED,
            InspectionStatus.ESCALATED,
        }
    ),
    InspectionStatus.NONCONFORMANCE_CONFIRMED: frozenset({InspectionStatus.ACTION_PENDING}),
    InspectionStatus.ACTION_PENDING: frozenset({InspectionStatus.ACTION_EXECUTING}),
    InspectionStatus.ACTION_EXECUTING: frozenset(
        {InspectionStatus.ACTION_COMPLETED, InspectionStatus.ACTION_FAILED}
    ),
    InspectionStatus.ACTION_FAILED: frozenset({InspectionStatus.ACTION_PENDING}),
    InspectionStatus.ACTION_COMPLETED: frozenset(
        {InspectionStatus.VERIFYING, InspectionStatus.CLOSED}
    ),
    InspectionStatus.VERIFYING: frozenset({InspectionStatus.CLOSED, InspectionStatus.ESCALATED}),
    InspectionStatus.ESCALATED: frozenset(
        {InspectionStatus.REVIEW_REQUIRED, InspectionStatus.BATCH_HELD}
    ),
    InspectionStatus.AUTO_RELEASED: frozenset(),
    InspectionStatus.RELEASE_APPROVED: frozenset(),
    InspectionStatus.CLOSED: frozenset(),
    InspectionStatus.REJECTED_INPUT: frozenset(),
}


def assert_inspection_transition(current: str, target: str) -> None:
    try:
        current_state = InspectionStatus(current)
        target_state = InspectionStatus(target)
    except ValueError as exc:
        raise DomainConflict(f"unknown inspection state transition: {current} -> {target}") from exc
    if target_state not in INSPECTION_TRANSITIONS[current_state]:
        raise DomainConflict(f"illegal inspection state transition: {current} -> {target}")


class PolicyRoute(StrEnum):
    AUTO_RELEASE = "AUTO_RELEASE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    BATCH_HOLD_AND_REVIEW = "BATCH_HOLD_AND_REVIEW"


class ReviewChoice(StrEnum):
    GOOD = "GOOD"
    REWORK = "REWORK"
    SCRAP = "SCRAP"
    INVESTIGATE = "INVESTIGATE"
    UNABLE_TO_DETERMINE = "UNABLE_TO_DETERMINE"


class ExternalActionStatus(StrEnum):
    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
