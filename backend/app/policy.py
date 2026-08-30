from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain import PolicyRoute


class ThresholdRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_code: str | None = None
    station_code: str | None = None
    review_threshold: float = Field(ge=0, le=1)
    hold_threshold: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def validate_threshold_order(self) -> ThresholdRule:
        if self.review_threshold >= self.hold_threshold:
            raise ValueError("review_threshold must be less than hold_threshold")
        return self

    @property
    def selector(self) -> tuple[str | None, str | None]:
        return self.product_code, self.station_code

    @property
    def specificity(self) -> int:
        return int(self.product_code is not None) + int(self.station_code is not None)


class PolicyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=64)
    default: ThresholdRule
    overrides: list[ThresholdRule] = Field(default_factory=list)
    # These gates are part of the platform contract, not a tenant preference.
    # Literal values make attempts to relax them fail schema validation.
    abnormal_auto_release: Literal[False] = False
    model_unavailable_auto_release: Literal[False] = False
    out_of_distribution_auto_release: Literal[False] = False
    image_quality_failure_auto_release: Literal[False] = False
    human_confirmation_for_external_action: Literal[True] = True

    @model_validator(mode="after")
    def validate_rules(self) -> PolicyConfig:
        if self.default.product_code is not None or self.default.station_code is not None:
            raise ValueError("default threshold rule cannot contain selectors")
        selectors: set[tuple[str | None, str | None]] = set()
        for rule in self.overrides:
            if rule.selector == (None, None):
                raise ValueError("override must select product_code and/or station_code")
            if rule.selector in selectors:
                raise ValueError(f"conflicting duplicate policy override: {rule.selector}")
            selectors.add(rule.selector)
        return self

    def resolve(self, product_code: str, station_code: str) -> ThresholdRule:
        matches = [
            rule
            for rule in self.overrides
            if (rule.product_code is None or rule.product_code == product_code)
            and (rule.station_code is None or rule.station_code == station_code)
        ]
        if not matches:
            return self.default
        matches.sort(key=lambda rule: rule.specificity, reverse=True)
        if len(matches) > 1 and matches[0].specificity == matches[1].specificity:
            raise ValueError("ambiguous policy overrides with equal specificity")
        return matches[0]


class PolicyEvaluation(BaseModel):
    route: PolicyRoute
    reason: str
    review_threshold: float
    hold_threshold: float


def evaluate_policy(
    score: float | None,
    policy: PolicyConfig | None,
    *,
    product_code: str,
    station_code: str,
    auto_release_enabled: bool = True,
    manual_review_enabled: bool = True,
    batch_hold_enabled: bool = True,
) -> PolicyEvaluation:
    if score is None or policy is None or not 0 <= score <= 1:
        return PolicyEvaluation(
            route=PolicyRoute.MANUAL_REVIEW,
            reason="safe fallback: model score or active policy unavailable/invalid",
            review_threshold=0,
            hold_threshold=1,
        )
    rule = policy.resolve(product_code, station_code)
    if score < rule.review_threshold:
        if auto_release_enabled:
            route = PolicyRoute.AUTO_RELEASE
            reason = f"score {score:.6f} < review_threshold {rule.review_threshold:.6f}"
        else:
            route = PolicyRoute.MANUAL_REVIEW
            reason = "automatic release disabled by tenant workflow configuration"
    elif score < rule.hold_threshold:
        route = PolicyRoute.MANUAL_REVIEW
        reason = (
            f"review_threshold {rule.review_threshold:.6f} <= score {score:.6f} "
            f"< hold_threshold {rule.hold_threshold:.6f}"
        )
    else:
        route = PolicyRoute.BATCH_HOLD_AND_REVIEW
        reason = f"score {score:.6f} >= hold_threshold {rule.hold_threshold:.6f}"
    # Workflow preferences may change how a safe route is operationalised, but
    # they can never turn an abnormal or uncertain result into auto-release.
    if route == PolicyRoute.BATCH_HOLD_AND_REVIEW and not batch_hold_enabled:
        if manual_review_enabled:
            route = PolicyRoute.MANUAL_REVIEW
            reason = "batch hold disabled by tenant workflow; human review required"
        else:
            reason = "review and batch hold disabled; fail-safe batch hold retained"
    elif route == PolicyRoute.MANUAL_REVIEW and not manual_review_enabled:
        if batch_hold_enabled:
            route = PolicyRoute.BATCH_HOLD_AND_REVIEW
            reason = "manual review disabled by tenant workflow; fail-safe batch hold applied"
        else:
            route = PolicyRoute.BATCH_HOLD_AND_REVIEW
            reason = "review and batch hold disabled; fail-safe batch hold retained"
    return PolicyEvaluation(
        route=route,
        reason=reason,
        review_threshold=rule.review_threshold,
        hold_threshold=rule.hold_threshold,
    )
