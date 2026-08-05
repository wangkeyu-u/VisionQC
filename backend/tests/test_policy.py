from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain import PolicyRoute
from app.policy import PolicyConfig, ThresholdRule, evaluate_policy


def test_threshold_boundaries_are_safe_and_deterministic() -> None:
    policy = PolicyConfig(
        version="1.0.0",
        default=ThresholdRule(review_threshold=0.4, hold_threshold=0.8),
    )

    assert evaluate_policy(0.399, policy, product_code="p", station_code="s").route == (
        PolicyRoute.AUTO_RELEASE
    )
    assert evaluate_policy(0.4, policy, product_code="p", station_code="s").route == (
        PolicyRoute.MANUAL_REVIEW
    )
    assert evaluate_policy(0.8, policy, product_code="p", station_code="s").route == (
        PolicyRoute.BATCH_HOLD_AND_REVIEW
    )


def test_missing_dependency_never_auto_releases() -> None:
    decision = evaluate_policy(None, None, product_code="p", station_code="s")
    assert decision.route == PolicyRoute.MANUAL_REVIEW
    assert "safe fallback" in decision.reason


def test_invalid_or_conflicting_thresholds_are_rejected() -> None:
    with pytest.raises(ValidationError):
        ThresholdRule(review_threshold=0.8, hold_threshold=0.8)

    with pytest.raises(ValidationError):
        PolicyConfig(
            version="1.0.0",
            default=ThresholdRule(review_threshold=0.4, hold_threshold=0.8),
            overrides=[
                ThresholdRule(product_code="p", review_threshold=0.2, hold_threshold=0.7),
                ThresholdRule(product_code="p", review_threshold=0.3, hold_threshold=0.6),
            ],
        )


def test_most_specific_override_wins() -> None:
    policy = PolicyConfig(
        version="1.0.0",
        default=ThresholdRule(review_threshold=0.4, hold_threshold=0.8),
        overrides=[
            ThresholdRule(product_code="p", review_threshold=0.3, hold_threshold=0.7),
            ThresholdRule(
                product_code="p",
                station_code="s",
                review_threshold=0.2,
                hold_threshold=0.6,
            ),
        ],
    )
    resolved = policy.resolve("p", "s")
    assert resolved.review_threshold == 0.2
    assert resolved.hold_threshold == 0.6
