"""Command-line entry point for the reproducible VisionQC ML workflow."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .calibration import calibrate_thresholds
from .dataset import download_dataset, generate_manifest, validate_user_dataset, verify_manifest
from .dataset_source import (
    CustomerDataProvenance,
    DatasetRegistration,
    DatasetRegistrationStatus,
    DatasetSourceType,
    demo_dataset_source,
    fingerprint_directory,
)
from .errors import VisionQCError
from .evaluation import evaluate_predictions
from .feedback import feedback_json_schema, load_feedback, write_feedback_re_evaluation_input
from .hashing import write_json
from .inference import VisionQCInferenceService
from .package import verify_model_package
from .provenance import runtime_environment
from .qualification import qualify_from_directory, qualify_from_run, write_qualification_package
from .registry import ModelRegistry, compare_candidate_packages
from .schemas import inference_json_schema
from .shadow import run_shadow_evaluation
from .training import run_patchcore_baseline

ML_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = ML_ROOT.parent


def _path(value: str) -> Path:
    return Path(value).expanduser()


def _print(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _config_payload(path: Path) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _category_from_source(path: Path) -> str:
    return str(json.loads(path.read_text(encoding="utf-8"))["category"])


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="visionqc-ml", description="VisionQC PatchCore and evaluation workflow")
    subcommands = parser.add_subparsers(dest="command", required=True)

    subcommands.add_parser("env", help="print reproducibility-relevant runtime and hardware information")

    schema = subcommands.add_parser("schema", help="export a published VisionQC JSON Schema")
    schema.add_argument("--output", type=_path, default=ML_ROOT / "schemas" / "inference-result.schema.json")
    schema.add_argument("--kind", choices=["inference", "feedback"], default="inference")

    data = subcommands.add_parser("data", help="download, manifest, or verify one MVTec AD product category")
    data_commands = data.add_subparsers(dest="data_command", required=True)
    download = data_commands.add_parser(
        "download",
        help="verify a locally obtained official archive and extract one category",
    )
    download.add_argument("--source", type=_path, default=None)
    download.add_argument("--category", default=None)
    download.add_argument("--dataset-root", type=_path, default=ML_ROOT / ".data" / "mvtec-ad")
    download.add_argument("--archive-cache", type=_path, default=ML_ROOT / ".cache" / "downloads")
    download.add_argument(
        "--archive",
        type=_path,
        required=False,
        default=None,
        help="local archive obtained from the official MVTec download form; no network access",
    )
    download.add_argument("--acknowledge-license", action="store_true")
    manifest = data_commands.add_parser("manifest", help="create the fixed, hashed train/validation/test manifest")
    manifest.add_argument("--dataset-root", type=_path, default=ML_ROOT / ".data" / "mvtec-ad")
    manifest.add_argument("--output-dir", type=_path, default=None)
    manifest.add_argument("--category", default="transistor")
    manifest.add_argument("--seed", type=int, default=20260804)
    manifest.add_argument("--validation-ratio", type=float, default=0.5)
    validate = data_commands.add_parser(
        "validate", help="validate a user-provided official MVTec directory without downloading"
    )
    validate.add_argument("--dataset-root", type=_path, required=True)
    validate.add_argument("--category", choices=["transistor", "bottle"], required=True)
    validate.add_argument("--source", type=_path, default=None)
    validate.add_argument("--acknowledge-license", action="store_true")
    verify = data_commands.add_parser("verify", help="rehash every manifest file and split")
    verify.add_argument("--manifest", type=_path, default=None)
    verify.add_argument("--meta", type=_path, default=None)
    verify.add_argument("--category", default="transistor")
    verify.add_argument("--dataset-root", type=_path, default=ML_ROOT / ".data" / "mvtec-ad")

    dataset = subcommands.add_parser("dataset", help="create a source-scoped dataset registration contract")
    dataset_commands = dataset.add_subparsers(dest="dataset_command", required=True)
    register_dataset = dataset_commands.add_parser(
        "register", help="validate a mounted source and write DatasetRegistration JSON"
    )
    register_dataset.add_argument("--source-type", choices=[item.value for item in DatasetSourceType], required=True)
    register_dataset.add_argument("--name", required=True)
    register_dataset.add_argument("--category", required=True)
    register_dataset.add_argument("--source-path", type=_path, default=None)
    register_dataset.add_argument("--source-config", type=_path, default=None)
    register_dataset.add_argument("--output", type=_path, required=True)
    register_dataset.add_argument("--acknowledge-license", action="store_true")
    register_dataset.add_argument("--customer-provenance", type=_path, default=None)

    calibration = subcommands.add_parser("calibrate", help="calibrate review/hold thresholds from validation JSONL")
    calibration.add_argument("--predictions", type=_path, required=True)
    calibration.add_argument("--output-dir", type=_path, required=True)
    calibration.add_argument("--policy-version", required=True)
    calibration.add_argument("--max-false-accept-rate", type=float, default=0.0)
    calibration.add_argument("--target-hold-recall", type=float, default=0.8)
    calibration.add_argument("--strategy", choices=["legacy", "safety_margin"], default="legacy")
    calibration.add_argument("--safety-margin", type=float, default=0.0)

    evaluate = subcommands.add_parser("evaluate", help="evaluate frozen thresholds on held-out test JSONL")
    evaluate.add_argument("--predictions", type=_path, required=True)
    evaluate.add_argument("--manifest", type=_path, required=True)
    evaluate.add_argument("--manifest-meta", type=_path, required=True)
    evaluate.add_argument("--dataset-root", type=_path, required=True)
    evaluate.add_argument("--thresholds", type=_path, required=True)
    evaluate.add_argument("--output-dir", type=_path, required=True)
    evaluate.add_argument("--model-id", required=True)
    evaluate.add_argument("--model-version", required=True)
    evaluate.add_argument("--performance-probe", type=_path, default=None)
    evaluate.add_argument("--gallery-dir", type=_path, default=None)

    pilot = subcommands.add_parser("pilot", help="write source-scoped Demo, benchmark, or customer Pilot evidence")
    pilot.add_argument("--category", choices=["transistor", "bottle"], required=True)
    pilot.add_argument(
        "--factory",
        "--context",
        dest="factory",
        required=True,
        help="report context label; it is not a claim of factory or customer data",
    )
    pilot.add_argument("--output-dir", type=_path, required=True)
    pilot.add_argument("--dataset-root", type=_path, default=None)
    pilot.add_argument("--source", type=_path, default=None)
    pilot.add_argument(
        "--run-dir",
        "--baseline-run",
        dest="run_dir",
        type=_path,
        default=None,
        help="immutable baseline run containing manifest-bound predictions, calibration, evaluation, probe, and gallery",
    )
    pilot.add_argument("--model-package", type=_path, default=None)
    pilot.add_argument(
        "--source-type",
        choices=[item.value for item in DatasetSourceType],
        default=DatasetSourceType.DEMO_SYNTHETIC.value,
        help="dataset source contract; defaults to the built-in DEMO_SYNTHETIC workflow",
    )
    pilot.add_argument(
        "--customer-provenance",
        type=_path,
        default=None,
        help="JSON file satisfying the CUSTOMER_PILOT provenance contract",
    )
    pilot.add_argument("--acknowledge-license", action="store_true")
    pilot.add_argument("--repository-root", type=_path, default=REPOSITORY_ROOT)

    baseline = subcommands.add_parser("baseline", help="train, calibrate, evaluate, and package PatchCore")
    baseline.add_argument("--config", type=_path, default=ML_ROOT / "configs" / "patchcore-transistor.yaml")
    baseline.add_argument("--manifest", type=_path, default=None)
    baseline.add_argument("--manifest-meta", type=_path, default=None)
    baseline.add_argument("--dataset-root", type=_path, default=None)
    baseline.add_argument("--run-dir", type=_path, default=None)
    baseline.add_argument("--package-root", type=_path, default=ML_ROOT / ".artifacts" / "model-packages")

    package = subcommands.add_parser("package", help="verify a versioned model package")
    package.add_argument("package_dir", type=_path)

    infer = subcommands.add_parser("infer", help="run one packaged model inference")
    infer.add_argument("--package-dir", type=_path, required=True)
    infer.add_argument("--image", type=_path, required=True)
    infer.add_argument("--inspection-id", required=True)
    infer.add_argument("--output-dir", type=_path, default=ML_ROOT / ".artifacts" / "inference")
    infer.add_argument("--device", choices=["auto", "cpu", "cuda", "gpu"], default="auto")
    infer.add_argument("--warmup-runs", type=int, default=3)

    registry = subcommands.add_parser("registry", help="manage the offline Model Registry lifecycle")
    registry.add_argument("--index", type=_path, default=ML_ROOT / ".artifacts" / "registry" / "index.json")
    registry_commands = registry.add_subparsers(dest="registry_command", required=True)
    register = registry_commands.add_parser("register", help="register an integrity-verified package as DRAFT")
    register.add_argument("--package-dir", type=_path, required=True)
    register.add_argument("--actor", default="system")
    register.add_argument("--tenant-id", default=None)
    register.add_argument("--product-code", default=None)
    register.add_argument("--deployment-pack-key", default=None)
    register.add_argument("--evidence-package", type=_path, default=None)
    for command, help_text in (
        ("evaluate", "move DRAFT to EVALUATED with evaluation evidence"),
        ("approve", "move EVALUATED to APPROVED with approval evidence"),
        ("activate", "activate an APPROVED package and retire the prior active version"),
        ("retire", "retire an active or approved package"),
    ):
        item = registry_commands.add_parser(command, help=help_text)
        item.add_argument("--model-id", required=True)
        item.add_argument("--model-version", required=True)
        item.add_argument("--actor", required=True)
        item.add_argument("--evidence-summary", required=True)
    rollback = registry_commands.add_parser("rollback", help="reactivate a prior package with explicit conditions")
    rollback.add_argument("--model-id", required=True)
    rollback.add_argument("--model-version", required=True)
    rollback.add_argument("--actor", required=True)
    rollback.add_argument("--evidence-summary", required=True)
    rollback.add_argument("--rollback-condition", required=True)
    compare = registry_commands.add_parser("compare", help="compare two package evaluation reports offline")
    compare.add_argument("--left-package", type=_path, required=True)
    compare.add_argument("--right-package", type=_path, required=True)
    compare.add_argument("--output", type=_path, default=None)

    shadow = subcommands.add_parser("shadow", help="run offline active/candidate shadow comparison")
    shadow_commands = shadow.add_subparsers(dest="shadow_command", required=True)
    shadow_compare = shadow_commands.add_parser("compare", help="compare precomputed scores and routes")
    shadow_compare.add_argument("--active-predictions", type=_path, required=True)
    shadow_compare.add_argument("--candidate-predictions", type=_path, required=True)
    shadow_compare.add_argument("--active-thresholds", type=_path, required=True)
    shadow_compare.add_argument("--candidate-thresholds", type=_path, required=True)
    shadow_compare.add_argument("--product-category", required=True)
    shadow_compare.add_argument("--output", type=_path, required=True)

    feedback = subcommands.add_parser("feedback", help="validate and package manual feedback for offline re-evaluation")
    feedback_commands = feedback.add_subparsers(dest="feedback_command", required=True)
    feedback_prepare = feedback_commands.add_parser("prepare", help="write a validated re-evaluation input contract")
    feedback_prepare.add_argument("--input", type=_path, required=True)
    feedback_prepare.add_argument("--output-dir", type=_path, required=True)
    feedback_prepare.add_argument("--product-category", default=None)
    feedback_schema = feedback_commands.add_parser("schema", help="write the manual feedback JSON Schema")
    feedback_schema.add_argument("--output", type=_path, default=ML_ROOT / "schemas" / "model-feedback.schema.json")
    return parser


def _dispatch(args: argparse.Namespace) -> Any:
    if args.command == "env":
        return runtime_environment()
    if args.command == "schema":
        write_json(args.output, inference_json_schema() if args.kind == "inference" else feedback_json_schema())
        return {"schema": str(args.output.resolve())}
    if args.command == "data":
        if args.data_command == "download":
            if args.archive is None:
                raise ValueError(
                    "automatic dataset downloads are disabled for qualification; obtain the archive from "
                    "the official MVTec AD page and pass it with --archive"
                )
            source = args.source
            if source is None:
                category = args.category or "transistor"
                source = ML_ROOT / "configs" / f"mvtec-ad-{category}.json"
            category = args.category or _category_from_source(source)
            source_category = _category_from_source(source)
            if source_category != category:
                raise ValueError(f"source category {source_category} does not match requested category {category}")
            return download_dataset(
                source,
                args.dataset_root,
                args.archive_cache,
                license_acknowledged=args.acknowledge_license,
                archive_path=args.archive,
            )
        if args.data_command == "manifest":
            output_dir = args.output_dir or ML_ROOT / ".artifacts" / "manifests" / f"{args.category}-v1"
            return generate_manifest(
                args.dataset_root,
                output_dir,
                args.seed,
                args.validation_ratio,
                args.category,
            )
        if args.data_command == "validate":
            if not args.acknowledge_license:
                raise ValueError("official MVTec data requires --acknowledge-license after license review")
            return validate_user_dataset(
                args.dataset_root,
                category=args.category,
                source_config=args.source,
                license_acknowledged=True,
            )
        manifest_path = args.manifest or ML_ROOT / ".artifacts" / "manifests" / f"{args.category}-v1" / "manifest.jsonl"
        meta_path = args.meta or ML_ROOT / ".artifacts" / "manifests" / f"{args.category}-v1" / "manifest-meta.json"
        return verify_manifest(manifest_path, args.dataset_root, meta_path)
    if args.command == "dataset":
        source_type = DatasetSourceType(args.source_type)
        if source_type == DatasetSourceType.DEMO_SYNTHETIC:
            source = demo_dataset_source(args.category).model_copy(update={"name": args.name})
        else:
            if args.source_path is None:
                raise ValueError("--source-path is required for optional dataset sources")
            provenance = (
                CustomerDataProvenance.model_validate(json.loads(args.customer_provenance.read_text(encoding="utf-8")))
                if args.customer_provenance is not None
                else None
            )
            if source_type == DatasetSourceType.OFFICIAL_BENCHMARK:
                if not args.acknowledge_license:
                    raise ValueError("OFFICIAL_BENCHMARK requires --acknowledge-license")
                receipt = validate_user_dataset(
                    args.source_path,
                    category=args.category,
                    source_config=args.source_config,
                    license_acknowledged=True,
                )
                with tempfile.TemporaryDirectory(prefix="visionqc-registration-") as temporary:
                    registration_manifest_meta = generate_manifest(
                        args.source_path if (args.source_path / args.category).is_dir() else args.source_path.parent,
                        Path(temporary),
                        category=args.category,
                    )
                category_root = (
                    args.source_path / args.category
                    if (args.source_path / args.category).is_dir()
                    else args.source_path
                )
                source = fingerprint_directory(
                    category_root,
                    source_type=source_type,
                    category=args.category,
                ).model_copy(
                    update={
                        "name": args.name,
                        "dataset_fingerprint": registration_manifest_meta["dataset_fingerprint"],
                        "manifest_sha256": registration_manifest_meta["manifest_sha256"],
                        "source_sha256": receipt.get("source_archive_sha256") or receipt.get("archive_sha256"),
                        "license_acknowledged": True,
                    }
                )
            else:
                source = fingerprint_directory(
                    args.source_path,
                    source_type=source_type,
                    category=args.category,
                ).model_copy(
                    update={
                        "name": args.name,
                        "status": (
                            DatasetRegistrationStatus.VALIDATED
                            if provenance is not None and provenance.consent
                            else DatasetRegistrationStatus.DRAFT
                        ),
                        "customer_provenance": provenance,
                        "risk_labels": []
                        if provenance is not None and provenance.consent
                        else ["CUSTOMER_PROVENANCE_INCOMPLETE", "PILOT_APPROVAL_BLOCKED"],
                    }
                )
        registration = DatasetRegistration(
            source=source,
            metadata={"source_path": str(args.source_path.resolve()) if args.source_path else None},
            created_at=datetime.now(timezone.utc),
        )
        write_json(args.output, registration.model_dump(mode="json"))
        return registration.model_dump(mode="json")
    if args.command == "calibrate":
        return calibrate_thresholds(
            args.predictions,
            args.output_dir,
            args.policy_version,
            args.max_false_accept_rate,
            args.target_hold_recall,
            strategy=args.strategy,
            safety_margin=args.safety_margin,
        ).model_dump(mode="json")
    if args.command == "evaluate":
        return evaluate_predictions(
            args.predictions,
            args.manifest,
            args.manifest_meta,
            args.dataset_root,
            args.thresholds,
            args.output_dir,
            {"id": args.model_id, "version": args.model_version, "adapter": "anomalib.patchcore.v2"},
            runtime_environment(),
            performance_probe_path=args.performance_probe,
            gallery_output_dir=args.gallery_dir,
        )
    if args.command == "pilot":
        source_type = DatasetSourceType(args.source_type)
        customer_provenance = (
            CustomerDataProvenance.model_validate(json.loads(args.customer_provenance.read_text(encoding="utf-8")))
            if args.customer_provenance is not None
            else None
        )
        if args.run_dir is not None:
            if args.model_package is None:
                raise ValueError("--model-package is required when --run-dir is supplied")
            return qualify_from_run(
                args.run_dir,
                factory=args.factory,
                category=args.category,
                model_package=args.model_package,
                output_dir=args.output_dir,
                dataset_root=args.dataset_root,
                source_config=args.source,
                repository_root=args.repository_root,
                source_type=source_type,
                customer_provenance=customer_provenance,
            )
        if args.model_package is not None:
            raise ValueError(
                "--model-package requires --run-dir so the validation/test evidence contract cannot be bypassed"
            )
        if args.dataset_root is not None:
            if source_type != DatasetSourceType.OFFICIAL_BENCHMARK:
                raise ValueError("--dataset-root directory imports currently require OFFICIAL_BENCHMARK")
            result = qualify_from_directory(
                args.dataset_root,
                category=args.category,
                source_config=args.source,
                output_dir=args.output_dir,
                repository_root=args.repository_root,
                license_acknowledged=args.acknowledge_license,
            )
            return result
        return write_qualification_package(
            args.output_dir,
            factory=args.factory,
            category=args.category,
            source_type=source_type,
            customer_provenance=customer_provenance,
            repository_root=args.repository_root,
        )
    if args.command == "baseline":
        config = _config_payload(args.config)
        category = str(config["data"]["category"])
        model_id = str(config["model"]["id"])
        model_version = str(config["model"]["version"])
        manifest: Path = args.manifest or ML_ROOT / ".artifacts" / "manifests" / f"{category}-v1" / "manifest.jsonl"
        manifest_meta: Path = args.manifest_meta or manifest.parent / "manifest-meta.json"
        dataset_root: Path = args.dataset_root or ML_ROOT / ".data" / "mvtec-ad"
        run_dir: Path = args.run_dir or ML_ROOT / ".artifacts" / "runs" / f"{model_id}-{model_version}"
        return run_patchcore_baseline(
            args.config,
            manifest,
            manifest_meta,
            dataset_root,
            run_dir,
            args.package_root,
            REPOSITORY_ROOT,
            ML_ROOT / "licenses" / "MVTEC-AD-NOTICE.md",
        )
    if args.command == "package":
        return verify_model_package(args.package_dir).model_dump(mode="json")
    if args.command == "infer":
        service = VisionQCInferenceService.from_package(args.package_dir, args.device)
        if args.warmup_runs:
            service.warmup(args.image, args.warmup_runs)
        return service.infer(args.image, args.inspection_id, args.output_dir).model_dump(mode="json")
    if args.command == "registry":
        if args.registry_command == "compare":
            result = compare_candidate_packages(args.left_package, args.right_package)
            if args.output:
                write_json(args.output, result)
            return result
        registry = ModelRegistry(args.index)
        if args.registry_command == "register":
            return registry.register_draft(
                args.package_dir,
                args.actor,
                tenant_id=args.tenant_id,
                product_code=args.product_code,
                deployment_pack_key=args.deployment_pack_key,
                evidence_package_path=args.evidence_package,
            ).model_dump(mode="json")
        if args.registry_command == "evaluate":
            return registry.evaluate(args.model_id, args.model_version, args.actor, args.evidence_summary).model_dump(
                mode="json"
            )
        if args.registry_command == "approve":
            return registry.approve(args.model_id, args.model_version, args.actor, args.evidence_summary).model_dump(
                mode="json"
            )
        if args.registry_command == "activate":
            return registry.activate(args.model_id, args.model_version, args.actor, args.evidence_summary).model_dump(
                mode="json"
            )
        if args.registry_command == "retire":
            return registry.retire(args.model_id, args.model_version, args.actor, args.evidence_summary).model_dump(
                mode="json"
            )
        if args.registry_command == "rollback":
            return registry.rollback(
                args.model_id,
                args.model_version,
                args.actor,
                args.evidence_summary,
                args.rollback_condition,
            ).model_dump(mode="json")
        raise AssertionError(f"unhandled registry command: {args.registry_command}")
    if args.command == "shadow":
        if args.shadow_command == "compare":
            return run_shadow_evaluation(
                args.active_predictions,
                args.candidate_predictions,
                args.active_thresholds,
                args.candidate_thresholds,
                args.output,
                product_category=args.product_category,
            )
        raise AssertionError(f"unhandled shadow command: {args.shadow_command}")
    if args.command == "feedback":
        if args.feedback_command == "prepare":
            records = load_feedback(args.input, product_category=args.product_category)
            return write_feedback_re_evaluation_input(records, args.output_dir)
        if args.feedback_command == "schema":
            write_json(args.output, feedback_json_schema())
            return {"schema": str(args.output.resolve())}
        raise AssertionError(f"unhandled feedback command: {args.feedback_command}")
    raise AssertionError(f"unhandled command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    """Run the CLI with structured errors suitable for CI and workers."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        result = _dispatch(args)
        _print(result)
        return 0
    except (VisionQCError, ValueError, FileNotFoundError, FileExistsError) as exc:
        payload = {
            "error": getattr(exc, "code", "invalid_request"),
            "message": str(exc),
            "type": type(exc).__name__,
        }
        print(json.dumps(payload, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
