#!/usr/bin/env python3
"""Customer-safe VisionQC pack initialization and preflight CLI.

The CLI creates configuration only.  It never creates or prints production
secrets; connector credentials are represented by secret references and are
expected to come from the deployment environment.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "backend"
INDUSTRY_ROOT = BACKEND_ROOT / "deployment-packs" / "industry-packs"
sys.path.insert(0, str(BACKEND_ROOT))

from app.deployment import (  # noqa: E402
    EdgeGatewayDefinition,
    GatewayWatchDefinition,
    IndustryPack,
    LocalizationDefinition,
    MigrationNotes,
    PackIntegrity,
    PackValidation,
    TenantDefinition,
    TenantOverlay,
    load_and_resolve_pack,
    load_industry_pack,
    load_manifest,
    load_tenant_overlay,
    payload_sha256,
    resolve_pack,
)


def _json_dump(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def _example_industry_path(name: str) -> Path:
    candidate = INDUSTRY_ROOT / f"{name}.json"
    if not candidate.exists():
        available = ", ".join(path.stem for path in sorted(INDUSTRY_ROOT.glob("*.json")))
        raise ValueError(f"unknown industry {name!r}; choose one of: {available}")
    return candidate


def _set_integrity(model: IndustryPack | TenantOverlay) -> dict[str, Any]:
    payload = model.model_dump(mode="json")
    digest = payload_sha256(payload)
    model.integrity = PackIntegrity(manifest_sha256=digest)
    return model.model_dump(mode="json")


def _watch_for_generated_pack(
    *,
    root: str,
    source: str,
    station_code: str,
    product_code: str,
    product_revision: str,
    timezone: str,
) -> GatewayWatchDefinition:
    # The generated contract is intentionally boring and easy to adapt.  A
    # site can refine it in the overlay without editing application code.
    return GatewayWatchDefinition(
        root=root,
        relative_path_regex=r"^station/(?P<station_code>[A-Za-z0-9_-]+)$",
        filename_regex=(
            r"^(?P<product>[A-Za-z0-9_-]+)__batch=(?P<batch>[A-Za-z0-9_-]+)__"
            r"captured=(?P<captured_at>[0-9]{8}T[0-9]{6})__seq=(?P<sequence>[0-9]{6})\."
            r"(?P<extension>png|jpe?g)$"
        ),
        capture_map={
            "product_code": "product",
            "batch_no": "batch",
            "station_code": "station_code",
            "captured_at": "captured_at",
        },
        defaults={"product_revision": product_revision},
        source=source,
        allowed_extensions=[".png", ".jpg", ".jpeg"],
        timestamp_formats=["%Y%m%dT%H%M%S"],
        timezone_offset=timezone,
        stable_for_seconds=1.0,
        archive_subdir=".archive",
        quarantine_subdir=".quarantine",
    )


def init_tenant(args: argparse.Namespace) -> int:
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}", args.tenant_id):
        raise ValueError("tenant-id must contain only letters, numbers, underscore or hyphen")
    industry_path = (
        Path(args.industry_pack).resolve()
        if args.industry_pack
        else _example_industry_path(args.industry)
    )
    industry = load_industry_pack(industry_path)
    defaults = industry.defaults
    default_product = defaults.get("product", {})
    default_station = defaults.get("station", {})
    product_code = args.product_code or str(
        default_product.get("code") or industry.products[0].code
    )
    product_revision = args.product_revision or str(
        default_product.get("revision") or industry.products[0].revision
    )
    station_code = args.station_code or str(
        default_station.get("code") or industry.stations[0].code
    )
    station_name = args.station_name or str(default_station.get("display_name") or station_code)
    station_description = str(
        default_station.get("description") or "Generated customer inspection station."
    )
    camera_profile = str(default_station.get("camera_profile") or "customer-configured")
    site_name = args.site_name or f"{args.tenant_name} site"
    output_dir = Path(args.output_dir).expanduser().resolve()
    watch_root = args.watch_root or "/var/lib/visionqc-gateway/incoming"
    gateway_id = args.gateway_id or f"{args.tenant_id}-gateway"

    overlay = TenantOverlay(
        overlay_key=f"tenants/{args.tenant_id}/{args.site_id}",
        version=args.version,
        display_name=f"{industry.display_name} · {site_name}",
        industry_pack={
            "key": industry.pack_key,
            "version": industry.version,
            "sha256": industry.integrity.manifest_sha256,
        },
        tenant=TenantDefinition(id=args.tenant_id, name=args.tenant_name),
        site={
            "id": args.site_id,
            "name": site_name,
            "timezone": args.timezone,
            "locale": args.locale,
        },
        input_mode=args.input_mode,
        products=[
            {
                "code": product_code,
                "display_name": args.product_name or product_code,
                "revision": product_revision,
                "aliases": [],
            }
        ],
        stations=[
            {
                "code": station_code,
                "display_name": station_name,
                "description": station_description,
                "camera_profile": camera_profile,
            }
        ],
        field_labels=industry.field_labels,
        terminology=industry.terminology,
        localization=LocalizationDefinition(
            default_locale=args.locale,
            supported_locales=sorted({args.locale, "en-US", "zh-CN"}),
            timezone=args.timezone,
            terminology=industry.localization.terminology,
        ),
        retention=industry.retention.model_copy(update={"raw_image_days": args.retention_days}),
        connectors={
            key: connector.model_copy(
                update={
                    "secret_refs": [f"VQC_{key.upper()}_API_TOKEN"]
                    if key in {"mes", "qms"} and not connector.simulated
                    else connector.secret_refs,
                }
            )
            for key, connector in industry.connectors.items()
        },
        edge_gateway=EdgeGatewayDefinition(
            gateway_id=gateway_id,
            target_tenant_id=args.tenant_id,
            watch=_watch_for_generated_pack(
                root=watch_root,
                source=f"edge-camera/{args.tenant_id}/{args.site_id}",
                station_code=station_code,
                product_code=product_code,
                product_revision=product_revision,
                timezone=args.timezone,
            ),
            simulator={
                "relative_dir_template": f"station/{station_code}",
                "filename_template": (
                    "{product}__batch={batch}__captured={captured_at}__seq={sequence}.{extension}"
                ),
                "product": product_code,
                "station": station_code,
                "product_revision": product_revision,
                "batch_prefix": f"{args.tenant_id.upper()}-DEMO",
                "extension": ".png",
            },
        ),
        validation=PackValidation(
            status="generated-pending-site-validation",
            validator="scripts/visionqc.py validate-pack",
            checks=[
                "overlay_schema",
                "industry_reference",
                "tenant_gateway_binding",
                "secret_refs",
                "integrity_hash",
            ],
            warnings=[
                "Generated configuration is not a production approval.",
                "Replace simulated connectors only after the customer's contract is approved.",
            ],
        ),
        integrity=PackIntegrity(manifest_sha256="0" * 64),
        migration=MigrationNotes(
            from_schema_versions=[
                "visionqc.tenant-overlay.v1",
                "visionqc.deployment-pack.v1",
            ],
            strategy="resolver",
            notes=(
                "Generated overlay is resolved with the referenced Industry Pack before activation."
            ),
        ),
        metadata={
            "generated_by": "visionqc init-tenant",
            "customer_specific": True,
            "real_connector_configured": False,
            "secret_material_included": False,
            "site_validation_required": True,
        },
    )
    overlay_payload = _set_integrity(overlay)
    overlay_path = output_dir / "tenant-overlay.json"
    _json_dump(overlay_path, overlay_payload)

    resolved = resolve_pack(industry, overlay)
    resolved_path = output_dir / "resolved-deployment-pack.json"
    _json_dump(resolved_path, resolved.model_dump(mode="json"))

    secret_refs = sorted(
        {
            secret_ref
            for connector in resolved.connectors.model_dump(mode="json").values()
            if connector
            for secret_ref in connector.get("secret_refs", [])
        }
    )
    env_lines = [
        "# Generated by VisionQC init-tenant. No real secret is stored here.",
        "VQC_GATEWAY_MODE=demo",
        "VQC_GATEWAY_ID=gateway-local",
        "VQC_GATEWAY_PACK_PATH=./resolved-deployment-pack.json",
        f"VQC_GATEWAY_WATCH_ROOT={watch_root}",
        "VQC_GATEWAY_BACKEND_URL=http://localhost:8000/api/v1",
        "VQC_GATEWAY_DATA_DIR=./gateway-state",
        "VQC_GATEWAY_STATUS_PORT=8090",
        "VQC_GATEWAY_UPLOAD_ENABLED=false",
        "VQC_GATEWAY_DATA_CONSENT=false",
        "",
        "# Production only: inject these through the customer's secret provider.",
        "# VQC_GATEWAY_AUTH_TOKEN=<short-lived-tenant-scoped-token>",
        "# VQC_GATEWAY_STATUS_TOKEN=<local-status-token>",
        *[f"# {secret_ref}=<injected-by-secret-provider>" for secret_ref in secret_refs],
        "# Connector refs are names only; do not paste credentials into this file.",
    ]
    (output_dir / ".env.example").write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "generated",
                "industry_pack": industry.pack_key,
                "tenant_id": args.tenant_id,
                "site_id": args.site_id,
                "overlay": str(overlay_path),
                "resolved_pack": str(resolved_path),
                "env_example": str(output_dir / ".env.example"),
                "secrets_created": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _classify(path: Path) -> tuple[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    schema = payload.get("schema_version")
    if schema == "visionqc.industry-pack.v1":
        return "industry", load_industry_pack(path)
    if schema == "visionqc.tenant-overlay.v1":
        return "overlay", load_tenant_overlay(path)
    if schema in {"visionqc.deployment-pack.v1", "visionqc.deployment-pack.v2"}:
        return "resolved", load_manifest(path)
    raise ValueError(f"unsupported pack schema in {path}: {schema!r}")


def _validate_connectors(manifest: Any) -> None:
    connectors = manifest.connectors.model_dump(mode="json")
    for name, config in connectors.items():
        if config is None:
            continue
        operations = config.get("operations", [])
        if len(operations) != len(set(operations)):
            raise ValueError(f"connector {name} declares duplicate operations")
        if not config.get("capability"):
            raise ValueError(f"connector {name} must declare capability")
        for secret_ref in config.get("secret_refs", []):
            if not re.fullmatch(r"[A-Z][A-Z0-9_]*", secret_ref):
                raise ValueError(f"connector {name} has invalid secret ref {secret_ref!r}")


def validate_paths(paths: list[Path], industry_path: Path | None, overlay_path: Path | None) -> int:
    results: list[dict[str, Any]] = []
    if industry_path or overlay_path:
        if not industry_path or not overlay_path:
            raise ValueError("--industry-pack and --overlay must be provided together")
        industry = load_industry_pack(industry_path)
        overlay = load_tenant_overlay(overlay_path)
        resolved = resolve_pack(industry, overlay)
        _validate_connectors(resolved)
        results.append(
            {
                "type": "resolved",
                "industry_pack": industry.pack_key,
                "tenant_id": resolved.tenant.id,
                "pack_key": resolved.pack_key,
                "version": resolved.version,
                "integrity": "valid",
                "status": "valid",
            }
        )
    for path in paths:
        if path.is_dir():
            resolved_path = path / "resolved-deployment-pack.json"
            overlay_file = path / "tenant-overlay.json"
            if resolved_path.exists():
                paths_to_check = [resolved_path]
            elif overlay_file.exists():
                paths_to_check = [overlay_file]
            else:
                paths_to_check = sorted(path.rglob("*.json"))
        else:
            paths_to_check = [path]
        for candidate in paths_to_check:
            kind, model = _classify(candidate)
            if kind == "resolved":
                _validate_connectors(model)
                result = {
                    "type": kind,
                    "pack_key": model.pack_key,
                    "tenant_id": model.tenant.id,
                    "version": model.version,
                    "integrity": "valid" if model.integrity else "legacy-v1",
                    "status": "valid",
                }
            else:
                result = {
                    "type": kind,
                    "key": model.pack_key if kind == "industry" else model.overlay_key,
                    "version": model.version,
                    "integrity": "valid",
                    "status": "valid",
                }
            results.append(result)
    if not results:
        raise ValueError("no pack files were provided")
    for result in results:
        print(json.dumps(result, ensure_ascii=False))
    return 0


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    message: str
    fix: str | None = None


def _check_directory(name: str, path: Path, *, create: bool) -> Check:
    try:
        if path.exists() and not path.is_dir():
            return Check(
                name,
                False,
                f"{path} exists but is not a directory",
                f"Choose or create a directory for {name.lower()}.",
            )
        if not path.exists():
            if not create:
                return Check(
                    name,
                    False,
                    f"directory does not exist: {path}",
                    "Create the directory or omit --no-create.",
                )
            path.mkdir(parents=True, exist_ok=True)
        probe = path / f".visionqc-preflight-{os.getpid()}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return Check(name, True, f"read/write access: {path}")
    except OSError as exc:
        return Check(
            name,
            False,
            f"cannot use {path}: {exc}",
            "Grant the gateway user read/write permission or choose another path.",
        )


def _check_port(port: int) -> Check:
    if not 1 <= port <= 65535:
        return Check(
            "status port",
            False,
            f"invalid TCP port {port}",
            "Choose a port between 1 and 65535.",
        )
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.25)
        if probe.connect_ex(("127.0.0.1", port)) == 0:
            return Check(
                "status port",
                False,
                f"TCP port {port} is already in use",
                "Stop the process using the port or set VQC_GATEWAY_STATUS_PORT to a free port.",
            )
    return Check("status port", True, f"TCP port {port} is available")


def _connector_checks(manifest: Any, *, timeout: float, skip_network: bool) -> list[Check]:
    checks: list[Check] = []
    for name, config in manifest.connectors.model_dump(mode="json").items():
        if config is None:
            continue
        endpoint = str(config["endpoint"])
        driver = str(config["driver"])
        secret_refs = [str(item) for item in config.get("secret_refs", [])]
        simulated = (
            bool(config.get("simulated"))
            or "mock" in driver.lower()
            or endpoint.startswith(("mock://", "memory://", "local://"))
        )
        if secret_refs and not simulated:
            missing = [ref for ref in secret_refs if not os.getenv(ref)]
            if missing:
                checks.append(
                    Check(
                        f"connector {name} secrets",
                        False,
                        f"required secret references are missing: {', '.join(missing)}",
                        (
                            "Inject the referenced variables from the customer's "
                            "secret provider; do not commit values."
                        ),
                    )
                )
                continue
        if simulated or skip_network:
            message = (
                "simulated/local contract"
                if not skip_network
                else "network check skipped by request"
            )
            checks.append(Check(f"connector {name}", True, f"{driver}: {message}"))
            continue
        if not endpoint.startswith(("http://", "https://")):
            checks.append(
                Check(
                    f"connector {name}",
                    False,
                    f"unsupported endpoint scheme in {endpoint!r}",
                    "Use an approved http(s) adapter or a declared simulated connector.",
                )
            )
            continue
        health_url = (
            endpoint.rstrip("/") + "/" + str(config.get("health_path", "/health")).lstrip("/")
        )
        try:
            response = httpx.get(health_url, timeout=timeout)
            if response.is_success:
                checks.append(
                    Check(
                        f"connector {name}",
                        True,
                        f"health check succeeded at {health_url}",
                    )
                )
            else:
                checks.append(
                    Check(
                        f"connector {name}",
                        False,
                        f"health check returned HTTP {response.status_code}",
                        "Verify the endpoint, network route and connector credentials.",
                    )
                )
        except httpx.HTTPError as exc:
            checks.append(
                Check(
                    f"connector {name}",
                    False,
                    f"health check failed: {type(exc).__name__}",
                    "Verify DNS, firewall, endpoint and secret-provider injection.",
                )
            )
    return checks


def _camera_check(index: int) -> Check:
    try:
        cv2 = importlib.import_module("cv2")
    except ImportError:
        return Check(
            "USB camera",
            False,
            "OpenCV camera dependency is not installed",
            "Install edge-gateway[camera] or disable USB camera mode.",
        )
    capture = cv2.VideoCapture(index)
    try:
        if not capture.isOpened():
            return Check(
                "USB camera",
                False,
                f"no camera is available at index {index}",
                "Connect the camera, grant OS camera permission, or use folder watch mode.",
            )
        return Check("USB camera", True, f"camera index {index} opened")
    finally:
        capture.release()


def preflight(args: argparse.Namespace) -> int:
    if args.industry_pack or args.overlay:
        if not args.industry_pack or not args.overlay:
            raise ValueError("--industry-pack and --overlay must be provided together")
        manifest = load_and_resolve_pack(
            Path(args.industry_pack).resolve(), Path(args.overlay).resolve()
        )
    else:
        manifest = load_manifest(Path(args.pack).resolve())
    checks: list[Check] = [
        Check(
            "deployment pack",
            True,
            f"{manifest.pack_key} / tenant {manifest.tenant.id} / version {manifest.version}",
        ),
        Check("dependency: pydantic", True, "installed"),
    ]
    for dependency in ("PIL", "httpx"):
        try:
            importlib.import_module(dependency)
            checks.append(Check(f"dependency: {dependency}", True, "installed"))
        except ImportError:
            checks.append(
                Check(
                    f"dependency: {dependency}",
                    False,
                    "not installed",
                    "Install the edge-gateway dependencies with uv sync --extra dev.",
                )
            )
    watch_root = Path(args.watch_root or manifest.edge_gateway.watch.root).expanduser()
    data_dir = Path(args.data_dir or ".visionqc-gateway").expanduser()
    checks.append(_check_directory("watch directory", watch_root, create=not args.no_create))
    checks.append(_check_directory("data directory", data_dir, create=not args.no_create))
    checks.append(_check_port(args.port))
    checks.extend(_connector_checks(manifest, timeout=args.timeout, skip_network=args.skip_network))
    camera_enabled = args.camera or bool(
        (manifest.collection or {}).camera.get("enabled", False) if manifest.collection else False
    )
    if camera_enabled:
        checks.append(_camera_check(args.camera_index))
    else:
        checks.append(
            Check(
                "USB camera",
                True,
                "not enabled; folder/API collection remains available",
            )
        )
    failures = [check for check in checks if not check.ok]
    if args.json:
        print(
            json.dumps(
                {
                    "status": "failed" if failures else "ready",
                    "checks": [check.__dict__ for check in checks],
                },
                ensure_ascii=False,
            )
        )
    else:
        print(f"VisionQC preflight · {manifest.pack_key} · tenant {manifest.tenant.id}")
        for check in checks:
            marker = "PASS" if check.ok else "FAIL"
            print(f"[{marker}] {check.name}: {check.message}")
            if not check.ok and check.fix:
                print(f"       Fix: {check.fix}")
        print(
            "Result: "
            + ("READY" if not failures else f"NOT READY ({len(failures)} checks need attention)")
        )
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser(
        "init-tenant", help="generate a tenant/site overlay and resolved runtime pack"
    )
    init.add_argument(
        "--industry",
        choices=[path.stem for path in sorted(INDUSTRY_ROOT.glob("*.json"))],
        default="electronics",
    )
    init.add_argument("--industry-pack", type=Path)
    init.add_argument("--tenant-id", required=True)
    init.add_argument("--tenant-name", default="Example tenant")
    init.add_argument("--site-id", default="site-01")
    init.add_argument("--site-name")
    init.add_argument("--locale", default="en-US")
    init.add_argument("--timezone", default="+08:00")
    init.add_argument(
        "--input-mode",
        choices=["api_upload", "folder_watch", "usb_camera"],
        default="folder_watch",
    )
    init.add_argument("--product-code")
    init.add_argument("--product-name")
    init.add_argument("--product-revision")
    init.add_argument("--station-code")
    init.add_argument("--station-name")
    init.add_argument("--gateway-id")
    init.add_argument("--watch-root")
    init.add_argument("--retention-days", type=int, default=30)
    init.add_argument("--version", default="1.0.0")
    init.add_argument("--output-dir", type=Path, required=True)
    init.set_defaults(handler=init_tenant)

    validate = subparsers.add_parser(
        "validate-pack", help="validate Industry Pack, overlay or resolved pack"
    )
    validate.add_argument("paths", nargs="*", type=Path)
    validate.add_argument("--industry-pack", type=Path)
    validate.add_argument("--overlay", type=Path)
    validate.set_defaults(
        handler=lambda args: validate_paths(
            [path.resolve() for path in args.paths],
            args.industry_pack.resolve() if args.industry_pack else None,
            args.overlay.resolve() if args.overlay else None,
        )
    )

    check = subparsers.add_parser(
        "preflight",
        help="check local paths, dependencies, ports, camera and connectors",
    )
    check.add_argument("--pack", type=Path)
    check.add_argument("--industry-pack", type=Path)
    check.add_argument("--overlay", type=Path)
    check.add_argument("--watch-root")
    check.add_argument("--data-dir")
    check.add_argument("--port", type=int, default=8090)
    check.add_argument("--camera", action="store_true")
    check.add_argument("--camera-index", type=int, default=0)
    check.add_argument("--timeout", type=float, default=3.0)
    check.add_argument("--skip-network", action="store_true")
    check.add_argument("--no-create", action="store_true")
    check.add_argument("--json", action="store_true")
    check.set_defaults(handler=preflight)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "preflight" and not (args.pack or (args.industry_pack and args.overlay)):
        parser.error("preflight requires --pack or both --industry-pack and --overlay")
    if (
        args.command == "validate-pack"
        and not args.paths
        and not (args.industry_pack and args.overlay)
    ):
        parser.error("validate-pack requires a path or both --industry-pack and --overlay")
    try:
        return int(args.handler(args))
    except (OSError, ValueError, json.JSONDecodeError, httpx.HTTPError) as exc:
        print(f"VisionQC command failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
