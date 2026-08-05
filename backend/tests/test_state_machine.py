from __future__ import annotations

import pytest

from app.domain import DomainConflict, assert_inspection_transition


def test_expected_quality_state_transitions() -> None:
    valid_path = [
        ("RECEIVED", "VALIDATED"),
        ("VALIDATED", "INFERENCING"),
        ("INFERENCING", "SCORED"),
        ("SCORED", "BATCH_HELD"),
        ("BATCH_HELD", "NONCONFORMANCE_CONFIRMED"),
        ("NONCONFORMANCE_CONFIRMED", "ACTION_PENDING"),
        ("ACTION_PENDING", "ACTION_EXECUTING"),
        ("ACTION_EXECUTING", "ACTION_COMPLETED"),
        ("ACTION_COMPLETED", "VERIFYING"),
        ("VERIFYING", "CLOSED"),
    ]
    for current, target in valid_path:
        assert_inspection_transition(current, target)


def test_model_cannot_jump_to_disposition_or_release_after_failure() -> None:
    with pytest.raises(DomainConflict):
        assert_inspection_transition("SCORED", "NONCONFORMANCE_CONFIRMED")
    with pytest.raises(DomainConflict):
        assert_inspection_transition("INFERENCE_FAILED", "AUTO_RELEASED")
    with pytest.raises(DomainConflict):
        assert_inspection_transition("BATCH_HELD", "CLOSED")
