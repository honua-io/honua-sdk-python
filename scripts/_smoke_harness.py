"""Shared staging smoke helpers for pytest and release validation."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from math import isclose
import os
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from uuid import uuid4

from honua_sdk import HonuaClient, HonuaHttpError, __version__ as HONUA_SDK_VERSION

DEFAULT_SERVICE_ID = "test_service"
DEFAULT_LAYER_ID = 0
DEFAULT_UID_PREFIX = "sdk-python-smoke"
DEFAULT_RESULTS_PATH = Path("staging-smoke-results.json")
DEFAULT_PROTOCOL_BBOX = (-180.0, -90.0, 180.0, 90.0)
DEFAULT_IMAGE_DISPLAY = "256,256,96"
DEFAULT_OGC_TILE_MATRIX_SET_ID = "WebMercatorQuad"
EXPECTED_QUERY_FIELDS = frozenset({"objectid", "name", "status", "count", "ratio", "uid"})
READ_QUERY_LIMIT = 2
WRITE_QUERY_LIMIT = 25
INITIAL_GEOMETRY = {"x": -122.4013, "y": 37.7925}
UPDATED_GEOMETRY = {"x": -122.4008, "y": 37.7931}
POINT_GEOMETRY_ABS_TOLERANCE = 1e-6
OPTIONAL_PROTOCOL_SKIP_HTTP_STATUSES = frozenset({400, 404, 405, 501})
MAX_BODY_SUMMARY_LENGTH = 1200


class SmokeConfigError(ValueError):
    """Raised when the staging smoke configuration is invalid."""


class UnsupportedProtocolSurface(RuntimeError):
    """Raised when a live target does not advertise enough data for an optional probe."""


@dataclass
class SmokeConfig:
    base_url: str
    service_id: str = DEFAULT_SERVICE_ID
    layer_id: int = DEFAULT_LAYER_ID
    api_key: str | None = None
    enable_write_smoke: bool = False
    uid_prefix: str = DEFAULT_UID_PREFIX
    results_path: Path = DEFAULT_RESULTS_PATH
    server_commit: str | None = None
    server_image: str | None = None
    seed_profile: str | None = None
    ogc_collection_id: str | None = None
    stac_collection_id: str | None = None
    ogc_process_id: str | None = None
    ogc_process_payload: Mapping[str, Any] | None = None
    protocol_bbox: tuple[float, float, float, float] = DEFAULT_PROTOCOL_BBOX

    def target_dict(self) -> dict[str, Any]:
        return {
            "base_url": self.base_url,
            "service_id": self.service_id,
            "layer_id": self.layer_id,
            "sdk_package_version": HONUA_SDK_VERSION,
            "server_commit": self.server_commit,
            "server_image": self.server_image,
            "seed_profile": self.seed_profile,
            "write_smoke_enabled": self.enable_write_smoke,
            "uid_prefix": self.uid_prefix,
            "ogc_collection_id": self.ogc_collection_id,
            "stac_collection_id": self.stac_collection_id,
            "ogc_process_id": self.ogc_process_id,
            "protocol_bbox": list(self.protocol_bbox),
        }


ProbeStatus = Literal["passed", "failed", "skipped"]


@dataclass
class ProbeResult:
    name: str
    status: ProbeStatus
    required: bool
    started_at: str
    completed_at: str
    details: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "name": self.name,
            "status": self.status,
            "required": self.required,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "details": self.details,
        }
        if self.error is not None:
            payload["error"] = self.error
        return payload


@dataclass
class SmokeReport:
    config: SmokeConfig
    started_at: str = field(default_factory=lambda: utc_now())
    probes: list[ProbeResult] = field(default_factory=list)
    completed_at: str | None = None

    def record(self, probe: ProbeResult) -> ProbeResult:
        self.probes.append(probe)
        return probe

    def finish(self) -> None:
        if self.completed_at is None:
            self.completed_at = utc_now()

    @property
    def overall_status(self) -> str:
        if any(probe.required and probe.status == "failed" for probe in self.probes):
            return "failed"
        return "passed"

    def counts(self) -> dict[str, int]:
        counts = {"passed": 0, "failed": 0, "skipped": 0}
        for probe in self.probes:
            counts[probe.status] += 1
        return counts

    def to_dict(self) -> dict[str, Any]:
        self.finish()
        return {
            "schema_version": 1,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "overall_status": self.overall_status,
            "target": self.config.target_dict(),
            "probe_counts": self.counts(),
            "probes": [probe.to_dict() for probe in self.probes],
        }

    def write(self, path: str | Path | None = None) -> Path:
        output_path = Path(path or self.config.results_path)
        if output_path.parent != Path("."):
            output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output_path


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_smoke_config_from_env(*, require_base_url: bool = True) -> SmokeConfig:
    base_url = _read_env("HONUA_BASE_URL")
    if not base_url:
        if require_base_url:
            raise SmokeConfigError("HONUA_BASE_URL is required for staging smoke runs.")
        raise SmokeConfigError("HONUA_BASE_URL is not configured.")

    layer_text = _read_env("HONUA_LAYER_ID") or str(DEFAULT_LAYER_ID)
    try:
        layer_id = int(layer_text)
    except ValueError as exc:
        raise SmokeConfigError("HONUA_LAYER_ID must be an integer.") from exc

    return SmokeConfig(
        base_url=base_url,
        service_id=_read_env("HONUA_SERVICE_ID") or DEFAULT_SERVICE_ID,
        layer_id=layer_id,
        api_key=_read_env("HONUA_API_KEY"),
        enable_write_smoke=_read_bool_env("HONUA_ENABLE_WRITE_SMOKE", default=False),
        uid_prefix=_read_env("HONUA_SMOKE_UID_PREFIX") or DEFAULT_UID_PREFIX,
        results_path=Path(_read_env("HONUA_SMOKE_RESULTS_PATH") or DEFAULT_RESULTS_PATH),
        server_commit=_read_env("HONUA_SERVER_COMMIT"),
        server_image=_read_env("HONUA_SERVER_IMAGE"),
        seed_profile=_read_env("HONUA_SEED_PROFILE"),
        ogc_collection_id=_read_env("HONUA_OGC_COLLECTION_ID"),
        stac_collection_id=_read_env("HONUA_STAC_COLLECTION_ID"),
        ogc_process_id=_read_env("HONUA_OGC_PROCESS_ID"),
        ogc_process_payload=_read_json_object_env("HONUA_OGC_PROCESS_PAYLOAD_JSON"),
        protocol_bbox=_read_bbox_env("HONUA_PROTOCOL_BBOX", default=DEFAULT_PROTOCOL_BBOX),
    )


def _serialize_probe_exception(exc: Exception) -> dict[str, Any]:
    message = exc.message if isinstance(exc, HonuaHttpError) else str(exc)
    payload = {
        "type": type(exc).__name__,
        "message": message,
    }
    if isinstance(exc, HonuaHttpError):
        payload["status_code"] = exc.status_code
        payload["body"] = exc.body
        payload["body_summary"] = _body_summary(exc.body)
    return payload


def _body_summary(body: Any) -> str | None:
    if body is None:
        return None
    if isinstance(body, str):
        text = body
    else:
        try:
            text = json.dumps(body, sort_keys=True, default=str)
        except TypeError:
            text = str(body)
    if len(text) <= MAX_BODY_SUMMARY_LENGTH:
        return text
    return text[: MAX_BODY_SUMMARY_LENGTH - 3] + "..."


def _probe_error_context(
    context: Mapping[str, Any] | None,
    exc: Exception,
) -> dict[str, Any]:
    error_context = dict(context or {})
    cleanup_error = getattr(exc, "_smoke_cleanup_error", None)
    if cleanup_error is not None:
        error_context["cleanup_error"] = dict(cleanup_error)
    return error_context


def _attach_cleanup_error(main_error: Exception, cleanup_error: Exception) -> Exception:
    main_error._smoke_cleanup_error = _serialize_probe_exception(cleanup_error)  # type: ignore[attr-defined]
    return main_error


def run_probe(
    name: str,
    func: Callable[[], dict[str, Any]],
    *,
    required: bool = True,
    context: Mapping[str, Any] | None = None,
    skip_http_statuses: set[int] | frozenset[int] | None = None,
) -> ProbeResult:
    started_at = utc_now()
    try:
        details = func()
        error = None
        status: ProbeStatus = "passed"
    except UnsupportedProtocolSurface as exc:
        details = {
            "reason": str(exc),
            "context": dict(context or {}),
        }
        error = None
        status = "skipped"
    except HonuaHttpError as exc:
        if skip_http_statuses is not None and exc.status_code in skip_http_statuses:
            details = {
                "reason": f"Protocol surface is not supported by this target (HTTP {exc.status_code}).",
                "context": dict(context or {}),
                "error": _serialize_probe_exception(exc),
            }
            error = None
            status = "skipped"
        else:
            details = {}
            error = _serialize_probe_exception(exc)
            error["context"] = _probe_error_context(context, exc)
            status = "failed"
    except Exception as exc:  # pragma: no cover - exercised through callers
        details = {}
        error = _serialize_probe_exception(exc)
        error["context"] = _probe_error_context(context, exc)
        status = "failed"

    return ProbeResult(
        name=name,
        status=status,
        required=required,
        started_at=started_at,
        completed_at=utc_now(),
        details=details,
        error=error,
    )


def skipped_probe(
    name: str,
    reason: str,
    *,
    required: bool = False,
    context: Mapping[str, Any] | None = None,
) -> ProbeResult:
    started_at = utc_now()
    details = {"reason": reason}
    if context:
        details["context"] = dict(context)
    return ProbeResult(
        name=name,
        status="skipped",
        required=required,
        started_at=started_at,
        completed_at=utc_now(),
        details=details,
    )


def assert_probe_passed(result: ProbeResult) -> None:
    if result.status == "passed":
        return

    if result.error is None:
        raise AssertionError(f"{result.name} did not pass: {result.details}")

    error = result.error
    status_code = error.get("status_code")
    if status_code is None:
        raise AssertionError(f"{result.name} failed: {error['type']}: {error['message']}")

    raise AssertionError(
        f"{result.name} failed with HTTP {status_code}: {error['message']}"
    )


def probe_context(
    config: SmokeConfig,
    *,
    protocol_surface: str,
    sdk_method: str,
    request_path: str | Sequence[str],
) -> dict[str, Any]:
    context = config.target_dict()
    context.update(
        {
            "protocol_surface": protocol_surface,
            "sdk_method": sdk_method,
            "request_path": request_path,
        }
    )
    return context


def protocol_probe_details(
    config: SmokeConfig,
    *,
    protocol_surface: str,
    sdk_method: str,
    request_path: str | Sequence[str],
    details: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = probe_context(
        config,
        protocol_surface=protocol_surface,
        sdk_method=sdk_method,
        request_path=request_path,
    )
    if details:
        payload.update(details)
    return payload


def run_smoke_suite(config: SmokeConfig) -> SmokeReport:
    report = SmokeReport(config=config)

    with HonuaClient(config.base_url, api_key=config.api_key) as client:
        report.record(
            run_probe(
                "readiness",
                lambda: probe_readiness(client, config),
                context=probe_context(
                    config,
                    protocol_surface="Honua Server health",
                    sdk_method="HonuaClient.readiness",
                    request_path="/healthz/ready",
                ),
            )
        )
        report.record(
            run_probe(
                "list_services",
                lambda: probe_list_services(client, config),
                context=probe_context(
                    config,
                    protocol_surface="GeoServices catalog",
                    sdk_method="HonuaClient.list_services",
                    request_path="/rest/services",
                ),
            )
        )
        report.record(
            run_probe(
                "query_seeded_layer",
                lambda: probe_query_seeded_layer(client, config),
                context=probe_context(
                    config,
                    protocol_surface="GeoServices FeatureServer",
                    sdk_method="HonuaClient.query_features",
                    request_path=_feature_server_layer_path(config, "/query"),
                ),
            )
        )

        if config.enable_write_smoke:
            report.record(
                run_probe(
                    "apply_edits_roundtrip",
                    lambda: probe_apply_edits_roundtrip(client, config),
                    context=probe_context(
                        config,
                        protocol_surface="GeoServices FeatureServer",
                        sdk_method="HonuaClient.apply_edits",
                        request_path=_feature_server_layer_path(config, "/applyEdits"),
                    ),
                )
            )
        else:
            report.record(
                skipped_probe(
                    "apply_edits_roundtrip",
                    "Write smoke disabled. Set HONUA_ENABLE_WRITE_SMOKE=true to enable applyEdits coverage.",
                    context=probe_context(
                        config,
                        protocol_surface="GeoServices FeatureServer",
                        sdk_method="HonuaClient.apply_edits",
                        request_path=_feature_server_layer_path(config, "/applyEdits"),
                    ),
                )
            )

        run_protocol_surface_smoke(client, config, report)

    return report


def run_protocol_surface_smoke(
    client: HonuaClient,
    config: SmokeConfig,
    report: SmokeReport,
) -> list[ProbeResult]:
    """Record SDK-owned live probes for protocol surfaces exposed by public clients."""

    probe_specs: list[tuple[str, Callable[[], dict[str, Any]], bool, dict[str, Any]]] = [
        (
            "feature_server_metadata",
            lambda: probe_feature_server_metadata(client, config),
            True,
            probe_context(
                config,
                protocol_surface="GeoServices FeatureServer",
                sdk_method="HonuaClient.feature_server(...).metadata",
                request_path=_feature_server_path(config),
            ),
        ),
        (
            "feature_server_layer_metadata",
            lambda: probe_feature_server_layer_metadata(client, config),
            True,
            probe_context(
                config,
                protocol_surface="GeoServices FeatureServer",
                sdk_method="HonuaClient.feature_server(...).layer_metadata",
                request_path=_feature_server_layer_path(config),
            ),
        ),
        (
            "map_server_metadata",
            lambda: probe_map_server_metadata(client, config),
            False,
            probe_context(
                config,
                protocol_surface="GeoServices MapServer",
                sdk_method="HonuaClient.map_server(...).metadata",
                request_path=_map_server_path(config),
            ),
        ),
        (
            "map_server_export",
            lambda: probe_map_server_export(client, config),
            False,
            probe_context(
                config,
                protocol_surface="GeoServices MapServer",
                sdk_method="HonuaClient.map_server(...).export",
                request_path=_map_server_path(config, "/export"),
            ),
        ),
        (
            "map_server_identify",
            lambda: probe_map_server_identify(client, config),
            False,
            probe_context(
                config,
                protocol_surface="GeoServices MapServer",
                sdk_method="HonuaClient.map_server(...).identify",
                request_path=_map_server_path(config, "/identify"),
            ),
        ),
        (
            "image_server_metadata",
            lambda: probe_image_server_metadata(client, config),
            False,
            probe_context(
                config,
                protocol_surface="GeoServices ImageServer",
                sdk_method="HonuaClient.image_server(...).metadata",
                request_path=_image_server_path(config),
            ),
        ),
        (
            "image_server_export",
            lambda: probe_image_server_export(client, config),
            False,
            probe_context(
                config,
                protocol_surface="GeoServices ImageServer",
                sdk_method="HonuaClient.image_server(...).export_image",
                request_path=_image_server_path(config, "/exportImage"),
            ),
        ),
        (
            "image_server_identify",
            lambda: probe_image_server_identify(client, config),
            False,
            probe_context(
                config,
                protocol_surface="GeoServices ImageServer",
                sdk_method="HonuaClient.image_server(...).identify",
                request_path=_image_server_path(config, "/identify"),
            ),
        ),
        (
            "ogc_features_landing_collections",
            lambda: probe_ogc_features_landing_collections(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Features",
                sdk_method="HonuaClient.ogc_features().landing/collections",
                request_path=["/ogc/features", "/ogc/features/collections"],
            ),
        ),
        (
            "ogc_features_collection_items",
            lambda: probe_ogc_features_collection_items(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Features",
                sdk_method="HonuaClient.ogc_features().collection(...).items",
                request_path=_ogc_collection_path("/ogc/features", config.ogc_collection_id or "<discovered>", "/items"),
            ),
        ),
        (
            "ogc_maps_landing",
            lambda: probe_ogc_maps_landing(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Maps",
                sdk_method="HonuaClient.ogc_maps().landing",
                request_path="/ogc/maps",
            ),
        ),
        (
            "ogc_maps_collection_map",
            lambda: probe_ogc_maps_collection_map(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Maps",
                sdk_method="HonuaClient.ogc_maps().collection_map",
                request_path=_ogc_collection_path("/ogc/maps", config.ogc_collection_id or "<discovered>", "/map"),
            ),
        ),
        (
            "ogc_tiles_collections",
            lambda: probe_ogc_tiles_collections(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Tiles",
                sdk_method="HonuaClient.ogc_tiles().collections",
                request_path="/ogc/tiles/collections",
            ),
        ),
        (
            "ogc_tiles_collection_tilesets",
            lambda: probe_ogc_tiles_collection_tilesets(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Tiles",
                sdk_method="HonuaClient.ogc_tiles().collection_tilesets",
                request_path=_ogc_collection_path("/ogc/tiles", config.ogc_collection_id or "<discovered>", "/tiles"),
            ),
        ),
        (
            "ogc_processes_list",
            lambda: probe_ogc_processes_list(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Processes",
                sdk_method="HonuaClient.ogc_processes().processes",
                request_path="/ogc/processes/processes",
            ),
        ),
        (
            "ogc_processes_execute",
            lambda: probe_ogc_processes_execute(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OGC API Processes",
                sdk_method="HonuaClient.ogc_processes().execute",
                request_path=f"/ogc/processes/processes/{_encode_segment(config.ogc_process_id or '<configured>')}/execution",
            ),
        ),
        (
            "stac_catalog_collections",
            lambda: probe_stac_catalog_collections(client, config),
            False,
            probe_context(
                config,
                protocol_surface="STAC",
                sdk_method="HonuaClient.stac().catalog/collections",
                request_path=["/stac", "/stac/collections"],
            ),
        ),
        (
            "stac_collection_items",
            lambda: probe_stac_collection_items(client, config),
            False,
            probe_context(
                config,
                protocol_surface="STAC",
                sdk_method="HonuaClient.stac().items",
                request_path=f"/stac/collections/{_encode_segment(config.stac_collection_id or '<discovered>')}/items",
            ),
        ),
        (
            "odata_service_document",
            lambda: probe_odata_service_document(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OData v4",
                sdk_method="HonuaClient.odata().service_document",
                request_path="/odata",
            ),
        ),
        (
            "odata_layer_features",
            lambda: probe_odata_layer_features(client, config),
            False,
            probe_context(
                config,
                protocol_surface="OData v4",
                sdk_method="HonuaClient.odata().features",
                request_path=f"/odata/Layers({config.layer_id})/Features",
            ),
        ),
    ]

    results: list[ProbeResult] = []
    for name, func, required, context in probe_specs:
        skip_http_statuses = None if required else OPTIONAL_PROTOCOL_SKIP_HTTP_STATUSES
        results.append(
            report.record(
                run_probe(
                    name,
                    func,
                    required=required,
                    context=context,
                    skip_http_statuses=skip_http_statuses,
                )
            )
        )
    return results


def probe_readiness(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.readiness()
    return protocol_probe_details(
        config,
        protocol_surface="Honua Server health",
        sdk_method="HonuaClient.readiness",
        request_path="/healthz/ready",
        details={
            "base_url": config.base_url,
            "response_keys": sorted(response.keys()),
            "status": response.get("status"),
        },
    )


def probe_list_services(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.list_services()
    services = response.get("services")
    if not isinstance(services, list):
        raise AssertionError("list_services() did not return a 'services' array.")

    matches = []
    for service in services:
        if not isinstance(service, Mapping):
            continue
        if service.get("name") == config.service_id:
            matches.append(
                {
                    "name": service.get("name"),
                    "type": service.get("type"),
                }
            )

    if not matches:
        raise AssertionError(
            f"Service {config.service_id!r} was not listed by /rest/services."
        )

    return protocol_probe_details(
        config,
        protocol_surface="GeoServices catalog",
        sdk_method="HonuaClient.list_services",
        request_path="/rest/services",
        details={
            "service_count": len(services),
            "matched_services": matches,
        },
    )


def probe_query_seeded_layer(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.query_features(
        config.service_id,
        config.layer_id,
        out_fields=["*"],
        return_geometry=True,
        extra_params={"resultRecordCount": READ_QUERY_LIMIT},
    )
    features = _response_features(response)
    if not features:
        raise AssertionError(
            "The seeded staging layer returned no features. The smoke suite expects seeded data for field-surface verification."
        )

    attributes = _feature_attributes(features[0])
    observed_fields = {str(key).lower() for key in attributes}
    missing_fields = sorted(EXPECTED_QUERY_FIELDS - observed_fields)
    if missing_fields:
        raise AssertionError(
            f"Seeded layer response is missing expected fields: {', '.join(missing_fields)}"
        )

    return protocol_probe_details(
        config,
        protocol_surface="GeoServices FeatureServer",
        sdk_method="HonuaClient.query_features",
        request_path=_feature_server_layer_path(config, "/query"),
        details={
            "sampled_feature_count": len(features),
            "sample_objectid": _extract_objectid(attributes),
            "observed_fields": sorted(observed_fields),
            "spatial_reference": response.get("spatialReference"),
        },
    )


def probe_feature_server_metadata(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.feature_server(config.service_id).metadata()
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices FeatureServer",
        sdk_method="HonuaClient.feature_server(...).metadata",
        request_path=_feature_server_path(config),
        details=_json_summary(response),
    )


def probe_feature_server_layer_metadata(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.feature_server(config.service_id).layer_metadata(config.layer_id)
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices FeatureServer",
        sdk_method="HonuaClient.feature_server(...).layer_metadata",
        request_path=_feature_server_layer_path(config),
        details=_json_summary(response),
    )


def probe_map_server_metadata(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.map_server(config.service_id).metadata()
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices MapServer",
        sdk_method="HonuaClient.map_server(...).metadata",
        request_path=_map_server_path(config),
        details=_json_summary(response),
    )


def probe_map_server_export(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    payload = client.map_server(config.service_id).export(
        config.protocol_bbox,
        size=(256, 256),
        image_format="png",
    )
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices MapServer",
        sdk_method="HonuaClient.map_server(...).export",
        request_path=_map_server_path(config, "/export"),
        details={
            "bbox": list(config.protocol_bbox),
            "byte_count": len(payload),
        },
    )


def probe_map_server_identify(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.map_server(config.service_id).identify(
        geometry=INITIAL_GEOMETRY,
        map_extent=config.protocol_bbox,
        image_display=DEFAULT_IMAGE_DISPLAY,
        layers=f"all:{config.layer_id}",
        return_geometry=False,
    )
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices MapServer",
        sdk_method="HonuaClient.map_server(...).identify",
        request_path=_map_server_path(config, "/identify"),
        details={
            **_json_summary(response),
            "bbox": list(config.protocol_bbox),
            "image_display": DEFAULT_IMAGE_DISPLAY,
        },
    )


def probe_image_server_metadata(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.image_server(config.service_id).metadata()
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices ImageServer",
        sdk_method="HonuaClient.image_server(...).metadata",
        request_path=_image_server_path(config),
        details=_json_summary(response),
    )


def probe_image_server_export(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    payload = client.image_server(config.service_id).export_image(
        config.protocol_bbox,
        size=(256, 256),
        image_format="png",
    )
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices ImageServer",
        sdk_method="HonuaClient.image_server(...).export_image",
        request_path=_image_server_path(config, "/exportImage"),
        details={
            "bbox": list(config.protocol_bbox),
            "byte_count": len(payload),
        },
    )


def probe_image_server_identify(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.image_server(config.service_id).identify(INITIAL_GEOMETRY)
    return protocol_probe_details(
        config,
        protocol_surface="GeoServices ImageServer",
        sdk_method="HonuaClient.image_server(...).identify",
        request_path=_image_server_path(config, "/identify"),
        details=_json_summary(response),
    )


def probe_ogc_features_landing_collections(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    ogc = client.ogc_features()
    landing = ogc.landing()
    collections = ogc.collections()
    collection_ids = _collection_ids(collections)
    return protocol_probe_details(
        config,
        protocol_surface="OGC API Features",
        sdk_method="HonuaClient.ogc_features().landing/collections",
        request_path=["/ogc/features", "/ogc/features/collections"],
        details={
            "landing_keys": sorted(landing.keys()),
            "collection_count": len(collection_ids),
            "collection_ids": collection_ids[:10],
        },
    )


def probe_ogc_features_collection_items(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    ogc = client.ogc_features()
    collection_id = _resolve_collection_id(
        configured_id=config.ogc_collection_id,
        collections=ogc.collections(),
        surface="OGC API Features",
    )
    collection = ogc.collection(collection_id)
    metadata = collection.metadata()
    items = collection.items(limit=READ_QUERY_LIMIT)
    features = items.get("features") if isinstance(items.get("features"), list) else []
    return protocol_probe_details(
        config,
        protocol_surface="OGC API Features",
        sdk_method="HonuaClient.ogc_features().collection(...).items",
        request_path=_ogc_collection_path("/ogc/features", collection_id, "/items"),
        details={
            "collection_id": collection_id,
            "metadata_keys": sorted(metadata.keys()),
            "item_count": len(features),
            "item_response_keys": sorted(items.keys()),
        },
    )


def probe_ogc_maps_landing(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.ogc_maps().landing()
    return protocol_probe_details(
        config,
        protocol_surface="OGC API Maps",
        sdk_method="HonuaClient.ogc_maps().landing",
        request_path="/ogc/maps",
        details=_json_summary(response),
    )


def probe_ogc_maps_collection_map(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    collection_id = _resolve_collection_id(
        configured_id=config.ogc_collection_id,
        collections=client.ogc_features().collections(),
        surface="OGC API Maps",
    )
    payload = client.ogc_maps().collection_map(collection_id, bbox=config.protocol_bbox)
    return protocol_probe_details(
        config,
        protocol_surface="OGC API Maps",
        sdk_method="HonuaClient.ogc_maps().collection_map",
        request_path=_ogc_collection_path("/ogc/maps", collection_id, "/map"),
        details={
            "collection_id": collection_id,
            "bbox": list(config.protocol_bbox),
            "byte_count": len(payload),
        },
    )


def probe_ogc_tiles_collections(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.ogc_tiles().collections()
    collection_ids = _collection_ids(response)
    return protocol_probe_details(
        config,
        protocol_surface="OGC API Tiles",
        sdk_method="HonuaClient.ogc_tiles().collections",
        request_path="/ogc/tiles/collections",
        details={
            **_json_summary(response),
            "collection_count": len(collection_ids),
            "collection_ids": collection_ids[:10],
        },
    )


def probe_ogc_tiles_collection_tilesets(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    tiles = client.ogc_tiles()
    collection_id = _resolve_collection_id(
        configured_id=config.ogc_collection_id,
        collections=tiles.collections(),
        surface="OGC API Tiles",
    )
    tilesets = tiles.collection_tilesets(collection_id)
    return protocol_probe_details(
        config,
        protocol_surface="OGC API Tiles",
        sdk_method="HonuaClient.ogc_tiles().collection_tilesets",
        request_path=_ogc_collection_path("/ogc/tiles", collection_id, "/tiles"),
        details={
            "collection_id": collection_id,
            **_json_summary(tilesets),
        },
    )


def probe_ogc_processes_list(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.ogc_processes().processes()
    processes = response.get("processes")
    process_ids = [
        str(process.get("id"))
        for process in processes or []
        if isinstance(process, Mapping) and process.get("id") is not None
    ]
    return protocol_probe_details(
        config,
        protocol_surface="OGC API Processes",
        sdk_method="HonuaClient.ogc_processes().processes",
        request_path="/ogc/processes/processes",
        details={
            **_json_summary(response),
            "process_count": len(process_ids),
            "process_ids": process_ids[:10],
        },
    )


def probe_ogc_processes_execute(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    if not config.ogc_process_id:
        raise UnsupportedProtocolSurface(
            "Set HONUA_OGC_PROCESS_ID and HONUA_OGC_PROCESS_PAYLOAD_JSON to enable process execution smoke."
        )
    if config.ogc_process_payload is None:
        raise UnsupportedProtocolSurface("HONUA_OGC_PROCESS_PAYLOAD_JSON is required when HONUA_OGC_PROCESS_ID is set.")

    processes = client.ogc_processes()
    response = processes.execute(config.ogc_process_id, config.ogc_process_payload)
    details: dict[str, Any] = {
        **_json_summary(response),
        "process_id": config.ogc_process_id,
        "payload_keys": sorted(config.ogc_process_payload.keys()),
    }
    job_id = _job_id(response)
    if job_id is not None:
        job = processes.job(job_id)
        details["job_id"] = job_id
        details["job_keys"] = sorted(job.keys())
        if str(job.get("status", "")).lower() in {"successful", "succeeded", "complete", "completed"}:
            results = processes.job_results(job_id)
            details["result_keys"] = sorted(results.keys())

    return protocol_probe_details(
        config,
        protocol_surface="OGC API Processes",
        sdk_method="HonuaClient.ogc_processes().execute",
        request_path=f"/ogc/processes/processes/{_encode_segment(config.ogc_process_id)}/execution",
        details=details,
    )


def probe_stac_catalog_collections(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    stac = client.stac()
    catalog = stac.catalog()
    collections = stac.collections()
    collection_ids = _collection_ids(collections)
    return protocol_probe_details(
        config,
        protocol_surface="STAC",
        sdk_method="HonuaClient.stac().catalog/collections",
        request_path=["/stac", "/stac/collections"],
        details={
            "catalog_keys": sorted(catalog.keys()),
            "collection_count": len(collection_ids),
            "collection_ids": collection_ids[:10],
        },
    )


def probe_stac_collection_items(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    stac = client.stac()
    collection_id = _resolve_collection_id(
        configured_id=config.stac_collection_id,
        collections=stac.collections(),
        surface="STAC",
    )
    response = stac.items(collection_id, extra_params={"limit": READ_QUERY_LIMIT})
    features = response.get("features") if isinstance(response.get("features"), list) else []
    return protocol_probe_details(
        config,
        protocol_surface="STAC",
        sdk_method="HonuaClient.stac().items",
        request_path=f"/stac/collections/{_encode_segment(collection_id)}/items",
        details={
            "collection_id": collection_id,
            "item_count": len(features),
            "item_response_keys": sorted(response.keys()),
        },
    )


def probe_odata_service_document(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.odata().service_document()
    return protocol_probe_details(
        config,
        protocol_surface="OData v4",
        sdk_method="HonuaClient.odata().service_document",
        request_path="/odata",
        details=_json_summary(response),
    )


def probe_odata_layer_features(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    response = client.odata().features(
        layer_id=config.layer_id,
        extra_params={"$top": READ_QUERY_LIMIT},
    )
    rows = response.get("value") if isinstance(response.get("value"), list) else []
    return protocol_probe_details(
        config,
        protocol_surface="OData v4",
        sdk_method="HonuaClient.odata().features",
        request_path=f"/odata/Layers({config.layer_id})/Features",
        details={
            **_json_summary(response),
            "row_count": len(rows),
        },
    )


def probe_apply_edits_roundtrip(client: HonuaClient, config: SmokeConfig) -> dict[str, Any]:
    uid = str(uuid4())
    description = build_smoke_description(config.uid_prefix, uid)
    details: dict[str, Any] = protocol_probe_details(
        config,
        protocol_surface="GeoServices FeatureServer",
        sdk_method="HonuaClient.apply_edits",
        request_path=_feature_server_layer_path(config, "/applyEdits"),
        details={
            "uid": uid,
            "description": description,
            "where": build_uid_where(uid),
        },
    )
    known_objectids: set[int] = set()
    main_error: Exception | None = None
    cleanup_error: Exception | None = None

    try:
        add_feature = _make_smoke_feature(
            uid=uid,
            name="SDK smoke add",
            description=description,
            status="active",
            count=1,
            geometry=INITIAL_GEOMETRY,
        )
        add_response = client.apply_edits(
            config.service_id,
            config.layer_id,
            adds=[add_feature],
            rollback_on_failure=True,
        )
        details["add_response"] = summarize_edit_response(add_response)
        add_objectid = _extract_objectid(_first_success_result(add_response, "addResults"))
        if add_objectid is not None:
            known_objectids.add(add_objectid)

        added_feature = _query_single_feature(client, config, uid)
        added_attributes = _feature_attributes(added_feature)
        added_geometry = _feature_geometry(added_feature)
        queried_objectid = _extract_objectid(added_attributes)
        if queried_objectid is None:
            raise AssertionError("Added smoke feature did not expose an objectid field.")
        known_objectids.add(queried_objectid)
        _assert_feature_fields(
            added_attributes,
            uid=uid,
            name="SDK smoke add",
            description=description,
            status="active",
            count=1,
        )
        _assert_point_geometry(added_geometry, expected=INITIAL_GEOMETRY)
        details["added_geometry"] = _point_geometry_summary(added_geometry)

        update_feature = _make_smoke_feature(
            uid=uid,
            name="SDK smoke updated",
            description=description,
            status="inactive",
            count=2,
            geometry=UPDATED_GEOMETRY,
            objectid=queried_objectid,
        )
        update_response = client.apply_edits(
            config.service_id,
            config.layer_id,
            updates=[update_feature],
            rollback_on_failure=True,
        )
        details["update_response"] = summarize_edit_response(update_response)
        _first_success_result(update_response, "updateResults")

        updated_feature = _query_single_feature(client, config, uid)
        updated_attributes = _feature_attributes(updated_feature)
        updated_geometry = _feature_geometry(updated_feature)
        _assert_feature_fields(
            updated_attributes,
            uid=uid,
            name="SDK smoke updated",
            description=description,
            status="inactive",
            count=2,
        )
        _assert_point_geometry(updated_geometry, expected=UPDATED_GEOMETRY)
        details["updated_geometry"] = _point_geometry_summary(updated_geometry)
    except Exception as exc:
        main_error = exc
    finally:
        try:
            details["cleanup"] = cleanup_smoke_records(
                client,
                config,
                uid=uid,
                known_objectids=known_objectids,
            )
        except Exception as exc:  # pragma: no cover - exercised by integration flow
            cleanup_error = exc

    if main_error is not None and cleanup_error is not None:
        raise _attach_cleanup_error(main_error, cleanup_error)
    if main_error is not None:
        raise main_error
    if cleanup_error is not None:
        raise cleanup_error

    return details


def cleanup_smoke_records(
    client: HonuaClient,
    config: SmokeConfig,
    *,
    uid: str,
    known_objectids: set[int] | None = None,
) -> dict[str, Any]:
    objectids = set(known_objectids or set())
    response = client.query_features(
        config.service_id,
        config.layer_id,
        where=build_uid_where(uid),
        out_fields=["objectid", "uid"],
        return_geometry=False,
        extra_params={"resultRecordCount": WRITE_QUERY_LIMIT},
    )
    features = _response_features(response)
    for feature in features:
        objectid = _extract_objectid(_feature_attributes(feature))
        if objectid is not None:
            objectids.add(objectid)

    if objectids:
        delete_response = client.apply_edits(
            config.service_id,
            config.layer_id,
            deletes=sorted(objectids),
            rollback_on_failure=True,
        )
        delete_summary = summarize_edit_response(delete_response)
    else:
        delete_summary = {
            "delete_total": 0,
            "delete_successes": 0,
        }

    verify_response = client.query_features(
        config.service_id,
        config.layer_id,
        where=build_uid_where(uid),
        out_fields=["objectid", "uid"],
        return_geometry=False,
        extra_params={"resultRecordCount": WRITE_QUERY_LIMIT},
    )
    remaining_features = _response_features(verify_response)
    if remaining_features:
        raise AssertionError(
            f"Cleanup left {len(remaining_features)} smoke feature(s) behind for uid {uid}."
        )

    return {
        "deleted_objectids": sorted(objectids),
        "delete_response": delete_summary,
        "remaining_feature_count": len(remaining_features),
    }


def summarize_edit_response(response: Mapping[str, Any]) -> dict[str, int]:
    summary: dict[str, int] = {}
    for key, prefix in (
        ("addResults", "add"),
        ("updateResults", "update"),
        ("deleteResults", "delete"),
    ):
        results = response.get(key)
        if not isinstance(results, list):
            continue
        summary[f"{prefix}_total"] = len(results)
        summary[f"{prefix}_successes"] = sum(
            1 for item in results if isinstance(item, Mapping) and item.get("success") is True
        )
    return summary


def build_uid_where(uid: str) -> str:
    escaped_uid = uid.replace("'", "''")
    return f"uid = '{escaped_uid}'"


def build_smoke_description(uid_prefix: str, uid: str) -> str:
    return f"{uid_prefix}:{uid}"


def load_smoke_report(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_smoke_summary(report: SmokeReport | Mapping[str, Any]) -> str:
    payload = report.to_dict() if isinstance(report, SmokeReport) else dict(report)
    counts = payload.get("probe_counts", {})
    target = payload.get("target", {})
    probes = payload.get("probes", [])

    lines = [
        "## Python SDK staging smoke",
        f"- Overall status: `{payload.get('overall_status', 'unknown')}`",
        f"- Target: `{target.get('base_url', 'unknown')}` / `{target.get('service_id', 'unknown')}` layer `{target.get('layer_id', 'unknown')}`",
        f"- Probe counts: passed `{counts.get('passed', 0)}`, failed `{counts.get('failed', 0)}`, skipped `{counts.get('skipped', 0)}`",
    ]

    failed_probes = [probe for probe in probes if probe.get("status") == "failed"]
    if failed_probes:
        lines.append("")
        lines.append("### Failures")
        for probe in failed_probes:
            error = probe.get("error") or {}
            message = error.get("message", "unknown failure")
            status_code = error.get("status_code")
            if status_code is None:
                lines.append(f"- `{probe.get('name', 'unknown')}`: {message}")
            else:
                lines.append(f"- `{probe.get('name', 'unknown')}`: HTTP {status_code} {message}")

    return "\n".join(lines) + "\n"


def _query_single_feature(
    client: HonuaClient,
    config: SmokeConfig,
    uid: str,
) -> Mapping[str, Any]:
    response = client.query_features(
        config.service_id,
        config.layer_id,
        where=build_uid_where(uid),
        out_fields=["*"],
        return_geometry=True,
        extra_params={"resultRecordCount": 2},
    )
    features = _response_features(response)
    if len(features) != 1:
        raise AssertionError(f"Expected 1 smoke feature for uid {uid}, found {len(features)}.")
    return features[0]


def _response_features(response: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    features = response.get("features")
    if not isinstance(features, list):
        raise AssertionError("Feature query did not return a 'features' array.")

    normalized: list[Mapping[str, Any]] = []
    for feature in features:
        if not isinstance(feature, Mapping):
            raise AssertionError("Feature query returned a non-object feature entry.")
        normalized.append(feature)
    return normalized


def _feature_attributes(feature: Mapping[str, Any]) -> Mapping[str, Any]:
    attributes = feature.get("attributes")
    if not isinstance(attributes, Mapping):
        raise AssertionError("Feature query result did not include an 'attributes' object.")
    return attributes


def _feature_geometry(feature: Mapping[str, Any]) -> Mapping[str, Any]:
    geometry = feature.get("geometry")
    if not isinstance(geometry, Mapping):
        raise AssertionError("Feature query result did not include a 'geometry' object.")
    return geometry


def _make_smoke_feature(
    *,
    uid: str,
    name: str,
    description: str | None = None,
    status: str,
    count: int,
    geometry: Mapping[str, float],
    objectid: int | None = None,
) -> dict[str, Any]:
    attributes: dict[str, Any] = {
        "uid": uid,
        "name": name,
        "status": status,
        "count": count,
    }
    if description is not None:
        attributes["description"] = description
    if objectid is not None:
        attributes["objectid"] = objectid

    return {
        "attributes": attributes,
        "geometry": dict(geometry),
    }


def _assert_feature_fields(
    attributes: Mapping[str, Any],
    *,
    uid: str,
    name: str,
    description: str | None = None,
    status: str,
    count: int,
) -> None:
    if attributes.get("uid") != uid:
        raise AssertionError(f"Expected uid {uid!r}, got {attributes.get('uid')!r}.")
    if attributes.get("name") != name:
        raise AssertionError(f"Expected name {name!r}, got {attributes.get('name')!r}.")
    if description is not None and attributes.get("description") != description:
        raise AssertionError(
            f"Expected description {description!r}, got {attributes.get('description')!r}."
        )
    if attributes.get("status") != status:
        raise AssertionError(f"Expected status {status!r}, got {attributes.get('status')!r}.")
    if int(attributes.get("count")) != count:
        raise AssertionError(f"Expected count {count!r}, got {attributes.get('count')!r}.")


def _assert_point_geometry(
    geometry: Mapping[str, Any],
    *,
    expected: Mapping[str, float],
) -> None:
    expected_x = float(expected["x"])
    expected_y = float(expected["y"])
    actual_x = _coerce_geometry_coord(geometry, "x")
    actual_y = _coerce_geometry_coord(geometry, "y")

    if not isclose(actual_x, expected_x, rel_tol=0.0, abs_tol=POINT_GEOMETRY_ABS_TOLERANCE):
        raise AssertionError(f"Expected geometry x {expected_x!r}, got {actual_x!r}.")
    if not isclose(actual_y, expected_y, rel_tol=0.0, abs_tol=POINT_GEOMETRY_ABS_TOLERANCE):
        raise AssertionError(f"Expected geometry y {expected_y!r}, got {actual_y!r}.")


def _coerce_geometry_coord(geometry: Mapping[str, Any], key: str) -> float:
    value = geometry.get(key)
    if value is None:
        raise AssertionError(f"Feature geometry did not include {key!r}.")
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise AssertionError(f"Feature geometry {key!r} was not numeric: {value!r}.") from exc


def _point_geometry_summary(geometry: Mapping[str, Any]) -> dict[str, Any]:
    summary = {
        "x": _coerce_geometry_coord(geometry, "x"),
        "y": _coerce_geometry_coord(geometry, "y"),
    }
    if "spatialReference" in geometry:
        summary["spatialReference"] = geometry["spatialReference"]
    return summary


def _first_success_result(response: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    results = response.get(key)
    if not isinstance(results, list) or not results:
        raise AssertionError(f"apply_edits() response did not include any {key}.")

    for result in results:
        if isinstance(result, Mapping) and result.get("success") is True:
            return result

    raise AssertionError(f"apply_edits() returned {key}, but none succeeded: {results}")


def _extract_objectid(payload: Mapping[str, Any]) -> int | None:
    for key in ("objectid", "objectId", "OBJECTID"):
        value = payload.get(key)
        if value is None:
            continue
        return int(value)
    return None


def _json_summary(response: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {"response_keys": sorted(str(key) for key in response)}
    for key in ("id", "name", "title", "status", "currentVersion"):
        value = response.get(key)
        if value is not None:
            summary[key] = value
    return summary


def _collection_ids(response: Mapping[str, Any]) -> list[str]:
    collections = response.get("collections")
    if not isinstance(collections, list):
        return []
    ids: list[str] = []
    for collection in collections:
        if not isinstance(collection, Mapping):
            continue
        collection_id = collection.get("id")
        if collection_id is not None:
            ids.append(str(collection_id))
    return ids


def _resolve_collection_id(
    *,
    configured_id: str | None,
    collections: Mapping[str, Any],
    surface: str,
) -> str:
    if configured_id:
        return configured_id

    collection_ids = _collection_ids(collections)
    if not collection_ids:
        raise UnsupportedProtocolSurface(
            f"{surface} did not advertise any collections; set the matching collection id explicitly if needed."
        )
    return collection_ids[0]


def _job_id(response: Mapping[str, Any]) -> str | None:
    for key in ("jobID", "jobId", "job_id", "id"):
        value = response.get(key)
        if value is not None:
            return str(value)
    return None


def _encode_segment(value: str) -> str:
    return quote(value, safe="")


def _service_protocol_path(config: SmokeConfig, protocol_name: str, suffix: str = "") -> str:
    return f"/rest/services/{_encode_segment(config.service_id)}/{protocol_name}{suffix}"


def _feature_server_path(config: SmokeConfig, suffix: str = "") -> str:
    return _service_protocol_path(config, "FeatureServer", suffix)


def _feature_server_layer_path(config: SmokeConfig, suffix: str = "") -> str:
    return _feature_server_path(config, f"/{config.layer_id}{suffix}")


def _map_server_path(config: SmokeConfig, suffix: str = "") -> str:
    return _service_protocol_path(config, "MapServer", suffix)


def _image_server_path(config: SmokeConfig, suffix: str = "") -> str:
    return _service_protocol_path(config, "ImageServer", suffix)


def _ogc_collection_path(root: str, collection_id: str, suffix: str = "") -> str:
    return f"{root}/collections/{_encode_segment(collection_id)}{suffix}"


def _read_bbox_env(
    name: str,
    *,
    default: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    value = _read_env(name)
    if value is None:
        return default
    parts = [part.strip() for part in value.split(",")]
    if len(parts) != 4:
        raise SmokeConfigError(f"{name} must contain four comma-separated numbers.")
    try:
        west, south, east, north = (float(part) for part in parts)
    except ValueError as exc:
        raise SmokeConfigError(f"{name} must contain four comma-separated numbers.") from exc
    return (west, south, east, north)


def _read_json_object_env(name: str) -> dict[str, Any] | None:
    value = _read_env(name)
    if value is None:
        return None
    try:
        payload = json.loads(value)
    except json.JSONDecodeError as exc:
        raise SmokeConfigError(f"{name} must be valid JSON.") from exc
    if not isinstance(payload, dict):
        raise SmokeConfigError(f"{name} must be a JSON object.")
    return payload


def _read_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


def _read_bool_env(name: str, *, default: bool) -> bool:
    value = _read_env(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}
