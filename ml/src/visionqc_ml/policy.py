"""Deterministic review/hold routing policy."""

from __future__ import annotations

from dataclasses import dataclass

from .schemas import PolicyDecision


@dataclass(frozen=True)
class ThresholdPolicy:
    """Versioned two-threshold policy with explicit boundary semantics."""

    version: str
    review_threshold: float
    hold_threshold: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.review_threshold < self.hold_threshold <= 1.0:
            raise ValueError("thresholds must satisfy 0 <= review_threshold < hold_threshold <= 1")

    def route(self, score: float) -> tuple[PolicyDecision, str]:
        """Route a normalized score without making a semantic defect claim."""
        if not 0.0 <= score <= 1.0:
            raise ValueError("score must be normalized to [0, 1]")
        if score < self.review_threshold:
            return PolicyDecision.AUTO_RELEASE, "score < review_threshold"
        if score < self.hold_threshold:
            return PolicyDecision.REVIEW_REQUIRED, "review_threshold <= score < hold_threshold"
        return PolicyDecision.BATCH_HOLD_AND_REVIEW, "score >= hold_threshold"

