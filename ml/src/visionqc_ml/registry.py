"""Small file-backed Model Registry for auditable PatchCore lifecycle changes."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from .errors import ModelPackageError
from .hashing import read_json, sha256_file, write_json
from .package import verify_model_package
from .qualification import verify_evidence_package
from .schemas import StrictModel

LifecycleStatus = Literal["DRAFT", "EVALUATED", "APPROVED", "ACTIVE", "RETIRED"]


class RegistryTransition(StrictModel):
    from_status: LifecycleStatus | None = None
    to_status: LifecycleStatus
    actor: str = Field(min_length=1)
    evidence_summary: str = Field(min_length=10)
    evidence_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    occurred_at: str
    reason: str | None = None
    correlation_id: str = "registry"


class RegistryEntry(StrictModel):
    schema_version: Literal["visionqc.model-registry-entry.v1"] = "visionqc.model-registry-entry.v1"
    model_id: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    category: str = Field(min_length=1)
    package_path: str = Field(min_length=1)
    package_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lifecycle_status: LifecycleStatus
    created_at: str
    updated_at: str
    transitions: list[RegistryTransition] = Field(min_length=1)
    tenant_id: str | None = None
    product_code: str | None = None
    deployment_pack_key: str | None = None
    evidence_package_path: str | None = None
    evidence_package_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    audit_reasons: list[str] = Field(default_factory=list)


class RegistryIndex(StrictModel):
    schema_version: Literal["visionqc.model-registry.v1"] = "visionqc.model-registry.v1"
    updated_at: str
    entries: list[RegistryEntry] = Field(default_factory=list)


_DIRECT_TRANSITIONS: dict[str, set[str]] = {
    "DRAFT": {"EVALUATED"},
    "EVALUATED": {"APPROVED"},
    "APPROVED": {"ACTIVE", "RETIRED"},
    "ACTIVE": {"RETIRED"},
    "RETIRED": set(),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_evidence(summary: str, actor: str) -> tuple[str, str]:
    normalized_summary = " ".join(summary.split())
    if len(normalized_summary) < 10:
        raise ValueError("lifecycle evidence summary must contain at least 10 non-whitespace characters")
    normalized_actor = actor.strip()
    if not normalized_actor:
        raise ValueError("lifecycle actor is required")
    return normalized_summary, normalized_actor


class ModelRegistry:
    """JSON index with explicit transition guards and append-only histories."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.index = self._load()

    def _load(self) -> RegistryIndex:
        if not self.path.is_file():
            return RegistryIndex(updated_at=_now())
        try:
            return RegistryIndex.model_validate(read_json(self.path))
        except Exception as exc:
            raise ValueError(f"invalid model registry index: {self.path}: {exc}") from exc

    def _persist(self) -> None:
        self.index = self.index.model_copy(update={"updated_at": _now()})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".partial")
        write_json(temporary, self.index.model_dump(mode="json"))
        temporary.replace(self.path)

    def _entry(self, model_id: str, model_version: str) -> RegistryEntry:
        for entry in self.index.entries:
            if entry.model_id == model_id and entry.model_version == model_version:
                return entry
        raise KeyError(f"model is not registered: {model_id}@{model_version}")

    def register_draft(
        self,
        package_dir: Path,
        actor: str = "system",
        *,
        tenant_id: str | None = None,
        product_code: str | None = None,
        deployment_pack_key: str | None = None,
        evidence_package_path: Path | None = None,
        correlation_id: str = "registry",
    ) -> RegistryEntry:
        """Register an integrity-verified package as DRAFT only."""
        manifest = verify_model_package(package_dir)
        evidence_sha: str | None = None
        if evidence_package_path is not None:
            evidence_sha = verify_evidence_package(
                evidence_package_path, expected_model_package_sha256=manifest.package_sha256
            )["evidence_package_sha256"]
        actor = actor.strip() or "system"
        if any(
            entry.model_id == manifest.model_id and entry.model_version == manifest.model_version
            for entry in self.index.entries
        ):
            raise ValueError(f"model is already registered: {manifest.model_id}@{manifest.model_version}")
        now = _now()
        transition = RegistryTransition(
            from_status=None,
            to_status="DRAFT",
            actor=actor,
            evidence_summary="Package integrity verified and registered as a draft candidate.",
            evidence_sha256=manifest.package_sha256,
            occurred_at=now,
            correlation_id=correlation_id,
        )
        entry = RegistryEntry(
            model_id=manifest.model_id,
            model_version=manifest.model_version,
            category=manifest.category,
            package_path=str(package_dir.resolve()),
            package_sha256=manifest.package_sha256,
            lifecycle_status="DRAFT",
            created_at=now,
            updated_at=now,
            transitions=[transition],
            tenant_id=tenant_id,
            product_code=product_code or manifest.category,
            deployment_pack_key=deployment_pack_key,
            evidence_package_path=str(evidence_package_path.resolve()) if evidence_package_path else None,
            evidence_package_sha256=evidence_sha,
        )
        self.index.entries.append(entry)
        self._persist()
        return entry

    def _transition(
        self,
        entry: RegistryEntry,
        to_status: LifecycleStatus,
        actor: str,
        evidence_summary: str,
        *,
        evidence_sha256: str | None = None,
        reason: str | None = None,
        allow_retired_reactivation: bool = False,
        correlation_id: str = "registry",
    ) -> RegistryEntry:
        summary, normalized_actor = _require_evidence(evidence_summary, actor)
        current = entry.lifecycle_status
        if to_status not in _DIRECT_TRANSITIONS[current] and not (
            allow_retired_reactivation and current == "RETIRED" and to_status == "ACTIVE"
        ):
            raise ValueError(f"illegal model lifecycle transition: {current} -> {to_status}")
        transition = RegistryTransition(
            from_status=current,
            to_status=to_status,
            actor=normalized_actor,
            evidence_summary=summary,
            evidence_sha256=evidence_sha256,
            occurred_at=_now(),
            reason=reason,
            correlation_id=correlation_id,
        )
        updated = entry.model_copy(
            update={
                "lifecycle_status": to_status,
                "updated_at": transition.occurred_at,
                "transitions": [*entry.transitions, transition],
            }
        )
        position = self.index.entries.index(entry)
        self.index.entries[position] = updated
        return updated

    def evaluate(self, model_id: str, model_version: str, actor: str, evidence_summary: str) -> RegistryEntry:
        entry = self._entry(model_id, model_version)
        verify_model_package(Path(entry.package_path))
        if entry.evidence_package_path:
            evidence = verify_evidence_package(
                Path(entry.evidence_package_path), expected_model_package_sha256=entry.package_sha256
            )
            if entry.evidence_package_sha256 != evidence["evidence_package_sha256"]:
                raise ModelPackageError("registered qualification evidence digest changed")
            gate_decision = str(evidence.get("gate_decision", evidence.get("decision")))
            if gate_decision != "GO":
                release = read_json(Path(entry.evidence_package_path) / "release-decision.json")
                failed = release.get("gates", {}).get("failed", [])
                decision = str(evidence.get("gate_decision", evidence.get("decision")))
                report_status = str(evidence.get("decision"))
                reason = (
                    f"qualification_gate_blocked:{decision}; report_status={report_status}; candidate remains DRAFT; "
                    f"failed_gates={','.join(str(item) for item in failed) or 'none'}"
                )
                summary, normalized_actor = _require_evidence(evidence_summary, actor)
                transition = RegistryTransition(
                    from_status="DRAFT",
                    to_status="DRAFT",
                    actor=normalized_actor,
                    evidence_summary=summary,
                    evidence_sha256=evidence["evidence_package_sha256"],
                    occurred_at=_now(),
                    reason=reason,
                )
                updated = entry.model_copy(
                    update={
                        "updated_at": transition.occurred_at,
                        "transitions": [*entry.transitions, transition],
                        "audit_reasons": [*entry.audit_reasons, reason],
                    }
                )
                self.index.entries[self.index.entries.index(entry)] = updated
                return self._finish(updated)
        evaluation_path = Path(entry.package_path) / "metrics" / "evaluation.json"
        return self._finish(
            self._transition(
                entry,
                "EVALUATED",
                actor,
                evidence_summary,
                evidence_sha256=sha256_file(evaluation_path),
            )
        )

    def approve(self, model_id: str, model_version: str, approver: str, evidence_summary: str) -> RegistryEntry:
        entry = self._entry(model_id, model_version)
        if entry.evidence_package_path:
            evidence = verify_evidence_package(
                Path(entry.evidence_package_path), expected_model_package_sha256=entry.package_sha256
            )
            if evidence.get("gate_decision", evidence.get("decision")) != "GO":
                raise ValueError(
                    "qualification evidence gate is not GO; candidate remains DRAFT and approval is blocked"
                )
            if (
                evidence.get("source_type") != "CUSTOMER_PILOT"
                or not evidence.get("approval_status") == "PENDING_APPROVAL"
            ):
                raise ValueError(
                    "benchmark/demo evidence cannot be approved; CUSTOMER_PILOT provenance is required and the candidate remains DRAFT"
                )
            evaluated_actor = entry.transitions[-1].actor
            if evaluated_actor == approver:
                raise ValueError("evaluator cannot approve the same qualification")
        return self._finish(self._transition(entry, "APPROVED", approver, evidence_summary))

    def activate(self, model_id: str, model_version: str, actor: str, evidence_summary: str) -> RegistryEntry:
        candidate = self._entry(model_id, model_version)
        if candidate.lifecycle_status != "APPROVED":
            raise ValueError(f"only APPROVED models can be activated, got {candidate.lifecycle_status}")
        manifest = verify_model_package(Path(candidate.package_path))
        if manifest.package_sha256 != candidate.package_sha256:
            raise ModelPackageError("registered package digest changed before activation")
        summary, normalized_actor = _require_evidence(evidence_summary, actor)
        if candidate.evidence_package_path:
            evidence = verify_evidence_package(
                Path(candidate.evidence_package_path), expected_model_package_sha256=manifest.package_sha256
            )
            if evidence.get("gate_decision", evidence.get("decision")) != "GO":
                raise ValueError("qualification evidence gate is not GO; activation is blocked")
            if evidence.get("source_type") != "CUSTOMER_PILOT" or evidence.get("approval_status") != "PENDING_APPROVAL":
                raise ValueError("benchmark/demo evidence cannot activate a model; CUSTOMER_PILOT approval is required")
            if normalized_actor in {
                transition.actor
                for transition in candidate.transitions
                if transition.to_status in {"EVALUATED", "APPROVED"}
            }:
                raise ValueError("activation actor must be distinct from evaluation and approval actors")
        same_product_active = [
            entry
            for entry in self.index.entries
            if entry.category == candidate.category
            and entry.model_id == candidate.model_id
            and entry.lifecycle_status == "ACTIVE"
        ]
        for previous in same_product_active:
            self._transition(
                previous,
                "RETIRED",
                normalized_actor,
                f"Retired as part of activating {candidate.model_id}@{candidate.model_version}. {summary}",
                evidence_sha256=manifest.package_sha256,
                reason="superseded_by_activation",
            )
        result = self._transition(
            candidate,
            "ACTIVE",
            normalized_actor,
            summary,
            evidence_sha256=manifest.package_sha256,
            reason="activation",
        )
        return self._finish(result)

    def retire(self, model_id: str, model_version: str, actor: str, evidence_summary: str) -> RegistryEntry:
        entry = self._entry(model_id, model_version)
        return self._finish(self._transition(entry, "RETIRED", actor, evidence_summary, reason="retirement"))

    def rollback(
        self,
        model_id: str,
        model_version: str,
        actor: str,
        evidence_summary: str,
        rollback_condition: str,
    ) -> RegistryEntry:
        """Reactivate a prior package only with a recorded rollback condition."""
        if len(rollback_condition.strip()) < 10:
            raise ValueError("rollback condition must be explicit and at least 10 characters")
        target = self._entry(model_id, model_version)
        if target.lifecycle_status not in {"RETIRED", "APPROVED"}:
            raise ValueError(f"rollback target must be RETIRED or APPROVED, got {target.lifecycle_status}")
        manifest = verify_model_package(Path(target.package_path))
        if manifest.package_sha256 != target.package_sha256:
            raise ModelPackageError("registered rollback package digest changed")
        summary, normalized_actor = _require_evidence(evidence_summary, actor)
        active_entries = [
            entry
            for entry in self.index.entries
            if entry.category == target.category
            and entry.model_id == target.model_id
            and entry.lifecycle_status == "ACTIVE"
        ]
        for active in active_entries:
            self._transition(
                active,
                "RETIRED",
                normalized_actor,
                f"Rollback requested because {rollback_condition.strip()}. {summary}",
                reason="rollback_current_active",
            )
        result = self._transition(
            target,
            "ACTIVE",
            normalized_actor,
            f"Rollback requested because {rollback_condition.strip()}. {summary}",
            evidence_sha256=manifest.package_sha256,
            reason="rollback",
            allow_retired_reactivation=True,
        )
        return self._finish(result)

    def _finish(self, entry: RegistryEntry) -> RegistryEntry:
        self._persist()
        return entry

    def to_dict(self) -> dict[str, Any]:
        return self.index.model_dump(mode="json")


def compare_candidate_packages(left_package: Path, right_package: Path) -> dict[str, Any]:
    """Compare two evaluated package reports without changing registry state."""
    left = verify_model_package(left_package)
    right = verify_model_package(right_package)
    if left.category != right.category:
        raise ValueError(f"candidate comparison requires one product category: {left.category} vs {right.category}")
    left_report = read_json(left_package / "metrics" / "evaluation.json")
    right_report = read_json(right_package / "metrics" / "evaluation.json")

    def metric(report: dict[str, Any], *path: str) -> float | None:
        value: Any = report
        for key in path:
            if not isinstance(value, dict):
                return None
            value = value.get(key)
        return float(value) if isinstance(value, float | int) else None

    metric_paths = {
        "image_auroc": ("metrics", "image_level", "auroc"),
        "review_f1": ("metrics", "image_level", "at_review_threshold", "f1"),
        "hold_recall": ("metrics", "image_level", "at_hold_threshold", "recall"),
        "false_accept_rate": ("metrics", "business", "false_accept_rate"),
        "false_reject_rate": ("metrics", "business", "false_reject_rate"),
        "warm_p95_ms": ("metrics", "performance", "warm_p95_ms"),
    }
    rows: dict[str, dict[str, float | None]] = {}
    for name, path in metric_paths.items():
        left_value = metric(left_report, *path)
        right_value = metric(right_report, *path)
        rows[name] = {
            "left": left_value,
            "right": right_value,
            "delta_right_minus_left": (
                right_value - left_value if left_value is not None and right_value is not None else None
            ),
        }
    return {
        "schema_version": "visionqc.candidate-comparison.v1",
        "category": left.category,
        "left": {
            "model_id": left.model_id,
            "model_version": left.model_version,
            "package_sha256": left.package_sha256,
        },
        "right": {
            "model_id": right.model_id,
            "model_version": right.model_version,
            "package_sha256": right.package_sha256,
        },
        "metrics": rows,
        "decision_note": "Comparison is offline evidence only; activation still requires approval and an explicit lifecycle transition.",
    }
